"""Unit tests for ``skill_parser.parse_skill`` and ``render_body``."""

import logging

from common.skills.skill_parser import Skill, parse_skill, render_body


class TestParseSkill:
    def test_full_frontmatter_and_multiple_steps(self):
        text = (
            "---\n"
            "name: summarize and save as CSV\n"
            "description: summarize thread, and save output as CSV\n"
            "---\n"
            "## summarize\n"
            "summarize the problems and solutions\n"
            "when summarizing check all information\n"
            "\n"
            "## write_csv\n"
            "save the summary as CSV\n"
            "when writing to CSV use tools\n"
        )
        skill = parse_skill("reply/summarize_csv", text)
        assert skill.name == "summarize and save as CSV"
        assert skill.description == "summarize thread, and save output as CSV"
        assert list(skill.steps.keys()) == ["summarize", "write_csv"]
        assert skill.steps["summarize"].startswith("summarize the problems")
        assert "when summarizing check all information" in skill.steps["summarize"]
        assert skill.steps["write_csv"].startswith("save the summary as CSV")
        assert skill.preamble == ""

    def test_frontmatter_only_no_h2_collapses_to_main(self):
        text = (
            "---\n"
            "name: Polite Reply\n"
            "description: Be polite.\n"
            "---\n"
            "\n"
            "Be polite and concise.\n"
        )
        skill = parse_skill("reply/polite_reply", text)
        assert skill.name == "Polite Reply"
        assert skill.description == "Be polite."
        assert skill.steps == {"main": "Be polite and concise."}

    def test_single_h2_collapses_to_main(self):
        text = (
            "---\n"
            "name: Single\n"
            "description: d\n"
            "---\n"
            "## only_one\n"
            "do the thing\n"
        )
        skill = parse_skill("reply/single", text)
        assert "main" in skill.steps
        assert "only_one" in skill.steps["main"]
        assert "do the thing" in skill.steps["main"]

    def test_preamble_merged_into_each_step(self):
        text = (
            "---\n"
            "name: x\n"
            "description: y\n"
            "---\n"
            "Shared rules: be polite.\n"
            "\n"
            "## first\n"
            "do A\n"
            "\n"
            "## second\n"
            "do B\n"
        )
        skill = parse_skill("reply/x", text)
        assert skill.preamble == "Shared rules: be polite."
        assert "Shared rules: be polite." in skill.steps["first"]
        assert "do A" in skill.steps["first"]
        assert "Shared rules: be polite." in skill.steps["second"]
        assert "do B" in skill.steps["second"]

    def test_no_frontmatter_warns_and_falls_back(self, caplog):
        text = "Be helpful.\nDo not be rude.\n"
        with caplog.at_level(logging.WARNING):
            skill = parse_skill("reply/general", text)
        assert any("missing frontmatter" in r.message for r in caplog.records)
        assert skill.name == "general"
        assert skill.description == "Be helpful."
        assert skill.steps == {"main": "Be helpful.\nDo not be rude."}

    def test_no_frontmatter_no_skill_id(self, caplog):
        with caplog.at_level(logging.WARNING):
            skill = parse_skill("", "first line\nsecond line\n")
        assert skill.name == ""
        assert skill.description == "first line"

    def test_empty_text(self):
        skill = parse_skill("reply/empty", "")
        assert skill.steps == {"main": ""}
        assert skill.name == "empty"
        assert skill.description == ""

    def test_frontmatter_missing_description_falls_back(self):
        text = (
            "---\n"
            "name: Only Name\n"
            "---\n"
            "first body line\n"
            "more\n"
        )
        skill = parse_skill("reply/only_name", text)
        assert skill.name == "Only Name"
        assert skill.description == "first body line"

    def test_frontmatter_missing_name_falls_back_to_folder(self):
        text = (
            "---\n"
            "description: a desc\n"
            "---\n"
            "body\n"
        )
        skill = parse_skill("reply/my_folder", text)
        assert skill.name == "my_folder"
        assert skill.description == "a desc"


class TestRenderBody:
    def test_single_main_step_returns_raw_body(self):
        skill = parse_skill("reply/p", "---\nname: P\ndescription: d\n---\nbody text\n")
        assert render_body(skill) == "body text"

    def test_multi_step_renders_preamble_and_sections(self):
        text = (
            "---\nname: x\ndescription: d\n---\n"
            "preamble line\n"
            "\n"
            "## a\nfirst\n\n## b\nsecond\n"
        )
        skill = parse_skill("reply/x", text)
        rendered = render_body(skill)
        assert "preamble line" in rendered
        assert "## a" in rendered and "first" in rendered
        assert "## b" in rendered and "second" in rendered

    def test_examples_appended(self):
        skill = Skill(id="reply/x", steps={"main": "body"}, raw_body="body")
        skill.examples = "## Examples\n\nfoo"
        rendered = render_body(skill)
        assert rendered.startswith("body")
        assert "## Examples" in rendered
        assert "foo" in rendered
