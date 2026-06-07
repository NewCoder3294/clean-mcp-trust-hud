"""Tests for the statusline renderer."""

from clean.scoring.statusline import render


def _state(**over):
    base = {
        "overall_score": 82,
        "overall_label": "REVIEW",
        "stale": False,
        "indexed": True,
        "skipped": False,
        "project_id": "proj",
        "indicators": [
            {"key": "grounding", "label": "Grounding", "score": 67, "skipped": False},
            {"key": "index_trust", "label": "Index", "score": 100, "skipped": False},
        ],
    }
    base.update(over)
    return base


def test_render_normal():
    line = render(_state(), color=False)
    assert line == "🛡 82 REVIEW · grnd 67 · idx 100"


def test_render_skipped_is_empty():
    assert render(_state(skipped=True), color=False) == ""


def test_render_not_indexed_is_neutral_hint():
    line = render(_state(indexed=False), color=False)
    assert "not indexed" in line
    assert "RISK" not in line  # never alarm for an unindexed repo


def test_render_stale_prefix():
    line = render(_state(stale=True), color=False)
    assert line.startswith("⚠")


def test_render_skips_skipped_indicators():
    state = _state(
        indicators=[
            {"key": "grounding", "label": "Grounding", "score": 67, "skipped": False},
            {"key": "alignment", "label": "Alignment", "score": 0, "skipped": True},
        ]
    )
    line = render(state, color=False)
    assert "grnd 67" in line
    assert "algn" not in line


def test_render_none_state_is_empty():
    assert render(None, color=False) == ""
