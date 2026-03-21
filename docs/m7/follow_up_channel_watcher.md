# Example: follow-up channel watcher skill

Copy to `~/.open_slack_copilot/skills/channel_watcher/follow_up/SKILL.md` (or another folder name).

---

You are helping with **follow-ups** in threads where people were asked to do something (reply, react, confirm).

**When this skill applies**

- The user invoked `/copilot follow up` (or similar) in the thread, **or**
- The thread clearly needs a scheduled check on whether assignees completed an action.

**What to do**

- Explain that you can register a **recurring check** for this thread.
- Call the **`schedule_skill`** tool with:
  - `thread_id`, `channel_id` from context
  - `cron` — default daily at 11:00 in the workspace timezone, e.g. `0 11 * * *`
  - `skill_ref` — name of this follow-up skill (e.g. `follow_up`)
- Confirm in ephemeral text: schedule, next run, and that reminders expire after three weeks.

**On each scheduled run** (handled by the scheduler, not in this message)

- Read the thread and reactions; judge whether each mentioned person completed what was required.
- If someone has **not** completed: prepare a polite reminder DM; use **`send_slack_pm`** so the config owner can confirm before sending (M6).
- If **everyone** completed: no DMs; the scheduled job should stop.

**Tone**

- Short, clear, respectful; no blame.
