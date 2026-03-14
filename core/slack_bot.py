import json
import re
from pathlib import Path

from common.llm.llm_client import llm_client
from common.progressive_disclosure import progressive_disclosure
from common.slack.slack_api import slack_api
from common.slack.slack_bot import slack_listener, slack_listener_with_threads
from common.slack.slack_rag import slack_rag
from config.config import load as load_config, parse_duration_seconds

DEFAULT_INSTRUCTION = "Draft a reply to this thread."
PROMPT_TEMPLATE = (Path(__file__).parent / "draft_prompt.md").read_text()
EXAMPLES_PATH = Path(__file__).parent / "example_threads.json"


def start():
    app = slack_listener.create_app()
    slack_listener_with_threads.register_copilot_command(app, _handle_copilot)
    _build_cross_channel_rags()
    _start_periodic_rag_schedules()
    slack_listener.start(app)


def _handle_copilot(channel_id: str, thread_ts: str, user_id: str,
                    user_text: str, thread_messages: list[dict]):
    try:
        draft = prepare_draft(channel_id, thread_ts, user_id, thread_messages, user_text)
        slack_api.send_ephemeral(channel_id, thread_ts, user_id, draft)
    except Exception:
        slack_api.send_ephemeral(
            channel_id, thread_ts, user_id, "Failed to generate draft, try again."
        )


def prepare_draft(channel_id: str, thread_ts: str, user_id: str,
                  thread_messages: list[dict], user_text: str) -> str:
    skills = _select_skills(thread_messages, user_text)
    thread_context = " ".join(m.get("text", "") for m in thread_messages[-5:])
    rag_results = _fetch_rag_context(channel_id, thread_ts, user_id, thread_messages)
    cross_rag_results = _fetch_cross_channel_rag(channel_id, thread_ts, user_id, thread_context)
    examples = _load_examples()
    prompt = compose_system_prompt(
        thread_messages, user_text, skills, rag_results, cross_rag_results, examples
    )
    return llm_client.generate(prompt)


def compose_system_prompt(thread_messages: list[dict], user_text: str,
                          skills: list[str] | None = None,
                          rag_results: list[dict] | None = None,
                          cross_rag_results: list[dict] | None = None,
                          examples: list[dict] | None = None) -> str:
    rendered = PROMPT_TEMPLATE.format(
        skills=_format_section("Skills", "\n\n".join(skills)) if skills else "",
        channel_context=_format_section("Relevant Channel Context",
            "\n".join(f"- {r.get('text', '')}" for r in rag_results)) if rag_results else "",
        cross_channel_context=_format_section("Cross-Channel Context",
            "\n".join(f"- [{r.get('channel', '?')}] {r.get('text', '')}" for r in cross_rag_results)) if cross_rag_results else "",
        examples=_format_section("Example Replies",
            "\n".join(f"Q: {e['question']}\nA: {e['answer']}" for e in examples)) if examples else "",
        thread=_format_thread(thread_messages),
        instruction=user_text.strip() if user_text.strip() else DEFAULT_INSTRUCTION,
    )
    return _collapse_blank_lines(rendered)


def _select_skills(thread_messages: list[dict], user_text: str) -> list[str]:
    skills = progressive_disclosure.select_skills("reply", thread_messages, user_text)
    if not skills:
        return [progressive_disclosure.get_default_instruction()]
    return skills


def _fetch_rag_context(channel_id: str, thread_ts: str, user_id: str,
                       thread_messages: list[dict]) -> list[dict]:
    try:
        if not slack_rag.is_ready(channel_id):
            slack_api.send_ephemeral(
                channel_id, thread_ts, user_id,
                "Preparing RAG for this channel, will update when done."
            )
            slack_rag.build(channel_id, _get_checkpoint_seconds())

        thread_context = " ".join(m.get("text", "") for m in thread_messages[-5:])
        return slack_rag.query_channel(channel_id, thread_context)
    except Exception:
        return []


def _fetch_cross_channel_rag(channel_id: str, thread_ts: str, user_id: str,
                             thread_context: str) -> list[dict]:
    cross_channels = _get_cross_channel_ids()
    if not cross_channels:
        return []

    try:
        missing = slack_rag.missing_channels(cross_channels)
        if missing:
            names = ", ".join(missing)
            slack_api.send_ephemeral(
                channel_id, thread_ts, user_id,
                f"Creating RAG for {names}, please wait."
            )
            checkpoint = _get_checkpoint_seconds()
            for ch in missing:
                slack_rag.build(ch, checkpoint)

        return slack_rag.query_cross_channel(
            cross_channels, thread_context, exclude_channel=channel_id
        )
    except Exception:
        return []


def _build_cross_channel_rags():
    cross_channels = _get_cross_channel_ids()
    if cross_channels:
        slack_rag.build_all_missing(cross_channels, _get_checkpoint_seconds())


def _start_periodic_rag_schedules():
    config = load_config()
    checkpoint = _get_checkpoint_seconds()
    for entry in config.get("rag", {}).get("slack", []):
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


def _get_cross_channel_ids() -> list[str]:
    config = load_config()
    return config.get("rag", {}).get("cross_channel", [])


def _get_checkpoint_seconds() -> float:
    config = load_config()
    duration = config.get("rag", {}).get("checkpoint_duration", "30d")
    return parse_duration_seconds(duration)


def _load_examples() -> list[dict]:
    if not EXAMPLES_PATH.exists():
        return []
    return json.loads(EXAMPLES_PATH.read_text())


def _format_section(title: str, body: str) -> str:
    return f"## {title}\n{body}"


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _format_thread(messages: list[dict]) -> str:
    return "\n".join(
        f"<@{m.get('user', 'unknown')}>: {m.get('text', '')}"
        for m in messages
    )
