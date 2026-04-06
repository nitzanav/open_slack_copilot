# Plan: Reply Confirmation + Revise

**Status:** Implemented in [`thread_reply_confirmation.py`](../../common/slack/slack_bot/thread_reply_confirmation.py). README describes **Revise** only until post-to-channel exists.

---

## What the code does today (refreshed)

| Area | Location | Behavior |
|------|----------|----------|
| ReAct loop | [`common/slack/copilot_pipeline.py`](../../common/slack/copilot_pipeline.py) | `run_react_loop(..., thread_messages=None, tools=...)` — if `thread_messages` is omitted, loads via `fetch_thread_messages(channel_id, thread_ts)`. |
| Context resolution | `resolve_copilot_slack_context` in same file | **Thread:** `thread_ts` + `fetch_thread_messages`. **Channel root (no thread):** anchor `ts` + `fetch_channel_tail_messages` (see `copilot_channel_context_limit`). |
| Entry points | [`common/slack/slack_bot/slack_listener_with_threads.py`](../../common/slack/slack_bot/slack_listener_with_threads.py) | `/copilot`, shortcut `draft_with_copilot`, and **`app_mention`** → all call the same handler in [`core/slack_bot.py`](../../core/slack_bot.py) `_handle_copilot`, optionally with pre-resolved `thread_messages`. |
| Reply confirmation | [`react_runner.py`](../../common/slack/slack_bot/react_runner.py) | `run_react_and_confirm` runs the ReAct loop and sends a Block Kit ephemeral with Revise. |
| Scheduled prompts | [`common/tools/prompt_scheduler/prompt_scheduler.py`](../../common/tools/prompt_scheduler/prompt_scheduler.py) | `run_react_and_confirm(..., excluded_tools=[SCHEDULE_PROMPT_TOOL])` to the scheduling user. |
| Tool confirmation | [`common/slack/slack_bot/tool_confirmation.py`](../../common/slack/slack_bot/tool_confirmation.py) | Risky tools (DMs, etc.) use a separate Confirm/Revise ephemeral pattern. |

---

## Goal (Revise only)

1. Replace successful reply ephemerals with **Block Kit** ephemerals that include a **Revise** button (no **Send** in this milestone).
2. **Revise** opens a **modal** with a multiline input whose default is:
   - `Please revise the following reply:`  
   - blank line  
   - full text of the reply shown in that ephemeral  
3. On **submit**, run the same backend path: call `run_react_loop` with the modal text as `user_text`, and the **same Slack context** as the original reply (see below).
4. Surfaces: **`/copilot`**, **shortcut**, **@mention**, and **scheduled** ephemerals.

---

## Critical design: context parity on revise

`run_react_loop` must see the **same** `thread_messages` semantics as the first run:

- **Thread / reply context:** `fetch_thread_messages(channel_id, thread_ts)` (default when `thread_messages` is `None` and `thread_ts` is the thread parent).
- **Channel-root context:** `fetch_channel_tail_messages(channel_id)` — **not** the same as calling `run_react_loop` with only `thread_ts` set to the message `ts` without passing `thread_messages`.

So modal **`private_metadata`** (or equivalent) must include at least:

- `channel_id`, `anchor_ts` (the `thread_ts` argument passed to `send_ephemeral` today),
- `user_id` passed into `run_react_loop` (invoker for copilot flows; job `metadata["user_id"]` for scheduler),
- **`context_kind`:** `"thread"` | `"channel_tail"` so the submit handler can build `thread_messages` the same way as `resolve_copilot_slack_context` / `_handle_copilot`.

Human **Revise** calls `run_react_loop` with default interactive tools (same as copilot). Scheduled cron runs are implemented in [`prompt_scheduler.py`](../../common/tools/prompt_scheduler/prompt_scheduler.py), which calls `run_react_and_confirm` with `excluded_tools=[SCHEDULE_PROMPT_TOOL]` (no recursive scheduling); other interactive tools stay available.

Then: `run_react_loop(channel_id, anchor_ts, user_id, user_text=<modal text>, thread_messages=<resolved>, channel_name=...)` on revise (no custom `tools`).

---

## Reply text in blocks (length limits)

Do **not** put the full reply in the button `value` (Slack limit ~2000 chars). Reuse the **chunked `section`** pattern from tool confirmation (`reply_body_0`, …) and **parse** the reply from `body["message"]["blocks"]` when opening the modal.

---

## Authorization

- **Copilot** (slash / shortcut / mention): only the user who received the ephemeral may click Revise / submit (match `body["user"]["id"]` to ephemeral recipient).
- **Scheduler:** ephemeral is sent to the user who created the schedule; only that user may act.

---

## Implementation outline

1. New module `common/slack/slack_bot/thread_reply_confirmation.py`: build blocks, parse reply, `app.action("reply_confirm_revise")` → `views.open`; `app.view` submission → resolve `thread_messages` from metadata → `run_react_loop` → `send_ephemeral_blocks` again with **Revise** only.
2. Helper `send_reply_confirmation(...)` used from `react_runner.py` (success path) and `prompt_scheduler.py`, passing **`context_kind`** and the rest of metadata for the button/modal.
3. Register handlers in `core/slack_bot.start()` next to `register_tool_confirmation_handlers`.
4. Tests: parser, auth, and `run_react_loop` called with correct `thread_messages` / `tools` for thread vs channel-tail and scheduler.
5. **README:** Until Send exists, describe **Revise** only or mark Send as "planned" so docs match the product.

---

## Out of scope (later)

- **Send** button, posting as user/bot, OAuth.

---

## Slack app configuration

- Interactivity and **modal** `view_submission` must be enabled for the new callback ids (same app as tool confirmation).
