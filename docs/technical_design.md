[← Back to README](../README.md)

# Technical Design

## RAG

- **Hybrid vectorial DB** — filter on fields: channel, from, to, with
- **Config example**: `{RAG: {slack: [{channel: "#abc", filter: {from: "@nitzan.aviram"}, update: "live/every 1h/every 1d"}]}}`

## Configuration

- **YAML** in `~/.open_slack_copilot/`
- **Python file** — abstraction layer, so if config source changes later it just hands over the file

## Coding Standards

- **KISS** — minimum layers, no unnecessary abstraction
  - If config needs an abstract layer, it just hands the object of the file's data without ny additional abstraction.
- **Decoupled & testable** — each file/folder = standalone public package
  - No knowledge coupling to existing core logic
  - Single responsibility, high cohesion
- **Small functions, top-down** — hide checks/boilerplate in sub-functions
  - Don't validate inline — push validation into the called function
  - e.g. `prepareNextDraft()` → `getSlackClient()` → `readMessages()` → `chooseMessage()` → `prepareDraft()`
  - No `if messages is empty` — check inside `chooseMessage()`. No null check — handle inside `prepareDraft()`. Reconnect inside `getSlackClient()`. Read 3 lines of top-down logic, not 20 lines of checks.
  - **Function names replace comments.** If you'd write a comment to explain what a block does, extract it into a function whose name *is* that explanation.
  - **Do:**
    ```python
    def parse_message_from_confirmation_blocks(blocks):
        body_blocks = _filter_body_blocks(blocks)
        sorted_blocks = _sort_by_block_index(body_blocks)
        return _join_block_texts(sorted_blocks)
    ```
  - **Don't:**
    ```python
    def parse_message_from_confirmation_blocks(blocks):
        # filter to body blocks
        body_blocks = [b for b in blocks if str(b.get("block_id") or "").startswith(PREFIX)]
        if not body_blocks:
            return None, "Could not read message."
        # sort by index
        def sort_key(b):
            try: return int(str(b.get("block_id") or "").split("_")[-1])
            except: return 0
        body_blocks.sort(key=sort_key)
        # join text
        parts = []
        for b in body_blocks:
            txt = b.get("text") or {}
            if txt.get("type") == "plain_text":
                parts.append(str(txt.get("text") or ""))
        combined = "".join(parts)
        if not combined:
            return None, "Could not read message."
        return combined, None
    ```
  - Same for builders — compose from named building blocks:
    ```python
    def _build_confirmation_blocks(target_label, message, target_user_id):
        body = _message_body_blocks(message)  # raises if too long
        return [_header_block(target_label), *body, _actions_block(target_user_id)]
    ```
- **No noise** — no logs, no comments, no boilerplate
  - Logs: use `@log` decorator, function name = log message
  - Comments: only "why", never "what" or "how". Wrap small blocks as named chunks.
- **Prefer external packages** — only if keeps code short and simple
  - Exclude if package adds more code or complication (LangGraph ✓)
- **Short code** — take assumptions, skip unnecessary validations
  - No time to read code. Make it short.
- **Meaningful names** — folders, files, functions, variables must be self-explanatory
  - Name functions by *what* they do for the caller, not *how* — e.g. `agent_tool_loop` not `generate_with_tools`, `suggest_sending_dm` not `queue_pending_dm`
  - If a function only exists for one caller and the name doesn't make sense in isolation, it shouldn't exist
  - Delete dead code immediately — unused functions (e.g. `generate_json_response`) rot and confuse readers
- **Validation pattern for tool handlers** — raise a private `_ValidationError`, catch once at the top
  - **Do:**
    ```python
    def handle_tool_call(arguments_json):
        try:
            args = json.loads(arguments_json or "{}")
            prompt = _require_str(args, "prompt")
            cron = _require_str(args, "cron")
            inv = _require_invocation_context()
        except _ValidationError as e:
            return json.dumps({"error": str(e)})
        # happy path — no validation clutter
        _write_job_to_disk(job_id, prompt, cron, inv)
    ```
  - **Don't:**
    ```python
    def handle_tool_call(arguments_json):
        args = json.loads(arguments_json or "{}")
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return json.dumps({"error": "prompt is required"})
        cron = (args.get("cron") or "").strip()
        if not cron:
            return json.dumps({"error": "cron is required"})
        inv = get_invocation()
        if not inv:
            return json.dumps({"error": "No invocation context"})
        if not inv.get("thread_ts"):
            return json.dumps({"error": "Could not determine thread_ts"})
        # actual logic buried after 12 lines of checks
    ```
- **Extract blocks of 6+ lines** into named functions that explain the *what*, hiding the *how*
  - e.g. `_write_job_to_disk(...)` instead of inline mkdir + write prompt + build meta dict + write json
  - e.g. `_append_assistant_tool_calls(...)` instead of inline dict construction
  - Large composers (like `compose_system_prompt`) should read as a sequence of named steps: `_format_skills_section`, `_format_channel_rag_section`, etc.
- **Documentation** — concise `.md`, 2-7 bold-titled bullets, 2-10 words each
  - 1-7 sub-bullets per bullet
  - Don't explain obvious things — people/AI will ask or read code
  - Link the same file/section instead of repeating data

# How to execute tasks
- **Per task flow** — vision → spec `.md` → STP with all edge cases → high-quality code per [coding standards](#coding-standards) → full unit tests with mocks → integration tests (mock only Slack API & LLM)

## Tests

- **Mock only** Slack API & LLM — don't mock vectorial DB
- **Simulate** full slack input content per use case
  - Thread content, channel content as test fixtures
- **Assert** both the prompt sent to AI and the draft output
  - Expect draft given answer from vectorial DB
- **STP per use case** — prerequisite step listing all use cases and test plan
- **Edge cases** — think as different as possible:
  - Regular thread in channel
  - New messages arrive after first draft
  - First message in channel (singleton thread, not full channel context)
  - Huge threads
  - Private messages

## Folder Convention

- **Design doc per folder** — `.md` explaining goal (product or technical) and design
- **Design doc per file** — `.md` per capability or module
- **Code** — `.py` file per capability step
- **Unit tests** — `_unit_test.py` per file, mock LLM or database
- **Integration tests** — `_integration_test.py`, integrates units but still mocks LLM/DB
- **One capability** per file, one group per folder
- **General docs/** — `prd.md` and `technical_design.md` linking all folder docs

### Example: `slack/`

```
slack.md                              — index & general description of folder
slack_api/
  slack_api.py
  slack_api.md
  slack_api_unit_test.py
slack_rag/
  slack_rag.py
  slack_rag.md
  slack_rag_unit_test.py
slack_unread_messages/
  slack_unread_messages.py
  slack_unread_messages.md
  slack_unread_messages_unit_test.py
slack_bot/
  slack_bot.md
  slack_listener.py
  slack_listener_unit_test.py
  slack_listener_integration_test.py
  slack_listener_with_threads.py
  slack_listener_with_threads_unit_test.py
  slack_listener_with_threads_integration_test.py
```

## Folder Structure Draft

```
config/
  default.yaml
  config.py                     # abstraction so config source can change later

common/                         # each file/folder = standalone decoupled package
  llm/
    llm_client
      llm_client.py
      llm_client_unit_test.py
  progressive_disclosure/       # A module that knows to use skills folder, load the list of titles of skills, ask the llm and then return the relevant skill.  
      progressive_disclosure.py  
      progressive_disclosure_unit_tests.py  
  rag/
    rag.py                      # load, read by filter/embedding, schedule updates
                                # status management, concurrency guard (no parallel updates)
    rag_unit_test.py
  slack/
    slack_api/
      slack_api.py              # read threads, edit draft, send messages, get user list
      slack_api_unit_test.py
    slack_bot/
      slack_bot.md
      slack_listener.py         # register callbacks: mention, slash command, channel filter
      slack_listener_unit_test.py
      slack_listener_integration_test.py
      slack_listener_with_threads.py  # same listeners + thread context enrichment
      slack_listener_with_threads_unit_test.py
      slack_listener_with_threads_integration_test.py
    slack_rag/
      slack_rag.py              # bridges slack channels/filters → rag.py, schedules updates
                                # may need to instantiate rag.py
      slack_rag_unit_test.py
    slack_unread_messages/
      slack_unread_messages.py  # scan unread messages, return as object
      slack_unread_messages_unit_test.py
  agent/                        # LangGraph conversation + tool selection
  tools/
    build_slack_rag.py          # intent: "given my recent messages in #abc..."
    prompt_scheduler/
      prompt_scheduler.py       # cron-based, hourly/daily. Runs saved scheduled prompts sequentially
                                # config in ~/.open_slack_copilot/scheduled_prompts/sched_<hex>/prompt.txt
      prompt_scheduler_unit_test.py
    skill_repository.py         # add/list skills
                                # natural language → save rule, confirm to user
                                # stored in ~/.open_slack_copilot/skills/skill123/SKILL.md

core/
  slack_bot.py

docs/
  readme.md
  prd.md
  technical_design.md           # links to docs in code folders (e.g. slack/slack_rag/slack_rag.md)
  coding_standards.md
  tasks/ (todo/ · in_progress/ · done/)
```

- **Open question** — summarize data before RAG insert or on fetch?

