# Open Slack CoPilot

AI-powered Slack bot for drafting replies, RAG-assisted context, and skill-based automation.

## How to Use

1. [Reply with Open Slack CoPilot](#reply-with-open-slack-copilot)
2. [Install the Slack App](#install-the-slack-app)
3. [Install Slack CoPilot](#install-slack-copilot)
4. [Run Slack CoPilot](#run-slack-copilot)
5. [Define Skills](#define-skills)

For examples of useful skills, see [`docs/examples/`](docs/examples/).

---

## Use Case: Follow Up on Action Items

A development manager posts a message to a user group asking everyone to complete a task (e.g. update on-call rotations, review a document, acknowledge a policy change). Instead of manually chasing people, the manager asks CoPilot to handle follow-ups.

**Follow Up** — install under `~/.open_slack_copilot/skills/follow_up/` (copy from [`skill_examples/follow_up/`](skill_examples/follow_up/SKILL.md)). Skills are chosen on the same flows as any draft — **`@CoPilot`**, the **Draft with CoPilot** message shortcut (opens a dialog for your instruction, then drafts), and **`/copilot`** in a thread.

### Flow

1. **Manager sends a message** in a channel mentioning a user group:
   > `@backend-team` Please review the RFC and mark ✅ when done.
2. **In the thread**, the manager writes:
   > `@CoPilot` please follow up
3. Progressive disclosure can include the **Follow Up** skill when it matches the thread and instruction; the model then follows that skill (schedule checks, DMs, etc.).

### What CoPilot does

1. **Infers check frequency** — hourly, daily, or a specific date based on urgency and any stated deadline (default: daily).
2. **Resolves target users** — reads **`<@U…>`** mentions from thread text where applicable, or uses **`list_usergroup_members`** for user groups (requires bot scope `usergroups:read`).
3. **Determines completion criteria** — infers the appropriate signal from context: an emoji reaction (e.g. ✅), a thread reply, or an external status update (e.g. Jira ticket).
4. **Creates a scheduled prompt** — calls the **`schedule_prompt`** tool (`prompt`, `cron`, optional `expires_in_days`) so the check repeats until the job expires.
5. **On each scheduled run** — checks every user against the criteria and sends a friendly DM reminder to anyone who hasn't completed, with a link back to the original thread.

> **Example DM:** "Hi! Friendly reminder — the backend team was asked to review the RFC. It looks like you haven't confirmed yet. Here's the original thread: _[link]_"

See the full skill definition at [`skill_examples/follow_up/SKILL.md`](skill_examples/follow_up/SKILL.md).

---

## Reply with Open Slack CoPilot

Go to a message you were mentioned in (or any message you want to draft a reply for):

1. **Hover** over the message in Slack.
2. Click the **&#x22EE;** (three-dot menu) on the right side of the message.
3. **Connect to apps** → **Draft with CoPilot**.
4. A **dialog** opens. Edit **Instruction for the LLM** if you want; it defaults to **Draft reply on my behalf for this thread**. Click **Submit**.
5. Expect an ephemeral message from the bot with the suggested reply.
6. Click **Revise** to open a modal, edit the instruction (the default includes the current draft), and submit to regenerate the reply. Posting the draft to the channel as you is not implemented yet.

### Mention @CoPilot

In a channel where the app is invited, you can **@mention** the bot (for example **@CoPilot**) on a message:

1. Type your mention in the message (optionally add instructions after it, same idea as text after `/copilot`).
2. Send the message.
3. You get an **ephemeral** draft in the thread under that message, like the shortcut flow (use **Revise** on that ephemeral as above).

**Context**: On a **channel root** message (not in a thread), the draft uses the most recent messages in the channel (see `copilot_channel_context_limit` in [`config/default.yaml`](config/default.yaml)). **Inside a thread**, the draft uses that thread’s messages.

---

## Install the Slack App

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**.
2. Choose **From a manifest** and select your workspace.
3. Switch the format selector to **JSON** and paste the manifest below.
4. Click **Create** and then **Install to Workspace** when prompted.
5. **Install App on workspace**: OAuth & Permissions → OAuth Tokens → Install

#### Slack App Manifest (JSON)

Paste this when creating the app from a manifest:

```json
{
    "display_information": {
        "name": "Open Slack CoPilot",
        "description": "AI-powered copilot for drafting Slack replies",
        "background_color": "#1a1a2e"
    },
    "features": {
        "bot_user": {
            "display_name": "CoPilot",
            "always_online": true
        },
        "shortcuts": [
            {
                "name": "Draft thread reply",
                "type": "message",
                "callback_id": "slack_copilot_draft_with_copilot",
                "description": "Draft a reply for this thread"
            },
            {
                "name": "Follow up",
                "type": "message",
                "callback_id": "slack_copilot_follow_up",
                "description": "Follow up with mentioned users on the thread"
            }
        ],
        "slash_commands": [
            {
                "command": "/copilot",
                "description": "Draft an AI reply in the current thread",
                "usage_hint": "[optional instruction]",
                "should_escape": false
            }
        ]
    },
    "oauth_config": {
        "redirect_urls": [
            "http://127.0.0.1:8765/slack/oauth/callback"
        ],
        "scopes": {
            "bot": [
                "app_mentions:read",
                "chat:write",
                "commands",
                "channels:history",
                "groups:history",
                "usergroups:read",
                "users:read"
            ],
            "user": [
                "chat:write"
            ]
        },
        "pkce_enabled": false
    },
    "settings": {
        "event_subscriptions": {
            "bot_events": [
                "app_mention"
            ]
        },
        "interactivity": {
            "is_enabled": true
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": true,
        "token_rotation_enabled": false,
        "is_mcp_enabled": false
    }
}
```

Message shortcuts must use `callback_id` **`slack_copilot_`** + the skill folder name (same name as under `~/.open_slack_copilot/skills/`, only `a-z`, `A-Z`, `_`, `-`). The app registers one Bolt listener for that pattern; shortcuts without the prefix or without a matching `SKILL.md` are ignored silently. See [Add a skill as a message shortcut](#add-a-skill-as-message-shortcut).

### 2. Get Your Credentials

After creating and installing the app, collect three tokens:

| Variable | Where to find it                                                                 | Format |
|---|----------------------------------------------------------------------------------|---|
| `SLACK_BOT_TOKEN` | **OAuth & Permissions** → Bot User OAuth Token          | `xoxb-...` |
| `SLACK_USER_TOKEN` | **OAuth & Permissions** → User OAuth Token          | `xoxp-...` |
| `SLACK_APP_TOKEN` | **Basic Information** → App-Level Tokens → Generate (scope: `connections:write`) | `xapp-...` |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys)             | `sk-...` |

### 3. Configure Secrets

```bash
cp .env.example .env
```

Edit `.env` with your tokens. The bot will refuse to start if any are missing.

### 4. Enable Socket Mode

If you used the manifest above, Socket Mode is already enabled. To verify or enable manually:

1. In your app settings, go to **Socket Mode** in the sidebar.
2. Toggle **Enable Socket Mode** on.
3. Make sure you have an App-Level Token with `connections:write` scope (see step 2).

### Configuration

- **Secrets:** Loaded from `.env` (keys: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `OPENAI_API_KEY`). See [`config/default.yaml`](config/default.yaml) for the mapping.
- **Defaults:** [`config/default.yaml`](config/default.yaml) (model, RAG settings)
- LLM model: `gpt-4o`
- RAG: In-memory Qdrant; configure `rag.slack` for channel RAG
- Skills: `~/.open_slack_copilot/skills/` (see [Define Skills](#define-skills))

---

## Install Slack CoPilot

```bash
git clone <your-repo-url>
cd open_slack_copilot
make install
```

---

## Run Slack CoPilot

```bash
make run
```

---

## Connect User OAuth (optional)

Only needed if you want CoPilot to **send messages on your behalf** (e.g. post a thread reply or DM from your Slack account via the `send_thread_reply_on_behalf_of_requester` tool). If you stick to the default `send_dm_as_app`, skip this section.

1. In your Slack app → **Basic Information**, copy **Client ID** and **Client Secret** into `.env`:

   ```
   SLACK_CLIENT_ID=...
   SLACK_CLIENT_SECRET=...
   ```

2. In your Slack app → **OAuth & Permissions**:
   - Add redirect URL: `http://127.0.0.1:8765/slack/oauth/callback`
   - Under **User Token Scopes**, add `chat:write`.
3. Start the localhost OAuth server (in a separate terminal):

   ```bash
   make oauth-server
   ```

4. Open `http://127.0.0.1:8765/slack/oauth/start` in your browser and complete the Slack consent. The user token is persisted at `~/.open_slack_copilot/slack_user_oauth/<user_id>.json` and picked up automatically by the bot.

---

## Define Skills

Skills are freeform markdown instructions that guide the bot's reply behavior. They live in:

```
~/.open_slack_copilot/
  skills/
    default.md            # optional — overrides the built-in default instruction
    <skill_name>/
      SKILL.md
```

- **Default skill** — To override the built-in default instruction, create `~/.open_slack_copilot/skills/default.md` with your own markdown. When no skill matches a thread, this file is used instead of the [bundled default](common/progressive_disclosure/default_instruction.md).
- **Additional skills** — Add folders under `~/.open_slack_copilot/skills/`. Each folder contains a `SKILL.md` file. The bot uses progressive disclosure to automatically select relevant skills per thread (including on **`@CoPilot`** and **`/copilot`**).

For examples of useful skills, see [`docs/examples/`](docs/examples/) and the **Follow Up** skill at [`skill_examples/follow_up/SKILL.md`](skill_examples/follow_up/SKILL.md).

### Add a skill as a message shortcut

1. Create `~/.open_slack_copilot/skills/<skill_directory>/SKILL.md` (see [`skill_examples/follow_up/SKILL.md`](skill_examples/follow_up/SKILL.md)).
2. [api.slack.com/apps](https://api.slack.com/apps) → your app → **Features** → **Shortcuts** → **Create New Shortcut** → **On messages**. **Callback ID** must match `slack_copilot_<skill_directory>` (e.g. `slack_copilot_follow_up` for `follow_up/`). Reinstall the app.
3. On a message: **⋯** → your shortcut → **Submit**.

---

**[Product Requirements & Technical Design (PRD)](docs/PRD.md)**
