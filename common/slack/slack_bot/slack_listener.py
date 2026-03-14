import ssl
import sys

import certifi
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.web import WebClient

from config.config import settings


def create_app() -> App:
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    client = WebClient(token=settings.slack_bot.token, ssl=ssl_context)
    return App(client=client)


def start(app: App):
    handler = SocketModeHandler(app, settings.slack_bot.app_token)
    try:
        handler.start()
    except KeyboardInterrupt:
        handler.close()
        sys.exit(0)
