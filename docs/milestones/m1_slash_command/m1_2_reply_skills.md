# M1.2 — Reply Skills (Progressive Disclosure)

## Requirements

- **Load reply skills** — read all skills from `~/.open_slack_copilot/skills/reply/<id>/SKILL.md`
- **Progressive disclosure** — two-pass: send skill titles to LLM, LLM picks relevant ones, load full content of selected skills into system prompt
- **Multiple skills** — LLM can select multiple relevant reply skills for one draft
- **Default fallback** — if no skill matches, use a hardcoded default instruction from a file in the codebase (e.g. "generate a reply based on the thread context")
- **Freeform format** — each SKILL.md is freeform markdown; LLM reads the whole file as instruction
- **Extend M1.1** — add selected skill content to system prompt before calling LLM

## Architecture

### Modules

- `common/progressive_disclosure/progressive_disclosure.py` — loads skill titles, asks LLM to pick, returns full content of selected skills
- `common/llm/llm_client/llm_client.py` — used by progressive disclosure for the selection pass
- `core/slack_bot.py` — calls progressive disclosure before composing the final prompt
### Config

No additional config. Skills path is a hardcoded convention: `~/.open_slack_copilot/skills/`

### Skill Storage

```
~/.open_slack_copilot/
  skills/
    reply/
      polite_reply/
        SKILL.md          # freeform markdown — LLM reads as instruction
      technical_review/
        SKILL.md
    channel_watcher/
      support_escalation/
        SKILL.md

# Default fallback lives in the codebase, not in the user skills directory:
common/progressive_disclosure/
  default_reply_instruction.md    # hardcoded: "generate a reply based on the thread context"
```

### Data Flow

```
prepare_draft_order(thread_messages, user_text)
       │
       ├── progressive_disclosure.select_skills("reply", thread_messages, user_text)
       │         │
       │         ├── load all SKILL.md titles from skills/reply/
       │         ├── LLM pass 1: "which skills are relevant?" → returns skill IDs
       │         └── load full SKILL.md content for selected IDs
       │
       ├── compose_system_prompt(thread_messages, user_text, selected_skills)
       ├── llm_client.generate(prompt)     ← LLM pass 2: generate draft
       └── slack_api.send_ephemeral(draft)
```

### Key Decisions

- **Two LLM calls** per draft: one for skill selection, one for draft generation
- **Skill title** = folder name (human-readable, e.g. `polite_reply`)
- **No skill metadata JSON yet** — just freeform SKILL.md; channel filter JSON is a later milestone (M14)

## STP — Software Test Procedure

### STP-1.2.1: Happy path — one skill matches

- **Precondition**: 3 reply skills exist. Thread with a technical question.
- **Input**: `/copilot`
- **Expected**: Progressive disclosure selects `technical_review` skill. System prompt includes skill content + thread. Draft reflects skill instructions.

### STP-1.2.2: Multiple skills match

- **Precondition**: Thread context is both technical and requires politeness.
- **Input**: `/copilot`
- **Expected**: LLM selects both `technical_review` and `polite_reply`. Both skill contents in system prompt. Draft combines both instructions.

### STP-1.2.3: No skill matches — fallback to hardcoded default

- **Precondition**: Thread context doesn't match any specific skill.
- **Input**: `/copilot`
- **Expected**: Progressive disclosure returns no matches. Hardcoded default instruction from codebase loaded (e.g. "generate a reply based on the thread context"). Draft uses that instruction.

### STP-1.2.4: No skills directory / empty directory

- **Precondition**: `skills/reply/` doesn't exist or is empty.
- **Input**: `/copilot`
- **Expected**: Progressive disclosure skipped entirely. Falls back to M1.1 behavior (no skill, just thread context).

### STP-1.2.5: Skill with very long content

- **Precondition**: A SKILL.md with 2000+ words.
- **Input**: `/copilot`
- **Expected**: Full skill content included in prompt. No truncation in this milestone.

### STP-1.2.6: User text overrides skill

- **Precondition**: Skill says "be formal". User text says "be casual".
- **Input**: `/copilot be casual`
- **Expected**: User text takes priority. System prompt positions user text after skill instructions so LLM weights it higher.

### STP-1.2.7: LLM fails during skill selection pass

- **Precondition**: LLM errors on the first (selection) call.
- **Input**: `/copilot`
- **Expected**: Fail fast — ephemeral error to user. No fallback to draft without skills.

## Unit Tests

**Files**: `common/progressive_disclosure/progressive_disclosure_unit_test.py`, `core/slack_bot_unit_test.py`

**Mock**: LLM client (both selection call and generation call)

### Test Cases

- **test_load_skill_titles** — given skills directory with 3 folders, assert 3 titles loaded
- **test_select_single_skill** — mock LLM returning one skill ID, assert full SKILL.md content returned
- **test_select_multiple_skills** — mock LLM returning two IDs, assert both contents returned
- **test_no_match_returns_hardcoded_default** — mock LLM returning empty selection, assert hardcoded default instruction from codebase loaded
- **test_empty_skills_dir** — assert progressive disclosure returns empty list, no LLM call made
- **test_missing_skills_dir** — assert progressive disclosure returns empty list gracefully
- **test_prompt_includes_skills** — assert `compose_system_prompt` includes skill content before thread context
- **test_user_text_positioned_after_skills** — assert user text comes after skill content in prompt

### Fixtures

- `fixture_skills_dir/` — directory with 3 SKILL.md files (no default — default is hardcoded in codebase)
- `fixture_thread_technical.json` — thread messages with technical content

## Integration Tests

**File**: `common/progressive_disclosure/progressive_disclosure_integration_test.py`

**Mock**: LLM client only. Skills directory is real (test fixtures on disk).

### Test Cases

- **test_end_to_end_skill_selection** — real skills directory → progressive disclosure → mock LLM picks skill → full content returned → verify content matches SKILL.md on disk
- **test_slash_command_with_skills** — simulate `/copilot` → thread enrichment → progressive disclosure → draft generation → ephemeral. Assert skill content present in the prompt sent to the draft LLM call.
