"""Tests for the full-screen dashboard renderer."""

import clean.scoring.dashboard as dash
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


"""clean-hud follows the launch directory's repo."""


def _score(score=71, label="REVIEW"):
    return {"overall_score": score, "overall_label": label, "skipped": False,
            "project_id": "proj", "stale": False, "indexed": True,
            "indicators": [{"key": "grounding", "label": "Grounding",
                            "score": 50, "skipped": False, "offenders": []}]}


def test_frame_shows_launch_repo_score(monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "git_context", lambda cwd: GitContext("o/repo", "main", "proj"))
    monkeypatch.setattr(dash, "read_repo_score", lambda pid: _score())
    out = dash._frame(dash.ScoringStateWriter(tmp_path), color=False)
    assert "71" in out and "REVIEW" in out
    assert "o/repo" in out  # header shows the launch repo


def test_frame_in_repo_without_score_shows_waiting_not_foreign(monkeypatch, tmp_path):
    # In a git repo with no per-repo score: show "waiting", NOT the global score.
    monkeypatch.setattr(dash, "git_context", lambda cwd: GitContext("o/repo", "main", "proj"))
    monkeypatch.setattr(dash, "read_repo_score", lambda pid: None)
    writer = dash.ScoringStateWriter(tmp_path)
    # Even if a global score exists, it must NOT appear (different repo's numbers).
    out = dash._frame(writer, color=False)
    assert "o/repo" in out
    assert "waiting for an edit to score" in out


def test_frame_outside_repo_falls_back_to_global(monkeypatch, tmp_path):
    monkeypatch.setattr(dash, "git_context", lambda cwd: GitContext(None, None, None))
    monkeypatch.setattr(dash, "read_repo_score", lambda pid: _score())  # must NOT be used (pid is None)
    captured = {"read": False}

    class _W:
        def read(self):
            captured["read"] = True
            return _score(88, "OK")

    out = dash._frame(_W(), color=False)
    assert captured["read"] is True  # global fallback used when outside any repo
    assert "88" in out
