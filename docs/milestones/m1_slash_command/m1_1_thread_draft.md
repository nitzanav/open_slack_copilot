# M1.1 — Thread Draft via `/copilot`

## Requirements

- **Listen** to `/copilot <optional text>` slash command in any channel/thread
- **Gather thread** — fetch all messages in the thread where the command was invoked via `slack_api`
- **Compose system prompt** — thread messages + user text (if provided)
- **Auto-detect intent** — if user text looks like a draft, revise it with context; if it looks like an instruction, follow it; if empty, use default "draft a reply"
- **Call LLM** — send system prompt via `llm_client` (LiteLLM) to generate draft
- **Send ephemeral** — post draft as ephemeral message (plain text) visible only to invoking user

## Architecture

### Modules

- `core/slack_bot.py` — orchestrator, calls `prepare_draft_order`
- `common/slack/slack_bot/slack_listener.py` — registers `/copilot` slash command callback via slack_bolt (Socket Mode)
- `common/slack/slack_bot/slack_listener_with_threads.py` — enriches event with full thread messages
- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly (delegating its methods as-is), plus additional helper functions as needed
- `common/llm/llm_client/llm_client.py` — `generate(system_prompt, user_prompt)` via LiteLLM
- `config/config.py` — reads `default.yaml` + env vars

### Config

**Env vars** (secrets, not in YAML):
- `SLACK_BOT_TOKEN` — Slack bot OAuth token
- `SLACK_APP_TOKEN` — Slack app-level token (for Socket Mode)

**`config/default.yaml`**:
```yaml
llm:
  model: "gpt-4o"       # LiteLLM model identifier
```

### Data Flow

```
/copilot <text> in thread
       │
       ▼
slack_listener.py ─ slash command event (channel_id, thread_ts, user_id, text)
       │
       ▼
slack_listener_with_threads.py ─ calls slack_api.read_thread(channel_id, thread_ts)
       │
       ▼
core/slack_bot.py :: prepare_draft_order(thread_messages, user_text)
       │
       ├── compose_system_prompt(thread_messages, user_text)
       ├── llm_client.generate(prompt)
       └── slack_api.send_ephemeral(channel_id, thread_ts, user_id, draft)
```

### Key Decisions

- **Single-user** bot — one config, one person's context
- **No memory** of previous drafts — each `/copilot` invocation is independent
- **User identity in prompt** — LLM outputs `<@USER_ID>` format (resolved from display names via slack_api)
- **Fail fast** — on LLM or Slack API error, send ephemeral error immediately, no retry

## STP — Software Test Procedure

### STP-1.1.1: Happy path — `/copilot` with instruction text

- **Precondition**: Thread with 3-5 messages in a public channel
- **Input**: `/copilot suggest a polite reply`
- **Expected**: Draft generated and sent as ephemeral. System prompt contains all thread messages + "suggest a polite reply" as instruction. LLM called once.

### STP-1.1.2: User provides draft text for revision

- **Precondition**: Thread with messages
- **Input**: `/copilot I agree and want to be informed`
- **Expected**: LLM detects this as a draft (not an instruction), revises it with thread context. Ephemeral contains the revised version.

### STP-1.1.3: No text after `/copilot`

- **Precondition**: Thread with messages
- **Input**: `/copilot`
- **Expected**: Default instruction used ("draft a reply"). Draft generated and sent as ephemeral.

### STP-1.1.4: Singleton thread (one message, no replies)

- **Precondition**: Channel message with no replies
- **Input**: `/copilot`
- **Expected**: System prompt contains only the single message. Draft generated and sent.

### STP-1.1.5: Large thread (50+ messages)

- **Precondition**: Thread with 50+ messages
- **Input**: `/copilot summarize and reply`
- **Expected**: All messages included in prompt. Draft generated. No truncation in M1.1 (truncation is a later concern).

### STP-1.1.6: Private channel

- **Precondition**: Thread in a private channel the bot is a member of
- **Input**: `/copilot`
- **Expected**: Same behavior as public channel.

### STP-1.1.7: Bot not in private channel

- **Precondition**: Thread in a private channel the bot is NOT a member of
- **Input**: `/copilot`
- **Expected**: Ephemeral error: "Add me to this channel first."

### STP-1.1.8: LLM failure

- **Precondition**: LLM service unreachable or returns error
- **Input**: `/copilot`
- **Expected**: Ephemeral error: "Failed to generate draft, try again." No retry.

### STP-1.1.9: Second invocation in same thread

- **Precondition**: User already invoked `/copilot` once in this thread
- **Input**: `/copilot` again
- **Expected**: Fresh draft generated with no memory of previous invocation.

## Unit Tests

**Files**: `core/slack_bot_unit_test.py`, `common/slack/slack_bot/slack_listener_unit_test.py`

**Framework**: pytest

**Mock**: Slack API (all HTTP calls), LLM client (generate method)

### Test Cases

- **test_compose_prompt_with_instruction** — given thread messages + instruction text, assert system prompt contains formatted thread + instruction
- **test_compose_prompt_with_draft_text** — given thread messages + "I agree and want to be informed", assert system prompt frames it as revision
- **test_compose_prompt_empty_text** — assert default instruction is used
- **test_compose_prompt_singleton_thread** — single message (no replies), assert prompt contains only that message and is valid
- **test_singleton_thread_draft_generated** — mock thread with 1 message, assert LLM called and draft sent as ephemeral (STP-1.1.4)
- **test_draft_output_forwarded** — mock LLM returning "Here is my draft", assert `send_ephemeral` called with that text
- **test_ephemeral_targets_correct_user** — assert `send_ephemeral` called with correct `channel_id`, `thread_ts`, `user_id`
- **test_llm_error_sends_error_ephemeral** — mock LLM raising exception, assert error ephemeral sent
- **test_slack_api_error_sends_error_ephemeral** — mock `read_thread` raising exception, assert error ephemeral

### Fixtures

- `fixture_thread_3_messages.json` — 3 messages with user IDs, timestamps, text
- `fixture_thread_singleton.json` — single message
- `fixture_thread_50_messages.json` — 50 messages

## Integration Tests

**File**: `common/slack/slack_bot/slack_listener_integration_test.py`

**Mock**: Slack API, LLM client. Do NOT mock vectorial DB (not used in M1.1).

### Test Cases

- **test_slash_command_end_to_end** — simulate slash command event arriving at `slack_listener.py` → enrichment via `slack_listener_with_threads.py` → `prepare_draft_order` → LLM call → ephemeral sent. Assert full chain.
- **test_singleton_thread_end_to_end** — simulate slash command in a thread with a single message (no replies) → enrichment returns 1 message → draft generated → ephemeral sent (STP-1.1.4)
- **test_thread_enrichment_passes_correct_ts** — assert `read_thread` called with exact `thread_ts` from the slash command event
- **test_callback_registration** — assert `/copilot` command is registered as a listener on app startup
