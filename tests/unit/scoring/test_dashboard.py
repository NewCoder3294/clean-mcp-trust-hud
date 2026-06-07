"""Tests for the full-screen dashboard renderer."""

from clean.scoring.dashboard import render_dashboard
from clean.scoring.statusline import GitContext


def _state(**over):
    base = {
        "overall_score": 49,
        "overall_label": "RISK",
        "stale": True,
        "indexed": True,
        "skipped": False,
        "project_id": "clean-mcp",
        "file_path": "/repo/src/grounding.py",
        "entity_count": 3,
        "updated_at": "2026-06-06T23:18:42",
        "indicators": [
            {
                "key": "grounding",
                "score": 100,
                "summary": "all resolved",
                "skipped": False,
                "offenders": [],
            },
            {
                "key": "blast_radius",
                "score": 20,
                "summary": "8 callers",
                "skipped": False,
                "offenders": [],
            },
            {
                "key": "orphan",
                "score": 40,
                "summary": "no references",
                "skipped": False,
                "offenders": [{"name": "ghost", "detail": "not found", "line": 42}],
            },
        ],
    }
    base.update(over)
    return base


_GIT = GitContext("cleanmcp/clean-mcp", "feat/trust-hud", "clean-mcp")


def test_dashboard_shows_repo_branch_and_overall():
    out = render_dashboard(_state(), _GIT, width=100, color=False)
    assert "cleanmcp/clean-mcp" in out
    assert "feat/trust-hud" in out
    assert "49/100 RISK" in out
    assert "TRUST" in out


def test_dashboard_shows_labels_and_meanings():
    out = render_dashboard(_state(), _GIT, width=100, color=False)
    assert "Real calls" in out
    assert "Impact" in out
    # the plain-English meaning is shown, not just the label
    assert "hallucinated" in out


def test_dashboard_lists_flagged_symbols():
    out = render_dashboard(_state(), _GIT, width=100, color=False)
    assert "Flagged" in out
    assert "ghost:42" in out


def test_dashboard_waiting_when_no_score():
    out = render_dashboard({"skipped": True}, _GIT, width=100, color=False)
    assert "waiting" in out
    assert "cleanmcp/clean-mcp" in out  # header still shown


def test_dashboard_not_indexed_hint():
    out = render_dashboard(_state(indexed=False), _GIT, width=100, color=False)
    assert "not indexed" in out


def test_dashboard_emits_ansi_when_colored():
    out = render_dashboard(_state(), _GIT, width=100, color=True)
    assert "\033[" in out


def test_dashboard_scrolls_flagged_list():
    offs = [{"name": f"sym{i}", "detail": "x", "line": i} for i in range(15)]
    st = _state(
        indicators=[
            {
                "key": "orphan",
                "score": 40,
                "summary": "many",
                "skipped": False,
                "offenders": offs,
            },
        ]
    )
    top = render_dashboard(st, _GIT, width=100, color=False, scroll=0)
    assert "sym0" in top and "sym14" not in top  # windowed to first 10
    assert "showing 1-10" in top
    scrolled = render_dashboard(st, _GIT, width=100, color=False, scroll=5)
    assert "sym14" in scrolled and "sym0" not in scrolled
