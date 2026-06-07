"""``clean-tree`` — a terminal file explorer with a Trust-HUD preview.

A dependency-free raw-ANSI TUI: a trust-colored file-tree sidebar on the left,
a syntax-highlighted preview (with Trust-HUD flag markers) on the right, and
open-in-vim. This module holds the pure render helpers; the interactive loop
and editor launch live alongside them (added in a later task). Reuses the
statusline palette, the daemon scorer, and read_source.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from ..util.source_reader import SourceReaderError, read_source
from . import treeview
from .daemon import request_score
from .highlight import highlight_line, language_for
from .navigate import ExplorerState, current, reduce, visible_rows
from .statusline import (
    _BOLD,
    _CYAN,
    _DIM,
    _WHITE,
    _color,
    _paint,
    git_context,
)

_CLEAR = "\033[2J\033[H"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_GUTTER_RE = re.compile(r"^\s*\d+\s*\|\s?")  # read_source's " N | " line prefix


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _trust_dot(score: dict | None, color: bool) -> tuple[str, str]:
    """Return (glyph, ansi-color) for a file's overall trust score."""
    if not score or score.get("overall_score") is None:
        return "○", _DIM
    return "●", _color(int(score["overall_score"]))


def _first_flagged_line(score: dict | None) -> int:
    """Smallest offender line across all indicators, or 1 when none."""
    if not score:
        return 1
    lines = [
        o["line"]
        for ind in score.get("indicators", [])
        for o in ind.get("offenders", [])
        if o.get("line")
    ]
    return min(lines) if lines else 1


def _offender_map(score: dict | None) -> dict[int, str]:
    """line number -> indicator label, for preview flag markers."""
    out: dict[int, str] = {}
    for ind in (score or {}).get("indicators", []):
        for o in ind.get("offenders", []):
            if o.get("line") and o["line"] not in out:
                out[o["line"]] = ind.get("label", "?")
    return out


def _repo_root(cwd: str) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.path.abspath(cwd)


def _score_for(state: ExplorerState, path: str, repo_root: str) -> dict | None:
    """Lazy, cached trust score for *path* via the warm daemon."""
    if path in state.score_cache:
        return state.score_cache[path]
    score = request_score(path, cwd=repo_root)
    state.score_cache[path] = score
    return score


def _sidebar_lines(state: ExplorerState, color: bool, height: int) -> list[str]:
    rows = visible_rows(state)
    n = len(rows)
    # Scroll-window so the cursor stays visible even when the tree is taller
    # than the viewport. Keep the cursor roughly centered.
    if n <= height:
        start = 0
    else:
        start = max(0, min(state.cursor - height // 2, n - height))
    lines: list[str] = []
    for offset, node in enumerate(rows[start : start + height]):
        idx = start + offset
        indent = "  " * node.depth
        if node.is_dir:
            caret = "▾ " if node.expanded else "▸ "
            body = _paint(caret + node.name + "/", _CYAN, color)
            row = f"{indent}{body}"
        else:
            score = state.score_cache.get(node.path)
            glyph, c = _trust_dot(score, color)
            num = (
                f"{int(score['overall_score']):>3}"
                if score and score.get("overall_score") is not None
                else "   "
            )
            row = f"{indent}{_paint(glyph, c, color)} {node.name}  {_paint(num, c, color)}"
        prefix = (
            _paint("›", _WHITE + _BOLD, color) + " " if idx == state.cursor else "  "
        )
        lines.append(prefix + row)
    return lines


def _preview_lines(
    state: ExplorerState, repo_root: str, color: bool, height: int
) -> list[str]:
    node = current(state)
    if node is None or node.is_dir:
        return [_paint("(directory)", _DIM, color)]
    score = state.score_cache.get(node.path)
    rel = os.path.relpath(node.path, repo_root)
    header = rel
    if score and score.get("overall_score") is not None:
        s = int(score["overall_score"])
        label = score.get("overall_label", "")
        header = rel + "  " + _paint(f"{s}/100 {label}", _color(s) + _BOLD, color)
    try:
        source, meta = read_source(repo_root, rel, max_lines=max(1, height - 2))
    except SourceReaderError:
        return [
            _paint(header, _WHITE + _BOLD, color),
            "",
            _paint("no preview", _DIM, color),
        ]
    lang = language_for(node.path)
    flags = _offender_map(score)
    start = meta.get("start_line", 1)
    out = [_paint(header, _WHITE + _BOLD, color), ""]
    for offset, raw in enumerate(source.splitlines()):
        lineno = start + offset
        code = _GUTTER_RE.sub("", raw)
        marker = (
            _paint(f"  ◀ {flags[lineno]}", _color(0), color) if lineno in flags else ""
        )
        gutter = _paint(f"{lineno:>4} ", _DIM, color)
        out.append(f"{gutter}{highlight_line(code, lang, color)}{marker}")
    return out


def render(
    state: ExplorerState,
    *,
    repo: str | None,
    branch: str | None,
    repo_root: str,
    width: int,
    height: int,
    color: bool,
    sidebar: bool = False,
) -> str:
    """Pure full-frame render (no terminal I/O)."""
    head = _paint("clean", _WHITE + _BOLD, color) + _paint(" ▸ ", _DIM, color)
    head += _paint(repo or os.path.basename(repo_root), _WHITE + _BOLD, color)
    if branch:
        head += _paint("  ⎇ ", _DIM, color) + _paint(branch, _CYAN, color)

    body_h = max(1, height - 3)
    show_preview = width >= 80
    sidebar_w = 34 if show_preview else width
    sidebar_lines = _sidebar_lines(state, color, body_h)
    preview = _preview_lines(state, repo_root, color, body_h) if show_preview else []

    rows_out = []
    for i in range(body_h):
        left = sidebar_lines[i] if i < len(sidebar_lines) else ""
        if show_preview:
            visible = _strip_ansi(left)
            pad = " " * max(0, sidebar_w - len(visible))
            right = preview[i] if i < len(preview) else ""
            rows_out.append(f"{left}{pad}{_paint('│', _DIM, color)} {right}")
        else:
            rows_out.append(left)

    open_hint = "e → editor" if sidebar else "e vim"
    footer = _paint(
        f"j/k move · l/⏎ open · h close · {open_hint} · r rescore · q quit",
        _DIM,
        color,
    )
    return "\n".join([head, ""] + rows_out + [footer])


def _tmux_send_keys(target: str, path: str, line: int) -> list[str]:
    """tmux argv that opens *path* at *line* in the vim running in pane *target*.

    Sends Escape (ensure normal mode), then ``:edit +<line> <path><CR>``. Spaces
    in the path are backslash-escaped for vim's command line.
    """
    # TODO(v2): only spaces are escaped; paths containing %, #, |, or \ are not
    # safe for vim's :edit command line.
    vim_path = path.replace(" ", r"\ ")
    return [
        "tmux",
        "send-keys",
        "-t",
        target,
        "Escape",
        f":edit +{line} {vim_path}",
        "Enter",
    ]


def _tmux_kill_session(session: str) -> list[str]:
    """tmux argv to destroy the whole IDE session (used on sidebar quit)."""
    return ["tmux", "kill-session", "-t", session]


def _open_in_pane(target: str, path: str, line: int) -> None:
    """Open *path* at *line* in the editor running in tmux pane *target*, then
    focus that pane. Used by ``clean-tree --sidebar``; does not touch our TTY."""
    try:
        subprocess.run(_tmux_send_keys(target, path, line), check=False)
        result = subprocess.run(
            ["tmux", "select-pane", "-t", target],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            sys.stderr.write(
                f"tmux select-pane failed: {result.stderr.decode().strip()}\n"
            )
    except OSError as e:
        sys.stderr.write(f"tmux error: {e}\n")


def _open_in_editor(path: str, line: int, fd, old_termios) -> None:
    """Suspend the TUI, run $EDITOR/vim at *line*, then restore raw mode."""
    import termios
    import tty

    editor = os.environ.get("EDITOR") or "vim"
    termios.tcsetattr(fd, termios.TCSADRAIN, old_termios)
    sys.stdout.write(_SHOW_CURSOR + _CLEAR)
    sys.stdout.flush()
    try:
        subprocess.call([editor, f"+{line}", path])
    except OSError as e:
        sys.stderr.write(f"editor error: {e}\n")
    finally:
        tty.setcbreak(fd)
        sys.stdout.write(_HIDE_CURSOR)
        sys.stdout.flush()


def _terminal_size() -> tuple[int, int]:
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except OSError:
        return 100, 30


def main() -> None:
    color = os.getenv("NO_COLOR") is None
    cwd = os.getcwd()
    repo_root = _repo_root(cwd)
    git = git_context(repo_root)
    state = ExplorerState(root=treeview.build_root(repo_root))

    in_sidebar = "--sidebar" in sys.argv[1:]

    if "--once" in sys.argv[1:] or (not sys.stdin.isatty() and not in_sidebar):
        w, h = _terminal_size()
        cur = current(state)
        if cur and not cur.is_dir:
            _score_for(state, cur.path, repo_root)
        print(
            render(
                state,
                repo=git.repo,
                branch=git.branch,
                repo_root=repo_root,
                width=w,
                height=h,
                color=color,
            )
        )
        return

    # Sidebar mode: opening a file targets the editor in another tmux pane, and
    # quitting tears the whole IDE session down.
    sidebar_target = os.environ.get("CLEAN_TREE_TARGET") if in_sidebar else None
    ide_session = os.environ.get("CLEAN_IDE_SESSION") if in_sidebar else None
    _interactive_loop(state, repo_root, git, color, sidebar_target, ide_session)


def _interactive_loop(
    state, repo_root, git, color, sidebar_target=None, ide_session=None
) -> None:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write(_HIDE_CURSOR)
    try:
        tty.setcbreak(fd)
        while True:
            cur = current(state)
            if cur and not cur.is_dir and cur.path not in state.score_cache:
                _score_for(state, cur.path, repo_root)
            w, h = _terminal_size()
            sys.stdout.write(
                _CLEAR
                + render(
                    state,
                    repo=git.repo,
                    branch=git.branch,
                    repo_root=repo_root,
                    width=w,
                    height=h,
                    color=color,
                    sidebar=bool(sidebar_target),
                )
                + "\n"
            )
            sys.stdout.flush()
            ready, _, _ = select.select([sys.stdin], [], [], 30)
            if not ready:
                continue
            ch = os.read(fd, 3).decode("utf-8", "ignore")
            state, action = reduce(state, ch)
            if action == "quit":
                break
            if action == "open":
                node = current(state)
                if node and not node.is_dir:
                    line = _first_flagged_line(state.score_cache.get(node.path))
                    if sidebar_target:
                        _open_in_pane(sidebar_target, node.path, line)
                    else:
                        _open_in_editor(node.path, line, fd, old)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()
    if ide_session:
        subprocess.run(_tmux_kill_session(ide_session), check=False)


if __name__ == "__main__":
    main()
