# Open Slack CoPilot

AI-powered Slack bot for drafting replies, RAG-assisted context, and skill-based automation.

**[Product Requirements & Technical Design (PRD)](docs/PRD.md)**

---

## Installation

### 1. Clone and Install Dependencies

```bash
git clone <your-repo-url>
cd open_slack_copilot
pip install -r requirements.txt
```

### 2. Create a Slack App

#### Step-by-step

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click **Create New App**.
2. Choose **From a manifest** and select your workspace.
3. Switch the format selector to **JSON** and paste the manifest below.
4. Click **Create** and then **Install to Workspace** when prompted.

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
    "scopes": {
      "bot": [
        "app_mentions:read",
        "chat:write",
        "commands",
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

### 3. Get Your Credentials

After creating and installing the app, collect three tokens:

| Variable | Where to find it | Format |
|---|---|---|
| `SLACK_BOT_TOKEN` | **OAuth & Permissions** → Bot User OAuth Token | `xoxb-...` |
| `SLACK_APP_TOKEN` | **Basic Information** → App-Level Tokens → Generate (scope: `connections:write`) | `xapp-...` |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `sk-...` |

**Getting each token:**

**SLACK_BOT_TOKEN** — In your app settings, go to **OAuth & Permissions** in the sidebar. After installing the app to your workspace, the **Bot User OAuth Token** appears at the top of the page. Copy it.

**SLACK_APP_TOKEN** — In your app settings, go to **Basic Information** in the sidebar. Scroll to **App-Level Tokens** and click **Generate Token and Scopes**. Give it a name (e.g. `socket`), add the scope `connections:write`, and click **Generate**. Copy the `xapp-` token.

**OPENAI_API_KEY** — Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys), create a new secret key, and copy it. This is used by LiteLLM to call the default model (`gpt-4o`).

### 4. Configure Secrets

```bash
cp .env.example .env
```

Edit `.env` with your tokens. The bot will refuse to start if any are missing.

### 5. Enable Socket Mode

If you used the manifest above, Socket Mode is already enabled. To verify or enable manually:

1. In your app settings, go to **Socket Mode** in the sidebar.
2. Toggle **Enable Socket Mode** on.
3. Make sure you have an App-Level Token with `connections:write` scope (see step 3).

### 6. Invite the Bot to Channels

In Slack, invite the bot to any channel where you want to use it:

```
/invite @CoPilot
```

---

## Run

```bash
make run
# or
python -m core.slack_bot
```

Then type `/copilot` inside any thread in a channel where the bot is present.

## Docker

```bash
make docker-build
make docker-run
```

Or run directly:

```bash
docker run --rm --env-file .env open-slack-copilot
```

## Makefile Targets

| Target | Description |
|---|---|
| `install` | Install dependencies |
| `run` | Run the bot |
| `test` | Run pytest |
| `docker-build` | Build Docker image |
| `docker-run` | Run bot in container |

## Configuration

- **Secrets:** Loaded from `.env` (keys: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `OPENAI_API_KEY`). See `config/default.yaml` for the mapping.
- **Defaults:** `config/default.yaml` (model, RAG settings)
- LLM model: `gpt-4o`
- RAG: In-memory Qdrant; configure `rag.slack` for channel RAG
- Skills: `~/.open_slack_copilot/skills/`
