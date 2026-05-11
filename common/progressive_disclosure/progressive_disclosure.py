import json
from pathlib import Path

from common.log import log
from common.llm.llm_client import llm_client
from common.skill_runs import skill_runs
from common.skill_thumbs_up import skill_thumbs_up

SKILLS_ROOT = Path.home() / ".open_slack_copilot" / "skills"
_SKILL_KINDS = ("reply", "watcher")

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
) -> list[tuple[str, str]]:
    """Stage 1: candidate skills matching the thread. Returns (id, text) pairs."""
    entries = _skill_entries_for_kind(skill_type)
    if not entries:
        return []

    thread_context = _summarize_context(thread_messages, user_text)
    skill_list = "\n".join(f"- {ref}" for ref, _ in entries)
    prompt = SELECTION_PROMPT.format(skill_list=skill_list, thread_context=thread_context)

    response = llm_client.generate(prompt)
    valid_refs = [ref for ref, _ in entries]
    selected_refs = _parse_selection(response, valid_refs)
    by_ref = dict(entries)
    return [(ref, by_ref[ref]) for ref in selected_refs if ref in by_ref]


@log
def select_single_skill(
    skill_type: str, thread_messages: list[dict], user_text: str,
) -> tuple[str, str] | None:
    """Stage 2: pick exactly one skill (LLM call). Returns (id, text) or None if none installed."""
    candidates = select_skills(skill_type, thread_messages, user_text)
    if not candidates:
        candidates = _skill_entries_for_kind(skill_type)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    thread_context = _summarize_context(thread_messages, user_text)
    skill_list = "\n".join(f"- {ref}" for ref, _ in candidates)
    prompt = SINGLE_SELECTION_PROMPT.format(
        skill_list=skill_list, thread_context=thread_context,
    )
    valid_refs = [ref for ref, _ in candidates]
    response = (llm_client.generate(prompt) or "").strip()
    picked_id = _parse_single_selection(response, valid_refs)
    by_ref = dict(candidates)
    if picked_id and picked_id in by_ref:
        return picked_id, by_ref[picked_id]
    return candidates[0]


def _skill_entries_for_kind(kind: str) -> list[tuple[str, str]]:
    if kind not in _SKILL_KINDS:
        return []
    base = SKILLS_ROOT / kind
    if not base.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for d in base.iterdir():
        if d.is_dir() and (d / "SKILL.md").is_file():
            ref = f"{kind}/{d.name}"
            skill_text = (d / "SKILL.md").read_text().strip()
            out.append((ref, _with_examples(ref, skill_text)))
    return out


def _with_examples(skill_id: str, skill_text: str) -> str:
    refs = skill_thumbs_up.recent_references(skill_id, limit=20)
    if not refs:
        return skill_text
    rendered: list[str] = []
    for r in refs:
        key = skill_runs._row_key(r.get("thread_ts", ""), r.get("action_ts", ""))
        row = skill_runs.get(key)
        if row:
            rendered.append(skill_runs.format_as_example(row))
    if not rendered:
        return skill_text
    return f"{skill_text}\n\n## Examples (recent good runs)\n\n" + "\n\n".join(rendered)


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
