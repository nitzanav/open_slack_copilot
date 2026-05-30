# Watchers

Per-channel JSON configs that pick **one** eligible thread per Slack tool confirmation and run a forced skill on it.

## **Configs** — `<watchers.storage_path>/<name>.json`

- Root path from `settings.watchers.storage_path` (default `~/.open_slack_copilot/watchers`)
- Schema: see [`watcher_config.py`](watcher_config.py)
- `trigger` must be `any_tool_confirmation` (only supported value)
- Invalid files are logged and skipped on load

## **Wake signal** — any successful tool confirmation

- Hooked in [`tool_confirmation.handle_confirm_action`](../slack/slack_bot/tool_confirmation.py) via `dispatch_watchers_async`
- Non-blocking: only enqueues a Huey task

## **Background runner** — Huey + SQLite, one task for all watchers

- Shared `huey` instance from [`common.task_queue.huey_app`](../task_queue/huey_app.py) (DB path: `settings.task_queue.db_path`)
- Task: `run_all_watchers` in [`watchers.py`](watchers.py)
- `@huey.lock_task("watchers")` collapses concurrent enqueues into one run

## **Filter chain (cheapest first)** — per distinct `thread_ts`

1. `skill_didnt_run_for` — check `skill_runs.find_latest_run`; reject without reading the thread
2. `thread_had_more_than_x_messages_since_last_skill_run` — fetch via `read_thread`, count messages since last run
3. `thread_quiet_for_x_seconds` — last message age from the same fetched thread

## **Dispatch** — `run_react_and_confirm(forced_skill_folder=cfg.run_skill_id)`

- `recipient_user_id == prepare_user_id == cfg.requester_user_id`
- `copilot_trigger="watcher"`, `copilot_action=f"watcher:{cfg.name}"`
- Stops after the first passing thread per watcher

## **CLI / Make** — debugging

- `make watcher_worker` — `huey_consumer common.watchers.watchers.huey`
- `make watchers_list` — print each loaded config
- `make watchers_run_once` — synchronous run for debugging
