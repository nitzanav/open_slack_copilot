import json
import re
from pathlib import Path

from common.log import log
from common.llm.llm_client import llm_client
from common.skill_runs import skill_runs
from common.skill_thumbs_up import skill_thumbs_up
from common.skills.skill_parser import Skill, parse_skill

SKILLS_ROOT = Path.home() / ".open_slack_copilot" / "skills"
_SKILL_KINDS = ("reply", "watcher")
# Reply skill folder name: one path segment, letters, underscore, hyphen.
_REPLY_SKILL_FOLDER_NAME_RE = re.compile(r"^[a-zA-Z_-]+\Z")

SELECTION_PROMPT = (
    "You are selecting relevant skills for drafting a Slack reply.\n"
    "Given the thread context and available skills, return a JSON array of "
    "skill references that are relevant. Return [] if none match.\n"
    "Each reference must be exactly as listed (kind/name).\n\n"
    "Available skills:\n{skill_list}\n\n"
    "Thread context:\n{thread_context}\n\n"
    "Return ONLY a JSON array, e.g. [\"reply/polite_reply\", \"watcher/checklist\"]"
)

SINGLE_SELECTION_PROMPT = (
    "Choose exactly ONE skill to drive this Slack copilot run.\n"
    "Pick the single most relevant skill id from the candidates below.\n"
    "Return ONLY the skill id (e.g. reply/polite_reply), no quotes, no extra text.\n\n"
    "Candidates:\n{skill_list}\n\n"
    "Thread context:\n{thread_context}"
)


@log
def select_skills(
    skill_type: str, thread_messages: list[dict], user_text: str,
) -> list[Skill]:
    """Stage 1: candidate skills. Each carries body text with examples appended."""
    entries = _skill_entries_for_kind(skill_type)
    if not entries:
        return []

    thread_context = _summarize_context(thread_messages, user_text)
    skill_list = _format_skill_list(entries)
    prompt = SELECTION_PROMPT.format(skill_list=skill_list, thread_context=thread_context)

    response = llm_client.generate(prompt)
    valid_refs = [s.id for s in entries]
    selected_refs = _parse_selection(response, valid_refs)
    by_ref = {s.id: s for s in entries}
    return [by_ref[ref] for ref in selected_refs if ref in by_ref]


def is_safe_reply_skill_folder_name(name: str) -> bool:
    """True when ``name`` is a single safe folder segment (``skills/reply/<name>/``)."""
    n = (name or "").strip()
    return bool(n) and _REPLY_SKILL_FOLDER_NAME_RE.match(n) is not None


@log
def load_forced_reply_skill(skill_folder: str) -> Skill | None:
    """Load ``reply/<skill_folder>/SKILL.md`` when present.

    ``skill_folder`` is the directory name under ``~/.open_slack_copilot/skills/reply/``
    (from a message shortcut ``callback_id`` after the ``slack_copilot_`` prefix).
    """
    cid = (skill_folder or "").strip()
    if not is_safe_reply_skill_folder_name(cid):
        return None
    d = SKILLS_ROOT / "reply" / cid
    if not d.is_dir() or not (d / "SKILL.md").is_file():
        return None
    ref = f"reply/{cid}"
    raw = (d / "SKILL.md").read_text().strip()
    return _skill_with_examples(ref, raw)


@log
def select_single_skill(
    skill_type: str, thread_messages: list[dict], user_text: str,
) -> Skill | None:
    """Stage 2: pick exactly one skill (LLM call)."""
    candidates = select_skills(skill_type, thread_messages, user_text)
    if not candidates:
        candidates = _skill_entries_for_kind(skill_type)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    thread_context = _summarize_context(thread_messages, user_text)
    skill_list = _format_skill_list(candidates)
    prompt = SINGLE_SELECTION_PROMPT.format(
        skill_list=skill_list, thread_context=thread_context,
    )
    valid_refs = [s.id for s in candidates]
    response = (llm_client.generate(prompt) or "").strip()
    picked_id = _parse_single_selection(response, valid_refs)
    by_ref = {s.id: s for s in candidates}
    if picked_id and picked_id in by_ref:
        return by_ref[picked_id]
    return candidates[0]


def _skill_entries_for_kind(kind: str) -> list[Skill]:
    if kind not in _SKILL_KINDS:
        return []
    base = SKILLS_ROOT / kind
    if not base.is_dir():
        return []
    out: list[Skill] = []
    for d in base.iterdir():
        if d.is_dir() and (d / "SKILL.md").is_file():
            ref = f"{kind}/{d.name}"
            raw = (d / "SKILL.md").read_text().strip()
            out.append(_skill_with_examples(ref, raw))
    return out


def _skill_with_examples(skill_id: str, raw: str) -> Skill:
    """Parse a SKILL.md and attach thumbs-up examples (rendered by render_body)."""
    skill = parse_skill(skill_id, raw)
    skill.examples = _format_examples_block(skill_id)
    skill._normalize_scalar_fields()
    return skill


def _format_skill_list(entries: list[Skill]) -> str:
    lines: list[str] = []
    for s in entries:
        desc = s.description
        lines.append(f"- {s.id}: {desc}" if desc else f"- {s.id}")
    return "\n".join(lines)


def _format_examples_block(skill_id: str) -> str:
    """Build the ``## Examples (recent good runs)`` section, or "" if none."""
    refs = skill_thumbs_up.recent_references(skill_id, limit=20)
    if not refs:
        return ""
    rendered: list[str] = []
    for r in refs:
        key = skill_runs._row_key(r.get("thread_ts", ""), r.get("action_ts", ""))
        row = skill_runs.get(key)
        if row:
            rendered.append(skill_runs.format_as_example(row))
    if not rendered:
        return ""
    return "## Examples (recent good runs)\n\n" + "\n\n".join(rendered)


def _parse_selection(response: str, valid_titles: list[str]) -> list[str]:
    try:
        start = response.index("[")
        end = response.index("]") + 1
        selected = json.loads(response[start:end])
        return [s for s in selected if s in valid_titles]
    except (ValueError, json.JSONDecodeError):
        return []


def _parse_single_selection(response: str, valid_refs: list[str]) -> str | None:
    text = (response or "").strip().strip("`\"' \n")
    if text in valid_refs:
        return text
    for ref in valid_refs:
        if ref in text:
            return ref
    return None


def _summarize_context(thread_messages: list[dict], user_text: str) -> str:
    # TODO: instead of thread_messages[-5:] need to take first 10 and then last 10 and put in the middle something like "20 other messages..."
    lines = [f"<@{m.get('user', '?')}>: {m.get('text', '')}" for m in thread_messages[-5:]]
    if user_text:
        lines.append(f"User instruction: {user_text}")
    return "\n".join(lines)
