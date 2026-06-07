"""Lazy structured tree model for the clean-tree explorer.

Reuses the always-skip directory set from the file-tree util but builds a
navigable node structure (with expand/collapse state) rather than a rendered
string. Children load lazily the first time a directory is expanded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..util.file_tree import should_skip_dir


@dataclass
class Node:
    path: str  # absolute path
    name: str  # basename
    is_dir: bool
    depth: int  # 0 = repo root; its children are depth 1
    expanded: bool = False
    loaded: bool = False
    children: list["Node"] = field(default_factory=list)


def build_root(repo_dir: str) -> Node:
    """Build the (expanded) root node for *repo_dir* with its children loaded."""
    abspath = os.path.abspath(repo_dir)
    root = Node(
        path=abspath,
        name=os.path.basename(abspath) or abspath,
        is_dir=True,
        depth=0,
        expanded=True,
    )
    load_children(root)
    return root


def load_children(node: Node, include_hidden: bool = False) -> None:
    """Populate *node*.children once (dirs first, then files, each sorted)."""
    if node.loaded or not node.is_dir:
        return
    try:
        entries = list(os.scandir(node.path))
    except OSError:
        node.loaded = True
        return
    dirs = sorted(
        (
            e
            for e in entries
            if e.is_dir(follow_symlinks=False)  # avoid symlink loops
            and not should_skip_dir(e.name, include_hidden)
        ),
        key=lambda e: e.name,
    )
    files = sorted(
        (
            e
            for e in entries
            if e.is_file() and (include_hidden or not e.name.startswith("."))
        ),
        key=lambda e: e.name,
    )
    node.children = [
        Node(path=e.path, name=e.name, is_dir=True, depth=node.depth + 1) for e in dirs
    ] + [
        Node(path=e.path, name=e.name, is_dir=False, depth=node.depth + 1)
        for e in files
    ]
    node.loaded = True


def expand(node: Node) -> None:
    if not node.is_dir:
        return
    load_children(node)
    node.expanded = True


def collapse(node: Node) -> None:
    node.expanded = False


def flatten(root: Node) -> list[Node]:
    """Visible rows in display order (root itself is a header, not a row)."""
    out: list[Node] = []

    def _rec(node: Node) -> None:
        for child in node.children:
            out.append(child)
            if child.is_dir and child.expanded:
                _rec(child)

    _rec(root)
    return out


def parent_index(rows: list[Node], idx: int) -> int | None:
    """Index in *rows* of the directory that contains rows[idx], or None."""
    if not 0 <= idx < len(rows):
        return None
    target_depth = rows[idx].depth - 1
    for j in range(idx - 1, -1, -1):
        if rows[j].depth == target_depth and rows[j].is_dir:
            return j
    return None
