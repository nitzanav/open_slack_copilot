from common.log import log
from common.slack.copilot_pipeline import (
    DEFAULT_INSTRUCTION,
    compose_system_prompt,
    fetch_cross_channel_rag as _fetch_cross_channel_rag,
    get_checkpoint_seconds,
    get_cross_channel_ids,
    load_examples as _load_examples,
    select_skills as _select_skills,
)
from common.slack.slack_api import slack_api
from common.slack.slack_bot import slack_listener, slack_listener_with_threads
from common.slack.slack_bot.react_runner import run_react_and_confirm
from common.slack.slack_rag import slack_rag
from common.slack.slack_directory_rag import slack_directory_rag
from common.tools.prompt_scheduler import reload_jobs_from_disk, shutdown_scheduler, start_scheduler
from config.config import settings, parse_duration_seconds


def _get_bot_user_id() -> str | None:
    return slack_api.get_bot_user_id()


def start():
    app = slack_listener.create_app()
    slack_listener_with_threads.register_tool_confirmation_handlers(app)
    slack_listener_with_threads.register_copilot_command(app, _handle_copilot)
    slack_listener_with_threads.register_copilot_shortcut(app, _handle_copilot)
    slack_listener_with_threads.register_copilot_app_mention(
        app, _handle_copilot, bot_user_id=_get_bot_user_id(),
    )
    _build_cross_channel_rags()
    _start_periodic_rag_schedules()
    _start_directory_rag()
    start_scheduler()
    reload_jobs_from_disk()
    try:
        slack_listener.start(app)
    finally:
        slack_rag.stop_scheduler()
        slack_directory_rag.stop_scheduler()
        shutdown_scheduler()


@log
def _handle_copilot(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    user_text: str,
    channel_name: str | None = None,
    thread_messages: list[dict] | None = None,
    context_kind: str = "thread",
    copilot_trigger: str | None = None,
    copilot_action: str | None = None,
):
    run_react_and_confirm(
        channel_id,
        thread_ts,
        user_id,
        user_id,
        user_text,
        context_kind=context_kind,
        channel_name=channel_name,
        thread_messages=thread_messages,
        copilot_trigger=copilot_trigger,
        copilot_action=copilot_action,
    )


def _build_cross_channel_rags():
    cross_channels = get_cross_channel_ids()
    if cross_channels:
        slack_rag.build_all_missing(cross_channels, get_checkpoint_seconds())


def _start_periodic_rag_schedules():
    checkpoint = get_checkpoint_seconds()
    for entry in settings.rag.slack:
        channel = entry.get("channel", "")
        update = entry.get("update", "")
        if not channel or not update:
            continue
        interval = _parse_update_interval(update)
        if interval:
            slack_rag.build_if_missing(channel, checkpoint)
            slack_rag.schedule_periodic_build(channel, interval, checkpoint)


def _parse_update_interval(update_str: str) -> float | None:
    parts = update_str.strip().split()
    if len(parts) == 2 and parts[0] == "every":
        return parse_duration_seconds(parts[1])
    return None


def _start_directory_rag():
    """Index workspace users + user groups for ``list_users`` / semantic lookup."""
    slack_directory_rag.build_if_missing()
    slack_directory_rag.schedule_daily_refresh()


if __name__ == "__main__":
    start()
