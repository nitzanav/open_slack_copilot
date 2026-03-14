import os
import sys

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


def create_app() -> App:
    return App(token=os.environ["SLACK_BOT_TOKEN"])


def start(app: App):
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    try:
        handler.start()
    except KeyboardInterrupt:
        handler.close()
        sys.exit(0)
