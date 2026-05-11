# Product Requirements (Summary)

> Full document: [docs/PRD.md](../docs/PRD.md)

## What It Is

A Slack copilot that drafts replies, manages scheduled prompts, and sends DMs on the user's behalf — powered by LLM + RAG over Slack channel history (Qdrant / fastembed).

## Implemented Features

- **Draft replies** — via message shortcut, @mention, or `/copilot`; uses channel RAG + cross-channel RAG + **reply** skills (progressive disclosure on each of those entry points)
- **Thread reply (on behalf of the requester)** — LLM tool `send_thread_reply_on_behalf_of_requester` with confirm/revise; posts in the thread on behalf of the requester when a user OAuth token exists in the `slack_user_oauth` data collection (`~/.open_slack_copilot/.../`), otherwise confirm surfaces an OAuth error
- **Data layer** — pluggable `common/data_layer/` file-backed key-value store (default under `~/.open_slack_copilot/`); prepared for a DB backend later
- **Follow-ups (action items)** — implemented as a **reply** skill ([`skill_examples/reply/follow_up/SKILL.md`](../skill_examples/reply/follow_up/SKILL.md)); install under `~/.open_slack_copilot/skills/reply/follow_up/`; uses `schedule_prompt`, `list_usergroup_members`, `send_dm_as_app`
- **Reply confirmation + Revise** — refine a reply with free-text instructions via modal
- **Send DM** — LLM tool `send_dm_as_app`; requesting user approves/rejects via ephemeral (tool confirmation). `send_dm_on_behalf_of_requester` (user OAuth) is defined but not registered yet.
- **Scheduled prompts** — LLM tool `schedule_prompt`; cron-based, stored on disk, reloaded on restart
- **Saved skills** — reusable behaviors in `~/.open_slack_copilot/skills/` (**reply** skills drive `/copilot`, shortcut, and @mention drafts; **watcher** kind exists for future M4 channel watch, not wired yet)
- **Skill thumbs-up learning** — every run picks exactly one skill (two-stage selection); tool-confirmation ephemerals expose a 👍 button. Clicked runs are appended to `<skill_dir>/thumbs_up.json` and rendered as inline examples in that skill's disclosure on subsequent runs. The run snapshot (tool_name, payload, text, run_log) lives in the `skill_runs` data_layer collection.

## Key Implementation Details

- Entry points: `/copilot` slash command, message shortcut, `@CoPilot` mention → all run `run_react_loop` → reply confirmation ephemeral with Revise button
- Channel RAG auto-builds if missing; cross-channel RAG built on startup from config
- Scheduled runs deliver replies as confirmation ephemerals to the user who created the schedule
- Tool confirmation flow: ephemeral Block Kit Confirm/Revise for DMs, thread reply, and similar tools; thread content is posted on behalf of the requester when OAuth is connected

## Not Yet Implemented

- Auto-draft replies to @mentions (M2)
- Watch channels & match watcher skills (M4)
- Future: watch command, smart RAG checkpoint, retry with backoff, rate limiting
