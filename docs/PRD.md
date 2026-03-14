# Open Slack CoPilot

[← Back to README](../README.md)

# Product Requirements

## Terms

- **RAG** — on-demand retriever tool from vectorial DB (shorter term)

## Use Cases

- **Draft replies** when mentioned
  - By default, use RAG of the relevant channel
  - Using list of predefined "reply skills"
- **Followups** — DM non-responders
- **Tech leader alerts** — notify when something requires attention
- **Channel supervision** — watch for interesting behavior or content
  - e.g. technical discussions
- **Urgent pending replies** — surface top unread
  - What counts as urgent? Prioritize top items
- **Answer support tickets**

## Skills/Tools

- **Saved Skills** — define reusable behaviors
  - "Followup" = whoever didn't reply/emoji, DM them privately
  - Exponential backoff from 1 day, expires after 3 weeks
  - Thee are two types of skills 
    - "reply skills" - will be selected when you are mentioned 
    - "channel watcher skills" - will be selected on channels you chose to watch
- **Channel RAG** — build and use retrieval from channel data
  - Build RAG from my answers (all or specific channel)
  - Build RAG of a specific channel
  - Keyword triggers — e.g. "answer like Dani on #support" → hybrid filter on `from`
  - Auto-checks if live RAG already exists & its status
- **Scheduled skills** — some tasks need hourly/timed checks
  - e.g. followup reminders need periodic scan to decide if to remind

## `slack_bot.py` Milestones

- **M1: Slash command** to compose response draft 
  - [M1.1: only thread data and the text after slash command](milestones/m1_slash_command/m1_1_thread_draft.md)
    - listen `/copilot` via `slack_listener_with_threads.py`
    - `prepare_draft_order(thread)`
      - Compose system prompt
      - Edit the draft order
      - Send as ephemeral in same channel
      - System prompt includes the thread context
  - [M1.2: Reply skills](milestones/m1_slash_command/m1_2_reply_skills.md) — add relevant reply skills (progressive disclosure) to the context 
  - [M1.3: Channel RAG](milestones/m1_slash_command/m1_3_channel_rag.md) — add to the system prompt 10 most relevant *summarized* messages from current channel via RAG
    - If RAG config missing → initiate preparation, send ephemeral "Preparing RAG for #X, will update when done"
    - Send draft ephemeral when RAG ready
    - Add hard-coded file of example threads & answers
  - [M1.4: Cross-channel RAG](milestones/m1_slash_command/m1_4_cross_channel_rag.md) — add to the system prompt 10 relevant from popular/related channels
    - If RAG missing → initiate, send ephemeral "Creating RAG for #X, #Y, #Z", wait for it
    - On installation, build RAG of popular threads
- [**M2: Auto-draft replies to mentions**](milestones/m2_auto_draft_mentions/m2_auto_draft_mentions.md) — listen via `slack_listener_with_threads.py`, filter for messages where the user is @mentioned, use reply skills (progressive disclosure) to draft a reply, always drafts (falls back to default reply skill). Send ephemeral with suggested draft.
  - reuses M1 flow with reply skills
  - use case — user wants to draft answers for all their mentions
- [**M4: Watch channels and match skills**](milestones/m4_watch_channels_match_skills/m4_watch_channels_match_skills.md) — listen to all messages in configured watch channels via `slack_listener_with_threads.py`, match "channel watcher skills" via progressive disclosure. Only acts when a skill matches (expected ~10% of messages). Send ephemeral with suggested draft.
- [**M5: Tool - mention people**](milestones/m5_mention_people/m5_mention_people.md) - it might not need something special
- [**M6: Tool - send slack PM**](milestones/m6_send_slack_pm/m6_send_slack_pm.md) — needs slack_api support for sending DMs, exposed as a LiteLLM tool for the LLM to call as a function
- [**M7: skill scheduler**](milestones/m7_skill_scheduler/m7_skill_scheduler.md) - user write `/copilot follow up` this will match a channel watcher skill - Check once a day at 11am, and send PM to users that were mentioned in the thread and didn't do the required action (set emoji, reply, or confirm what was required)` the llm then will disclose the schedule tool to enable the llm to register a prompt to the tool with the thread id to next day.

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
- **No noise** — no logs, no comments, no boilerplate
  - Logs: use `@log` decorator, function name = log message
  - Comments: only "why", never "what" or "how". Wrap small blocks as named chunks.
- **Prefer external packages** — only if keeps code short and simple
  - Exclude if package adds more code or complication (LangGraph ✓)
- **Short code** — take assumptions, skip unnecessary validations
  - No time to read code. Make it short.
- **Meaningful names** — folders, files, functions, variables must be self-explanatory
- **Documentation** — concise `.md`, 2-7 bold-titled bullets, 2-10 words each
  - 1-7 sub-bullets per bullet
  - Don't explain obvious things — people/AI will ask or read code
  - Link the same file/section instead of repeating data

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
    skills_scheduler/
      skills_scheduler.py       # cron-based, hourly/daily. Runs saved scheduled prompts sequentially
                                # config in ~/.open_slack_copilot/scheduled_skills/skill123/SKILL.md
      skills_scheduler.md
      skills_scheduler_unit_test.py
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


## Future Milestones (notes)

- **M8**: `/copilot watch #channel` — slash command to add channels to watch config YAML
- **M9**: Smart RAG checkpoint — store last-indexed timestamp per channel, fetch only newer messages on restart (instead of always re-fetching from config checkpoint)
- **M10**: Retry with backoff — silent retry on LLM/Slack API failures before showing error
- **M11**: Replace hard-coded example threads file with RAG-sourced examples
- **M12**: Auto-detect popular/related channels by volume/activity for cross-channel RAG
- **M13**: Rate limiting for M4 watched channels — protect against skills matching too frequently
- **M14**: Channel watcher skill channel filter — JSON file in skill folder to restrict skill to specific channels

# How to execute tasks
- **Per task flow** — vision → spec `.md` → STP with all edge cases → high-quality code per [coding standards](#coding-standards) → full unit tests with mocks → integration tests (mock only Slack API & LLM)
