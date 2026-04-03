# Agent log (structured LLM action history)

[← Back to PRD](../../PRD.md)

This milestone adds an **append-only agent log** for each copilot run, **LLM-generated summaries** (2–20 words) of what happened, and **injection of recent agent log lines** into the system prompt so scheduled prompts and follow-ups have continuity.

---

## 1. Product specification

### 1.1 Goals

- Record every successful `prepare_draft` completion with **who triggered it**, **what kind of run** it was, and a **short natural-language summary** of the outcome.
- Persist each event in two places: a **global** file and a **per-thread** file under the repo directory **`agent_logs/`** (filesystem path; the product name in prompts and docs is **agent log**, singular).
- Surface the last **N** events for the same Slack thread inside **`compose_system_prompt`** (before the current instruction), with **N** configurable (default 10).

### 1.2 When to write a log line

| Condition | Log? |
|-----------|------|
| `prepare_draft` returns normally (including **empty** draft text) | Yes — append one NDJSON line and run summarizer |
| Exception before return (`ThreadFetchError`, LLM error, etc.) | No |

### 1.3 What the summary describes

The summary is the **primary user-meaningful outcome** of that run, not only the draft body. Examples of focus:

- A **reply draft** or **revision** (user asked shorter, more formal, etc.).
- A **scheduled prompt** was registered (tool outcome dominates).
- A **reminder / PM** was sent or queued (tool outcome dominates).

The implementation must pass enough context (final text + **tool trace**) into the summarizer so it can choose the right emphasis.

### 1.4 Triggers (structured enum)

All values are stable **snake_case** strings stored in JSON.

| Slack / runtime source | `trigger` value |
|------------------------|-----------------|
| `/copilot` | `slash_command` |
| Message shortcut “Draft with copilot” | `message_shortcut` |
| `app_mention` | `app_mention` |
| Revise modal submit (any originating flow) | `message_shortcut_revise` |
| APScheduler fires stored prompt | `scheduled_prompt` |

**Note:** Revise always uses `message_shortcut_revise` even if the original draft came from slash or mention — the field is a **trigger kind**, not UI provenance.

### 1.5 Actions (structured enum)

| Situation | Suggested `action` value |
|-----------|---------------------------|
| Normal draft / revise run producing (or attempting) a reply | `suggested_draft` |
| Cron execution of a stored scheduled prompt | `activated_scheduled_prompt` |

(Future milestones may add more `action` values if new run types appear.)

### 1.6 On-disk layout (v1)

Root directory: **`<repo>/agent_logs/`** (fixed path relative to repository root; no configurable path in v1).

```
agent_logs/
  llm_actions.log                          # all events, NDJSON
  channel/
    <channel_id>/
      thread/
        <thread_ts>/
          llm_actions.log                  # same lines as global, scoped to thread
```

- **`thread_ts`** is the same anchor the app already uses everywhere (including channel-root “tail” context: the parent message `ts` from `resolve_copilot_slack_context`).
- Slack `thread_ts` values contain a dot (e.g. `1234567890.123456`); they are valid single path segments on common filesystems.

### 1.7 NDJSON record schema

One JSON object per line:

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 UTC |
| `channel` | string | Slack channel ID (`C…`) |
| `thread_ts` | string | Thread anchor |
| `trigger` | string | See §1.4 |
| `action` | string | See §1.5 |
| `summary` | string | 2–20 words, plain text |

Example:

```json
{"timestamp":"2026-04-03T12:00:00+00:00","channel":"C0123","thread_ts":"1234.5678","trigger":"scheduled_prompt","action":"activated_scheduled_prompt","summary":"Reminded Dan and John to confirm deploy"}
```

### 1.8 Agent log (prompt injection — compact format)

When `prepare_draft` is called with activation metadata (`copilot_trigger` + `copilot_action`), **before** building the system prompt:

1. Read the per-thread `llm_actions.log` (if present).
2. Take the last **`llm_action_history_limit`** valid JSON lines (default **10**, clamp e.g. 1–50), oldest-first for display.
3. Build a **compact** block for the model. **Do not repeat `channel` or `thread_ts` on each line** — the thread block and channel context already establish where this is.

**Exact layout** (markdown body under a single section heading):

```markdown
## Agent log

[2026-03-14 16:26] message shortcut revise - suggested draft: wrote shorter draft
[2026-03-14 09:00] scheduled prompt - activated scheduled prompt: reminded Dan and John
```

- **Heading:** `## Agent log` (singular).
- **Each line:** `[YYYY-MM-DD HH:MM]` (UTC, derived from the record `timestamp`) **then** `<trigger> - <action>: <summary>`.
- **Trigger and action** in this block are the same enum strings as in NDJSON, but **rendered for reading**: replace `_` with a space (e.g. `message_shortcut_revise` → `message shortcut revise`, `suggested_draft` → `suggested draft`, `activated_scheduled_prompt` → `activated scheduled prompt`).
- **Summary:** verbatim from the record (already plain language).

**On-disk NDJSON** still includes `timestamp`, `channel`, `thread_ts`, `trigger`, `action`, `summary` for each line — only the **injected agent log** omits channel/thread on every history row.

If there is no history or activation is omitted, **omit the whole section** (no `## Agent log` header, no placeholder).

### 1.9 Configuration

In `config/default.yaml` under `slack_bot:`:

```yaml
llm_action_history_limit: 10
```

---

## 2. Code design

### 2.1 Module layout

| Piece | Location | Responsibility |
|-------|----------|----------------|
| Log I/O, path helpers, summarizer wrapper | `common/slack/llm_action_log.py` (new) | `agent_logs_root()`, `append_entry()`, `read_recent_for_thread()`, `summarize_copilot_run()` |
| Tool loop with trace | `common/llm/llm_client/llm_client.py` | `agent_tool_loop` returns final text **and** ordered list of tool executions |
| Orchestration | `common/slack/copilot_pipeline.py` | `prepare_draft`: read history → `compose_system_prompt` → tool loop → summarize → append |
| Prompt template | `common/slack/draft_prompt.md` | Optional `{agent_log}` block (agent log section) |
| Entry points | `slack_listener_with_threads.py`, `draft_revise_actions.py`, `prompt_scheduler.py`, `core/slack_bot.py` | Pass `copilot_trigger` / `copilot_action` |

### 2.2 Repository root resolution

Mirror [`EXAMPLES_PATH`](../../../common/slack/copilot_pipeline.py) style:

```python
_REPO_ROOT = Path(__file__).resolve().parents[2]  # from common/slack/*.py
AGENT_LOGS_ROOT = _REPO_ROOT / "agent_logs"
```

All paths derive from `AGENT_LOGS_ROOT` (or a single function that returns it).

### 2.3 Concurrency

- Use a **process-wide `threading.Lock()`** around append operations so concurrent Slack handlers do not interleave bytes in `agent_logs/llm_actions.log`.
- Per-thread files: same lock is sufficient (single lock for all agent log writes keeps ordering predictable and implementation simple).

### 2.4 `agent_tool_loop` contract change

**Today:** returns `str` (final assistant content).

**After:** return a small **result object** or **tuple** usable only inside `prepare_draft`, for example:

```python
@dataclass
class AgentToolLoopResult:
    text: str
    tool_trace: list[ToolCallRecord]

@dataclass
class ToolCallRecord:
    name: str
    result_preview: str  # truncated JSON string, max ~400–800 chars per call
```

Implementation detail: while handling each `tool_calls` batch in the loop, append `(name, truncated result)` to `tool_trace`. On early exit (max rounds), still return whatever text and trace exist.

**Callers:** Only `prepare_draft` in `copilot_pipeline.py` needs updating; tests that mock `agent_tool_loop` should set `return_value` to `AgentToolLoopResult("...", [])` or a simple namespace.

### 2.5 `prepare_draft` signature (backward compatible)

Add optional keyword-only style parameters:

```python
def prepare_draft(
    channel_id: str,
    thread_ts: str,
    user_id: str,
    user_text: str,
    ...,
    copilot_trigger: str | None = None,
    copilot_action: str | None = None,
) -> str:
```

- If **`copilot_trigger` and `copilot_action` are both `None`**: skip reading history, skip append/summarize (preserves existing unit tests and internal callers).
- If **both set**: read recent lines, inject into `compose_system_prompt`, run loop, then summarize and append.

### 2.6 `compose_system_prompt` extension

```python
def compose_system_prompt(
    ...,
    agent_log_section: str = "",
) -> str:
```

- `agent_log_section` is either `""` or the full **Agent log** subsection: `## Agent log` plus newline-separated compact lines per §1.8 (no channel/thread per line).
- `draft_prompt.md` gains a placeholder `{agent_log}`, placed **after** `## Thread` and **before** `## Instruction` so schedules see thread content first, then the agent log, then the current ask.

### 2.7 Summarization (`summarize_copilot_run`)

- Input: `trigger`, `action`, trimmed `user_text`, `final_text` (may be empty), `tool_trace` (may be empty).
- Call `llm_client.generate(system=..., user=...)` with instructions: output **2–20 words**, plain English, describe the **main outcome** (prefer tool outcomes when they are the substantive result).
- On failure or empty model output: fallback string from heuristics (keywords from tool names / `user_text`) or `"Copilot run completed"`.

### 2.8 Sequence (happy path)

```mermaid
sequenceDiagram
  participant Slack
  participant Handler as EntryHandler
  participant Prep as prepare_draft
  participant Log as llm_action_log
  participant Compose as compose_system_prompt
  participant Loop as agent_tool_loop
  participant LLM as llm_client

  Slack->>Handler: event
  Handler->>Prep: copilot_trigger, copilot_action
  Prep->>Log: read_recent_for_thread
  Log-->>Prep: entries
  Prep->>Compose: agent_log_section
  Compose-->>Prep: system_prompt
  Prep->>Loop: tools, prompts
  Loop-->>Prep: AgentToolLoopResult
  Prep->>LLM: generate summary
  LLM-->>Prep: summary text
  Prep->>Log: append_entry global + thread
  Prep-->>Handler: draft str
```

### 2.9 Testing strategy

- **Unit:** `llm_action_log` — append twice, read tail, corrupt middle line skipped, limit respected.
- **Unit:** `prepare_draft` with mocks — when trigger/action set, `compose_system_prompt` receives a non-empty **Agent log** section if log file seeded in tmp_path (monkeypatch `agent_logs` root).
- **Unit:** `agent_tool_loop` — fake tool call produces trace entries with expected names.
- Existing tests that omit `copilot_trigger` / `copilot_action` remain unchanged.

### 2.10 Hygiene

- **Repository:** add this line to [`.gitignore`](../../../.gitignore) at repo root so runtime data is never committed:

  ```
  /agent_logs/
  ```

  (`*.log` already ignores individual `.log` files; ignoring the directory is clearer and covers any future files under it.)

- Do not confuse **`docs/milestones/agent_logs/`** (this milestone documentation folder name) with **`agent_logs/`** at repo root (runtime NDJSON files for the **agent log** feature).

---

## 3. Implementation checklist (for PRs)

- [ ] Add `common/slack/llm_action_log.py`
- [ ] Extend `agent_tool_loop` + `prepare_draft` + `compose_system_prompt` + `draft_prompt.md`
- [ ] Wire triggers from slash / shortcut / mention / revise / scheduler
- [ ] `default.yaml`: `llm_action_history_limit`
- [ ] `.gitignore`: `/agent_logs/`
- [ ] Tests (log module + pipeline mocks)
