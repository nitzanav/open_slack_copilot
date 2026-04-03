# Follow Up

When asked to follow up with users on an action item from a Slack thread.

## Goal

Register a `scheduled_prompt` that re-checks completion and DMs users who have not acted.

## Steps

Two contexts — follow the matching path.

### A. First invocation (user asks to follow up)

1. **Infer check frequency or exact date** - daily, hourly or exact date. Default: daily.
2. **Resolve target users** — Slack tool for user groups; use mentions directly if listed.
3. **Completion criteria** (pick from context):
   - **Emoji reaction** — e.g. ✅ (`:white_check_mark:`). Reactions and the users who set them are already included in the thread context.
   - **Thread confirmation** — acknowledgment reply in the thread.
   - **External status** — e.g. Jira; use the right tool to verify.
4. **`scheduled_prompt`** — **Description:** user IDs; completion criteria and how to check each user; frequency. **Instruction:** (1) check each user, (2) DM anyone not done with action summary + thread link.

   Example:

   ```
   description: |
     RFC review in #backend (thread: https://slack.com/archives/C04XX/p17120...).
     Users: U0A1B2C, U3D4E5F, U6G7H8I.
     Done when: ✅ on original message (reactions in thread context).
     Frequency: daily.

   instruction: |
     1. From thread context for C04XX / p17120..., see who has ✅.
     2. For [U0A1B2C, U3D4E5F, U6G7H8I] missing ✅, DM with reminder + thread URL.
   ```

### B. Scheduled run (skill disclosed inside a scheduled prompt)

1. **Check each user** — thread context (reactions, replies) vs criteria in the scheduled prompt.
2. **Remind** — DM if not done: action item + thread link; polite, brief.

## Tone

Polite and brief. No guilt; urgent tone only if the original message was urgent.
