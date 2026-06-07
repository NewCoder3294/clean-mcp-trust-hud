# clean-ide — tmux-backed docked sidebar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add `clean-ide`: one command that opens a tmux session with a vim editor pane + a narrow right `clean-tree` sidebar, where pressing Enter in the sidebar opens the file in the editor pane.

**Architecture:** Two changes. (1) `explorer.py` gains a `--sidebar` mode whose "open" action sends the file to a target tmux pane (`tmux send-keys`) instead of launching vim inline; the command-building is a pure, tested helper. (2) A new `ide.py` (`clean-ide` entry point) launches and wires the tmux session (editor pane + narrow sidebar pane, sidebar gets the editor pane id via `CLEAN_TREE_TARGET`), enables mouse, and attaches.

**Tech Stack:** Python 3.10+ stdlib (`os`, `sys`, `subprocess`, `shutil`, `shlex`), tmux 3.x, pytest.

---

## File structure

| File | Responsibility |
|------|----------------|
| `src/clean/scoring/explorer.py` (modify) | Add `_tmux_send_keys` (pure), `_open_in_pane`, and `--sidebar` handling in `main()`/`_interactive_loop`. |
| `src/clean/scoring/ide.py` (create) | `clean-ide` launcher: build the tmux session, wire the sidebar, attach. |
| `pyproject.toml` (modify) | Add `clean-ide` script entry point. |
| `tests/unit/scoring/test_explorer.py` (modify) | Tests for `_tmux_send_keys` + sidebar open dispatch. |
| `tests/unit/scoring/test_ide.py` (create) | Tests for the launcher's pure helpers (tmux-missing guard, command construction). |
| `src/clean/scoring/docs.md` + `README.md` (modify) | Document `clean-ide`. |

---

## Task 1: `--sidebar` mode in explorer.py

**Files:**
- Modify: `src/clean/scoring/explorer.py`
- Test: `tests/unit/scoring/test_explorer.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/scoring/test_explorer.py`; add `import subprocess` and the new symbols to the explorer import line):

```python
def test_tmux_send_keys_builds_open_command():
    from clean.scoring.explorer import _tmux_send_keys

    cmd = _tmux_send_keys("%3", "/repo/src/a.py", 12)
    assert cmd == [
        "tmux", "send-keys", "-t", "%3",
        "Escape", ":edit +12 /repo/src/a.py", "Enter",
    ]


def test_tmux_send_keys_escapes_spaces_for_vim():
    from clean.scoring.explorer import _tmux_send_keys

    cmd = _tmux_send_keys("%3", "/repo/a b.py", 1)
    assert cmd[-2] == r":edit +1 /repo/a\ b.py"


def test_open_in_pane_invokes_tmux(monkeypatch):
    from clean.scoring import explorer

    calls = []
    monkeypatch.setattr(
        explorer.subprocess, "run", lambda *a, **k: calls.append(a[0])
    )
    explorer._open_in_pane("%5", "/repo/a.py", 7)
    # send-keys then select-pane
    assert calls[0][:4] == ["tmux", "send-keys", "-t", "%5"]
    assert calls[1] == ["tmux", "select-pane", "-t", "%5"]
```

- [ ] **Step 2: Run, confirm failure**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_explorer.py -q`
Expected: FAIL — `ImportError: cannot import name '_tmux_send_keys'`.

- [ ] **Step 3: Implement.** Add these two functions to `src/clean/scoring/explorer.py` (place them just above `_open_in_editor`):

```python
def _tmux_send_keys(target: str, path: str, line: int) -> list[str]:
    """tmux argv that opens *path* at *line* in the vim running in pane *target*.

    Sends Escape (ensure normal mode), then ``:edit +<line> <path><CR>``. Spaces
    in the path are backslash-escaped for vim's command line.
    """
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


def _open_in_pane(target: str, path: str, line: int) -> None:
    """Open *path* at *line* in the editor running in tmux pane *target*, then
    focus that pane. Used by `clean-tree --sidebar`; does NOT touch our own TTY."""
    try:
        subprocess.run(_tmux_send_keys(target, path, line), check=False)
        subprocess.run(["tmux", "select-pane", "-t", target], check=False)
    except OSError as e:
        sys.stderr.write(f"tmux error: {e}\n")
```

- [ ] **Step 4: Wire `--sidebar` into `main()` and `_interactive_loop`.** Replace the existing `main()` and `_interactive_loop` with:

```python
def main() -> None:
    color = os.getenv("NO_COLOR") is None
    cwd = os.getcwd()
    repo_root = _repo_root(cwd)
    git = git_context(repo_root)
    state = ExplorerState(root=treeview.build_root(repo_root))

    if "--once" in sys.argv[1:] or not sys.stdin.isatty():
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

    # Sidebar mode: opening a file targets the editor in another tmux pane.
    sidebar_target = (
        os.environ.get("CLEAN_TREE_TARGET") if "--sidebar" in sys.argv[1:] else None
    )
    _interactive_loop(state, repo_root, git, color, sidebar_target)


def _interactive_loop(state, repo_root, git, color, sidebar_target=None) -> None:
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
```

- [ ] **Step 5: Run tests + lint**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_explorer.py -q && .venv/bin/ruff check src/clean/scoring/explorer.py tests/unit/scoring/test_explorer.py && .venv/bin/ruff format --check src/clean/scoring/explorer.py`
Expected: all pass; ruff clean (format the file if needed).

- [ ] **Step 6: Commit**

```bash
git add src/clean/scoring/explorer.py tests/unit/scoring/test_explorer.py
git commit -m "feat(explorer): --sidebar mode opens files into a tmux editor pane"
```

---

## Task 2: `clean-ide` launcher + entry point + docs

**Files:**
- Create: `src/clean/scoring/ide.py`
- Modify: `pyproject.toml`, `src/clean/scoring/docs.md`, `README.md`
- Test: `tests/unit/scoring/test_ide.py`

- [ ] **Step 1: Write the failing test** (`tests/unit/scoring/test_ide.py`):

```python
"""Tests for the clean-ide launcher helpers."""

import pytest

from clean.scoring import ide


def test_sidebar_command_uses_module_invocation():
    cmd = ide._sidebar_command("/usr/bin/python3", "%4")
    # runs the explorer module in --sidebar mode with the editor pane id exported
    assert "clean.scoring.explorer --sidebar" in cmd
    assert "CLEAN_TREE_TARGET=%4" in cmd
    assert "/usr/bin/python3" in cmd


def test_require_tmux_raises_when_missing(monkeypatch):
    monkeypatch.setattr(ide.shutil, "which", lambda _name: None)
    with pytest.raises(SystemExit):
        ide._require_tmux()


def test_require_tmux_ok_when_present(monkeypatch):
    monkeypatch.setattr(ide.shutil, "which", lambda _name: "/opt/homebrew/bin/tmux")
    ide._require_tmux()  # does not raise
```

- [ ] **Step 2: Run, confirm failure**

Run: `.venv/bin/python -m pytest tests/unit/scoring/test_ide.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clean.scoring.ide'`.

- [ ] **Step 3: Implement `src/clean/scoring/ide.py`:**

```python
"""``clean-ide`` — launch a tmux session: vim editor pane + clean-tree sidebar.

One command opens an IDE-style layout in any terminal that can run tmux: the
main pane runs your editor; a narrow right pane runs ``clean-tree --sidebar``.
Pressing Enter on a file in the sidebar opens it in the editor pane. Quitting
the sidebar (or the editor) tears the session down. tmux is required but stays
invisible — you only ever run ``clean-ide``.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

_SIDEBAR_WIDTH = "36"  # columns for the right-hand tree pane


def _require_tmux() -> None:
    if shutil.which("tmux") is None:
        sys.exit(
            "clean-ide needs tmux (it stays hidden). Install it with:\n"
            "  brew install tmux\n"
        )


def _sidebar_command(python: str, editor_pane: str) -> str:
    """Shell command for the sidebar pane: run the explorer in --sidebar mode
    with the editor pane id exported so 'open' targets it."""
    run = f"{shlex.quote(python)} -m clean.scoring.explorer --sidebar"
    return f"CLEAN_TREE_TARGET={editor_pane} {run}"


def main() -> None:
    _require_tmux()
    cwd = os.getcwd()
    editor = os.environ.get("EDITOR") or "vim"
    session = f"clean-ide-{os.getpid()}"

    # Main pane runs the editor; capture its pane id.
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-c", cwd, editor],
        check=True,
    )
    editor_pane = subprocess.run(
        ["tmux", "list-panes", "-t", session, "-F", "#{pane_id}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # Narrow right pane runs the sidebar, told which pane to open files into.
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-h",
            "-l",
            _SIDEBAR_WIDTH,
            "-t",
            session,
            "-c",
            cwd,
            _sidebar_command(sys.executable, editor_pane),
        ],
        check=True,
    )

    # Niceties: click-to-focus panes; hide the tmux status bar; start in editor.
    for opt in (["mouse", "on"], ["status", "off"]):
        subprocess.run(["tmux", "set-option", "-t", session, *opt], check=False)
    subprocess.run(["tmux", "select-pane", "-t", editor_pane], check=False)

    # Replace this process with the attached session (blocks until it ends).
    os.execvp("tmux", ["tmux", "attach-session", "-t", session])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add the entry point to `pyproject.toml`** — after `clean-tree = ...` in `[project.scripts]`:

```toml
clean-ide = "clean.scoring.ide:main"
```

- [ ] **Step 5: Reinstall, test, lint**

Run:
```bash
.venv/bin/pip install -e . -q
.venv/bin/python -m pytest tests/unit/scoring/test_ide.py tests/unit/scoring/test_explorer.py -q
.venv/bin/ruff check src/clean/scoring/ide.py tests/unit/scoring/test_ide.py
.venv/bin/ruff format --check src/clean/scoring/ide.py tests/unit/scoring/test_ide.py
command -v clean-ide || ls .venv/bin/clean-ide
```
Expected: tests pass; ruff clean; `clean-ide` script present in `.venv/bin/`.

- [ ] **Step 6: Document** — add to `src/clean/scoring/docs.md` Contents table:

```markdown
| `ide.py` | `clean-ide` entry point: launches a tmux session (editor pane + narrow `clean-tree --sidebar` pane) so opening a file in the tree loads it in the editor. tmux required but hidden. |
```
And add a short `clean-ide` note to `README.md` near the `clean-tree` entry: "`clean-ide` — IDE layout: your editor on the left, the trust-colored tree as a docked right sidebar; Enter opens files into the editor (needs tmux)."

- [ ] **Step 7: Commit**

```bash
git add src/clean/scoring/ide.py pyproject.toml tests/unit/scoring/test_ide.py src/clean/scoring/docs.md README.md
git commit -m "feat(ide): clean-ide tmux launcher — editor pane + docked clean-tree sidebar"
```

---

## Manual verification (human, real terminal)

In Terminal.app: `cd ~/clean-mcp-trust-hud && .venv/bin/clean-ide`. Expect a vim pane on the left and the trust-colored tree on the right. In the tree: `j/k` move, `l` expand; press Enter on a file → it opens in the vim pane at the first flagged line; click between panes to switch focus (mouse on); `q` in the tree ends the session.

## Self-review notes

- Spec coverage: docked right sidebar (Task 2 split-window `-h -l 36`) ✓; opens file into editor pane (Task 1 `_open_in_pane` + Task 2 `CLEAN_TREE_TARGET`) ✓; open at first flagged line (`_first_flagged_line` reused) ✓; tmux hidden/one command (`clean-ide`) ✓; tmux-missing guard (`_require_tmux`) ✓; mouse click-to-focus ✓.
- Deferred (not in any task): non-vim editors, configurable split ratio, reusing an existing tmux session.
- Type consistency: `_tmux_send_keys(target, path, line) -> list[str]`, `_open_in_pane(target, path, line)`, `_sidebar_command(python, editor_pane) -> str`, `_require_tmux()` used consistently across tasks and tests.
