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

## Reply with Open Slack CoPilot

Go to a message you were mentioned in (or any message you want to draft a reply for):

1. **Hover** over the message in Slack.
2. Click the **&#x22EE;** (three-dot menu) on the right side of the message.
3. **Connect to apps** → **Draft with CoPilot**.
4. Expect an ephemeral message from the bot with the suggested reply.
5. Click **Send** or **Revise**.

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
    "shortcuts": [
      {
        "name": "Draft with CoPilot",
        "type": "message",
        "callback_id": "draft_with_copilot",
        "description": "Draft a reply for this message"
      }
    ],
    "bot_user": {
      "display_name": "CoPilot",
      "always_online": true
    },
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "app_mentions:read",
        "chat:write",
        "channels:history",
        "groups:history"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "app_mention"
      ]
    },
    "org_deploy_enabled": false,
    "socket_mode_enabled": true,
    "token_rotation_enabled": false
  }
}
```

### 2. Get Your Credentials

After creating and installing the app, collect three tokens:

| Variable | Where to find it                                                                 | Format |
|---|----------------------------------------------------------------------------------|---|
| `SLACK_BOT_TOKEN` | **OAuth & Permissions** → Bot User OAuth Token          | `xoxb-...` |
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

## Define Skills

Skills are freeform markdown instructions that guide the bot's reply behavior. They live in:

```
~/.open_slack_copilot/
  skills/
    reply/
      default.md            # optional — overrides the built-in default instruction
      <skill_name>/
        SKILL.md
```

- **Default skill** — To override the built-in default reply instruction, create `~/.open_slack_copilot/skills/reply/default.md` with your own markdown. When no skill matches a thread, this file is used instead of the [bundled default](common/progressive_disclosure/default_reply_instruction.md).
- **Additional skills** — Add folders under `~/.open_slack_copilot/skills/reply/`. Each folder contains a `SKILL.md` file. The bot uses progressive disclosure to automatically select relevant skills per thread.

For examples of useful skills, see [`docs/examples/`](docs/examples/).

---

**[Product Requirements & Technical Design (PRD)](docs/PRD.md)**
