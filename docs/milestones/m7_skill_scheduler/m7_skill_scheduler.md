# M7 — Skill Scheduler

[← Back to PRD](../../PRD.md)

## Requirements

- **Register scheduled prompts** — when user invokes `/copilot follow up` (or similar), the LLM matches a channel watcher skill that requires scheduling, then uses the `schedule` tool to register a recurring prompt
- **APScheduler runtime** — scheduled skills run via APScheduler (in-process), supporting cron expressions (hourly, daily, etc.)
- **Stored on disk** — each scheduled skill stored at `~/.open_slack_copilot/scheduled_skills/<id>/SKILL.md` + `metadata.json`
- **LLM judges completion** — when a scheduled prompt fires, the LLM reads the thread and decides whether the required action was done (emoji, reply, confirmation)
- **DM non-completers** — if action not done, use M6 (send_slack_pm tool with confirmation) to DM the relevant people
- **Exponential backoff** — reminders start at 1 day interval, double each time, expire after 3 weeks
- **Sequential execution** — scheduled skills run one at a time, not in parallel

## Architecture

### Modules

- `common/tools/skills_scheduler/skills_scheduler.py` — registers/removes scheduled jobs via APScheduler; on trigger, loads SKILL.md + metadata, calls LLM to evaluate thread state, acts accordingly
- `common/tools/skills_scheduler/schedule_tool.py` — LiteLLM tool definition; the LLM calls this to register a new scheduled skill
- `common/slack/slack_api/slack_api.py` — exposes the slack_bolt client directly, plus helper functions as needed
- `common/llm/llm_client/llm_client.py` — evaluates thread state, decides if action was done
- `common/tools/send_slack_pm.py` — reused from M6 for sending DM reminders (with confirmation)
- `config/config.py` — path to scheduled_skills directory

### Scheduled Skill Storage

```
~/.open_slack_copilot/
  scheduled_skills/
    followup_abc123/
      SKILL.md            # freeform: "Check if mentioned users have replied or reacted.
                          #  If not, DM them with a polite reminder."
      metadata.json       # { thread_id, channel_id, user_id, cron, created_at,
                          #   last_run, next_run, backoff_days, expires_at }
```

### metadata.json Schema

```json
{
  "thread_id": "1234567890.123456",
  "channel_id": "C0123ABC",
  "user_id": "U0123XYZ",
  "skill_ref": "followup",
  "cron": "0 11 * * *",
  "created_at": "2026-03-13T10:00:00Z",
  "last_run": null,
  "next_run": "2026-03-14T11:00:00Z",
  "backoff_days": 1,
  "expires_at": "2026-04-03T10:00:00Z"
}
```

### Data Flow — Registration

```
User types `/copilot follow up` in a thread
       │
       ▼
slack_listener.py → prepare_draft_order(thread, "follow up", skills)
       │
       ├── progressive_disclosure selects "followup" channel watcher skill
       ├── LLM sees skill says "schedule daily check"
       ├── LLM calls schedule_tool(thread_id, channel_id, cron="0 11 * * *", skill_ref="followup")
       │
       ▼
schedule_tool.py
       │
       ├── create ~/.open_slack_copilot/scheduled_skills/followup_<id>/
       │     ├── SKILL.md (copied from channel watcher skill)
       │     └── metadata.json (thread_id, channel_id, cron, backoff_days=1, expires_at=now+3w)
       │
       ├── register APScheduler job with cron expression
       └── return "Follow-up scheduled: daily at 11am, expires in 3 weeks"
```

### Data Flow — Execution (daily trigger)

```
APScheduler fires job for followup_abc123
       │
       ▼
skills_scheduler.py :: run_scheduled_skill("followup_abc123")
       │
       ├── load SKILL.md + metadata.json
       ├── check: expired? (now > expires_at) → remove job, done
       ├── check: backoff (now < last_run + backoff_days) → skip, done
       │
       ├── slack_api.read_thread(channel_id, thread_id)
       ├── slack_api.get_reactions(channel_id, thread_id)
       │
       ├── LLM evaluates: "Given this thread and reactions, did the mentioned users
       │   complete the required action (reply, emoji, confirm)?"
       │
       ├── if action done → remove scheduled job, done
       │
       ├── if action NOT done:
       │     ├── LLM composes reminder DM for each non-completer
       │     ├── for each: send_slack_pm tool (with confirmation from M6)
       │     ├── update metadata: last_run=now, backoff_days *= 2
       │     └── done
       │
       └── save updated metadata.json
```

### LiteLLM Tool Definition — schedule_tool

```
Tool name: schedule_skill
Description: "Schedule a recurring check for this thread. The skill will be evaluated periodically."
Parameters:
  - thread_id (string): the Slack thread timestamp
  - channel_id (string): the channel ID
  - cron (string): cron expression (e.g. "0 11 * * *" for daily at 11am)
  - skill_ref (string): which skill to use for evaluation
Returns: confirmation message with schedule details
```

### Key Decisions

- **APScheduler in-process** — runs in the same Python process as the bot; jobs persisted via disk (metadata.json), re-registered on app restart
- **Sequential execution** — APScheduler configured with max_instances=1 and a single-threaded executor
- **LLM judges** — no hardcoded rules for "action done"; the LLM reads the thread + reactions and decides
- **Exponential backoff** — 1d → 2d → 4d → 8d → 16d → expires at 21d (3 weeks)
- **DM confirmation** — reminder DMs go through M6's confirmation flow; the requesting user must approve each DM

## STP — Software Test Procedure

### STP-7.1: Happy path — register a follow-up schedule

- **Precondition**: User in a thread where they assigned tasks to people.
- **Input**: `/copilot follow up`
- **Expected**: LLM matches follow-up skill, calls `schedule_skill` tool. SKILL.md + metadata.json created. APScheduler job registered. Ephemeral: "Follow-up scheduled: daily at 11am, expires in 3 weeks."

### STP-7.2: Scheduled check — action NOT done

- **Precondition**: Scheduled follow-up exists. Thread has 3 mentioned users. None have replied or reacted.
- **Input**: APScheduler fires the job at 11am.
- **Expected**: LLM reads thread, judges action not done. Composes DM for each non-completer. 3 DM confirmations sent to the scheduling user. `backoff_days` updated from 1 to 2.

### STP-7.3: Scheduled check — action DONE

- **Precondition**: All mentioned users have replied or reacted.
- **Input**: APScheduler fires.
- **Expected**: LLM judges action done. Scheduled job removed. No DMs sent. Ephemeral: "Follow-up complete, all actions done."

### STP-7.4: Scheduled check — partial completion

- **Precondition**: 2 of 3 mentioned users have replied.
- **Input**: APScheduler fires.
- **Expected**: LLM identifies the 1 non-completer. DM confirmation sent for that person only. Backoff updated.

### STP-7.5: Exponential backoff

- **Precondition**: Follow-up created 5 days ago. backoff_days=4 (already reminded twice: day 1, day 3).
- **Input**: APScheduler fires on day 5.
- **Expected**: `now - last_run < backoff_days` (last_run was day 3, backoff=4, day 5 - day 3 = 2 < 4). Skip this check.

### STP-7.6: Expiration after 3 weeks

- **Precondition**: Follow-up created 22 days ago. expires_at = created_at + 21 days.
- **Input**: APScheduler fires.
- **Expected**: Job expired. Removed from scheduler. No LLM call. No DMs.

### STP-7.7: App restart — reload scheduled jobs

- **Precondition**: 3 scheduled skills exist on disk.
- **Input**: App restarts.
- **Expected**: skills_scheduler scans `scheduled_skills/` directory, re-registers all 3 jobs with APScheduler using metadata cron expressions.

### STP-7.8: Concurrent schedule execution prevented

- **Precondition**: Two scheduled jobs fire at the same time.
- **Input**: Both triggers arrive.
- **Expected**: Jobs run sequentially (APScheduler max_instances=1). Second waits for first to complete.

### STP-7.9: LLM failure during evaluation

- **Precondition**: LLM unreachable when scheduled job fires.
- **Input**: Job fires.
- **Expected**: Fail fast. Job stays scheduled for next run. No DMs sent. Error logged via `@log`.

### STP-7.10: Thread deleted or inaccessible

- **Precondition**: The thread referenced in metadata no longer exists.
- **Input**: Job fires.
- **Expected**: `read_thread` returns error. Scheduled job removed (no point retrying). Ephemeral to scheduling user: "Thread no longer accessible, follow-up removed."

## Unit Tests

**Files**: `common/tools/skills_scheduler/skills_scheduler_unit_test.py`, `common/tools/skills_scheduler/schedule_tool_unit_test.py`

**Mock**: Slack API, LLM client, filesystem (for SKILL.md / metadata.json)

### Test Cases

- **test_register_creates_files** — call `schedule_skill`, assert SKILL.md and metadata.json created at expected path
- **test_register_creates_apscheduler_job** — assert APScheduler `add_job` called with correct cron
- **test_metadata_schema** — assert metadata.json contains all required fields
- **test_run_action_not_done** — mock LLM returning "not done", assert DM tool called for non-completers
- **test_run_action_done** — mock LLM returning "done", assert job removed, no DMs
- **test_run_partial_done** — mock LLM returning 1 non-completer out of 3, assert 1 DM
- **test_backoff_skips** — set last_run to yesterday, backoff=2, assert job skipped
- **test_backoff_doubles** — after run, assert backoff_days *= 2 in metadata
- **test_expiration_removes_job** — set expires_at to past, assert job removed
- **test_reload_on_startup** — create 3 metadata files on disk, call reload, assert 3 APScheduler jobs registered
- **test_sequential_execution** — assert APScheduler configured with max_instances=1
- **test_thread_inaccessible** — mock `read_thread` error, assert job removed
- **test_tool_definition_schema** — assert `schedule_skill` tool matches LiteLLM format

### Fixtures

- `fixture_scheduled_skill/SKILL.md` — follow-up skill content
- `fixture_scheduled_skill/metadata.json` — valid metadata
- `fixture_thread_with_reactions.json` — thread messages + reactions data

## Integration Tests

**File**: `common/tools/skills_scheduler/skills_scheduler_integration_test.py`

**Mock**: Slack API, LLM client

### Test Cases

- **test_register_to_execution** — `/copilot follow up` → skill matched → schedule registered → manually trigger job → LLM evaluates → DM confirmations sent
- **test_full_lifecycle** — register → first check (not done, DM sent) → second check after backoff (still not done) → third check (done, job removed)
- **test_restart_recovery** — register job → simulate app restart → assert job re-registered → trigger → correct behavior
