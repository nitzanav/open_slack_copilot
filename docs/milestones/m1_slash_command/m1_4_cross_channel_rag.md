# M1.4 — Cross-Channel RAG

## Requirements

- **Retrieve 10 relevant messages from other channels** — from popular/related channels, added to system prompt alongside channel RAG results
- **Channel list from config** — manually configured list of channels to include in cross-channel RAG
- **Auto-build on app start** — when the application starts, build RAG for all configured cross-channel sources using the checkpoint (default 1 month back)
- **Auto-initiate missing RAG** — if a configured channel's RAG doesn't exist at query time, start building it; send ephemeral "Creating RAG for #X, #Y, #Z"; wait for completion
- **Reuse M1.3 infrastructure** — same `rag.py`, `slack_rag.py`, Qdrant, per-channel lock, summarize-on-insert
- **Separate from channel RAG** — cross-channel results are additional context, not replacing the current channel's RAG results

## Architecture

### Modules

- `common/slack/slack_rag/slack_rag.py` — extended with `query_cross_channel(channel_ids, thread_context, top_k=10)` — queries multiple channels, merges results by relevance
- `common/rag/rag.py` — no changes, already supports per-channel indexes
- `core/slack_bot.py` — on startup, triggers RAG build for configured cross-channel list; in `prepare_draft_order`, calls both channel RAG and cross-channel RAG
- `config/config.py` — cross-channel config: list of channels

### Config Example

```yaml
rag:
  checkpoint_duration: "30d"
  cross_channel:
    - "#engineering"
    - "#product"
    - "#design"
  slack:
    - channel: "#support"
      update: "every 1h"
```

### Data Flow

```
App starts
       │
       └── for each channel in config.rag.cross_channel:
               slack_rag.build_if_missing(channel_id)

prepare_draft_order(thread_messages, user_text, skills)
       │
       ├── slack_rag.query(current_channel_id, context, top_k=10)          ← M1.3
       ├── slack_rag.query_cross_channel(cross_channel_ids, context, top_k=10)  ← M1.4
       │         │
       │         ├── for each channel: check RAG status
       │         │     ├── ready → query
       │         │     └── missing → build, send ephemeral "Creating RAG for #X, #Y"
       │         │
       │         └── merge results from all channels, rank by relevance, return top 10
       │
       ├── compose_system_prompt(thread, user_text, skills, channel_rag, cross_rag, examples)
       ├── llm_client.generate(prompt)
       └── slack_api.send_ephemeral(draft)
```

### Key Decisions

- **Config-based channel list** — auto-detect by volume/activity is a later milestone (M12)
- **Merged ranking** — cross-channel results from multiple channels are merged into one ranked list of 10
- **Startup build** — non-blocking; app starts serving `/copilot` immediately, RAG builds in background
- **Same checkpoint strategy** — always fetches from `checkpoint_duration` back, no incremental indexing yet (M9)

## STP — Software Test Procedure

### STP-1.4.1: Happy path — all cross-channel RAGs exist

- **Precondition**: RAG built for #engineering, #product, #design. User in #support thread.
- **Input**: `/copilot`
- **Expected**: 10 results from current channel RAG + 10 results from cross-channel (merged from #engineering, #product, #design). Both sets in system prompt. Draft uses both.

### STP-1.4.2: Some cross-channel RAGs missing

- **Precondition**: #engineering RAG exists, #product and #design RAGs missing.
- **Input**: `/copilot` in #support
- **Expected**: Ephemeral "Creating RAG for #product, #design." Builds complete. Draft includes cross-channel results from all three.

### STP-1.4.3: App startup builds cross-channel RAGs

- **Precondition**: Fresh app start, no RAGs exist.
- **Input**: App starts.
- **Expected**: RAG build initiated for each channel in `cross_channel` config. Builds run in background. App is responsive to `/copilot` during build.

### STP-1.4.4: Cross-channel query while build in progress

- **Precondition**: #engineering RAG building (lock held). User invokes `/copilot`.
- **Input**: `/copilot`
- **Expected**: Cross-channel query uses available RAGs (skips #engineering or waits). Draft generated with partial cross-channel context.

### STP-1.4.5: No cross-channel config

- **Precondition**: `cross_channel` key missing from config YAML.
- **Input**: `/copilot`
- **Expected**: Cross-channel RAG step skipped entirely. Behaves like M1.3 only.

### STP-1.4.6: Current channel is also in cross-channel list

- **Precondition**: User is in #engineering. #engineering is also in `cross_channel` list.
- **Input**: `/copilot`
- **Expected**: Deduplicate — don't return the same messages twice. Channel RAG and cross-channel RAG exclude duplicates.

### STP-1.4.7: Cross-channel build failure for one channel

- **Precondition**: Slack API error when fetching #design history.
- **Input**: `/copilot`
- **Expected**: #design skipped. Cross-channel results from #engineering and #product only. Draft still generated.

## Unit Tests

**Files**: `common/slack/slack_rag/slack_rag_unit_test.py`

**Mock**: Slack API, LLM client. Do NOT mock Qdrant.

### Test Cases

- **test_query_cross_channel_merges_results** — insert docs in 3 channel indexes, query cross-channel, assert top 10 returned across all channels
- **test_cross_channel_deduplication** — same message in channel RAG and cross-channel, assert no duplicates
- **test_missing_channel_triggers_build** — query cross-channel with one missing index, assert build triggered
- **test_no_cross_channel_config** — empty config, assert cross-channel query returns empty, no errors
- **test_startup_builds_all** — mock config with 3 channels, trigger startup, assert 3 builds initiated
- **test_partial_failure** — one channel build fails, assert others still complete and results returned

### Fixtures

- `fixture_cross_channel_config.yaml` — config with 3 channels
- Reuse channel history fixtures from M1.3

## Integration Tests

**File**: `common/slack/slack_rag/slack_rag_integration_test.py`

**Mock**: Slack API, LLM client. Qdrant is real.

### Test Cases

- **test_startup_to_query** — simulate app start → background builds → `/copilot` query → cross-channel results in prompt
- **test_full_draft_with_channel_and_cross_channel** — simulate `/copilot` → channel RAG + cross-channel RAG + skills → all in prompt → draft generated
