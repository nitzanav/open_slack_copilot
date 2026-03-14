import sys

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config.config import settings


def create_app() -> App:
    return App(token=settings.slack_bot.token)


def start(app: App):
    handler = SocketModeHandler(app, settings.slack_bot.app_token)
    try:
        handler.start()
    except KeyboardInterrupt:
        handler.close()
        sys.exit(0)
