"""Parse leading step table from ``SKILL.md`` (optional multi-step skills).

Steps are returned as an ordered ``dict[str, str]`` of ``step_name ->
instruction``. Callers index steps by name and rely on insertion order to walk
through them.
"""

from __future__ import annotations

import re


def _strip_cell(s: str) -> str:
    return (s or "").strip().strip("*").strip()


def _is_step_table_header(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    return _strip_cell(cells[0]).lower() == "step" and _strip_cell(cells[1]).lower() == "instruction"


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(re.match(r"^:?-+:?$", (c or "").strip()) for c in cells if (c or "").strip())


def _split_table_row(line: str) -> list[str] | None:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    return [p.strip() for p in s[1:-1].split("|")]


def parse_steps_from_markdown(text: str) -> tuple[dict[str, str], str]:
    """If the first non-empty block is a ``| Step | Instruction |`` table, return
    ``(steps, body_after_table)``.

    Otherwise return a single implicit ``main`` step whose instruction is the
    full text.
    """
    raw = (text or "").strip()
    if not raw:
        return ({"main": ""}, "")

    lines = raw.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return ({"main": ""}, "")

    first = _split_table_row(lines[i])
    if not first or len(first) < 2 or not _is_step_table_header(first):
        return ({"main": raw}, raw)

    i += 1
    if i >= len(lines):
        return ({"main": raw}, raw)

    sep = _split_table_row(lines[i])
    if not sep or not _is_separator_row(sep):
        return ({"main": raw}, raw)

    i += 1
    steps: dict[str, str] = {}
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            break
        cells = _split_table_row(line)
        if not cells or len(cells) < 2:
            break
        name = _strip_cell(cells[0])
        if name:
            steps[name] = _strip_cell(cells[1])
        i += 1

    if not steps:
        return ({"main": raw}, raw)

    while i < len(lines) and not lines[i].strip():
        i += 1
    body = "\n".join(lines[i:]).strip()
    return (steps, body)


def skill_folder_from_skill_id(skill_id: str | None) -> str:
    if not skill_id or not str(skill_id).strip():
        return "copilot"
    return str(skill_id).strip().split("/")[-1].strip() or "copilot"
