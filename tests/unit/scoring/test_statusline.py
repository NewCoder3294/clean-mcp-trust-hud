"""Tests for the statusline renderer."""

import json

import clean.scoring.statusline as sl
from clean.scoring.statusline import (
    GitContext,
    SystemContext,
    _ctx_color,
    _ctx_meter,
    _ctx_used_pct,
    _current_task,
    _lang_from_path,
    _select_reason,
    build_clean_row,
    legend,
    render,
    system_context,
)


def _ind(key, score, offenders=()):
    return {"key": key, "label": key, "score": score, "skipped": False,
            "offenders": [{"name": n, "detail": "", "line": 1} for n in offenders]}


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
    git = GitContext("o/r", "main", "proj")
    line = render(_state(project_id="proj"), git=git, color=False)
    assert "\n" in line  # git row + clean-mcp row
    assert "█" in line  # bar chart present


def test_layers_git_on_row1_clean_mcp_on_row2():
    git = GitContext("cleanmcp/clean-mcp", "feat/trust-hud", "proj")
    row1, row2 = render(_state(project_id="proj"), git=git, color=False).split("\n")
    # Row 1 = git control only.
    assert "cleanmcp/clean-mcp" in row1 and "feat/trust-hud" in row1
    assert "TRUST" not in row1
    # Row 2 = clean-mcp layer (overall + metrics).
    assert "TRUST" in row2
    assert "Real calls" in row2


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


# --- system row (model · context meter · task) -------------------------------


def test_ctx_used_pct_scales_to_usable_context(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)
    # 16.5% reserved for autocompact: 16.5% remaining => 0% usable left => 100% used.
    assert _ctx_used_pct({"remaining_percentage": 16.5}) == 100
    # 100% remaining => 0% used.
    assert _ctx_used_pct({"remaining_percentage": 100}) == 0
    # Missing data => None (segment hidden).
    assert _ctx_used_pct({}) is None


def test_ctx_used_pct_honors_autocompact_override(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "500000")
    # buffer = 500k/1M = 50%; 50% remaining => fully used.
    assert _ctx_used_pct({"remaining_percentage": 50, "total_tokens": 1_000_000}) == 100


def test_ctx_color_bands():
    assert _ctx_color(10) != _ctx_color(70)  # green vs orange
    assert _ctx_color(49) == _ctx_color(0)  # both green
    assert _ctx_color(95) == _ctx_color(80)  # both red


def test_ctx_meter_shows_border_percent_and_skull():
    low = _ctx_meter(30, color=False)
    assert "ctx" in low and "▕" in low and "▏" in low and "30%" in low
    assert "💀" not in low
    assert "💀" in _ctx_meter(90, color=False)


def test_system_line_renders_three_segments():
    line = render(
        _state(),
        system=SystemContext(model="Opus 4.8", ctx_used=42, task="Wiring the HUD"),
        color=False,
    )
    row1 = line.split("\n")[0]
    assert "Opus 4.8" in row1
    assert "42%" in row1
    assert "Wiring the HUD" in row1


def test_render_drops_system_row_when_empty():
    # No system context => behaves exactly like the old two-row render.
    line = render(_state(), git=GitContext("o/r", "main", "proj"), color=False)
    assert "ctx" not in line
    assert line.count("\n") == 1  # git row + clean row only


def test_current_task_reads_in_progress_todo(tmp_path, monkeypatch):
    todos_dir = tmp_path / "todos"
    todos_dir.mkdir()
    (todos_dir / "sess-abc-agent-1.json").write_text(
        json.dumps(
            [
                {"status": "completed", "activeForm": "Old thing"},
                {"status": "in_progress", "activeForm": "Doing the thing"},
            ]
        )
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert _current_task("sess-abc") == "Doing the thing"
    # Path-traversal session ids are rejected.
    assert _current_task("../evil") is None
    assert _current_task(None) is None


def test_system_context_from_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    sc = system_context(
        {
            "model": {"display_name": "Opus 4.8"},
            "context_window": {"remaining_percentage": 100},
            "session_id": "nope",
        }
    )
    assert sc.model == "Opus 4.8"
    assert sc.ctx_used == 0
    assert sc.task is None


# --- reason selector (_select_reason) ----------------------------------------


def test_reason_review_names_grounding_calls():
    state = {"overall_score": 71, "indicators": [_ind("grounding", 50, ["load_index", "warm_model"])]}
    assert _select_reason(state) == " · check 2 calls: load_index, warm_model"


def test_reason_risk_says_likely_hallucinated():
    state = {"overall_score": 38, "indicators": [_ind("grounding", 20, ["foo"])]}
    assert _select_reason(state) == " · likely hallucinated: foo"


def test_reason_caps_symbol_list_at_two():
    state = {"overall_score": 71, "indicators": [_ind("grounding", 30, ["a", "b", "c", "d"])]}
    assert _select_reason(state) == " · check 4 calls: a, b +2"


def test_reason_falls_back_to_weakest_metric_phrase():
    state = {"overall_score": 72, "indicators": [
        _ind("grounding", 100), _ind("orphan", 40), _ind("alignment", 90)]}
    assert _select_reason(state) == " · low reuse"


def test_reason_empty_when_all_metrics_healthy():
    state = {"overall_score": 96, "indicators": [_ind("grounding", 100), _ind("orphan", 90)]}
    assert _select_reason(state) == ""


def test_reason_check_singular_call():
    state = {"overall_score": 71, "indicators": [_ind("grounding", 50, ["single_fn"])]}
    assert _select_reason(state) == " · check 1 call: single_fn"


def test_reason_caps_exactly_three_offenders():
    state = {"overall_score": 71, "indicators": [_ind("grounding", 30, ["a", "b", "c"])]}
    assert _select_reason(state) == " · check 3 calls: a, b +1"


# --- build_clean_row (row-3 state machine) ------------------------------------


def _good(score=71, label="REVIEW", offenders=("load_index", "warm_model")):
    return {"overall_score": score, "overall_label": label, "skipped": False,
            "project_id": "proj",
            "indicators": [_ind("grounding", 50, list(offenders))]}


GIT = GitContext("o/repo", "main", "proj")


def test_lang_from_path_known_and_unknown():
    assert _lang_from_path("/x/View.swift") == "Swift"
    assert _lang_from_path("/x/mod.py") == "Python"
    assert _lang_from_path("/x/data.zzz") == "ZZZ"
    assert _lang_from_path(None) is None


def test_clean_row_ok_is_calm():
    row = build_clean_row(_good(96, "OK", ()), None, GIT, color=False)
    assert row == "● OK 96"


def test_clean_row_review_names_calls():
    row = build_clean_row(_good(71, "REVIEW"), None, GIT, color=False)
    assert row == "● REVIEW 71 · check 2 calls: load_index, warm_model"


def test_clean_row_risk_wording():
    row = build_clean_row(_good(38, "RISK", ("foo",)), None, GIT, color=False)
    assert row == "● RISK 38 · likely hallucinated: foo"


def test_clean_row_last_good_when_current_file_skipped():
    recent = {"skipped": True, "project_id": "proj", "file_path": "/x/View.swift"}
    row = build_clean_row(_good(71, "REVIEW", ()), recent, GIT, color=False)
    assert row == "○ 71 REVIEW · last good · Swift not scored"


def test_clean_row_not_a_repo_is_empty():
    assert build_clean_row(None, None, GitContext(None, None, None), color=False) == ""


def test_clean_row_indexed_but_unscored(monkeypatch):
    monkeypatch.setattr(sl, "_project_indexed", lambda pid: True)
    assert build_clean_row(None, None, GIT, color=False) == "clean · edit a Py/JS/TS file to score"


def test_clean_row_not_indexed(monkeypatch):
    monkeypatch.setattr(sl, "_project_indexed", lambda pid: False)
    row = build_clean_row(None, None, GitContext("o/repo", "main", "proj"), color=False)
    assert row == "clean · not indexed — index o/repo"


def test_clean_row_skipped_recent_wrong_project_falls_through_to_live():
    # recent skip belongs to a DIFFERENT repo -> not just_skipped_here -> live verdict.
    recent = {"skipped": True, "project_id": "OTHER", "file_path": "/x/View.swift"}
    row = build_clean_row(_good(71, "REVIEW"), recent, GIT, color=False)
    assert row == "● REVIEW 71 · check 2 calls: load_index, warm_model"


def test_clean_row_last_good_without_file_path_omits_language_note():
    recent = {"skipped": True, "project_id": "proj", "file_path": None}
    row = build_clean_row(_good(71, "REVIEW", ()), recent, GIT, color=False)
    assert row == "○ 71 REVIEW · last good"
