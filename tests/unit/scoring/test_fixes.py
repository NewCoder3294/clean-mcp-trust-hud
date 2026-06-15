"""Tests for the self-healing fix inbox."""

from clean.scoring.fixes import suggest_candidates


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
