# Plan: Ephemeral draft **Revise**

**Status:** Implemented in [`draft_revise_actions.py`](../../common/slack/slack_bot/draft_revise_actions.py). README describes **Revise** only until post-to-channel exists.

---

## What the code does today (refreshed)

| Area | Location | Behavior |
|------|----------|----------|
| Draft pipeline | [`common/slack/copilot_pipeline.py`](../../common/slack/copilot_pipeline.py) | `prepare_draft(..., thread_messages=None, tools=...)` — if `thread_messages` is omitted, loads via `fetch_thread_messages(channel_id, thread_ts)`. |
| Context resolution | `resolve_copilot_slack_context` in same file | **Thread:** `thread_ts` + `fetch_thread_messages`. **Channel root (no thread):** anchor `ts` + `fetch_channel_tail_messages` (see `copilot_channel_context_limit`). |
| Entry points | [`common/slack/slack_bot/slack_listener_with_threads.py`](../../common/slack/slack_bot/slack_listener_with_threads.py) | `/copilot`, shortcut `draft_with_copilot`, and **`app_mention`** → all call the same handler in [`core/slack_bot.py`](../../core/slack_bot.py) `_handle_copilot`, optionally with pre-resolved `thread_messages`. |
| Draft delivery | [`core/slack_bot.py`](../../core/slack_bot.py) | `slack_api.send_ephemeral(..., text=draft)` — **no Block Kit, no Revise.** |
| Scheduled prompts | [`common/tools/prompt_scheduler/prompt_scheduler.py`](../../common/tools/prompt_scheduler/prompt_scheduler.py) | `prepare_draft(..., tools=[SEND_SLACK_PM_TOOL])`, then `send_ephemeral` to the scheduling user. |
| Interactive precedent | [`common/slack/slack_bot/dm_confirmation.py`](../../common/slack/slack_bot/dm_confirmation.py) | Chunked sections + `send_ephemeral_blocks` + `action_id` handlers. |

---

## Goal (Revise only)

1. Replace successful draft ephemerals with **Block Kit** ephemerals that include a **Revise** button (no **Send** in this milestone).
2. **Revise** opens a **modal** with a multiline input whose default is:
   - `Please revise the following reply:`  
   - blank line  
   - full text of the draft shown in that ephemeral  
3. On **submit**, run the same backend path as an instruction to `/copilot`: call `prepare_draft` with the modal text as `user_text`, and the **same Slack context** as the original draft (see below).
4. Surfaces: **`/copilot`**, **shortcut**, **@mention**, and **scheduled** ephemerals.

---

## Critical design: context parity on revise

`prepare_draft` must see the **same** `thread_messages` semantics as the first draft:

- **Thread / reply context:** `fetch_thread_messages(channel_id, thread_ts)` (default when `thread_messages` is `None` and `thread_ts` is the thread parent).
- **Channel-root context:** `fetch_channel_tail_messages(channel_id)` — **not** the same as calling `prepare_draft` with only `thread_ts` set to the message `ts` without passing `thread_messages`.

So modal **`private_metadata`** (or equivalent) must include at least:

- `channel_id`, `anchor_ts` (the `thread_ts` argument passed to `send_ephemeral` today),
- `user_id` passed into `prepare_draft` (invoker for copilot flows; job `metadata["user_id"]` for scheduler),
- **`context_kind`:** `"thread"` | `"channel_tail"` so the submit handler can build `thread_messages` the same way as `resolve_copilot_slack_context` / `_handle_copilot`.

Human **Revise** calls `prepare_draft` with default interactive tools (same as copilot). Scheduled cron runs are implemented in [`prompt_scheduler.py`](../../common/tools/prompt_scheduler/prompt_scheduler.py), which calls `prepare_draft` with `excluded_tools=[SCHEDULE_PROMPT_TOOL]` (no recursive scheduling); other interactive tools stay available.

Then: `prepare_draft(channel_id, anchor_ts, user_id, user_text=<modal text>, thread_messages=<resolved>, channel_name=...)` on revise (no custom `tools`).

---

## Draft text in blocks (length limits)

Do **not** put the full draft in the button `value` (Slack limit ~2000 chars). Reuse the **chunked `section`** pattern from DM confirmation (`draft_body_0`, …) and **parse** the draft from `body["message"]["blocks"]` when opening the modal.

---

## Authorization

- **Copilot** (slash / shortcut / mention): only the user who received the ephemeral may click Revise / submit (match `body["user"]["id"]` to ephemeral recipient).
- **Scheduler:** ephemeral is sent to the user who created the schedule; only that user may act.

---

## Implementation outline

1. New module e.g. `common/slack/slack_bot/draft_revise_actions.py`: build blocks, parse draft, `app.action("draft_revise")` → `views.open`; `app.view` submission → resolve `thread_messages` from metadata → `prepare_draft` → `send_ephemeral_blocks` again with **Revise** only.
2. Helper `send_draft_ephemeral_with_revise(...)` used from `core/slack_bot.py` (success path) and `prompt_scheduler.py`, passing **`context_kind`** and the rest of metadata for the button/modal.
3. Register handlers in `core/slack_bot.start()` next to `register_dm_confirmation_handlers`.
4. Tests: parser, auth, and `prepare_draft` called with correct `thread_messages` / `tools` for thread vs channel-tail and scheduler.
5. **README:** Until Send exists, describe **Revise** only or mark Send as “planned” so docs match the product.

---

## Out of scope (later)

- **Send** button, posting as user/bot, OAuth.

---

## Slack app configuration

- Interactivity and **modal** `view_submission` must be enabled for the new callback ids (same app as DM confirmation).
