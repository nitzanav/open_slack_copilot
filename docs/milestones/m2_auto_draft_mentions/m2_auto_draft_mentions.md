# M2 — Auto-Draft Replies to Mentions

[← Back to PRD](../../PRD.md)

## Requirements

- **Listen for @mentions** — via `slack_listener_with_threads.py` (Socket Mode), detect when the configured user is @mentioned in any public channel
- **Enrich with thread context** — fetch full thread where the mention occurred
- **Select reply skills** — use progressive disclosure to pick relevant reply skills; always draft (fallback to hardcoded default instruction from codebase if none match)
- **Reuse M1 flow** — call `prepare_draft_order` with thread context, user text = empty (auto-draft), and selected reply skills
- **Send ephemeral to user** — the configured user (single-user bot owner) receives the draft as ephemeral in the thread
- **No rate limiting** — every mention triggers a draft (rate limiting is M13)
- **Shared utilities with M4** — common listener infrastructure and draft generation; separate handler files

## Architecture

### Modules

- `common/slack/slack_bot/slack_listener_with_threads.py` — registers `app_mention` event listener; enriches with thread context
- `common/slack/slack_bot/mention_handler.py` — M2-specific handler: filters for user mentions, calls M1 flow with reply skills
- `core/slack_bot.py` — `prepare_draft_order` (from M1.1), already supports skills (M1.2) and RAG (M1.3/M1.4)
- `common/progressive_disclosure/progressive_disclosure.py` — selects reply skills
- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly, plus helper functions as needed
- `config/config.py` — configured user ID (whose mentions to watch)

### Data Flow

```
Someone @mentions the configured user in a thread
       │
       ▼
slack_listener_with_threads.py ─ app_mention event
       │
       ├── filter: is the mentioned user == configured user?
       │
       ▼
mention_handler.py
       │
       ├── slack_api.read_thread(channel_id, thread_ts)
       ├── progressive_disclosure.select_skills("reply", thread_messages)
       ├── prepare_draft_order(thread_messages, user_text="", skills)
       │         ├── (includes RAG if available from M1.3/M1.4)
       │         ├── llm_client.generate(prompt)
       │         └── slack_api.send_ephemeral(channel, thread_ts, configured_user, draft)
       └── done
```

### Shared Code with M4

```
common/slack/slack_bot/
  slack_listener_with_threads.py   # shared: registers both mention + channel watch listeners
  mention_handler.py               # M2: filters mentions, uses reply skills
  channel_watcher_handler.py       # M4: filters watched channels, uses channel watcher skills
  draft_utils.py                   # shared: prepare_draft_order wrapper, ephemeral sending
```

### Key Decisions

- **Public channels only** — Socket Mode delivers `app_mention` for public channels without bot membership; private channels require membership
- **Single-user** — only watches mentions of the configured user
- **Always drafts** — unlike M4, M2 always produces a draft (hardcoded default instruction as fallback)
- **No user text** — since this is auto-triggered, there's no `/copilot <text>` input; LLM drafts from thread context + skills only

## STP — Software Test Procedure

### STP-2.1: Happy path — user mentioned in thread, reply skill matches

- **Precondition**: User configured. Reply skills exist. Thread with 5 messages where someone @mentions the user.
- **Input**: `app_mention` event fires.
- **Expected**: Thread fetched. Reply skill selected. Draft generated. Ephemeral sent to configured user in the thread.

### STP-2.2: Mention with no matching skill — default fallback

- **Precondition**: Thread topic doesn't match any specific reply skill.
- **Input**: `app_mention` event.
- **Expected**: Hardcoded default instruction loaded from codebase. Draft generated with default instruction + thread context.

### STP-2.3: Mention in channel-level message (not a thread)

- **Precondition**: Someone @mentions the user in a channel-level message (no thread_ts).
- **Input**: `app_mention` event.
- **Expected**: Treated as singleton thread (1 message). Draft generated.

### STP-2.4: Multiple mentions in rapid succession

- **Precondition**: User mentioned 3 times in 3 different threads within seconds.
- **Input**: 3 `app_mention` events.
- **Expected**: 3 independent drafts generated and sent. No deduplication. No rate limiting (M13).

### STP-2.5: Mention of a different user (not configured)

- **Precondition**: Someone @mentions a user other than the configured user.
- **Input**: `app_mention` event.
- **Expected**: Event ignored. No draft generated.

### STP-2.6: Mention in private channel (bot is member)

- **Precondition**: Bot added to private channel. User mentioned.
- **Input**: `app_mention` event.
- **Expected**: Same behavior as public channel. Draft generated and sent.

### STP-2.7: LLM failure during draft

- **Precondition**: LLM unreachable.
- **Input**: `app_mention` event.
- **Expected**: Ephemeral error sent to user. Fail fast, no retry.

### STP-2.8: Mention with RAG available (M1.3 integration)

- **Precondition**: Channel RAG exists.
- **Input**: `app_mention` event.
- **Expected**: RAG results included in prompt alongside skills and thread context.

## Unit Tests

**Files**: `common/slack/slack_bot/mention_handler_unit_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_mention_triggers_draft** — simulate `app_mention` event for configured user, assert `prepare_draft_order` called
- **test_wrong_user_ignored** — simulate `app_mention` for a different user, assert no draft generated
- **test_uses_reply_skills** — assert `progressive_disclosure.select_skills("reply", ...)` called
- **test_default_fallback** — mock progressive disclosure returning empty, assert hardcoded default instruction from codebase loaded
- **test_ephemeral_sent_to_configured_user** — assert `send_ephemeral` called with configured user ID
- **test_no_user_text** — assert `prepare_draft_order` called with `user_text=""`
- **test_singleton_thread** — event with no thread_ts, assert single message treated as thread
- **test_multiple_mentions_independent** — 3 events, assert 3 independent draft calls

### Fixtures

- `fixture_app_mention_event.json` — standard app_mention event payload
- `fixture_app_mention_wrong_user.json` — mention of different user
- Reuse thread fixtures from M1.1

## Integration Tests

**File**: `common/slack/slack_bot/mention_handler_integration_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_mention_event_to_ephemeral** — simulate full flow: `app_mention` event → thread enrichment → skill selection → LLM call → ephemeral sent
- **test_mention_with_rag** — simulate mention in channel with RAG → RAG results in prompt
- **test_listener_registration** — assert `app_mention` listener registered on startup
