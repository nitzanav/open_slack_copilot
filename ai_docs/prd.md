# Product Requirements (Summary)

> Full document: [docs/PRD.md](../docs/PRD.md)

## What It Is

A Slack copilot that drafts replies, manages scheduled prompts, and sends DMs on the user's behalf — powered by LLM + RAG over Slack channel history (Qdrant / fastembed).

## Implemented Features

- **Draft replies** — via message shortcut, @mention, or `/copilot`; uses channel RAG + cross-channel RAG + **reply** skills (progressive disclosure on each of those entry points)
- **Follow-ups (action items)** — implemented as a **reply** skill ([`skill_examples/reply/follow_up/SKILL.md`](../skill_examples/reply/follow_up/SKILL.md)); install under `~/.open_slack_copilot/skills/reply/follow_up/`; uses `schedule_prompt`, `list_usergroup_members`, `send_slack_pm`
- **Draft revise** — refine a draft with free-text instructions via modal
- **Send DM** — LLM tool `send_slack_pm`; requesting user approves/rejects via ephemeral
- **Scheduled prompts** — LLM tool `schedule_prompt`; cron-based, stored on disk, reloaded on restart
- **Saved skills** — reusable behaviors in `~/.open_slack_copilot/skills/` (**reply** skills drive `/copilot`, shortcut, and @mention drafts; **watcher** kind exists for future M4 channel watch, not wired yet)

## Key Implementation Details

- Entry points: `/copilot` slash command, message shortcut, `@CoPilot` mention → all run `prepare_draft` → ephemeral with Revise button
- Channel RAG auto-builds if missing; cross-channel RAG built on startup from config
- Scheduled runs deliver drafts as ephemerals to the user who created the schedule
- DM confirmation flow: ephemeral Block Kit Send/Cancel to the requesting user

## Not Yet Implemented

- Auto-draft replies to @mentions (M2)
- Watch channels & match watcher skills (M4)
- Future: watch command, smart RAG checkpoint, retry with backoff, rate limiting
