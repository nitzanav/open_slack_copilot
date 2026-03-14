# M5 — Tool: Mention People

[← Back to PRD](../../PRD.md)

## Requirements

- **Resolve user IDs** — provide the LLM with a `resolve_user(display_name)` capability so it can output `<@USER_ID>` format in drafts
- **Expose as LLM tool** — available as a LiteLLM function/tool that the LLM can call during draft generation
- **No restrictions** — LLM can mention anyone in the workspace (it's a draft, user reviews before sending)
- **Workspace user list** — `slack_api` provides `get_users()` to resolve display names to Slack user IDs
- **Seamless in drafts** — when the LLM generates a draft containing a mention, it appears as a proper `<@U123>` reference in the ephemeral

## Architecture

### Modules

- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly, plus helper functions as needed (e.g. `resolve_user` for name-to-ID lookup, cached user list)
- `common/tools/mention_people.py` — LiteLLM tool definition wrapping `slack_api.resolve_user`
- `common/llm/llm_client/llm_client.py` — extended to accept tools list and handle tool calls in the response
- `core/slack_bot.py` — passes `mention_people` tool to LLM during `prepare_draft_order`

### Data Flow

```
prepare_draft_order(thread_messages, user_text, skills)
       │
       ├── compose prompt (as before)
       ├── llm_client.generate(prompt, tools=[mention_people])
       │         │
       │         ├── LLM generates draft, calls mention_people("Nitzan")
       │         ├── mention_people → slack_api.resolve_user("Nitzan") → "<@U123>"
       │         ├── LLM receives tool result, continues generating
       │         └── final draft includes "<@U123>"
       │
       └── slack_api.send_ephemeral(draft)    ← Slack renders <@U123> as @Nitzan
```

### LiteLLM Tool Definition

```
Tool name: mention_people
Description: "Resolve a person's name to a Slack mention. Call this when you want to @mention someone in the draft."
Parameters:
  - display_name (string): the person's name or username
Returns: "<@USER_ID>" string, or error if not found
```

### Key Decisions

- **User list cached** — `get_users()` fetches once and caches for the session; workspace user list rarely changes
- **LLM resolves mentions via tool call** — not post-processing; the LLM explicitly decides who to mention
- **No restriction on who can be mentioned** — it's a draft; the user reviews it

## STP — Software Test Procedure

### STP-5.1: Happy path — LLM mentions a user

- **Precondition**: Workspace has user "Nitzan" (U123). Thread context references Nitzan.
- **Input**: `/copilot reply and mention Nitzan`
- **Expected**: LLM calls `mention_people("Nitzan")`, gets `<@U123>`, draft includes `<@U123>`. Ephemeral renders as @Nitzan.

### STP-5.2: LLM mentions multiple users

- **Precondition**: Workspace has "Nitzan" (U123) and "Dan" (U456).
- **Input**: `/copilot mention the people who should review this`
- **Expected**: LLM calls `mention_people` twice. Draft includes both `<@U123>` and `<@U456>`.

### STP-5.3: User not found

- **Precondition**: LLM tries to mention "NonExistentUser".
- **Input**: Draft generation with mention tool call.
- **Expected**: `resolve_user` returns error/None. LLM handles gracefully — either skips the mention or writes the name as plain text.

### STP-5.4: LLM doesn't use mention tool

- **Precondition**: Thread doesn't warrant mentioning anyone.
- **Input**: `/copilot`
- **Expected**: LLM generates draft without calling `mention_people`. Tool not invoked. Draft is plain text.

### STP-5.5: Ambiguous name (multiple matches)

- **Precondition**: Two users named "Alex" in workspace.
- **Input**: LLM calls `mention_people("Alex")`.
- **Expected**: Return the first match or an error with candidates list. LLM can retry with a more specific name.

### STP-5.6: User list cache

- **Precondition**: `get_users()` already called once in this session.
- **Input**: Second `mention_people` call.
- **Expected**: No additional Slack API call. Cached user list used.

## Unit Tests

**Files**: `common/tools/mention_people_unit_test.py`, `common/slack/slack_api/slack_api_unit_test.py`

**Mock**: Slack API (users.list endpoint)

### Test Cases

- **test_resolve_user_found** — mock user list with "Nitzan" → U123, assert `resolve_user("Nitzan")` returns `<@U123>`
- **test_resolve_user_not_found** — assert returns None or error message
- **test_resolve_user_case_insensitive** — "nitzan" matches "Nitzan"
- **test_resolve_user_by_username** — resolve by Slack username (not display name)
- **test_user_list_cached** — call `get_users()` twice, assert Slack API called only once
- **test_tool_definition_schema** — assert tool schema matches LiteLLM expected format
- **test_ambiguous_name** — two users named "Alex", assert deterministic behavior

### Fixtures

- `fixture_users_list.json` — workspace users list (10 users with IDs, display names, usernames)

## Integration Tests

**File**: `common/tools/mention_people_integration_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_draft_with_mention_tool** — simulate LLM calling mention_people during generation → tool resolves → draft includes `<@USER_ID>`
- **test_draft_without_mention** — LLM generates without calling tool → no tool invocation, draft is plain text
- **test_mention_in_full_flow** — `/copilot mention Nitzan in the reply` → full M1 flow with tool → ephemeral contains `<@U123>`
