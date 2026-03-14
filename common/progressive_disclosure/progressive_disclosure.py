import json
from pathlib import Path

from common.log import log
from common.llm.llm_client import llm_client

SKILLS_ROOT = Path.home() / ".open_slack_copilot" / "skills"
_BUNDLED_DEFAULT_INSTRUCTION = (Path(__file__).parent / "default_reply_instruction.md").read_text().strip()
USER_DEFAULT_INSTRUCTION_PATH = Path.home() / ".open_slack_copilot" / "reply_skills" / "default.md"

SELECTION_PROMPT = (
    "You are selecting relevant skills for drafting a Slack reply.\n"
    "Given the thread context and available skills, return a JSON array of "
    "skill folder names that are relevant. Return [] if none match.\n\n"
    "Available skills:\n{skill_list}\n\n"
    "Thread context:\n{thread_context}\n\n"
    "Return ONLY a JSON array of skill names, e.g. [\"polite_reply\", \"technical_review\"]"
)


@log
def select_skills(skill_type: str, thread_messages: list[dict], user_text: str) -> list[str]:
    skills_dir = SKILLS_ROOT / skill_type
    titles = _load_skill_titles(skills_dir)
    if not titles:
        return []

    thread_context = _summarize_context(thread_messages, user_text)
    skill_list = "\n".join(f"- {t}" for t in titles)
    prompt = SELECTION_PROMPT.format(skill_list=skill_list, thread_context=thread_context)

    response = llm_client.generate(prompt)
    selected = _parse_selection(response, titles)
    return [_read_skill(skills_dir / name / "SKILL.md") for name in selected]


def get_default_instruction() -> str:
    if USER_DEFAULT_INSTRUCTION_PATH.is_file():
        return USER_DEFAULT_INSTRUCTION_PATH.read_text().strip()
    return _BUNDLED_DEFAULT_INSTRUCTION


def _load_skill_titles(skills_dir: Path) -> list[str]:
    if not skills_dir.exists():
        return []
    return [d.name for d in skills_dir.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]


def _read_skill(path: Path) -> str:
    return path.read_text().strip()


def _parse_selection(response: str, valid_titles: list[str]) -> list[str]:
    try:
        start = response.index("[")
        end = response.index("]") + 1
        selected = json.loads(response[start:end])
        return [s for s in selected if s in valid_titles]
    except (ValueError, json.JSONDecodeError):
        return []


def _summarize_context(thread_messages: list[dict], user_text: str) -> str:
    lines = [f"<@{m.get('user', '?')}>: {m.get('text', '')}" for m in thread_messages[-5:]]
    if user_text:
        lines.append(f"User instruction: {user_text}")
    return "\n".join(lines)
