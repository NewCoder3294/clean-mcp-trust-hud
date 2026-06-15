"""Tests for the self-healing fix inbox."""

import clean.scoring.fixes as fixes_mod
from clean.scoring.fixes import (
    FixSuggestion,
    _fix_id,
    apply_fix,
    propose_fixes,
    read_fixes,
    suggest_candidates,
    write_fixes,
)
from clean.scoring.base import FileScore, IndicatorResult, Offender


class _FakeEntity:
    def __init__(self, name):
        self.name = name


class _FakeStore:
    """Returns names containing the queried token (mimics get_by_name_substring)."""

    def __init__(self, names):
        self._names = names

    def get_by_name_substring(self, project_id, pattern, limit=20):
        p = pattern.lower()
        return [_FakeEntity(n) for n in self._names if p in n.lower()][:limit]


def _score(offenders=(Offender("load_index", "no match", 42),), confidence=1.0,
           skipped=False, indexed=True, project_id="proj"):
    return FileScore(
        project_id=project_id, file_path="/p/mod.py", overall_score=40,
        overall_label="RISK",
        indicators=[IndicatorResult("grounding", "Grounding", 40, "1 unresolved",
                                    offenders=tuple(offenders), confidence=confidence)],
        entity_count=3, stale=False, indexed=indexed, skipped=skipped)


def test_propose_queues_a_fix_for_high_confidence_hallucination(tmp_path):
    store = _FakeStore(["load_repo_index", "warm_model"])
    propose_fixes(_score(), store, base=tmp_path)
    fixes = read_fixes("proj", base=tmp_path)
    assert len(fixes) == 1
    assert fixes[0]["bad_symbol"] == "load_index"
    assert fixes[0]["candidates"] == ["load_repo_index"]


def test_no_fix_when_index_stale(tmp_path):
    store = _FakeStore(["load_repo_index"])
    propose_fixes(_score(confidence=0.7), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_no_fix_when_skipped(tmp_path):
    store = _FakeStore(["load_repo_index"])
    propose_fixes(_score(skipped=True), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_no_fix_when_unindexed(tmp_path):
    store = _FakeStore(["load_repo_index"])
    propose_fixes(_score(indexed=False), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_no_fix_when_no_near_match(tmp_path):
    store = _FakeStore(["totally_unrelated"])
    propose_fixes(_score(), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_reproposing_same_file_prunes_resolved_offenders(tmp_path):
    store = _FakeStore(["load_repo_index", "warm_model_fn"])
    propose_fixes(_score(), store, base=tmp_path)  # queues load_index
    # Re-score: the hallucination is gone, a different one appears.
    propose_fixes(_score(offenders=(Offender("warm_model", "no match", 9),)),
                  store, base=tmp_path)
    fixes = read_fixes("proj", base=tmp_path)
    assert len(fixes) == 1 and fixes[0]["bad_symbol"] == "warm_model"


def test_resolved_hallucination_clears_inbox(tmp_path):
    store = _FakeStore(["load_repo_index"])
    propose_fixes(_score(), store, base=tmp_path)  # queues load_index
    assert len(read_fixes("proj", base=tmp_path)) == 1
    # Re-score: grounding is fresh but the hallucination is gone (no offenders).
    propose_fixes(_score(offenders=()), store, base=tmp_path)
    assert read_fixes("proj", base=tmp_path) == []


def test_suggests_near_miss_real_symbol():
    names = ["load_repo_index", "warm_model", "save_state"]
    assert suggest_candidates("load_index", names) == ["load_repo_index"]


def test_no_candidates_below_cutoff():
    names = ["completely_different", "unrelated_thing"]
    assert suggest_candidates("load_index", names) == []


def test_matches_on_final_segment_of_dotted_symbol():
    # bad "self._procss" should match indexed method "Worker._process" via segment.
    names = ["Worker._process", "Worker._run"]
    assert suggest_candidates("self._procss", names) == ["_process"]


def test_returns_at_most_n_candidates():
    names = ["load_index_a", "load_index_b", "load_index_c", "load_index_d"]
    out = suggest_candidates("load_index", names, n=3)
    assert len(out) == 3


def _entry(file_path="/p/mod.py", bad="load_index", cands=("load_repo_index",)):
    return {
        "id": _fix_id(file_path, bad), "file_path": file_path, "line": 42,
        "bad_symbol": bad, "candidates": list(cands), "created_at": "2026-06-14T00:00:00",
    }


def test_write_then_read_round_trips(tmp_path):
    write_fixes("proj", [_entry()], base=tmp_path)
    got = read_fixes("proj", base=tmp_path)
    assert len(got) == 1 and got[0]["bad_symbol"] == "load_index"


def test_read_missing_returns_empty_list(tmp_path):
    assert read_fixes("nope", base=tmp_path) == []


def test_empty_project_id_is_ignored(tmp_path):
    write_fixes("", [_entry()], base=tmp_path)
    assert read_fixes("", base=tmp_path) == []


def test_fix_id_is_stable_for_same_file_and_symbol():
    assert _fix_id("/p/mod.py", "load_index") == _fix_id("/p/mod.py", "load_index")
    assert _fix_id("/p/mod.py", "load_index") != _fix_id("/p/mod.py", "warm_model")


def test_fixsuggestion_dataclass_fields():
    s = FixSuggestion(id="x", file_path="/p/m.py", line=1, bad_symbol="b",
                      candidates=["c"], created_at="t")
    assert s.bad_symbol == "b" and s.candidates == ["c"]


def _file_entry(path, bad="load_index", cands=("load_repo_index",)):
    return {"id": "x", "file_path": str(path), "line": 2, "bad_symbol": bad,
            "candidates": list(cands), "created_at": "t"}


def test_apply_replaces_unique_occurrence(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def f():\n    return load_index()\n")
    assert apply_fix(_file_entry(f)) == "applied"
    assert f.read_text() == "def f():\n    return load_repo_index()\n"


def test_apply_is_stale_when_symbol_absent(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def f():\n    return other()\n")
    assert apply_fix(_file_entry(f)) == "stale"
    assert "other()" in f.read_text()  # untouched


def test_apply_is_stale_when_ambiguous(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("load_index()\nload_index()\n")  # two occurrences -> never guess
    assert apply_fix(_file_entry(f)) == "stale"
    assert f.read_text() == "load_index()\nload_index()\n"


def test_apply_does_not_touch_substring_matches(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("x = load_index\ny = load_index_helper\n")  # whole-word only
    assert apply_fix(_file_entry(f)) == "applied"
    assert f.read_text() == "x = load_repo_index\ny = load_index_helper\n"


def test_apply_pick_selects_candidate(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("load_index()\n")
    assert apply_fix(_file_entry(f, cands=("a_fn", "load_repo_index")), pick=1) == "applied"
    assert f.read_text() == "load_repo_index()\n"


def test_apply_bad_pick_returns_error(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("load_index()\n")
    assert apply_fix(_file_entry(f), pick=5) == "error"


def test_apply_missing_file_is_stale(tmp_path):
    assert apply_fix(_file_entry(tmp_path / "nope.py")) == "stale"


def test_apply_empty_bad_symbol_returns_error(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("x = foo()\n")
    assert apply_fix({"file_path": str(f), "bad_symbol": "", "candidates": ["bar"]}) == "error"


def test_cli_lists_pending_fixes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    write_fixes("proj", [_entry()], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes"])
    fixes_mod.main()
    out = capsys.readouterr().out
    assert "load_index → load_repo_index" in out


def test_cli_apply_removes_entry_on_success(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    f = tmp_path / "mod.py"
    f.write_text("load_index()\n")
    entry = {"id": "abc123", "file_path": str(f), "line": 1, "bad_symbol": "load_index",
             "candidates": ["load_repo_index"], "created_at": "t"}
    write_fixes("proj", [entry], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes", "apply", "abc123"])
    fixes_mod.main()
    assert "applied" in capsys.readouterr().out.lower()
    assert read_fixes("proj", base=tmp_path) == []
    assert f.read_text() == "load_repo_index()\n"


def test_cli_reject_removes_entry(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    entry = {"id": "abc123", "file_path": "/p/m.py", "line": 1, "bad_symbol": "x",
             "candidates": ["y"], "created_at": "t"}
    write_fixes("proj", [entry], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes", "reject", "abc123"])
    fixes_mod.main()
    assert read_fixes("proj", base=tmp_path) == []


def test_cli_unknown_id_reports_not_found(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    write_fixes("proj", [_entry()], base=tmp_path)
    monkeypatch.setattr("sys.argv", ["clean-fixes", "apply", "nope"])
    fixes_mod.main()
    out = capsys.readouterr().out
    assert "No pending fix" in out
    assert read_fixes("proj", base=tmp_path) != []  # nothing removed


def test_cli_bad_args_prints_usage(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixes_mod, "FIX_INBOX_DIR", tmp_path)
    monkeypatch.setattr(fixes_mod, "_current_project_id", lambda: "proj")
    monkeypatch.setattr("sys.argv", ["clean-fixes", "bogus"])
    fixes_mod.main()
    assert "usage: clean-fixes" in capsys.readouterr().out
