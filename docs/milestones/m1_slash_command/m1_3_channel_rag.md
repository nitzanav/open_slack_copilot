# M1.3 — Channel RAG

## Requirements

- **Retrieve 10 relevant messages** — from current channel's RAG, summarized, added to system prompt
- **Summarize on insert** — messages are summarized before being stored in the vectorial DB (Qdrant)
- **Hybrid filter** — RAG supports filtering by `channel`, `from`, `to`, `with` fields
- **Auto-initiate RAG** — if RAG doesn't exist for channel, start building it; send ephemeral "Preparing RAG for #X, will update when done"; send draft when ready
- **Checkpoint-based fetch** — on first build, fetch messages from configurable checkpoint (default: 1 month back); periodic refresh also uses this checkpoint
- **Per-channel concurrency lock** — only one RAG update per channel at a time; other `/copilot` calls in the same channel wait or get served from existing index
- **Hard-coded examples** — include a file of example threads & answers in the codebase, added to system prompt alongside RAG results
- **Config-driven** — RAG config in YAML: channel, filter fields, update frequency

## Architecture

### Modules

- `common/rag/rag.py` — generic RAG: load, query by filter/embedding, schedule periodic updates, concurrency guard (per-channel lock), status management
- `common/slack/slack_rag/slack_rag.py` — bridges Slack channels → `rag.py`; reads channel config, triggers builds, translates Slack filters to RAG queries
- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly, plus helper functions as needed
- `common/llm/llm_client/llm_client.py` — used to summarize messages before RAG insert
- `core/slack_bot.py` — calls `slack_rag` to get relevant messages, adds to prompt
- `config/config.py` — RAG config: channels, filters, update frequency, checkpoint duration

### RAG Config Example (in `default.yaml`)

```yaml
rag:
  checkpoint_duration: "30d"    # fetch messages from this far back
  slack:
    - channel: "#support"
      filter:
        from: "@nitzan"
      update: "every 1h"
    - channel: "#engineering"
      update: "every 1d"
```

### Data Flow — Draft with RAG

```
prepare_draft_order(thread_messages, user_text, skills)
       │
       ├── slack_rag.query(channel_id, thread_context, top_k=10)
       │         │
       │         ├── check RAG status for channel
       │         │     ├── exists & ready → query Qdrant
       │         │     └── missing → initiate build, send ephemeral "Preparing..."
       │         │
       │         └── return 10 summarized messages
       │
       ├── load hard-coded examples file
       ├── compose_system_prompt(thread, user_text, skills, rag_results, examples)
       ├── llm_client.generate(prompt)
       └── slack_api.send_ephemeral(draft)
```

### Data Flow — RAG Build

```
slack_rag.build(channel_id)
       │
       ├── acquire per-channel lock
       ├── slack_api.read_channel_history(channel_id, oldest=now - checkpoint)
       ├── for each message: llm_client.summarize(message) → summary
       ├── rag.insert(channel_id, summaries with metadata: from, to, with, ts)
       ├── release lock
       └── notify caller: "RAG ready"
```

### Key Decisions

- **Summarize on insert** — default strategy; keeps vectorial DB entries concise
- **Qdrant** as vectorial DB — not mocked in tests
- **Checkpoint always re-fetched** — no last-indexed tracking in this milestone (see M9)
- **Periodic update** — uses APScheduler to re-run build at configured frequency, same checkpoint
- **Hard-coded examples** — file at `core/example_threads.json` or similar; appended to prompt alongside RAG results

## STP — Software Test Procedure

### STP-1.3.1: Happy path — RAG exists, 10 results returned

- **Precondition**: RAG built for #support with 100+ indexed messages.
- **Input**: `/copilot` in a #support thread
- **Expected**: 10 most relevant summarized messages retrieved from Qdrant. System prompt includes them. Draft uses RAG context.

### STP-1.3.2: RAG not yet built — auto-initiate

- **Precondition**: No RAG for #engineering. Channel has messages.
- **Input**: `/copilot` in #engineering thread
- **Expected**: Ephemeral "Preparing RAG for #engineering, will update when done." RAG build starts. When done, draft generated and sent as ephemeral.

### STP-1.3.3: RAG build in progress (concurrent request)

- **Precondition**: RAG build running for #support (lock held). Another user invokes `/copilot`.
- **Input**: `/copilot` in #support thread
- **Expected**: Second invocation waits for build to complete (or uses stale index if one exists), then generates draft.

### STP-1.3.4: Channel with fewer than 10 messages in RAG

- **Precondition**: RAG for #small-channel has only 3 indexed messages.
- **Input**: `/copilot`
- **Expected**: Returns 3 messages (all available). Draft still generated.

### STP-1.3.5: RAG with hybrid filter

- **Precondition**: RAG config has `filter: {from: "@nitzan"}` for #support.
- **Input**: `/copilot` in #support
- **Expected**: RAG query applies filter — only messages from @nitzan returned. Prompt includes filtered results.

### STP-1.3.6: Hard-coded examples included

- **Precondition**: `example_threads.json` file exists with 5 example Q&A pairs.
- **Input**: `/copilot`
- **Expected**: Example threads appended to system prompt alongside RAG results.

### STP-1.3.7: RAG build fails (Slack API error fetching history)

- **Precondition**: Slack API returns error when fetching channel history.
- **Input**: `/copilot` in channel with no existing RAG
- **Expected**: Ephemeral error: "Failed to prepare RAG for #X." Draft generation proceeds without RAG (falls back to M1.1 + skills only).

### STP-1.3.8: LLM summarization failure during build

- **Precondition**: LLM fails while summarizing a message during RAG build.
- **Input**: RAG build triggered
- **Expected**: Skip that message, continue building. Log via `@log` decorator.

### STP-1.3.9: Periodic RAG refresh

- **Precondition**: RAG for #support configured with `update: "every 1h"`.
- **Input**: 1 hour elapses.
- **Expected**: RAG rebuild triggered automatically. Re-fetches from checkpoint. Replaces old index entries.

## Unit Tests

**Files**: `common/rag/rag_unit_test.py`, `common/slack/slack_rag/slack_rag_unit_test.py`

**Mock**: Slack API, LLM client. Do NOT mock Qdrant.

### Test Cases

- **test_query_returns_top_10** — insert 20 documents, query, assert 10 returned ranked by relevance
- **test_query_with_filter** — insert docs with different `from` fields, query with filter, assert only matching docs returned
- **test_query_empty_index** — query on empty channel, assert empty list returned
- **test_build_fetches_from_checkpoint** — mock `read_channel_history`, assert called with `oldest = now - 30d`
- **test_build_summarizes_each_message** — mock LLM, assert `summarize` called once per message
- **test_build_inserts_into_qdrant** — after build, query Qdrant, assert documents present
- **test_concurrency_lock** — two concurrent builds for same channel, assert second waits
- **test_concurrent_different_channels** — two builds for different channels, assert both proceed
- **test_build_failure_releases_lock** — mock Slack API error during build, assert lock released
- **test_rag_status_check** — assert `slack_rag.query` detects missing index and triggers build

### Fixtures

- `fixture_channel_history_100.json` — 100 channel messages
- `fixture_channel_history_3.json` — 3 messages
- `example_threads.json` — hard-coded example Q&A pairs

## Integration Tests

**File**: `common/slack/slack_rag/slack_rag_integration_test.py`

**Mock**: Slack API, LLM client. Qdrant is real (test instance).

### Test Cases

- **test_build_then_query** — trigger build with mocked channel history → messages summarized → inserted into Qdrant → query returns relevant results
- **test_slash_command_triggers_rag_build** — simulate `/copilot` in channel with no RAG → ephemeral "Preparing..." → build completes → draft ephemeral sent with RAG context in prompt
- **test_periodic_refresh_replaces_old** — build RAG, trigger refresh with new messages, assert updated content returned on query
