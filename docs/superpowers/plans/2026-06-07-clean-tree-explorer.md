# clean-tree Terminal File Explorer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `clean-tree`, a dependency-free terminal file explorer with a trust-colored tree sidebar, a syntax-highlighted + Trust-HUD-flag preview, and open-in-vim.

**Architecture:** Four focused modules in `src/clean/scoring/`: `treeview.py` (pure tree model via a lazy structured walk), `highlight.py` (pure dep-free syntax highlighter), `navigate.py` (pure key reducer), and `explorer.py` (raw-ANSI TUI shell + entry point). Reuses `statusline.py` ANSI helpers, `util/file_tree._should_skip`, `util/source_reader.read_source`, and `scoring/daemon.request_score`. Mirrors the existing `dashboard.py` raw-mode loop.

**Tech Stack:** Python 3.10+, stdlib only (`os`, `re`, `termios`, `tty`, `select`, `subprocess`, `dataclasses`), pytest.

---

## File structure

| File | Responsibility |
|------|----------------|
| `src/clean/scoring/treeview.py` (create) | `Node` model + `build_root`, `load_children`, `flatten`, `expand`, `collapse`, `parent_index`. Structured lazy directory walk. |
| `src/clean/scoring/highlight.py` (create) | `language_for(path)`, `highlight_line(line, lang, color)` — dep-free per-language token coloring. |
| `src/clean/scoring/navigate.py` (create) | `ExplorerState`, `visible_rows`, `reduce(state, key) -> (state, action)`. |
| `src/clean/scoring/explorer.py` (create) | TUI: `render`, trust dots, preview, lazy-score cache, editor launch, `main`. Entry `clean-tree`. |
| `tests/unit/scoring/test_treeview.py` (create) | treeview model tests |
| `tests/unit/scoring/test_highlight.py` (create) | highlighter tests |
| `tests/unit/scoring/test_navigate.py` (create) | reducer tests |
| `tests/unit/scoring/test_explorer.py` (create) | pure render + trust dot + preview tests |
| `pyproject.toml` (modify) | add `clean-tree` script entry point |
| `src/clean/scoring/docs.md` (modify) | document the explorer |

---

## Task 1: Tree model (`treeview.py`)

**Files:**
- Create: `src/clean/scoring/treeview.py`
- Test: `tests/unit/scoring/test_treeview.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/scoring/test_treeview.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_treeview.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clean.scoring.treeview'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/clean/scoring/treeview.py
"""Lazy structured tree model for the clean-tree explorer.

Reuses the always-skip directory set from the file-tree util but builds a
navigable node structure (with expand/collapse state) rather than a rendered
string. Children load lazily the first time a directory is expanded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..util.file_tree import _should_skip


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
        (e for e in entries if e.is_dir() and not _should_skip(e.name, include_hidden)),
        key=lambda e: e.name,
    )
    files = sorted((e for e in entries if e.is_file()), key=lambda e: e.name)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_treeview.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/treeview.py tests/unit/scoring/test_treeview.py
git commit -m "feat(explorer): lazy structured tree model for clean-tree"
```

---

## Task 2: Syntax highlighter (`highlight.py`)

**Files:**
- Create: `src/clean/scoring/highlight.py`
- Test: `tests/unit/scoring/test_highlight.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/scoring/test_highlight.py
"""Tests for the dep-free syntax highlighter."""

from clean.scoring import highlight


def test_language_for_known_extensions():
    assert highlight.language_for("a/b/x.py") == "python"
    assert highlight.language_for("x.ts") == "ts"
    assert highlight.language_for("x.tsx") == "ts"
    assert highlight.language_for("x.js") == "js"
    assert highlight.language_for("x.md") is None


def test_plain_mode_is_passthrough():
    line = "def foo():  # hi"
    assert highlight.highlight_line(line, "python", color=False) == line


def test_keyword_and_comment_get_ansi_when_colored():
    out = highlight.highlight_line("def foo():  # hi", "python", color=True)
    assert "\033[" in out  # some ANSI emitted
    assert "def" in out and "foo" in out  # text preserved
    # a comment-only line is fully dimmed
    c = highlight.highlight_line("# just a comment", "python", color=True)
    assert c.startswith("\033[2m")  # _DIM


def test_unknown_language_is_passthrough():
    assert highlight.highlight_line("anything", None, color=True) == "anything"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_highlight.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clean.scoring.highlight'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/clean/scoring/highlight.py
"""Dependency-free syntax highlighting for the explorer preview.

Tokenizes a single line of Python/JS/TS into comment / string / number /
keyword / default spans and paints them with the statusline ANSI palette.
With color=False it returns the line unchanged.
"""

from __future__ import annotations

import re

from .statusline import _BLUE, _BOLD, _CYAN, _DIM, _GREEN, _paint

_EXT_LANG = {
    ".py": "python",
    ".js": "js",
    ".jsx": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".mjs": "js",
    ".cjs": "js",
}

_KEYWORDS = {
    "python": {
        "def", "class", "return", "if", "elif", "else", "for", "while", "try",
        "except", "finally", "with", "as", "import", "from", "raise", "yield",
        "lambda", "pass", "break", "continue", "and", "or", "not", "in", "is",
        "None", "True", "False", "async", "await", "global", "nonlocal",
    },
    "js": {
        "function", "return", "if", "else", "for", "while", "try", "catch",
        "finally", "const", "let", "var", "class", "extends", "new", "import",
        "from", "export", "default", "await", "async", "yield", "typeof",
        "null", "undefined", "true", "false", "this", "super",
    },
}
_KEYWORDS["ts"] = _KEYWORDS["js"] | {
    "interface", "type", "enum", "implements", "public", "private", "protected",
    "readonly", "namespace", "declare", "as", "keyof",
}

# comment | string | number | identifier  (order matters: comments/strings first)
_TOKEN_RE = re.compile(
    r"(?P<comment>#[^\n]*|//[^\n]*)"
    r"|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')"
    r"|(?P<number>\b\d+(?:\.\d+)?\b)"
    r"|(?P<ident>[A-Za-z_]\w*)"
)


def language_for(path: str) -> str | None:
    _, ext = os.path.splitext(path)
    return _EXT_LANG.get(ext.lower())


def highlight_line(line: str, lang: str | None, color: bool) -> str:
    if not color or lang not in _KEYWORDS:
        return line
    keywords = _KEYWORDS[lang]

    def _sub(m: re.Match) -> str:
        if m.lastgroup == "comment":
            return _paint(m.group(), _DIM, True)
        if m.lastgroup == "string":
            return _paint(m.group(), _GREEN, True)
        if m.lastgroup == "number":
            return _paint(m.group(), _CYAN, True)
        text = m.group()
        if text in keywords:
            return _paint(text, _BLUE + _BOLD, True)
        return text

    return _TOKEN_RE.sub(_sub, line)


import os  # noqa: E402  (kept after the regex for readability)
```

> Note: move `import os` to the top with the other imports when implementing — it is shown at the bottom only to keep the regex block contiguous. Final file must have all imports at the top (ruff will enforce this).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_highlight.py -q && .venv/bin/ruff check src/clean/scoring/highlight.py`
Expected: PASS (4 passed); ruff: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/highlight.py tests/unit/scoring/test_highlight.py
git commit -m "feat(explorer): dep-free syntax highlighter for preview"
```

---

## Task 3: Key reducer (`navigate.py`)

**Files:**
- Create: `src/clean/scoring/navigate.py`
- Test: `tests/unit/scoring/test_navigate.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_navigate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clean.scoring.navigate'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/clean/scoring/navigate.py
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
        state.cursor = min(n - 1, state.cursor + 1)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_navigate.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/navigate.py tests/unit/scoring/test_navigate.py
git commit -m "feat(explorer): pure key reducer for navigation"
```

---

## Task 4: Explorer render + scoring + preview (`explorer.py`, pure parts)

**Files:**
- Create: `src/clean/scoring/explorer.py`
- Test: `tests/unit/scoring/test_explorer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/scoring/test_explorer.py
"""Tests for the explorer's pure render helpers."""

from clean.scoring import treeview
from clean.scoring.explorer import (
    _first_flagged_line,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_explorer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clean.scoring.explorer'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/clean/scoring/explorer.py
"""``clean-tree`` — a terminal file explorer with a Trust-HUD preview.

A dependency-free raw-ANSI TUI: a trust-colored file-tree sidebar on the left,
a syntax-highlighted preview (with Trust-HUD flag markers) on the right, and
open-in-vim. Mirrors the dashboard.py terminal machinery; reuses the statusline
palette, the daemon scorer, and read_source.
"""

from __future__ import annotations

import os
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


def _trust_dot(score: dict | None, color: bool) -> tuple[str, str]:
    """Return (glyph, ansi-color) for a file's overall trust score."""
    if not score or score.get("overall_score") is None:
        return "○", _DIM
    return "●", _color(int(score["overall_score"]))


def _first_flagged_line(score: dict | None) -> int:
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


def _sidebar_lines(
    state: ExplorerState, repo_root: str, color: bool, height: int
) -> list[str]:
    rows = visible_rows(state)
    lines: list[str] = []
    for i, node in enumerate(rows[:height]):
        indent = "  " * node.depth
        if node.is_dir:
            caret = "▾ " if node.expanded else "▸ "
            label = caret + node.name + "/"
            body = _paint(label, _CYAN, color)
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
        if i == state.cursor:
            row = _paint("›", _WHITE + _BOLD, color) + " " + row
        else:
            row = "  " + row
        lines.append(row)
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
        header = (
            f"{rel}  {_paint(str(score['overall_score']) + '/100 '
            + score.get('overall_label', ''), _color(int(score['overall_score'])) + _BOLD, color)}"
        )
    try:
        source, _meta = read_source(repo_root, rel, max_lines=height)
    except SourceReaderError:
        return [header, "", _paint("no preview", _DIM, color)]
    lang = language_for(node.path)
    flags = _offender_map(score)
    out = [_paint(header, _WHITE + _BOLD, color), ""]
    for n, raw in enumerate(source.splitlines()[: height - 2], start=1):
        marker = ""
        if n in flags:
            marker = _paint(f"  ◀ {flags[n]}", _color(0), color)
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
    sidebar = _sidebar_lines(state, repo_root, color, body_h)
    preview = _preview_lines(state, repo_root, color, body_h) if show_preview else []

    rows_out = []
    for i in range(body_h):
        left = sidebar[i] if i < len(sidebar) else ""
        if show_preview:
            # pad left column to sidebar_w (ANSI-naive pad is fine for our glyphs)
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


def _strip_ansi(s: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", s)
```

> Note: the f-string for `header` in `_preview_lines` spans lines for readability in this plan; when implementing, write it as a single-line f-string so it parses. Run ruff format after.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_explorer.py -q && .venv/bin/ruff check src/clean/scoring/explorer.py`
Expected: PASS (3 passed); ruff: All checks passed!

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/explorer.py tests/unit/scoring/test_explorer.py
git commit -m "feat(explorer): trust-colored render, lazy scoring, trust-aware preview"
```

---

## Task 5: Interactive loop + editor launch + entry point

**Files:**
- Modify: `src/clean/scoring/explorer.py` (add `_open_in_editor`, `main`, `_interactive_loop`)
- Modify: `pyproject.toml` (add `clean-tree` script)

- [ ] **Step 1: Add the editor launch + loop + main to `explorer.py`**

Append to `src/clean/scoring/explorer.py`:

```python
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
    except FileNotFoundError:
        sys.stderr.write(f"editor not found: {editor}\n")
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

    if "--once" in sys.argv[1:] or not sys.stdin.isatty():
        w, h = _terminal_size()
        # score the first file so --once frames show a real color
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

    _interactive_loop(state, repo_root, git, color)


def _interactive_loop(state, repo_root, git, color) -> None:
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
                    _open_in_editor(node.path, line, fd, old)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add the entry point to `pyproject.toml`**

In `[project.scripts]`, add the line after `clean-hud`:

```toml
clean-tree = "clean.scoring.explorer:main"
```

- [ ] **Step 3: Reinstall so the script registers, then smoke-test `--once`**

Run:
```bash
.venv/bin/pip install -e . -q && printf '' | .venv/bin/clean-tree --once | sed 's/\x1b\[[0-9;]*m//g' | head -20
```
Expected: prints the header (`clean ▸ …`), a tree with `src`/files, and the footer keymap — no traceback.

- [ ] **Step 4: Run the full scoring test suite + lint/format**

Run:
```bash
.venv/bin/python -m pytest tests/unit/scoring -q && .venv/bin/ruff check src/clean/scoring/ && .venv/bin/ruff format --check src/clean/scoring/explorer.py
```
Expected: all pass; ruff clean (run `.venv/bin/ruff format src/clean/scoring/explorer.py` if format check fails, then re-run).

- [ ] **Step 5: Commit**

```bash
git add src/clean/scoring/explorer.py pyproject.toml
git commit -m "feat(explorer): interactive loop, open-in-vim, clean-tree entry point"
```

---

## Task 6: Docs + manual verification

**Files:**
- Modify: `src/clean/scoring/docs.md`
- Modify: `README.md` (add `clean-tree` to the entry-point/usage list if one exists)

- [ ] **Step 1: Document the explorer in `src/clean/scoring/docs.md`**

Add a row to the Contents table:

```markdown
| `explorer.py` | `clean-tree` entry point: trust-colored file-tree sidebar + syntax-highlighted, Trust-HUD-flagged preview; opens files in `$EDITOR`/vim. Tree model in `treeview.py`, highlighter in `highlight.py`, key reducer in `navigate.py`. |
```

- [ ] **Step 2: Manual verification (interactive — do this in a real terminal)**

Run: `cd ~/clean-mcp-trust-hud && .venv/bin/clean-tree`
Verify:
- Tree renders with the repo name header; `j/k` move; `l` expands a dir; `h` collapses.
- Navigating onto a `.py` file shows a colored trust dot + number and a highlighted preview; a flagged file shows `◀ <indicator>` markers.
- `Enter`/`e` opens the file in vim at the first flagged line; `:q` returns to the explorer.
- `q` exits cleanly and the cursor is restored.

- [ ] **Step 3: Commit**

```bash
git add src/clean/scoring/docs.md README.md
git commit -m "docs(explorer): document clean-tree usage"
```

---

## Self-review notes

- **Spec coverage:** standalone explorer + preview (Tasks 4-5) ✓; trust-aware preview with flag overlay (`_offender_map`, `_preview_lines`) ✓; lazy on-highlight scoring via daemon (`_score_for`, cache in `ExplorerState`) ✓; open at first flagged line (`_first_flagged_line`, Task 5) ✓; hand-rolled ANSI mirroring dashboard ✓; key bindings (Task 3 reducer) ✓; visual header/dots/divider/footer (`render`) ✓; error handling (`SourceReaderError`, daemon-down → `None` score, narrow-terminal `show_preview`) ✓; testing of the three pure modules + render ✓; entry point (Task 5) ✓.
- **Deferred items** (fuzzy find, mouse, git markers, file ops) intentionally not in any task.
- **Type consistency:** `Node`, `ExplorerState`, `reduce`, `render`, `_trust_dot`, `_first_flagged_line` names/signatures match across tasks. `request_score` returns `dict | None` (used as score dict everywhere). `read_source(repo_dir, rel, max_lines=…)` matches the real signature.
- **Known implementation nits flagged for the engineer:** move `import os` to the top in `highlight.py`; write the `header` f-string in `_preview_lines` on one line. Both are called out at their step.
