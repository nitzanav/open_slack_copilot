import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from common.log import log
from common.slack.copilot_pipeline import ThreadFetchError, prepare_draft
from common.slack.slack_api import slack_api
from common.tools.schedule_tool import scheduled_prompts_root
from common.tools.send_slack_pm import SEND_SLACK_PM_TOOL
from config.config import settings

_logger = logging.getLogger("open_slack_copilot")

_scheduler: BackgroundScheduler | None = None


def _ensure_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        executors = {"default": ThreadPoolExecutor(1)}
        job_defaults = {"coalesce": True, "max_instances": 1}
        _scheduler = BackgroundScheduler(
            executors=executors, job_defaults=job_defaults, timezone="UTC"
        )
    return _scheduler


def start_scheduler():
    s = _ensure_scheduler()
    if not s.running:
        s.start()


def shutdown_scheduler():
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def job_dir(job_id: str) -> Path:
    return scheduled_prompts_root() / job_id


def register_job_from_disk(job_id: str):
    start_scheduler()
    meta_path = job_dir(job_id) / "metadata.json"
    if not meta_path.is_file():
        return
    meta = json.loads(meta_path.read_text())
    cron = meta.get("cron", "")
    try:
        trigger = CronTrigger.from_crontab(cron, timezone="UTC")
    except ValueError:
        _logger.error("Invalid cron for job %s: %s", job_id, cron)
        return
    s = _ensure_scheduler()
    s.add_job(
        run_scheduled_prompt,
        trigger=trigger,
        args=[job_id],
        id=job_id,
        replace_existing=True,
    )


def reload_jobs_from_disk():
    root = scheduled_prompts_root()
    if not root.is_dir():
        return
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "metadata.json").is_file():
            register_job_from_disk(d.name)


def remove_job(job_id: str, delete_files: bool = True):
    s = _ensure_scheduler()
    try:
        s.remove_job(job_id)
    except Exception:
        pass
    if delete_files:
        shutil.rmtree(job_dir(job_id), ignore_errors=True)


def _owner_id() -> str | None:
    oid = str(settings.slack_bot.get("config_owner_user_id") or "").strip()
    return oid or None


@log
def run_scheduled_prompt(job_id: str):
    root = job_dir(job_id)
    meta_path = root / "metadata.json"
    if not meta_path.is_file():
        remove_job(job_id, delete_files=True)
        return

    meta = json.loads(meta_path.read_text())
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromisoformat(meta["expires_at"].replace("Z", "+00:00"))
    if now >= expires_at:
        remove_job(job_id, delete_files=True)
        return

    prompt_path = root / "prompt.txt"
    if not prompt_path.is_file():
        remove_job(job_id, delete_files=True)
        return

    prompt_text = prompt_path.read_text().strip()
    channel_id = meta["channel_id"]
    thread_ts = meta["thread_ts"]
    user_id = meta.get("user_id") or ""

    try:
        result = prepare_draft(
            channel_id,
            thread_ts,
            user_id,
            user_text=prompt_text,
            tools=[SEND_SLACK_PM_TOOL],
        )
    except ThreadFetchError:
        remove_job(job_id, delete_files=True)
        owner = _owner_id()
        if owner:
            slack_api.send_ephemeral(
                channel_id,
                thread_ts,
                owner,
                "Scheduled prompt removed: thread is no longer accessible.",
            )
        return
    except Exception as exc:
        _logger.error("Scheduled prompt %s error: %s", job_id, exc)
        return

    owner = _owner_id()
    if owner and result:
        slack_api.send_ephemeral(channel_id, thread_ts, owner, result)
