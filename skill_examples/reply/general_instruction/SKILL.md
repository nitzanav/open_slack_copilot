# General Instruction

**Reply skill** — Install under `~/.open_slack_copilot/skills/reply/general_instruction/` (copy from the repo’s `skill_examples/reply/general_instruction/`). Loaded with other **reply** skills on **`@CoPilot`**, **Draft with CoPilot**, and **`/copilot`** runs.

## When this applies

Use this skill when **no other installed reply skill is clearly more specific**, and the user’s message is an **action request** or imperative—not only thread drafting or tone/style tweaks.

Typical phrasing includes things like: create or update a ticket (e.g. Jira), send a DM or channel message for them, schedule or cancel something, run a lookup and act on the result, file a doc, post an update, remind someone, or “do X on my behalf.”

## What to do

1. **Treat it as a task** — Prefer carrying out the request with the tools and APIs available in this environment (Slack tools, MCP servers, shell, codebase) rather than answering with generic advice alone.
2. **Minimal clarification** — Ask only for details that block execution (missing recipient, channel, ticket project, etc.). If defaults are safe and reversible, proceed.
3. **Confirm when policies require it** — If the stack uses confirmation flows for destructive or sensitive actions, follow those; otherwise execute.
4. **Slack-specific** — When the outcome is a Slack message, use the appropriate send/post tools for the context (thread vs DM vs channel) and respect existing confirmation patterns for posting on behalf of the user.

If the user only wants wording for a reply with no separate side-effect (no ticket, no DM, no external system), prefer **`draft_thread_reply`** or another specialized reply skill instead of this one.
