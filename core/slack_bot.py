from common.llm.llm_client import llm_client
from common.slack.slack_api import slack_api
from common.slack.slack_bot import slack_listener, slack_listener_with_threads

DEFAULT_INSTRUCTION = "Draft a reply to this thread."


def start():
    app = slack_listener.create_app()
    slack_listener_with_threads.register_copilot_command(app, _handle_copilot)
    slack_listener.start(app)


def _handle_copilot(channel_id: str, thread_ts: str, user_id: str,
                    user_text: str, thread_messages: list[dict]):
    try:
        draft = prepare_draft(thread_messages, user_text)
        slack_api.send_ephemeral(channel_id, thread_ts, user_id, draft)
    except Exception:
        slack_api.send_ephemeral(
            channel_id, thread_ts, user_id, "Failed to generate draft, try again."
        )


def prepare_draft(thread_messages: list[dict], user_text: str) -> str:
    prompt = compose_system_prompt(thread_messages, user_text)
    return llm_client.generate(prompt)


def compose_system_prompt(thread_messages: list[dict], user_text: str) -> str:
    thread_block = _format_thread(thread_messages)
    instruction = user_text.strip() if user_text.strip() else DEFAULT_INSTRUCTION
    return (
        "You are a helpful assistant drafting a Slack reply.\n\n"
        f"## Thread\n{thread_block}\n\n"
        f"## Instruction\n{instruction}"
    )


def _format_thread(messages: list[dict]) -> str:
    return "\n".join(
        f"<@{m.get('user', 'unknown')}>: {m.get('text', '')}"
        for m in messages
    )
