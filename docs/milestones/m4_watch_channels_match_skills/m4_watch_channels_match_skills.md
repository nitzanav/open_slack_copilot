# M4 — Watch Channels and Match Skills

[← Back to PRD](../../PRD.md)

## Requirements

- **Listen to all messages** in configured watch channels via `slack_listener_with_threads.py` (Socket Mode)
- **Match watch skills** — use progressive disclosure; only act when a skill matches
- **Expected to mostly not act** — ~90% of messages won't match any skill; this is normal
- **Enrich with thread context** — when a skill matches, fetch full thread
- **Reuse M1 flow** — call `prepare_draft_order` with thread context, matched skills, no user text
- **Send ephemeral to watcher user** — each watcher skill defines a `watcher_user_id` in its `metadata.json`; the draft ephemeral is sent to that user
- **All channel watcher skills checked** — every message is checked against all channel watcher skills (skill-level channel filter is M14)
- **Shared utilities with M2** — common listener infrastructure and draft generation; separate handler file

## Architecture

### Modules

- `common/slack/slack_bot/slack_listener_with_threads.py` — registers `message` event listener for configured watch channels
- `common/slack/slack_bot/channel_watcher_handler.py` — M4-specific handler: receives message events, runs progressive disclosure with channel watcher skills, drafts if match
- `core/slack_bot.py` — `prepare_draft_order` (reused)
- `common/progressive_disclosure/progressive_disclosure.py` — selects skills (same flat `skills/<name>/` layout)
- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly, plus helper functions as needed
- `config/config.py` — list of watched channels

### Skill Storage

```
~/.open_slack_copilot/
  skills/
    support_escalation/
      SKILL.md          # freeform: "When a customer reports a P1 bug, draft an escalation..."
      metadata.json     # { "watcher_user_id": "U123ABC" }
    unanswered_question/
      SKILL.md          # freeform: "When a question has been asked 2+ hours ago with no reply..."
      metadata.json     # { "watcher_user_id": "U456DEF" }
```

#### `metadata.json` (required per watcher skill)

```json
{
  "watcher_user_id": "U123ABC"
}
```

`watcher_user_id` — Slack user ID who receives the draft ephemeral when this skill matches. Each skill can target a different user.

### Config Example

```yaml
watch_channels:
  - "#support"
  - "#engineering"
  - "#sales"
```

### Data Flow

```
New message in a watched channel
       │
       ▼
slack_listener_with_threads.py ─ message event (channel_id, ts, thread_ts, text)
       │
       ├── filter: is channel in config.watch_channels?
       │
       ▼
channel_watcher_handler.py
       │
       ├── progressive_disclosure.select_skills(message_text)
       │         │
       │         ├── LLM pass 1: "does any skill apply to this message?"
       │         └── returns matched skills (possibly empty)
       │
       ├── if no skills matched → STOP (do nothing, ~90% of cases)
       │
       ├── slack_api.read_thread(channel_id, thread_ts)
       ├── read metadata.json from each matched skill → watcher_user_id
       ├── prepare_draft_order(thread_messages, user_text="", matched_skills)
       │         ├── (includes RAG if available)
       │         ├── llm_client.generate(prompt)
       │         └── slack_api.send_ephemeral(channel, thread_ts, watcher_user_id, draft)
       └── done
```

### Key Decisions

- **Skill match is gatekeeper** — unlike M2 which always drafts, M4 only drafts when a skill matches
- **Progressive disclosure on every message** — one LLM call per message in watched channels for skill selection; this could be expensive on high-volume channels (M13 adds rate limiting)
- **Thread context only fetched after match** — skip expensive thread fetching when no skill matches
- **No skill-level channel filter yet** — all channel watcher skills checked against all watched channels (M14)

## STP — Software Test Procedure

### STP-4.1: Happy path — skill matches, draft generated

- **Precondition**: Watching #support. Channel watcher skill "support_escalation" exists. Customer posts a P1 bug report.
- **Input**: `message` event in #support.
- **Expected**: Progressive disclosure selects `support_escalation`. Thread fetched. Draft generated. Ephemeral sent to skill's `watcher_user_id`.

### STP-4.2: No skill matches — nothing happens

- **Precondition**: Watching #support. Message is a casual "good morning".
- **Input**: `message` event.
- **Expected**: Progressive disclosure returns empty. No thread fetch. No draft. No ephemeral. Silent no-op.

### STP-4.3: Multiple skills match

- **Precondition**: Message triggers both "support_escalation" and "unanswered_question" skills.
- **Input**: `message` event.
- **Expected**: Both skills selected. Draft combines both skill instructions.

### STP-4.4: Message in non-watched channel

- **Precondition**: Message in #random (not in `watch_channels` config).
- **Input**: `message` event.
- **Expected**: Event ignored before progressive disclosure. No LLM call.

### STP-4.5: Thread reply in watched channel

- **Precondition**: Reply in a thread in #support.
- **Input**: `message` event with `thread_ts`.
- **Expected**: Skill check runs on the reply message. If skill matches, full thread fetched and draft generated.

### STP-4.6: Channel-level message (new thread) in watched channel

- **Precondition**: New top-level message in #support.
- **Input**: `message` event without `thread_ts`.
- **Expected**: Skill check runs. If matches, treated as singleton thread. Draft generated.

### STP-4.7: High-volume burst (10 messages in 5 seconds)

- **Precondition**: 10 messages arrive in quick succession in #support.
- **Input**: 10 `message` events.
- **Expected**: All 10 checked against skills. Only matching ones get drafts. No rate limiting in M4 (see M13).

### STP-4.8: LLM failure during skill selection

- **Precondition**: LLM unreachable during progressive disclosure.
- **Input**: `message` event.
- **Expected**: Fail fast — error logged. Message skipped.

### STP-4.9: No channel watcher skills exist

- **Precondition**: No watch skills installed (no `SKILL.md` folders under `skills/`).
- **Input**: `message` event in watched channel.
- **Expected**: Progressive disclosure skipped. No action taken. No error.

### STP-4.10: Draft includes RAG context

- **Precondition**: Channel RAG exists for #support. Skill matches.
- **Input**: `message` event.
- **Expected**: RAG results included in prompt alongside matched skill and thread context.

## Unit Tests

**Files**: `common/slack/slack_bot/channel_watcher_handler_unit_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_skill_match_triggers_draft** — simulate message event, mock progressive disclosure returning a skill, assert `prepare_draft_order` called
- **test_no_match_does_nothing** — mock progressive disclosure returning empty, assert no `read_thread`, no `send_ephemeral`
- **test_non_watched_channel_ignored** — message in channel not in config, assert no progressive disclosure call
- **test_uses_progressive_disclosure** — assert `select_skills(...)` called on message text
- **test_thread_only_fetched_after_match** — assert `read_thread` NOT called before progressive disclosure, only after match
- **test_ephemeral_sent_to_watcher_user** — assert `send_ephemeral` uses `watcher_user_id` from skill's `metadata.json`
- **test_empty_skills_dir_no_action** — no channel watcher skills, assert no LLM call
- **test_multiple_skills_combined** — mock 2 skills matching, assert both in prompt

### Fixtures

- `fixture_message_event_support.json` — message event in #support
- `fixture_message_event_random.json` — message event in non-watched channel
- `fixture_channel_watcher_skills/` — test skills directory

## Integration Tests

**File**: `common/slack/slack_bot/channel_watcher_handler_integration_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_message_to_ephemeral** — simulate message → skill match → thread fetch → draft → ephemeral to `watcher_user_id`
- **test_message_no_match_silent** — simulate message → no match → verify no side effects
- **test_listener_registration** — assert message listener registered for watched channels on startup
