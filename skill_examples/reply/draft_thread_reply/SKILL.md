# Draft Thread Reply

**Reply skill** — Default skill for drafting thread replies. Install under `~/.open_slack_copilot/skills/reply/draft_thread_reply/` (copy from the repo's `skill_examples/reply/draft_thread_reply/`).

Reply accurately, be short and concise, focus on what matters for the answer. When you have the final wording, call **send_thread_reply_on_behalf_of_requester** once with the full message text so the **requester** (the person who started this run) can confirm; the post goes to the thread on their behalf when Slack user OAuth is connected.
