"""Tests for the self-healing fix inbox."""

from clean.scoring.fixes import suggest_candidates
from clean.scoring.fixes import FixSuggestion, _fix_id, read_fixes, write_fixes


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
