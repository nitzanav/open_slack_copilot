import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.log import log
from common.tools.draft_context import get_invocation
from config.config import settings

_MAX_EXPIRY_DAYS = 14
_DEFAULT_EXPIRY_DAYS = 7

SCHEDULE_PROMPT_TOOL = {
    "type": "function",
    "function": {
        "name": "schedule_prompt",
        "description": (
            "Schedule a recurring prompt for this thread. "
            "The prompt will be executed on each cron trigger as if the user "
            "invoked /copilot with that text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The instruction to run on each trigger, e.g. "
                        "'Check if mentioned users added a checkmark emoji. "
                        "If not, DM each a polite reminder.'"
                    ),
                },
                "cron": {
                    "type": "string",
                    "description": "Five-field cron in UTC, e.g. 0 10 * * * for daily 10:00",
                },
                "expires_in_days": {
                    "type": "integer",
                    "description": f"Days until the schedule expires (default {_DEFAULT_EXPIRY_DAYS}, max {_MAX_EXPIRY_DAYS})",
                },
            },
            "required": ["prompt", "cron"],
        },
    },
}


class _ValidationError(Exception):
    pass


def scheduled_prompts_root() -> Path:
    return Path(settings.scheduled_prompts.storage_path).expanduser()


@log
def handle_schedule_prompt_call(arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json or "{}")
        prompt = _require_str(args, "prompt")
        cron = _require_str(args, "cron")
        expires_in = _parse_expires_in(args)
        inv = _require_invocation_context()
    except _ValidationError as e:
        return json.dumps({"error": str(e)})

    job_id = f"sched_{uuid.uuid4().hex[:16]}"
    _write_job_to_disk(job_id, prompt, cron, expires_in, inv)

    from common.tools.prompt_scheduler import register_job_from_disk

    register_job_from_disk(job_id)
    return json.dumps({
        "status": "scheduled",
        "job_id": job_id,
        "message": f"Prompt scheduled with cron {cron!r}; expires in {expires_in} days.",
    })


def _require_str(args: dict, key: str) -> str:
    val = (args.get(key) or "").strip()
    if not val:
        raise _ValidationError(f"{key} is required")
    return val


def _parse_expires_in(args: dict) -> int:
    raw = args.get("expires_in_days", _DEFAULT_EXPIRY_DAYS)
    try:
        days = min(int(raw), _MAX_EXPIRY_DAYS)
    except (TypeError, ValueError):
        return _DEFAULT_EXPIRY_DAYS
    return max(days, 1)


def _require_invocation_context() -> dict:
    inv = get_invocation()
    if not inv:
        raise _ValidationError("No active invocation context")
    if not inv.get("thread_ts") or not inv.get("channel_id"):
        raise _ValidationError("Could not determine thread_ts / channel_id")
    return inv


def _write_job_to_disk(
    job_id: str, prompt: str, cron: str, expires_in: int, inv: dict
):
    job_dir = scheduled_prompts_root() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "prompt.txt").write_text(prompt)

    now = datetime.now(timezone.utc)
    meta = {
        "thread_ts": inv["thread_ts"],
        "channel_id": inv["channel_id"],
        "user_id": inv.get("user_id", ""),
        "cron": cron,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "expires_at": (now + timedelta(days=expires_in)).isoformat().replace("+00:00", "Z"),
    }
    (job_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
