# tests/unit/scoring/test_navigate.py
"""Tests for the explorer key reducer."""

from clean.scoring import treeview
from clean.scoring.navigate import ExplorerState, reduce, visible_rows


def _state(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a")
    (tmp_path / "README.md").write_text("r")
    return ExplorerState(root=treeview.build_root(str(tmp_path)))


def test_jk_moves_cursor_and_clamps(tmp_path):
    s = _state(tmp_path)
    s, act = reduce(s, "j")
    assert s.cursor == 1 and act is None
    s, _ = reduce(s, "j")  # clamp at last row (2 rows: src, README.md)
    assert s.cursor == 1
    s, _ = reduce(s, "k")
    s, _ = reduce(s, "k")  # clamp at 0
    assert s.cursor == 0


def test_l_expands_dir_then_h_collapses(tmp_path):
    s = _state(tmp_path)  # cursor on "src"
    s, act = reduce(s, "l")
    assert act is None
    assert [n.name for n in visible_rows(s)] == ["src", "a.py", "README.md"]
    s, _ = reduce(s, "h")  # collapse src
    assert [n.name for n in visible_rows(s)] == ["src", "README.md"]


def test_enter_on_file_returns_open(tmp_path):
    s = _state(tmp_path)
    s, _ = reduce(s, "l")  # expand src
    s, _ = reduce(s, "j")  # move to a.py
    s, act = reduce(s, "\r")
    assert act == "open"


def test_q_returns_quit(tmp_path):
    s = _state(tmp_path)
    _, act = reduce(s, "q")
    assert act == "quit"


def test_empty_tree_navigation_is_noop(tmp_path):
    s = ExplorerState(root=treeview.build_root(str(tmp_path)))
    s, act = reduce(s, "j")
    assert s.cursor == 0 and act is None
    s, act = reduce(s, "G")
    assert s.cursor == 0 and act is None


def test_g_and_G_jump_to_top_and_bottom(tmp_path):
    s = _state(tmp_path)
    s, _ = reduce(s, "G")
    assert s.cursor == 1  # README.md is last
    s, act = reduce(s, "g")
    assert s.cursor == 0 and act is None


def test_arrow_keys_move_cursor(tmp_path):
    s = _state(tmp_path)
    s, act = reduce(s, "\x1b[B")  # down
    assert s.cursor == 1 and act is None
    s, act = reduce(s, "\x1b[A")  # up
    assert s.cursor == 0 and act is None


def test_h_on_file_moves_to_parent(tmp_path):
    s = _state(tmp_path)
    s, _ = reduce(s, "l")  # expand src
    s, _ = reduce(s, "j")  # cursor -> a.py
    s, act = reduce(s, "h")
    assert s.cursor == 0 and act is None  # back to src


def test_r_clears_score_cache_for_current_file(tmp_path):
    s = _state(tmp_path)
    s, _ = reduce(s, "l")
    s, _ = reduce(s, "j")
    file_path = visible_rows(s)[s.cursor].path
    s.score_cache[file_path] = {"score": 9}
    s, act = reduce(s, "r")
    assert file_path not in s.score_cache and act is None


def test_enter_toggles_dir(tmp_path):
    s = _state(tmp_path)  # cursor on src (collapsed)
    s, act = reduce(s, "\r")
    assert act is None and visible_rows(s)[1].name == "a.py"
    s, act = reduce(s, "\r")
    assert act is None and len(visible_rows(s)) == 2


def test_Q_and_ctrl_c_return_quit(tmp_path):
    s = _state(tmp_path)
    assert reduce(s, "Q")[1] == "quit"
    assert reduce(s, "\x03")[1] == "quit"
