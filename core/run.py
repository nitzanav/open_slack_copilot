"""Run the Slack bot together with the localhost user-OAuth HTTP server.

The OAuth server runs in a daemon thread so it shuts down with the bot.
If Slack OAuth client credentials are not configured, the OAuth server is
skipped (logged as a warning) and the bot still starts.
"""

from __future__ import annotations

import threading

from common.log import log
from core import slack_bot, slack_user_oauth_server


def _user_oauth_configured() -> bool:
    from config.config import settings

    uo = settings.slack_bot.get("user_oauth") or {}
    if not isinstance(uo, dict):
        return False
    return bool((uo.get("client_id") or "").strip() and (uo.get("client_secret") or "").strip())


@log
def _start_oauth_server_thread() -> None:
    t = threading.Thread(
        target=slack_user_oauth_server.main,
        name="slack-user-oauth-server",
        daemon=True,
    )
    t.start()


def main() -> None:
    if _user_oauth_configured():
        _start_oauth_server_thread()
    else:
        print(  # noqa: T201 — CLI entry
            "[run] User OAuth server not started (SLACK_CLIENT_ID / SLACK_CLIENT_SECRET not set). "
            "That's fine for most setups — configure these only if you need the bot to send "
            "messages on behalf of people across your organization via OAuth."
        )
    slack_bot.start()


if __name__ == "__main__":
    main()
