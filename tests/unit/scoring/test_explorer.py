"""Tests for the explorer's pure render helpers."""

from clean.scoring import explorer
from clean.scoring import treeview
from clean.scoring.explorer import (
    _first_flagged_line,
    _offender_map,
    _preview_lines,
    _strip_ansi,
    _trust_dot,
    render,
)
from clean.scoring.navigate import ExplorerState


def test_trust_dot_bands():
    assert _trust_dot({"overall_score": 95}, color=False)[0] == "●"
    assert _trust_dot(None, color=False)[0] == "○"  # unscored


def test_first_flagged_line_picks_min_offender():
    score = {
        "indicators": [
            {"label": "Orphan", "offenders": [{"name": "f", "line": 14}]},
            {"label": "Grounding", "offenders": [{"name": "g", "line": 9}]},
        ]
    }
    assert _first_flagged_line(score) == 9
    assert _first_flagged_line({"indicators": []}) == 1
    assert _first_flagged_line(None) == 1


def test_render_shows_tree_rows_and_header(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("r")
    state = ExplorerState(root=treeview.build_root(str(tmp_path)))
    out = render(
        state,
        repo="o/r",
        branch="main",
        repo_root=str(tmp_path),
        width=100,
        height=20,
        color=False,
    )
    assert "o/r" in out
    assert "src" in out and "README.md" in out
    assert "j/k" in out  # footer keymap


def _file_state(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    return ExplorerState(root=treeview.build_root(str(tmp_path)))


def test_offender_map_first_label_wins_and_skips_missing_line():
    score = {
        "indicators": [
            {"label": "Orphan", "offenders": [{"name": "a", "line": 5}, {"name": "b"}]},
            {"label": "Grounding", "offenders": [{"name": "c", "line": 5}]},
        ]
    }
    assert _offender_map(score) == {5: "Orphan"}  # first label wins; no-line skipped
    assert _offender_map(None) == {}


def test_trust_dot_empty_dict_and_zero():
    assert _trust_dot({}, color=False)[0] == "○"
    assert _trust_dot({"overall_score": 0}, color=False)[0] == "●"


def test_strip_ansi_leaves_non_color_escapes():
    assert _strip_ansi("\033[92mhi\033[0m") == "hi"
    assert _strip_ansi("\033[2Jx") == "\033[2Jx"  # clear-screen not stripped


def test_preview_no_score_header_has_no_per_hundred(tmp_path):
    s = _file_state(tmp_path)
    lines = _preview_lines(s, str(tmp_path), color=False, height=10)
    assert "/100" not in lines[0]
    assert "a.py" in lines[0]


def test_preview_directory_placeholder(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a")
    s = ExplorerState(root=treeview.build_root(str(tmp_path)))  # cursor on src dir
    assert _preview_lines(s, str(tmp_path), color=False, height=10) == ["(directory)"]


def test_preview_source_error_shows_no_preview(tmp_path, monkeypatch):
    from clean.scoring import explorer
    from clean.util.source_reader import SourceReaderError

    def boom(*a, **k):
        raise SourceReaderError("nope")

    monkeypatch.setattr(explorer, "read_source", boom)
    out = _preview_lines(_file_state(tmp_path), str(tmp_path), color=False, height=10)
    assert out[-1] == "no preview"


def test_render_width_lt_80_hides_preview(tmp_path):
    out = render(
        _file_state(tmp_path),
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=79,
        height=10,
        color=False,
    )
    assert "│" not in out


def test_sidebar_shows_trust_number(tmp_path):
    s = _file_state(tmp_path)
    node = treeview.flatten(s.root)[0]
    s.score_cache[node.path] = {
        "overall_score": 73,
        "overall_label": "REVIEW",
        "indicators": [],
    }
    out = render(
        s,
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=100,
        height=10,
        color=False,
    )
    assert "73" in out


def test_sidebar_windows_to_keep_cursor_visible(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i:02}.py").write_text("x")
    s = ExplorerState(root=treeview.build_root(str(tmp_path)))
    s.cursor = 18
    out = render(
        s,
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=100,
        height=8,
        color=False,
    )
    assert "f18.py" in out  # cursor row visible despite small viewport
    assert "›" in out  # cursor marker shown


def test_preview_strips_read_source_gutter(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    s = ExplorerState(root=treeview.build_root(str(tmp_path)))  # cursor on a.py
    lines = _preview_lines(s, str(tmp_path), color=False, height=10)
    body = "\n".join(lines[2:])  # skip header + blank
    assert "|" not in body  # read_source's "N |" gutter stripped, not doubled
    assert "x = 1" in body and "y = 2" in body
    assert body.count("x = 1") == 1  # code not duplicated


def test_tmux_send_keys_builds_open_command():
    cmd = explorer._tmux_send_keys("%3", "/repo/src/a.py", 12)
    assert cmd == [
        "tmux",
        "send-keys",
        "-t",
        "%3",
        "Escape",
        ":edit +12 /repo/src/a.py",
        "Enter",
    ]


def test_tmux_send_keys_escapes_spaces_for_vim():
    cmd = explorer._tmux_send_keys("%3", "/repo/a b.py", 1)
    assert cmd[-2] == r":edit +1 /repo/a\ b.py"


def test_tmux_send_keys_escapes_vim_specials():
    cmd = explorer._tmux_send_keys("%3", "/repo/a|b%c#d`e.py", 1)
    assert cmd[-2] == r":edit +1 /repo/a\|b\%c\#d\`e.py"


def test_tmux_send_keys_rejects_newline():
    import pytest

    with pytest.raises(ValueError):
        explorer._tmux_send_keys("%3", "/repo/evil\nq!.py", 1)


def test_open_in_pane_skips_path_with_newline(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(explorer.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    explorer._open_in_pane("%5", "/repo/evil\nq!.py", 1)
    assert calls == []  # nothing was ever sent to tmux
    assert "cannot open file" in capsys.readouterr().err


def test_open_in_pane_invokes_tmux(monkeypatch):
    calls = []

    class _R:
        returncode = 0
        stderr = b""

    def fake_run(*a, **k):
        calls.append(a[0])
        return _R()

    monkeypatch.setattr(explorer.subprocess, "run", fake_run)
    explorer._open_in_pane("%5", "/repo/a.py", 7)
    assert calls[0][:4] == ["tmux", "send-keys", "-t", "%5"]
    assert calls[1] == ["tmux", "select-pane", "-t", "%5"]


def test_open_in_pane_swallows_oserror(monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("no tmux")

    monkeypatch.setattr(explorer.subprocess, "run", boom)
    explorer._open_in_pane("%5", "/repo/a.py", 7)  # must not raise
    assert "tmux error" in capsys.readouterr().err


def test_tmux_kill_session_builds_command():
    assert explorer._tmux_kill_session("clean-ide-9") == [
        "tmux",
        "kill-session",
        "-t",
        "clean-ide-9",
    ]


def test_main_passes_sidebar_target_and_session_to_loop(monkeypatch, tmp_path):
    import sys as _sys

    seen = {}

    def fake_loop(state, repo_root, git, color, sidebar_target=None, ide_session=None):
        seen["target"] = sidebar_target
        seen["session"] = ide_session

    monkeypatch.setattr(explorer, "_interactive_loop", fake_loop)
    monkeypatch.setattr(_sys, "argv", ["clean-tree", "--sidebar"])
    monkeypatch.setenv("CLEAN_TREE_TARGET", "%9")
    monkeypatch.setenv("CLEAN_IDE_SESSION", "clean-ide-77")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.py").write_text("x")
    explorer.main()
    assert seen["target"] == "%9"
    assert seen["session"] == "clean-ide-77"


def test_render_sidebar_uses_compact_footer(tmp_path):
    from clean.scoring import treeview
    from clean.scoring.navigate import ExplorerState

    (tmp_path / "a.py").write_text("x = 1\n")
    st = ExplorerState(root=treeview.build_root(str(tmp_path)))
    # Sidebar mode (narrow) → compact footer that fits a 40-col pane.
    narrow = render(
        st,
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=40,
        height=10,
        color=False,
        sidebar=True,
    )
    footer = narrow.split("\n")[-1]
    assert "⏎ open" in footer and "q quit" in footer
    assert "r rescore" not in footer  # the long hints are dropped when narrow
    # Wide standalone (non-sidebar) → full footer with all hints.
    wide = render(
        st,
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=120,
        height=10,
        color=False,
        sidebar=False,
    )
    assert "r rescore" in wide and "h close" in wide


def test_sidebar_mode_renders_tree_only_even_when_wide(tmp_path):
    """In --sidebar mode the preview pane is suppressed regardless of width, so
    the code opens in the editor pane instead of inside clean-tree."""
    from clean.scoring import treeview
    from clean.scoring.navigate import ExplorerState

    (tmp_path / "a.py").write_text("x = 1\n")
    st = ExplorerState(root=treeview.build_root(str(tmp_path)))
    wide_sidebar = render(
        st,
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=160,
        height=12,
        color=False,
        sidebar=True,
    )
    wide_normal = render(
        st,
        repo="o/r",
        branch=None,
        repo_root=str(tmp_path),
        width=160,
        height=12,
        color=False,
        sidebar=False,
    )
    assert "│" not in wide_sidebar  # no internal tree|preview divider
    assert "(directory)" not in wide_sidebar
    assert "│" in wide_normal  # normal wide mode still splits


def test_sidebar_truncates_long_names_no_wrap(tmp_path):
    """Every rendered line must fit the width — long filenames are ellipsized,
    not wrapped (wrapping scrolled the pane and hid the header)."""
    from clean.scoring import treeview
    from clean.scoring.navigate import ExplorerState
    from clean.scoring.explorer import _strip_ansi

    longname = "2026-06-07-clean-ide-tmux-sidebar-really-long-name.md"
    (tmp_path / longname).write_text("x")
    st = ExplorerState(root=treeview.build_root(str(tmp_path)))
    out = render(
        st,
        repo="o/r",
        branch="main",
        repo_root=str(tmp_path),
        width=40,
        height=12,
        color=False,
        sidebar=True,
    )
    for line in out.split("\n"):
        assert len(_strip_ansi(line)) <= 40  # nothing exceeds the pane width
    assert "…" in out  # the long name was ellipsized


def test_split_keys_batched_and_escape_sequences():
    assert explorer._split_keys("jjj") == ["j", "j", "j"]
    assert explorer._split_keys("\x1b[B") == ["\x1b[B"]  # down-arrow kept whole
    assert explorer._split_keys("\x1b[Bk") == ["\x1b[B", "k"]
    assert explorer._split_keys("j\rq") == ["j", "\r", "q"]
    assert explorer._split_keys("") == []
