import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from common.tools.append_csv_row import (
    APPEND_CSV_ROW,
    APPEND_CSV_ROW_TOOL,
    _INJECTED_COLUMNS,
)
from common.tools.react_context import react_invocation_context


@pytest.fixture
def data_root(tmp_path):
    from config.config import settings

    original = settings.get("data_layer", {})
    settings.set("data_layer", {**original, "root": str(tmp_path)})
    yield tmp_path
    settings.set("data_layer", original)


def _invoke(fields):
    return json.loads(APPEND_CSV_ROW.handle(json.dumps(fields)))


def test_tool_schema_name():
    assert APPEND_CSV_ROW_TOOL["function"]["name"] == "append_csv_row"


@patch("common.tools.append_csv_row.slack_api")
def test_creates_file_with_header_and_appends(mock_api, data_root):
    mock_api.get_channel_prefixed_name.return_value = "#general"
    with react_invocation_context(
        "C1", "T1.0", "Ureq", skill_id="my_skill", action_ts="A1.0",
    ):
        out1 = _invoke({"sentiment": "positive", "topic": "release"})
        out2 = _invoke({"sentiment": "negative", "topic": "bug"})

    path = Path(out1["path"])
    assert path == data_root / "data" / "my_skill.csv"
    assert out1["status"] == "appended"
    assert out2["status"] == "appended"

    with path.open() as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(_INJECTED_COLUMNS) + ["sentiment", "topic"]
    assert rows[1] == ["my_skill", "#general", "T1.0", "A1.0", "positive", "release"]
    assert rows[2] == ["my_skill", "#general", "T1.0", "A1.0", "negative", "bug"]


@patch("common.tools.append_csv_row.slack_api")
def test_existing_header_is_preserved(mock_api, data_root):
    mock_api.get_channel_prefixed_name.return_value = "#general"
    with react_invocation_context(
        "C1", "T1.0", "Ureq", skill_id="s1", action_ts="A1.0",
    ):
        _invoke({"a": "1", "b": "2"})
        _invoke({"a": "9", "c": "ignored"})

    with (data_root / "data" / "s1.csv").open() as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(_INJECTED_COLUMNS) + ["a", "b"]
    assert rows[2][-2:] == ["9", ""]


@patch("common.tools.append_csv_row.slack_api")
def test_llm_cannot_override_injected_columns(mock_api, data_root):
    mock_api.get_channel_prefixed_name.return_value = "#general"
    with react_invocation_context(
        "C1", "T1.0", "Ureq", skill_id="s2", action_ts="A1.0",
    ):
        _invoke({"skill_id": "spoof", "thread_ts": "spoof", "note": "ok"})

    with (data_root / "data" / "s2.csv").open() as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(_INJECTED_COLUMNS) + ["note"]
    assert rows[1] == ["s2", "#general", "T1.0", "A1.0", "ok"]


def test_requires_skill_id():
    with react_invocation_context("C1", "T1.0", "Ureq"):
        out = _invoke({"x": "y"})
    assert "error" in out
