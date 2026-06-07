"""Pure key reducer for the clean-tree explorer.

Keeps navigation logic free of terminal side effects so it is unit-testable.
`reduce` returns the (mutated) state plus an action the shell must perform:
"open" (launch the editor on the current file), "quit", or None.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import treeview
from .treeview import Node


@dataclass
class ExplorerState:
    root: Node
    cursor: int = 0
    score_cache: dict[str, dict | None] = field(default_factory=dict)


def visible_rows(state: ExplorerState) -> list[Node]:
    return treeview.flatten(state.root)


def current(state: ExplorerState) -> Node | None:
    rows = visible_rows(state)
    if 0 <= state.cursor < len(rows):
        return rows[state.cursor]
    return None


_DOWN = ("j", "\x1b[B")
_UP = ("k", "\x1b[A")
_RIGHT = ("l", "\x1b[C")
_LEFT = ("h", "\x1b[D")
_OPEN = ("\r", "\n", "e")
_TOP = ("g", "\x1b[H")
_BOTTOM = ("G", "\x1b[F")
_QUIT = ("q", "Q", "\x03")


def reduce(state: ExplorerState, key: str) -> tuple[ExplorerState, str | None]:
    rows = visible_rows(state)
    n = len(rows)
    cur = rows[state.cursor] if 0 <= state.cursor < n else None

    if key in _QUIT:
        return state, "quit"
    if key in _DOWN:
        state.cursor = max(0, min(n - 1, state.cursor + 1))
        return state, None
    if key in _UP:
        state.cursor = max(0, state.cursor - 1)
        return state, None
    if key in _TOP:
        state.cursor = 0
        return state, None
    if key in _BOTTOM:
        state.cursor = max(0, n - 1)
        return state, None
    if key == "r":  # force re-score current file
        if cur and not cur.is_dir:
            state.score_cache.pop(cur.path, None)
        return state, None
    if key in _RIGHT:
        if cur and cur.is_dir:
            treeview.expand(cur)
            return state, None
        if cur and not cur.is_dir:
            return state, "open"
        return state, None
    if key in _OPEN:
        if cur and cur.is_dir:
            (treeview.collapse if cur.expanded else treeview.expand)(cur)
            return state, None
        if cur and not cur.is_dir:
            return state, "open"
        return state, None
    if key in _LEFT:
        if cur and cur.is_dir and cur.expanded:
            treeview.collapse(cur)
            return state, None
        pidx = treeview.parent_index(rows, state.cursor)
        if pidx is not None:
            state.cursor = pidx
        return state, None
    return state, None
