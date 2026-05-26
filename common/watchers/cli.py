"""Debug CLI: ``python -m common.watchers.cli list|run_once``."""

from __future__ import annotations

import sys

from common.watchers.watchers import run_watchers_for_trigger
from common.watchers.watchers_root import load_all, watchers_root


def _cmd_list() -> int:
    configs = load_all()
    if not configs:
        print(f"(no watchers under {watchers_root()})")
        return 0
    for cfg in configs:
        print(f"- {cfg.name}")
        print(f"    trigger:                  {cfg.trigger}")
        print(f"    requester_user_id:        {cfg.requester_user_id}")
        print(f"    channel_id:               {cfg.channel_id}")
        print(f"    run_skill_id:             {cfg.run_skill_id}")
        print(f"    thread_started_after:     {cfg.thread_started_after}s")
        print(f"    skill_didnt_run_for:      {cfg.skill_didnt_run_for}s")
        print(f"    messages_since_last_run > {cfg.thread_had_more_than_x_messages_since_last_skill_run}")
        print(f"    thread_quiet_for:         {cfg.thread_quiet_for_x_seconds}s")
    return 0


def _cmd_run_once() -> int:
    run_watchers_for_trigger("any_tool_confirmation")
    return 0


def main(argv: list[str]) -> int:
    cmd = (argv[1] if len(argv) > 1 else "").strip()
    if cmd == "list":
        return _cmd_list()
    if cmd == "run_once":
        return _cmd_run_once()
    print("Usage: python -m common.watchers.cli list|run_once", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
