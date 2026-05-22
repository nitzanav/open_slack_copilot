"""Unit tests for ``skill_steps.parse_steps_from_markdown``."""

from common.skills.skill_steps import (
    parse_steps_from_markdown,
    skill_folder_from_skill_id,
)


def test_parse_no_table_single_main():
    text = "Hello\n\nWorld"
    steps, body = parse_steps_from_markdown(text)
    assert body == text
    assert steps == {"main": text}


def test_parse_empty_text():
    steps, body = parse_steps_from_markdown("")
    assert body == ""
    assert steps == {"main": ""}


def test_parse_leading_step_table():
    md = """| Step | Instruction |
|------|-------------|
| summarize | Summarize the thread |
| post | Post the reply |

Shared footer.
"""
    steps, body = parse_steps_from_markdown(md)
    assert steps == {
        "summarize": "Summarize the thread",
        "post": "Post the reply",
    }
    assert list(steps.keys()) == ["summarize", "post"]
    assert body.strip() == "Shared footer."


def test_skill_folder_from_skill_id():
    assert skill_folder_from_skill_id("reply/draft_thread_reply") == "draft_thread_reply"
    assert skill_folder_from_skill_id(None) == "copilot"
