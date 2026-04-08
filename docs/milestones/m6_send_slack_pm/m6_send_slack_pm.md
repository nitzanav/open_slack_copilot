# M6 — Tool: Send Slack PM

[← Back to PRD](../../PRD.md)

## Requirements

- **Slack API for DMs** — `slack_api` supports `send_dm(user_id, text)` to send direct messages
- **Expose as LLM tool** — available as a LiteLLM function/tool the LLM can call during draft generation or skill execution
- **Confirmation required** — LLM cannot send DMs autonomously; every DM must be confirmed by the user via ephemeral before sending
- **Any content** — the LLM can compose any text for the DM (content defined by the skill/context)
- **User resolution** — works with M5's `resolve_user` to get the target user ID

## Architecture

### Modules

- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly, plus helper functions as needed (e.g. DM sending via the client's `conversations.open` + `chat.postMessage`)
- `common/tools/send_slack_pm.py` — LiteLLM tool definition; does NOT send immediately, returns a "pending DM" that requires confirmation
- `common/slack/slack_bot/dm_confirmation.py` — handles the confirmation flow: sends ephemeral with DM preview + "Send" / "Cancel" buttons, listens for action
- `common/llm/llm_client/llm_client.py` — already supports tools from M5
- `core/slack_bot.py` — passes `send_slack_pm` tool alongside `mention_people`

### Data Flow

```
LLM decides to send a DM during draft generation
       │
       ├── LLM calls send_slack_pm(user="Nitzan", message="Hey, please review the PR")
       │
       ▼
send_slack_pm tool (does NOT send yet)
       │
       ├── resolve_user("Nitzan") → <@U123>
       ├── return pending_dm = {user_id: "U123", text: "Hey, please review the PR"}
       │
       ▼
dm_confirmation.py
       │
       ├── send ephemeral to requesting user:
       │     "Draft DM to @Nitzan: 'Hey, please review the PR'"
       │     [Send] [Cancel]
       │
       ├── user clicks [Send]
       │     └── slack_api.send_dm("U123", "Hey, please review the PR")
       │
       └── user clicks [Cancel]
             └── ephemeral: "DM cancelled."
```

### LiteLLM Tool Definition

```
Tool name: send_slack_pm
Description: "Send a direct message to a user. The message will be shown to you for confirmation before sending."
Parameters:
  - user (string): display name or user ID of the recipient
  - message (string): the DM content
Returns: JSON with `status: tool_confirmation_requested` (actual sending happens after user confirms)
```

### Key Decisions

- **Never auto-send** — all DMs require explicit user confirmation via Slack interactive buttons
- **Ephemeral confirmation** — the DM preview is shown as ephemeral (only visible to the requesting user)
- **Interactive buttons** — requires Slack Block Kit with action handlers registered in `slack_listener.py`
- **Tool returns immediately** — the LLM gets JSON including `status: tool_confirmation_requested` and can continue generating the rest of the draft

## STP — Software Test Procedure

### STP-6.1: Happy path — LLM sends DM, user confirms

- **Precondition**: User "Dan" (U456) exists. Skill instructs LLM to send a follow-up DM.
- **Input**: LLM calls `send_slack_pm(user="Dan", message="Please check the thread")`
- **Expected**: Ephemeral to requesting user: "Draft DM to @Dan: 'Please check the thread' [Send] [Cancel]". User clicks Send. DM sent to Dan.

### STP-6.2: User cancels the DM

- **Precondition**: Same as STP-6.1.
- **Input**: User clicks Cancel.
- **Expected**: Ephemeral "DM cancelled." DM NOT sent.

### STP-6.3: Multiple DMs in one draft

- **Precondition**: Skill requires DMs to 3 people.
- **Input**: LLM calls `send_slack_pm` 3 times.
- **Expected**: 3 separate confirmation ephemerals. User can confirm/cancel each independently.

### STP-6.4: Recipient not found

- **Precondition**: LLM tries to DM "NonExistent".
- **Input**: `send_slack_pm(user="NonExistent", message="...")`
- **Expected**: Tool returns error. LLM handles gracefully — reports inability to find user.

### STP-6.5: LLM doesn't use DM tool

- **Precondition**: Simple reply draft, no DM needed.
- **Input**: `/copilot`
- **Expected**: Tool not invoked. Draft generated normally.

### STP-6.6: DM with long content

- **Precondition**: LLM composes a 500-word DM.
- **Input**: `send_slack_pm(user="Dan", message="<long text>")`
- **Expected**: Full content shown in confirmation ephemeral. On confirm, full content sent as DM.

### STP-6.7: Slack API failure on DM send

- **Precondition**: User confirms, but Slack API returns error.
- **Input**: User clicks Send.
- **Expected**: Ephemeral error: "Failed to send DM to @Dan." Fail fast.

### STP-6.8: Confirmation timeout

- **Precondition**: User doesn't click Send or Cancel.
- **Input**: No action taken.
- **Expected**: Ephemeral remains visible. No DM sent. No timeout (Slack ephemerals are ephemeral by nature).

## Unit Tests

**Files**: `common/tools/send_slack_pm_unit_test.py`, `common/slack/slack_bot/dm_confirmation_unit_test.py`

**Mock**: Slack API

### Test Cases

- **test_tool_returns_pending** — call `send_slack_pm` tool, assert JSON has `tool_confirmation_requested`, NOT sent
- **test_resolve_user_called** — assert `resolve_user` invoked with the user parameter
- **test_confirmation_ephemeral_sent** — assert ephemeral with Block Kit buttons sent to requesting user
- **test_confirm_sends_dm** — simulate "Send" button action, assert `slack_api.send_dm` called with correct user_id and text
- **test_cancel_no_dm** — simulate "Cancel" action, assert `send_dm` NOT called
- **test_dm_failure_error_ephemeral** — mock `send_dm` raising error, assert error ephemeral sent
- **test_user_not_found** — mock `resolve_user` returning None, assert tool returns error
- **test_tool_definition_schema** — assert schema matches LiteLLM format

### Fixtures

- `fixture_block_action_send.json` — Slack interactive action payload for "Send" button
- `fixture_block_action_cancel.json` — Slack interactive action payload for "Cancel" button

## Integration Tests

**File**: `common/tools/send_slack_pm_integration_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_llm_to_confirmation_to_send** — LLM calls tool → pending DM → ephemeral sent → simulate confirm action → DM sent
- **test_llm_to_confirmation_to_cancel** — same flow but cancel → no DM
- **test_full_draft_with_dm_tool** — `/copilot follow up with Dan` → skill triggers DM tool → confirmation → send → verify DM content matches thread context
