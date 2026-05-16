"""Parse a ``SKILL.md`` file into a typed :class:`Skill`.

The on-disk format is::

    ---
    name: <short display name>
    description: <one-line description used by progressive disclosure>
    ---
    optional preamble text shared by every step

    ## <step_name>
    instruction for this step

    ## <next_step_name>
    instruction for the next step

Rules:
- The frontmatter ``---`` block holds ``name`` and ``description``. They are
  surfaced to the LLM during skill selection (progressive disclosure).
- Each ``##`` heading defines a step: heading text -> step name, body until
  the next ``##`` (or EOF) -> instruction.
- Text before the first ``##`` is the *preamble* and is prepended to every
  step's instruction so steps share common context.
- Zero or one ``##`` heading collapses to a single implicit ``main`` step
  whose instruction is the full body (preamble + lone section).
- If the frontmatter block is missing, ``parse_skill`` logs a warning and
  falls back to: ``description`` = first non-empty body line, ``name`` =
  skill folder portion of ``skill_id``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

_logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<body>.*?)\n---\s*(?:\n|\Z)",
    re.DOTALL,
)
_H2_RE = re.compile(r"^##\s+(?P<name>.+?)\s*$", re.MULTILINE)


@dataclass
class Skill:
    """A parsed ``SKILL.md`` file.

    ``examples`` is an optional extra block (e.g. recent thumbs-up runs) that
    callers can attach via progressive disclosure; it is not part of the file
    itself, but :func:`render_body` will append it after the steps.
    """

    id: str = ""
    name: str = ""
    description: str = ""
    preamble: str = ""
    steps: dict[str, str] = field(default_factory=dict)
    raw_body: str = ""
    examples: str = ""

    def __post_init__(self) -> None:
        self._normalize_scalar_fields()

    def _normalize_scalar_fields(self) -> None:
        """Strip id/name/description/examples/preamble once; callers should not repeat ``(x or '').strip()``."""
        self.id = (self.id or "").strip()
        self.name = (self.name or "").strip()
        self.description = (self.description or "").strip()
        self.examples = (self.examples or "").strip()
        self.preamble = (self.preamble or "").strip()


def parse_skill(skill_id: str, text: str) -> Skill:
    """Parse a ``SKILL.md`` document for the given ``skill_id``.

    ``skill_id`` is the ``kind/folder`` reference (e.g. ``reply/follow_up``);
    its trailing segment is used as a fallback when the frontmatter is missing
    a ``name`` field.
    """
    raw = text or ""
    name, description, body = _split_frontmatter(raw)
    if name is None and description is None:
        _logger.warning(
            "SKILL.md for %s is missing frontmatter; using first-line fallback "
            "for description and folder name for name. Add a `---\\nname: ...\\n"
            "description: ...\\n---` block.",
            skill_id or "(unknown skill)",
        )
        name = _folder_segment(skill_id)
        description = _first_non_empty_line(body)
    else:
        if not name:
            name = _folder_segment(skill_id)
        if not description:
            description = _first_non_empty_line(body)

    preamble, steps = _split_steps(body)
    if not steps:
        steps = {"main": body.strip()}
        preamble = ""

    if preamble:
        steps = {
            step_name: _merge_preamble(preamble, instruction)
            for step_name, instruction in steps.items()
        }

    return Skill(
        id=skill_id or "",
        name=name or "",
        description=description or "",
        preamble=preamble,
        steps=steps,
        raw_body=body,
    )


def render_body(skill: Skill) -> str:
    """Flatten a Skill into the body string used as system-prompt instructions.

    Used when callers still consume a single instruction blob rather than
    walking ``skill.steps`` one at a time. Appends ``skill.examples`` (if any).
    """
    if skill.steps == {"main": skill.raw_body.strip()}:
        body = skill.raw_body.strip()
    else:
        parts: list[str] = []
        if skill.preamble.strip():
            parts.append(skill.preamble.strip())
        for name, inst in skill.steps.items():
            section = f"## {name}\n{inst}".strip()
            parts.append(section)
        body = "\n\n".join(p for p in parts if p).strip()
    examples = skill.examples
    if not examples:
        return body
    if not body:
        return examples
    return f"{body}\n\n{examples}"


def _split_frontmatter(raw: str) -> tuple[str | None, str | None, str]:
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return None, None, raw.lstrip("\n")
    fm = m.group("body")
    body = raw[m.end():].lstrip("\n")
    name: str | None = None
    description: str | None = None
    for line in fm.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "name":
            name = value
        elif key == "description":
            description = value
    return name or "", description or "", body


def _split_steps(body: str) -> tuple[str, dict[str, str]]:
    """Return ``(preamble, steps)`` from a body string.

    Empty ``steps`` means no ``##`` headings were found.
    """
    if not body.strip():
        return "", {}
    matches = list(_H2_RE.finditer(body))
    if not matches:
        return "", {}
    if len(matches) == 1:
        # Single ## treated as implicit single step; preamble (if any) becomes
        # part of the implicit step in the caller's collapse path.
        return "", {}
    preamble = body[: matches[0].start()].strip()
    steps: dict[str, str] = {}
    for i, m in enumerate(matches):
        step_name = m.group("name").strip()
        section_start = m.end()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        instruction = body[section_start:section_end].strip()
        if step_name:
            steps[step_name] = instruction
    return preamble, steps


def _merge_preamble(preamble: str, instruction: str) -> str:
    pre = preamble.strip()
    inst = instruction.strip()
    if not pre:
        return inst
    if not inst:
        return pre
    return f"{pre}\n\n{inst}"


def _first_non_empty_line(body: str) -> str:
    for line in (body or "").splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def _folder_segment(skill_id: str | None) -> str:
    if not skill_id or not str(skill_id).strip():
        return ""
    return str(skill_id).strip().split("/")[-1].strip()
