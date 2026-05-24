import json
from unittest.mock import patch

import pytest

from common.skill_thumbs_up import skill_thumbs_up as stu


@pytest.fixture
def skills_root(tmp_path):
    with patch("common.skill_thumbs_up.skill_thumbs_up.SKILLS_ROOT", tmp_path):
        yield tmp_path


def test_add_reference_creates_file(skills_root):
    ok = stu.add_reference("foo", "1.0", "2026-05-10T00:00:00+00:00")
    assert ok is True
    path = skills_root / "foo" / "thumbs_up.json"
    assert path.is_file()
    data = json.loads(path.read_text())
    assert data == [{"thread_ts": "1.0", "action_ts": "2026-05-10T00:00:00+00:00"}]


def test_add_reference_dedupes(skills_root):
    stu.add_reference("foo", "1.0", "a")
    stu.add_reference("foo", "1.0", "a")
    stu.add_reference("foo", "1.0", "b")
    refs = stu.recent_references("foo")
    assert refs == [
        {"thread_ts": "1.0", "action_ts": "a"},
        {"thread_ts": "1.0", "action_ts": "b"},
    ]


def test_add_reference_invalid_skill_id(skills_root):
    assert stu.add_reference("", "1.0", "a") is False
    assert stu.add_reference("reply/foo", "1.0", "a") is False


def test_add_reference_missing_values(skills_root):
    assert stu.add_reference("foo", "", "a") is False
    assert stu.add_reference("foo", "1.0", "") is False


def test_caps_at_max_kept(skills_root):
    for i in range(stu._MAX_KEPT + 10):
        stu.add_reference("foo", "1.0", f"a{i}")
    refs = stu.recent_references("foo", limit=stu._MAX_KEPT + 50)
    assert len(refs) == stu._MAX_KEPT
    assert refs[-1] == {"thread_ts": "1.0", "action_ts": f"a{stu._MAX_KEPT + 9}"}


def test_recent_references_missing_file(skills_root):
    assert stu.recent_references("foo") == []


def test_recent_references_limit_zero(skills_root):
    stu.add_reference("foo", "1.0", "a")
    assert stu.recent_references("foo", limit=0) == []
