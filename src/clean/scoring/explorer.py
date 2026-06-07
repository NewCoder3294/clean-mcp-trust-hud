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
import sys  # noqa: F401  (used by the interactive loop added in Task 5)

from ..util.source_reader import SourceReaderError, read_source
from . import treeview  # noqa: F401  (used by main(), added in Task 5)
from .daemon import request_score
from .highlight import highlight_line, language_for
from .navigate import ExplorerState, current, reduce, visible_rows  # noqa: F401
from .statusline import (
    _BOLD,
    _CYAN,
    _DIM,
    _WHITE,
    _color,
    _paint,
    git_context,  # noqa: F401  (used by main(), added in Task 5)
)

_CLEAR = "\033[2J\033[H"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


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
        source, _meta = read_source(repo_root, rel, max_lines=height)
    except SourceReaderError:
        return [
            _paint(header, _WHITE + _BOLD, color),
            "",
            _paint("no preview", _DIM, color),
        ]
    lang = language_for(node.path)
    flags = _offender_map(score)
    out = [_paint(header, _WHITE + _BOLD, color), ""]
    for n, raw in enumerate(source.splitlines()[: height - 2], start=1):
        marker = _paint(f"  ◀ {flags[n]}", _color(0), color) if n in flags else ""
        gutter = _paint(f"{n:>4} ", _DIM, color)
        out.append(f"{gutter}{highlight_line(raw, lang, color)}{marker}")
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
) -> str:
    """Pure full-frame render (no terminal I/O)."""
    head = _paint("clean", _WHITE + _BOLD, color) + _paint(" ▸ ", _DIM, color)
    head += _paint(repo or os.path.basename(repo_root), _WHITE + _BOLD, color)
    if branch:
        head += _paint("  ⎇ ", _DIM, color) + _paint(branch, _CYAN, color)

    body_h = max(1, height - 3)
    show_preview = width >= 80
    sidebar_w = 34 if show_preview else width
    sidebar = _sidebar_lines(state, color, body_h)
    preview = _preview_lines(state, repo_root, color, body_h) if show_preview else []

    rows_out = []
    for i in range(body_h):
        left = sidebar[i] if i < len(sidebar) else ""
        if show_preview:
            visible = _strip_ansi(left)
            pad = " " * max(0, sidebar_w - len(visible))
            right = preview[i] if i < len(preview) else ""
            rows_out.append(f"{left}{pad}{_paint('│', _DIM, color)} {right}")
        else:
            rows_out.append(left)

    footer = _paint(
        "j/k move · l/⏎ open · h close · e vim · r rescore · q quit", _DIM, color
    )
    return "\n".join([head, ""] + rows_out + [footer])
