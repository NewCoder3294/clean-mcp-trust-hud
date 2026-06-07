"""Tests for the explorer tree model."""

from clean.scoring import treeview


def _make_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a")
    (tmp_path / "src" / "b.py").write_text("b")
    (tmp_path / "node_modules").mkdir()  # must be skipped
    (tmp_path / "node_modules" / "x.js").write_text("x")
    (tmp_path / "README.md").write_text("r")
    return tmp_path


def test_build_root_lists_dirs_before_files_and_skips_junk(tmp_path):
    repo = _make_repo(tmp_path)
    root = treeview.build_root(str(repo))
    names = [n.name for n in root.children]
    assert names == ["src", "README.md"]  # dir first, node_modules skipped


def test_flatten_only_shows_expanded_children(tmp_path):
    root = treeview.build_root(str(_make_repo(tmp_path)))
    rows = treeview.flatten(root)
    assert [n.name for n in rows] == ["src", "README.md"]  # src collapsed
    src = root.children[0]
    treeview.expand(src)
    rows = treeview.flatten(root)
    assert [n.name for n in rows] == ["src", "a.py", "b.py", "README.md"]


def test_collapse_hides_children_and_parent_index(tmp_path):
    root = treeview.build_root(str(_make_repo(tmp_path)))
    src = root.children[0]
    treeview.expand(src)
    rows = treeview.flatten(root)
    # a.py is at index 1; its parent (src) is at index 0
    assert treeview.parent_index(rows, 1) == 0
    treeview.collapse(src)
    assert [n.name for n in treeview.flatten(root)] == ["src", "README.md"]


def test_parent_index_root_file_and_out_of_bounds(tmp_path):
    (tmp_path / "README.md").write_text("r")
    root = treeview.build_root(str(tmp_path))
    rows = treeview.flatten(root)
    assert treeview.parent_index(rows, 0) is None  # root-level file, no parent dir
    assert treeview.parent_index(rows, -1) is None  # out of bounds
    assert treeview.parent_index(rows, 99) is None  # out of bounds


def test_expand_twice_does_not_double_children(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a")
    root = treeview.build_root(str(tmp_path))
    src = root.children[0]
    treeview.expand(src)
    treeview.expand(src)
    assert [n.name for n in src.children] == ["a.py"]  # not doubled


def test_empty_dir_loads_to_empty_children(tmp_path):
    (tmp_path / "empty").mkdir()
    root = treeview.build_root(str(tmp_path))
    empty = root.children[0]
    treeview.expand(empty)
    assert empty.children == [] and empty.loaded is True


def test_hidden_files_excluded_by_default(tmp_path):
    (tmp_path / ".env").write_text("x")
    (tmp_path / "main.py").write_text("y")
    root = treeview.build_root(str(tmp_path))
    assert [n.name for n in root.children] == ["main.py"]  # .env hidden
