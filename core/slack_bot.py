from common.log import log
from common.slack.copilot_pipeline import (
    DEFAULT_INSTRUCTION,
    ThreadFetchError,
    compose_system_prompt,
    fetch_cross_channel_rag as _fetch_cross_channel_rag,
    get_checkpoint_seconds,
    get_cross_channel_ids,
    load_examples as _load_examples,
    prepare_draft,
    select_skills as _select_skills,
)
from common.slack.slack_api import slack_api
from common.slack.slack_bot import slack_listener, slack_listener_with_threads
from common.slack.slack_bot.draft_revise_actions import send_draft_ephemeral_with_revise
from common.slack.slack_rag import slack_rag
from common.tools.prompt_scheduler import reload_jobs_from_disk, shutdown_scheduler, start_scheduler
from config.config import settings, parse_duration_seconds


def _get_bot_user_id() -> str | None:
    try:
        return slack_api.get_client().auth_test()["user_id"]
    except Exception:
        return None


def start():
    app = slack_listener.create_app()
    slack_listener_with_threads.register_dm_confirmation_handlers(app)
    slack_listener_with_threads.register_draft_revise_handlers(app)
    slack_listener_with_threads.register_copilot_command(app, _handle_copilot)
    slack_listener_with_threads.register_copilot_shortcut(app, _handle_copilot)
    slack_listener_with_threads.register_copilot_app_mention(
        app, _handle_copilot, bot_user_id=_get_bot_user_id(),
    )
    _build_cross_channel_rags()
    _start_periodic_rag_schedules()
    start_scheduler()
    reload_jobs_from_disk()
    try:
        slack_listener.start(app)
    finally:
        slack_rag.stop_scheduler()
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
):
    try:
        draft = prepare_draft(
            channel_id,
            thread_ts,
            user_id,
            user_text,
            channel_name=channel_name,
            thread_messages=thread_messages,
        )
        send_draft_ephemeral_with_revise(
            channel_id,
            thread_ts,
            user_id,
            user_id,
            draft,
            context_kind=context_kind,
        )
    except ThreadFetchError:
        slack_api.send_ephemeral(
            channel_id,
            thread_ts,
            user_id,
            "Add me to this channel first. /invite @CoPilot",
        )
    except Exception:
        slack_api.send_ephemeral(
            channel_id, thread_ts, user_id, "Failed to generate draft, try again."
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


if __name__ == "__main__":
    start()
