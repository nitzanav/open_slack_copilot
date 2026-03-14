# Open Slack CoPilot

AI-powered Slack bot for drafting replies, RAG-assisted context, and skill-based automation.

**[→ Product Requirements & Technical Design (PRD)](docs/PRD.md)**

## Quick Start

### Install

```bash
pip install -r requirements.txt
```

### Run

1. **Set environment variables:**

   - `SLACK_BOT_TOKEN` — Slack Bot token
   - `SLACK_APP_TOKEN` — Slack App token (Socket Mode)
   - `OPENAI_API_KEY` — LLM API key (default model: gpt-4o)

2. **Start the bot:**

   ```bash
   make run
   # or
   python -m core.slack_bot
   ```

## Slack App Setup

- Enable **Socket Mode**
- **Bot Token Scopes:** `app_mentions:read`, `chat:write`, `commands`, `channels:history`, `groups:history`
- Add slash command `/copilot`
- Install app to your workspace

## Docker

```bash
make docker-build
make docker-run
```

Or with `docker run`:

```bash
docker run --rm -e SLACK_BOT_TOKEN=... -e SLACK_APP_TOKEN=... -e OPENAI_API_KEY=... open-slack-copilot
```

## Makefile Targets

| Target        | Description           |
|---------------|-----------------------|
| `install`     | Install dependencies  |
| `run`         | Run the bot           |
| `test`        | Run pytest            |
| `docker-build`| Build Docker image    |
| `docker-run`  | Run bot in container  |

## Configuration

- Config: `config/default.yaml`
- LLM model: `gpt-4o` (configurable in config)
- RAG: Uses in-memory Qdrant by default; configure `rag.slack` for channel RAG
- Skills: `~/.open_slack_copilot/skills/`
