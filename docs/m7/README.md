# M7 — Skill scheduler (user docs)

[← Back to PRD](../PRD.md) · [Full milestone spec](../milestones/m7_skill_scheduler/m7_skill_scheduler.md)

## What it does

- **Recurring thread checks** — After `/copilot follow up`, the model can register a daily (or cron) job for that thread.
- **Disk-backed jobs** — Each job is a folder under `~/.open_slack_copilot/scheduled_skills/<id>/` with `SKILL.md` and `metadata.json`.
- **LLM decides completion** — On each run, the model reads the thread and decides if required actions (reply, emoji, confirmation) are done.
- **DM reminders** — Non-completers get DMs via the M6 flow (owner confirms before send).
- **Backoff and expiry** — Reminders use exponential backoff (starting at 1 day) and stop after three weeks.

## Skill files here

| File | Use |
|---|---|
| [follow_up_channel_watcher.md](follow_up_channel_watcher.md) | Example **channel watcher** skill text for follow-up + scheduling |

Copy into `~/.open_slack_copilot/skills/channel_watcher/<name>/SKILL.md` and tune for your workspace.

## Related

- **M6** — [send Slack PM](../milestones/m6_send_slack_pm/m6_send_slack_pm.md) (confirmation for reminder DMs)
- **M4** — [watch channels & match skills](../milestones/m4_watch_channels_match_skills/m4_watch_channels_match_skills.md)
