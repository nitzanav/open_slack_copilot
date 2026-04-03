# Follow Up

**Reply skill** — Install under `~/.open_slack_copilot/skills/reply/follow_up/` (copy from the repo’s `skill_examples/reply/follow_up/`). The bot loads **reply** skills via progressive disclosure on every draft: **`@CoPilot`**, the **Draft with CoPilot** message shortcut, and **`/copilot`** in a thread (same `prepare_draft` path). This skill applies when the thread and instruction match (e.g. “please follow up”).

When asked to follow up with users on an action item from a Slack thread.

## Goal

Register a **`schedule_prompt`** job that re-checks completion and DMs users who have not acted.

## Steps

Two contexts — follow the matching path.

### A. First invocation (user asks to follow up)

1. **Infer check frequency or exact date** - daily, hourly or exact date. Default: daily.
2. **Resolve target users** — For **named people**, read **`<@U…>`** from thread message text (Slack stores mentions that way) and use the **Users** roster in context for id ↔ name. For **user groups**, call `list_usergroup_members` (S… id, `<!subteam^S…>` in the message, or handle).
3. **Completion criteria** (pick from context):
   - **Emoji reaction** — e.g. ✅ (`:white_check_mark:`). Reactions and the users who set them are already included in the thread context.
   - **Thread confirmation** — acknowledgment reply in the thread.
   - **External status** — e.g. Jira; use the right tool to verify.
4. **`schedule_prompt`** — **`prompt`:** embed user IDs, completion criteria, how to check each user, and thread/channel refs. **`cron`:** 5-field UTC (hourly, daily, or a specific clock time). **`expires_in_days`:** optional; if omitted, default is **7** days; **maximum 14**. The scheduler stops firing after that (`expires_at` on the job). For follow-ups, pass **`expires_in_days: 14`** unless the thread clearly needs a shorter run.

   Example (shape of the tool call):

   ```
   prompt: |
     Follow-up: RFC review in #backend, thread https://slack.com/archives/C04XX/p17120...
     Users: U0A1B2C, U3D4E5F, U6G7H8I. Done when: ✅ on original message (reactions in thread context).
     1. From thread context, see who has ✅.
     2. For anyone missing ✅, DM reminder + thread URL.
   cron: "0 9 * * *"
   expires_in_days: 14
   ```

### B. Scheduled run (same reply pipeline; instruction is the saved prompt)

1. **Check each user** — thread context (reactions, replies) vs criteria in the scheduled prompt.
2. **Remind** — DM if not done: action item + thread link; polite, brief.

## Tone

Polite and brief. No guilt; urgent tone only if the original message was urgent.
