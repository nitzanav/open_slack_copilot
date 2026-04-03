# Open Slack CoPilot

[← Back to README](../README.md)

# Product Requirements

## Terms

- **RAG** — on-demand retriever tool from vectorial DB (Qdrant with fastembed `BAAI/bge-small-en-v1.5`)

## Use Cases

### Implemented

- **Draft replies** — via message shortcut, @mention, or `/copilot` slash command
  - Uses RAG of the relevant channel + cross-channel RAG
  - Using list of predefined **reply** skills selected via progressive disclosure (same pipeline for shortcut, @mention, and slash command)
  - **Follow-ups on action items** — example **reply** skill [`skill_examples/reply/follow_up/SKILL.md`](../skill_examples/reply/follow_up/SKILL.md) (install under `~/.open_slack_copilot/skills/reply/follow_up/`); uses `schedule_prompt`, `list_usergroup_members`, `send_slack_pm`. Capability map: [M15](milestones/m15_follow_ups_use_case/m15_follow_ups_use_case.md)
- **Draft Revise** — refine a generated draft with free-text instructions via a modal
- **Send DM** — LLM can invoke `send_slack_pm` tool; the config owner approves/rejects via ephemeral confirmation
- **Scheduled prompts** — LLM can invoke `schedule_prompt` tool to register a cron job that re-runs a prompt on a thread (e.g. follow-up reminders); see [M15](milestones/m15_follow_ups_use_case/m15_follow_ups_use_case.md) for tooling details and remaining gaps (e.g. external status checks)

### Future / Not Implemented

- [**Follow-ups — remaining gaps**](milestones/m15_follow_ups_use_case/m15_follow_ups_use_case.md) — e.g. Jira / external completion signals; see milestone capability map
- **Watching Channel supervision** — requests are handled properly? on time?
- **Create jira ticket** for this action item according to my policy
- **Remind me** if I didnt reply on time
- **Urgent pending replies** — whenever there is a talk on urgent bug, notify me in DM
- **Tech leader alerts** — let me know when there is a significant architectural change without a discussion
- **Notify me** when they talk about a feature that I'm part of
- **Answer support tickets**
- **Notify when there is a customer with too many issues**
- Notify others —
  - when they pasted API key in a public channel
  - Don't change data of merchants, even on their behalf
  - they didn't respond fast enough - example: dev-on-call didn't see an alert


## Skills/Tools

- **Saved Skills** — define reusable behaviors in `~/.open_slack_copilot/skills/`
  - Two kinds defined in code (`progressive_disclosure.py`):
    - **"reply" skills** — selected via progressive disclosure when drafting a reply (**implemented**); used for `/copilot`, message shortcut, and **`@CoPilot`** app mention. Example: [Follow Up](../skill_examples/reply/follow_up/SKILL.md) (`skills/reply/follow_up/`)
    - **"watcher" skills** — intended for passive channel watching (M4); kind exists in code but is **not wired** into the pipeline yet — distinct from **reply** skills such as Follow Up
  - Default reply instruction can be overridden via `~/.open_slack_copilot/skills/reply/default.md`
- **Channel RAG** — build and use retrieval from channel data
  - Build RAG of a specific channel (messages indexed with reaction summaries)
  - Auto-checks if live RAG already exists & its status (`is_ready`, `build_if_missing`)
  - Cross-channel RAG built on startup for channels listed in `rag.cross_channel` config
  - Periodic rebuild via `rag.slack[].update: "every <duration>"` config
- **Scheduled prompts** — LLM tool `schedule_prompt` with 5-field cron, optional `expires_in_days` (default 7, max 14)
  - Jobs stored on disk at `~/.open_slack_copilot/scheduled_prompts/<job_id>/`
  - Reloaded from disk on restart via APScheduler
  - Scheduled runs deliver draft ephemerals to the **config owner** (not the original user)
  - Nested scheduling is prevented (`schedule_prompt` tool excluded from scheduled runs)
- **Send Slack PM** — LLM tool `send_slack_pm`; resolves user, queues DM for **config owner approval** via ephemeral Block Kit (Send / Cancel)
- **User group members** — LLM tool `list_usergroup_members`; Slack API `usergroups.list` + `usergroups.users.list` via `slack_api` (requires bot scope `usergroups:read`)
- **Example threads** — hard-coded file (`common/slack/example_threads.json`) loaded into the system prompt


## Milestones

- **M1: Slash command (implemented)** — compose response draft
  - [M1.1: thread data and text after slash command](milestones/m1_slash_command/m1_1_thread_draft.md)
    - listen `/copilot` via `slack_listener_with_threads.py` (requires use inside a thread)
    - `prepare_draft(...)` in `copilot_pipeline.py`:
      - Compose system prompt (skills, RAG context, cross-channel RAG, example threads, thread messages, instruction)
      - Run `agent_tool_loop` with `schedule_prompt`, `send_slack_pm`, and `list_usergroup_members` tools
      - Send draft as ephemeral with Revise button via `send_draft_ephemeral_with_revise`
  - [M1.2: Reply skills](milestones/m1_slash_command/m1_2_reply_skills.md) — add relevant reply skills (progressive disclosure) to the context
  - [M1.3: Channel RAG](milestones/m1_slash_command/m1_3_channel_rag.md) — add to the system prompt relevant messages from current channel via RAG
    - If RAG not ready → initiate build, send ephemeral "Preparing RAG for #X, will update when done"
    - Send draft ephemeral when RAG ready
    - Add hard-coded file of example threads & answers
  - [M1.4: Cross-channel RAG](milestones/m1_slash_command/m1_4_cross_channel_rag.md) — add to the system prompt relevant messages from configured cross-channels
    - If RAG missing → build on startup for channels in `rag.cross_channel` config
- **Message shortcut (implemented)** — `draft_with_copilot` message shortcut (three-dot menu → Connect to apps). Resolves context: on a channel root post → recent channel tail (`copilot_channel_context_limit` messages); in a thread → thread messages. Runs the same `prepare_draft` + ephemeral flow. Registered in `slack_listener_with_threads.py`.
- **App @mention (implemented)** — `@CoPilot` in a channel runs the same draft + ephemeral flow as the message shortcut (optional text after the mention). Context: recent channel messages on a root post, or the thread when the mention is in a thread. Filters out self-mentions and subtyped messages. Registered in `slack_listener_with_threads.py` with `app_mention`; see README.
- **Draft Revise (implemented)** — Successful drafts are sent as Block Kit ephemerals with a **Revise** button (`common/slack/slack_bot/draft_revise_actions.py`). The user gets a modal with an instruction field (placeholder hint), optional checkbox to include the original draft in the prompt, and submit re-runs `prepare_draft` with the same Slack context (thread vs channel tail) as the original generation. Applies to `/copilot`, shortcut, @mention, and scheduled prompt results to the config owner. Posting the draft to the channel (as user or bot) is out of scope for this milestone.
- **DM confirmation (implemented)** — When the LLM invokes `send_slack_pm`, the config owner (`config_owner_user_id`) gets an ephemeral Block Kit confirmation with Send / Cancel buttons (`common/slack/slack_bot/dm_confirmation.py`). Only the config owner can approve.
- [**M6: Tool - send slack PM (implemented)**](milestones/m6_send_slack_pm/m6_send_slack_pm.md) — `send_slack_pm` LiteLLM tool; resolves user via `slack_api.resolve_user`, queues DM for config owner confirmation
- [**M7: Skill scheduler (implemented)**](milestones/m7_skill_scheduler/m7_skill_scheduler.md) — `schedule_prompt` LiteLLM tool lets the LLM register a cron-based prompt on a thread. Jobs are stored on disk, reloaded on restart. Scheduled runs call `prepare_draft` and send the result as an ephemeral to the config owner.

### Not Implemented

- [**M15: Follow-ups use case**](milestones/m15_follow_ups_use_case/m15_follow_ups_use_case.md) — document and track implementation of the [Follow Up **reply** skill example](../skill_examples/reply/follow_up/SKILL.md): infer cadence, resolve targets, completion checks, `schedule_prompt`, scheduled re-runs, DMs; maps each capability to code or **to be done**
- [**M2: Auto-draft replies to mentions**](milestones/m2_auto_draft_mentions/m2_auto_draft_mentions.md) — listen for messages where the user is @mentioned, use reply skills (progressive disclosure) to draft a reply automatically. Send ephemeral with suggested draft. Requires a `message` event listener (not yet wired).
  - reuses M1 flow with reply skills
  - use case — user wants to draft answers for all their mentions
- [**M4: Watch channels and match skills**](milestones/m4_watch_channels_match_skills/m4_watch_channels_match_skills.md) — listen to all messages in configured watch channels, match "channel watcher skills" via progressive disclosure. Only acts when a skill matches (expected ~10% of messages). Requires a `message` event listener and wiring watcher skills into the pipeline (not yet implemented).
- [**M5: Tool - mention people**](milestones/m5_mention_people/m5_mention_people.md) — it might not need something special


## Future Milestones (notes)

- **M8**: `/copilot watch #channel` — slash command to add channels to watch config YAML
- **M9**: Smart RAG checkpoint — store last-indexed timestamp per channel, fetch only newer messages on restart (instead of always re-fetching from config checkpoint)
- **M10**: Retry with backoff — silent retry on LLM/Slack API failures before showing error
- **M11**: Replace hard-coded example threads file with RAG-sourced examples
- **M12**: Auto-detect popular/related channels by volume/activity for cross-channel RAG
- **M13**: Rate limiting for M4 watched channels — protect against skills matching too frequently
- **M14**: Channel watcher skill channel filter — JSON file in skill folder to restrict skill to specific channels

