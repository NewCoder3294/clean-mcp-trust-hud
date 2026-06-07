"""Tests for the statusline renderer."""

from clean.scoring.statusline import GitContext, legend, render


def _state(**over):
    base = {
        "overall_score": 82,
        "overall_label": "REVIEW",
        "stale": False,
        "indexed": True,
        "skipped": False,
        "project_id": "proj",
        "indicators": [
            {"key": "grounding", "label": "Grounding", "score": 80, "skipped": False},
            {"key": "blast_radius", "label": "Impact", "score": 100, "skipped": False},
            {"key": "index_trust", "label": "Index", "score": 40, "skipped": False},
        ],
    }
    base.update(over)
    return base


def test_render_uses_plain_english_labels_and_score():
    line = render(_state(), color=False)
    assert "82/100 REVIEW" in line
    assert "Real calls" in line  # grounding -> plain label
    assert "Impact" in line
    assert "grounding" not in line  # raw keys never shown


def test_index_trust_is_not_shown_as_a_bar():
    # index_trust is folded into the 'stale' tag, not the metric line.
    line = render(_state(), color=False)
    assert "Index" not in line


def test_render_is_two_lines_with_metrics():
    line = render(_state(), color=False)
    assert "\n" in line
    assert "█" in line  # bar chart present


def test_render_git_context_shows_repo_and_branch():
    git = GitContext("cleanmcp/clean-mcp", "feat/trust-hud", "clean-mcp")
    line = render(_state(project_id="clean-mcp"), git=git, color=False)
    assert "cleanmcp/clean-mcp" in line
    assert "feat/trust-hud" in line


def test_render_mismatched_repo_hides_scores():
    git = GitContext("o/other", "main", "other")
    line = render(_state(project_id="proj"), git=git, color=False)
    assert "no recent score" in line
    assert "82/100" not in line


def test_render_not_indexed_is_neutral_hint():
    line = render(_state(indexed=False), color=False)
    assert "not indexed" in line
    assert "RISK" not in line


def test_render_stale_prefix():
    assert "stale" in render(_state(stale=True), color=False)


def test_render_has_no_emojis():
    line = render(
        _state(),
        git=GitContext("o/r", "main", "proj"),
        color=False,
    )
    for emoji in ("📁", "🛡", "⚠"):
        assert emoji not in line


def test_render_skips_skipped_indicators():
    state = _state(
        indicators=[
            {"key": "grounding", "label": "Grounding", "score": 80, "skipped": False},
            {"key": "alignment", "label": "Alignment", "score": 0, "skipped": True},
        ]
    )
    line = render(state, color=False)
    assert "Real calls" in line
    assert "Style" not in line  # alignment skipped


def test_render_empty_when_nothing_to_show():
    assert render(None, color=False) == ""


def test_legend_explains_every_metric():
    text = legend()
    for label in ("Real calls", "Impact", "Used", "Index", "Style", "Unique"):
        assert label in text
