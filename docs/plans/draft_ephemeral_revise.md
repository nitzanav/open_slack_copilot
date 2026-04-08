# Plan: Reply confirmation + Revise (historical)

**Status:** Superseded. Thread replies now use the **`send_thread_reply`** copilot tool and the shared **`tool_confirmation`** flow (Block Kit ephemeral with **Revise** + **Confirm**), not a separate reply-only module.

---

## Current behavior (refreshed)

| Area | Location | Behavior |
|------|----------|----------|
| ReAct loop | [`common/slack/copilot_pipeline.py`](../../common/slack/copilot_pipeline.py) | `run_react_loop` returns `ReactLoopResult`; user prompt requires **`send_thread_reply`**; `react_invocation_context` carries `context_kind`. |
| Context resolution | `resolve_copilot_slack_context` | **Thread:** `thread_ts` + `fetch_thread_messages`. **Channel root:** anchor `ts` + `fetch_channel_tail_messages`. |
| Entry points | [`slack_listener_with_threads.py`](../../common/slack/slack_bot/slack_listener_with_threads.py) | `/copilot`, shortcut `draft_with_copilot`, `app_mention` → [`_handle_copilot`](../../core/slack_bot.py) → `run_react_and_confirm`. |
| Thread reply UX | [`send_thread_reply.py`](../../common/tools/send_thread_reply.py) + [`tool_confirmation.py`](../../common/slack/slack_bot/tool_confirmation.py) | LLM calls `send_thread_reply` → ephemeral to requester with **Revise** + **Confirm**; confirm runs `execute_after_confirm` → `slack_api.post_thread_message`. |
| After ReAct | [`react_runner.py`](../../common/slack/slack_bot/react_runner.py) | If trace shows queued `send_thread_reply`, no extra draft ephemeral; otherwise ephemeral explains the model must call the tool. |
| Scheduled prompts | [`prompt_scheduler.py`](../../common/tools/prompt_scheduler/prompt_scheduler.py) | `run_react_and_confirm(..., excluded_tools=[SCHEDULE_PROMPT_TOOL])` to the user in job metadata. |
| Other risky tools | [`tool_confirmation.py`](../../common/slack/slack_bot/tool_confirmation.py) | e.g. `send_slack_pm` — same Revise + Confirm pattern; payload includes `context_kind` for revise parity. |

---

## Context parity on tool Revise

Modal submit reads **`context_kind`** from the tool confirmation payload and passes it to `run_react_and_confirm` so **channel_tail** vs **thread** matches the original run.

---

## Authorization

Ephemerals are targeted to the requesting user; interactive payloads should match Slack’s visibility model (only that user sees the confirmation).

---

## Slack app configuration

Interactivity and modal `view_submission` enabled for tool confirmation callback ids (same app).
