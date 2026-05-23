"""Convert common Markdown fragments to Slack mrkdwn for chat_postMessage (mrkdwn=True)."""

from __future__ import annotations

import re

_FENCED_CODE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_BOLD_ASTERISKS = re.compile(r"\*\*(.+?)\*\*")
_BOLD_UNDERSCORES = re.compile(r"__(.+?)__")
_STRIKE = re.compile(r"~~(.+?)~~")
_ATX_HEADER = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)


def to_slack_mrkdwn(text: str) -> str:
    """
    Normalize LLM/GitHub-style Markdown so Slack renders it when mrkdwn=True.

    Converts **bold** to *bold*, ATX headers to bold lines, and ~~strike~~ to ~strike~.
    Fenced and inline code spans are left unchanged.
    """
    if not text:
        return text

    stashed: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        stashed.append(match.group(0))
        return f"\ufffdS{len(stashed) - 1}\ufffd"

    out = _FENCED_CODE.sub(_stash, text)
    out = _INLINE_CODE.sub(_stash, out)
    out = _BOLD_ASTERISKS.sub(r"*\1*", out)
    out = _BOLD_UNDERSCORES.sub(r"*\1*", out)
    out = _STRIKE.sub(r"~\1~", out)
    out = _ATX_HEADER.sub(r"*\1*", out)

    for index, raw in enumerate(stashed):
        out = out.replace(f"\ufffdS{index}\ufffd", raw)
    return out
