# Open Slack CoPilot

[← Back to README](../README.md)

# Product Requirements

## Terms

- **RAG** — on-demand retriever tool from vectorial DB (shorter term)

## Use Cases

- **Draft replies** when mentioned
  - By default, use RAG of the relevant channel
  - Using list of predefined "reply skills"
- **Followups** — When I request to followup to report when done to a group of people, remind them.
- **Watching Channel supervision** — requests are handled properly? on time?
- **Create jira ticket** for this action item according to my policy
- **Remind me** if I didnt reply on time
- **Urgent pending replies** — whenever there is a talk on urgent bug, notify me in DM
- **Tech leader alerts** — let me know when there is a significant architectural change without a discussion
- **Notify me** when they talk about my a feature that I part of
- **Answer support tickets**
- **Notify when there is a customer with too many issue**
- Notify others - 
  - then they pasted API key in a public channel
  - Don't change data of merchants, even on their behalf
  - they didn't respond fast enough - example: dev-on-call didn't see an alert


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
- **Scheduled prompts** — some tasks need hourly/timed checks
  - e.g. followup reminders need periodic scan to decide if to remind
  - Scheduled prompts should use "watcher" skills as context


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
- **App @mention (implemented)** — `@CoPilot` in a channel runs the same draft + ephemeral flow as the message shortcut (optional text after the mention like `/copilot`). Context: recent channel messages on a root post, or the thread when the mention is in a thread. Registered in `slack_listener_with_threads.py` with `app_mention`; see README.
- **Draft Revise (implemented)** — Successful drafts are sent as Block Kit ephemerals with a **Revise** button (`common/slack/slack_bot/draft_revise_actions.py`). The user gets a modal with an instruction field (placeholder hint), optional checkbox to include the original draft in the prompt, and submit re-runs `prepare_draft` with default interactive tools and the same Slack context (thread vs channel tail) as the original generation. Applies to `/copilot`, shortcut, @mention, and scheduled prompt results to the config owner. Posting the draft to the channel (as user or bot) is out of scope for this milestone.
- [**M2: Auto-draft replies to mentions**](milestones/m2_auto_draft_mentions/m2_auto_draft_mentions.md) — listen via `slack_listener_with_threads.py`, filter for messages where the user is @mentioned, use reply skills (progressive disclosure) to draft a reply, always drafts (falls back to default reply skill). Send ephemeral with suggested draft.
  - reuses M1 flow with reply skills
  - use case — user wants to draft answers for all their mentions
- [**M4: Watch channels and match skills**](milestones/m4_watch_channels_match_skills/m4_watch_channels_match_skills.md) — listen to all messages in configured watch channels via `slack_listener_with_threads.py`, match "channel watcher skills" via progressive disclosure. Only acts when a skill matches (expected ~10% of messages). Send ephemeral with suggested draft.
- [**M5: Tool - mention people**](milestones/m5_mention_people/m5_mention_people.md) - it might not need something special
- [**M6: Tool - send slack PM**](milestones/m6_send_slack_pm/m6_send_slack_pm.md) — needs slack_api support for sending DMs, exposed as a LiteLLM tool for the LLM to call as a function
- [**M7: skill scheduler**](milestones/m7_skill_scheduler/m7_skill_scheduler.md) - user write `/copilot follow up` this will match a channel watcher skill - Check once a day at 11am, and send PM to users that were mentioned in the thread and didn't do the required action (set emoji, reply, or confirm what was required)` the llm then will disclose the schedule tool to enable the llm to register a prompt to the tool with the thread id to next day.



## Future Milestones (notes)

- **M8**: `/copilot watch #channel` — slash command to add channels to watch config YAML
- **M9**: Smart RAG checkpoint — store last-indexed timestamp per channel, fetch only newer messages on restart (instead of always re-fetching from config checkpoint)
- **M10**: Retry with backoff — silent retry on LLM/Slack API failures before showing error
- **M11**: Replace hard-coded example threads file with RAG-sourced examples
- **M12**: Auto-detect popular/related channels by volume/activity for cross-channel RAG
- **M13**: Rate limiting for M4 watched channels — protect against skills matching too frequently
- **M14**: Channel watcher skill channel filter — JSON file in skill folder to restrict skill to specific channels

