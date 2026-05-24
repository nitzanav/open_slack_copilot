import json
import re

from slack_bolt import App

from common.log import log
from common.slack import copilot_user_notify
from common.slack.copilot_pipeline import (
    MESSAGE_SHORTCUT_CALLBACK_PATTERN,
    ThreadFetchError,
    load_forced_skill,
    parse_copilot_shortcut_callback_id,
    skill_folder_valid_for_forced_modal,
    resolve_copilot_slack_context,
)
from common.progressive_disclosure.progressive_disclosure import SKILLS_ROOT
from common.progressive_disclosure import progressive_disclosure
from common.slack.slack_api import slack_api
from common.slack.slack_bot import tool_confirmation

register_tool_confirmation_handlers = (
    tool_confirmation.register_tool_confirmation_handlers
)

_MENTION_TOKEN_RE = re.compile(r"<@[^>]+>\s*")

CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL = "copilot_shortcut_draft_modal"
BLOCK_SHORTCUT_INSTRUCTION = "copilot_shortcut_instruction"
ACTION_SHORTCUT_INSTRUCTION_TEXT = "copilot_shortcut_instruction_text"
def _instruction_default_for_message_shortcut(skill_folder: str) -> str:
    """Minimal user text naming which skill the shortcut invoked."""
    folder = (skill_folder or "").strip()
    loaded = load_forced_skill(folder)
    skill_text = loaded[1] if loaded else None
    display_name = progressive_disclosure.skill_display_name(folder, skill_text)
    safe = display_name.replace('"', "'")
    return f'user asked to trigger skill "{safe}".'


def _strip_app_mention_tokens(text: str) -> str:
    return _MENTION_TOKEN_RE.sub("", text or "").strip()


def _thread_has_no_visible_replies(channel_id: str, parent_ts: str) -> bool:
    """True when the parent message has no replies yet (only the root in the thread).

    App mention events may omit thread metadata (e.g. ``reply_count``); we ask Slack
    via ``conversations.replies`` so this matches the workspace.
    """
    try:
        messages = slack_api.read_thread(channel_id, parent_ts)
    except Exception:
        return True
    return len(messages) <= 1


_DUMMY_FIRST_NON_ROOT_THREAD_MESSAGE = "Starting thread..."


def post_dummy_first_non_root_message_for_ephemeral_visibility_if_needed(
    channel_id: str,
    parent_ts: str,
    context_kind: str,
) -> None:
    """For channel-root copilot context only: post a minimal bot reply if needed so thread ephemerals show.

    Slack hides thread-scoped ephemerals until the thread exists in the UI, which
    requires at least one non-root message. No-op for ``thread`` context or when
    replies already exist.
    """
    if context_kind != "channel_tail":
        return
    if not _thread_has_no_visible_replies(channel_id, parent_ts):
        return
    try:
        slack_api.post_thread_message_as_app(
            channel_id, parent_ts, _DUMMY_FIRST_NON_ROOT_THREAD_MESSAGE,
        )
    except Exception:
        pass


def register_copilot_command(app: App, handler):

    @app.command("/copilot")
    def handle_copilot(ack, command):
        ack()
        channel_id = command["channel_id"]
        user_id = command["user_id"]
        user_text = command.get("text", "")

        thread_ts = _extract_thread_ts(command)
        if not thread_ts:
            copilot_user_notify.notify_error(
                channel_id, None, user_id, "Use /copilot inside a thread.",
            )
            return

        handler(
            channel_id=channel_id,
            thread_ts=thread_ts,
            user_id=user_id,
            user_text=user_text,
            channel_name=command.get("channel_name"),
            context_kind="thread",
            copilot_trigger="slash_command",
            copilot_action="send_thread_reply_on_behalf_of_requester",
            anchor_message_text=user_text,
        )


def _shortcut_draft_modal_metadata(
    channel_id: str,
    message_ts: str,
    thread_ts: str | None,
    user_id: str,
    channel_name: str | None,
    skill_folder: str,
    anchor_message_text: str | None = None,
) -> str:
    payload = {
        "skill_folder": skill_folder,
        "channel_id": channel_id,
        "message_ts": message_ts,
        "user_id": user_id,
    }
    if thread_ts is not None:
        payload["thread_ts"] = thread_ts
    if channel_name is not None:
        payload["channel_name"] = channel_name
    anchor = (anchor_message_text or "").strip()
    if anchor:
        payload["anchor_message_text"] = anchor
    return json.dumps(payload, separators=(",", ":"))


def _build_shortcut_draft_modal_view(
    private_metadata: str,
    initial_instruction: str,
) -> dict:
    return {
        "type": "modal",
        "callback_id": CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL,
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "CoPilot", "emoji": True},
        "submit": {"type": "plain_text", "text": "Submit", "emoji": True},
        "close": {"type": "plain_text", "text": "Cancel", "emoji": True},
        "blocks": [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Describe what you want in plain language. *Examples:* keep it to two sentences; "
                            "bullet the action items; friendly but firm; summarize the thread then reply; "
                            "politely decline; match the thread's tone."
                        ),
                    },
                ],
            },
            {
                "type": "input",
                "block_id": BLOCK_SHORTCUT_INSTRUCTION,
                "hint": {
                    "type": "plain_text",
                    "text": (
                        "Uses this thread's messages (or recent channel context on a root post). "
                        "After submit you can still use Revise on the draft."
                    ),
                    "emoji": True,
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": ACTION_SHORTCUT_INSTRUCTION_TEXT,
                    "multiline": True,
                    "initial_value": initial_instruction,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. Shorter, bullets, polite no, add a deadline\u2026",
                    },
                },
                "label": {
                    "type": "plain_text",
                    "text": "Instruction for the LLM",
                    "emoji": True,
                },
            },
        ],
    }


def register_copilot_shortcut(app: App, handler):

    @log
    def handle_copilot_message_shortcut(ack, shortcut, client):
        ack()
        shortcut_callback_id = str(shortcut.get("callback_id") or "").strip()
        skill_folder = parse_copilot_shortcut_callback_id(
            shortcut_callback_id,
        )
        if skill_folder is None:
            return
        channel_id = shortcut["channel"]["id"]
        user_id = shortcut["user"]["id"]
        message = shortcut["message"]
        response_url = shortcut.get("response_url")
        anchor_fallback = message.get("thread_ts") or message["ts"]

        if not skill_folder_valid_for_forced_modal(skill_folder):
            _send_missing_skill_error(
                channel_id, anchor_fallback, user_id, response_url,
                skill_folder,
            )
            return

        try:
            resolve_copilot_slack_context(channel_id, message)
        except ThreadFetchError:
            _send_channel_error(channel_id, anchor_fallback, user_id, response_url)
            return

        anchor_text = _strip_app_mention_tokens(message.get("text", ""))
        meta = _shortcut_draft_modal_metadata(
            channel_id,
            message["ts"],
            message.get("thread_ts"),
            user_id,
            shortcut["channel"].get("name"),
            skill_folder,
            anchor_message_text=anchor_text,
        )
        initial_instruction = _instruction_default_for_message_shortcut(
            skill_folder,
        )
        view = _build_shortcut_draft_modal_view(meta, initial_instruction)
        try:
            client.views_open(trigger_id=shortcut["trigger_id"], view=view)
        except Exception:
            if response_url:
                try:
                    slack_api.respond_ephemeral(
                        response_url,
                        "Could not open dialog. Try again.",
                    )
                except Exception:
                    pass

    app.shortcut(MESSAGE_SHORTCUT_CALLBACK_PATTERN)(
        handle_copilot_message_shortcut,
    )

    @app.view(CALLBACK_COPILOT_SHORTCUT_DRAFT_MODAL)
    @log
    def handle_shortcut_draft_modal_submit(ack, body, _client):
        view = body.get("view") or {}
        meta_raw = view.get("private_metadata") or ""
        try:
            meta = json.loads(meta_raw)
        except json.JSONDecodeError:
            ack(
                response_action="errors",
                errors={
                    BLOCK_SHORTCUT_INSTRUCTION: "Invalid dialog state.",
                },
            )
            return
        skill_folder = str(meta.get("skill_folder") or "").strip()
        if not skill_folder_valid_for_forced_modal(skill_folder):
            ack(
                response_action="errors",
                errors={
                    BLOCK_SHORTCUT_INSTRUCTION: "Invalid dialog state.",
                },
            )
            return
        channel_id = str(meta.get("channel_id") or "")
        message_ts = str(meta.get("message_ts") or "")
        user_id = str(meta.get("user_id") or "")
        if not channel_id or not message_ts or not user_id:
            ack(
                response_action="errors",
                errors={
                    BLOCK_SHORTCUT_INSTRUCTION: "Missing Slack context.",
                },
            )
            return
        message = {"ts": message_ts}
        thread_ts_meta = meta.get("thread_ts")
        if thread_ts_meta:
            message["thread_ts"] = thread_ts_meta
        values = view.get("state", {}).get("values", {})
        block = values.get(BLOCK_SHORTCUT_INSTRUCTION) or {}
        el = block.get(ACTION_SHORTCUT_INSTRUCTION_TEXT) or {}
        instruction = (el.get("value") or "").strip()
        if not instruction:
            instruction = _instruction_default_for_message_shortcut(
                skill_folder,
            )
        try:
            anchor_ts, thread_messages = resolve_copilot_slack_context(
                channel_id, message,
            )
        except ThreadFetchError:
            ack(
                response_action="errors",
                errors={
                    BLOCK_SHORTCUT_INSTRUCTION: (
                        "Could not load thread. Try again."
                    ),
                },
            )
            return
        channel_name = meta.get("channel_name")
        if not isinstance(channel_name, str):
            channel_name = None
        elif not channel_name.strip():
            channel_name = None
        context_kind = (
            "channel_tail" if not message.get("thread_ts") else "thread"
        )
        anchor_message_text = str(meta.get("anchor_message_text") or "").strip() or None
        ack()
        handler(
            channel_id=channel_id,
            thread_ts=anchor_ts,
            user_id=user_id,
            user_text=instruction,
            thread_messages=thread_messages,
            channel_name=channel_name,
            context_kind=context_kind,
            copilot_trigger="message_shortcut",
            copilot_action="send_thread_reply_on_behalf_of_requester",
            forced_skill_folder=skill_folder,
            anchor_message_text=anchor_message_text,
        )


def register_copilot_app_mention(app: App, handler, bot_user_id: str | None = None):

    @app.event("app_mention")
    @log
    def handle_app_mention(event):
        if event.get("subtype"):
            return
        if bot_user_id and event.get("user") == bot_user_id:
            return
        channel_id = event["channel"]
        user_id = event["user"]
        user_text = _strip_app_mention_tokens(event.get("text", ""))
        message = {"ts": event["ts"]}
        if event.get("thread_ts"):
            message["thread_ts"] = event["thread_ts"]
        anchor_fallback = event.get("thread_ts") or event["ts"]

        try:
            anchor_ts, thread_messages = resolve_copilot_slack_context(channel_id, message)
        except ThreadFetchError:
            copilot_user_notify.notify_error(
                channel_id,
                anchor_fallback,
                user_id,
                "Add me to this channel first. /invite @CoPilot",
            )
            return

        context_kind = "channel_tail" if not event.get("thread_ts") else "thread"
        post_dummy_first_non_root_message_for_ephemeral_visibility_if_needed(
            channel_id, anchor_ts, context_kind,
        )
        handler(
            channel_id=channel_id,
            thread_ts=anchor_ts,
            user_id=user_id,
            user_text=user_text,
            thread_messages=thread_messages,
            channel_name=None,
            context_kind=context_kind,
            copilot_trigger="app_mention",
            copilot_action="send_thread_reply_on_behalf_of_requester",
            anchor_message_text=user_text,
        )


def _extract_thread_ts(command: dict) -> str | None:
    return command.get("thread_ts") or command.get("message_ts")


def _send_channel_error(channel_id: str, thread_ts: str, user_id: str,
                       response_url: str | None):
    msg = "Add me to this channel first. /invite @CoPilot"
    try:
        copilot_user_notify.notify_error(channel_id, thread_ts, user_id, msg)
        return
    except Exception:
        pass
    if response_url:
        try:
            slack_api.respond_ephemeral(response_url, msg)
        except Exception:
            pass


def _send_missing_skill_error(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    response_url: str | None,
    skill_folder: str,
) -> None:
    expected_path = SKILLS_ROOT / skill_folder / "SKILL.md"
    msg = (
        f"Skill not installed: `{skill_folder}`.\n"
        f"Expected `{expected_path}`. "
        "Add the SKILL.md or run `./install_skill_examples.sh`, then retry."
    )
    try:
        copilot_user_notify.notify_error(channel_id, thread_ts, user_id, msg)
        return
    except Exception:
        pass
    if response_url:
        try:
            slack_api.respond_ephemeral(response_url, msg)
        except Exception:
            pass
