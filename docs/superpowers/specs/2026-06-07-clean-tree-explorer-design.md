# clean-tree — terminal file explorer with Trust-HUD preview

**Status:** approved design · **Date:** 2026-06-07 · **Branch:** feat/trust-hud

## Summary

A standalone, dependency-free terminal UI (`clean-tree`) that opens the
project's file tree as a left sidebar with a live code preview on the right.
Files are colored by their Trust-HUD score (lazily, as you browse), the preview
syntax-highlights the source and marks the exact lines the Trust-HUD flagged,
and pressing Enter opens the file in `$EDITOR` (default `vim`) at the previewed
line. It reuses the existing `clean-hud` terminal machinery and the clean-mcp
scoring/index data — no new dependencies, no new silos.

## Goals

- Browse the repo as a trust-colored tree in the terminal (sidebar layout).
- Preview the highlighted file with dep-free syntax coloring + Trust-HUD flag
  overlay.
- Open the selected file in vim at the previewed line; return to the explorer
  on quit.
- Match the btop/tmux aesthetic of the existing HUD; degrade gracefully.

## Non-goals (v1)

Fuzzy find (`/`), mouse support, git-status markers, file operations
(create/rename/delete), multi-root workspaces. These are explicitly deferred.

## Decisions (locked during brainstorming)

| Decision | Choice |
|----------|--------|
| Interaction model | Standalone explorer TUI: tree sidebar + code preview; vim takes over the screen on open, returns on `:q`. |
| Preview richness | Trust-aware: dep-free syntax highlighting **plus** marking the lines/symbols the Trust-HUD flagged. |
| Tree trust scores | Lazy, on-highlight via the warm daemon; cached for the session. |
| Editor | `$EDITOR` if set, else `vim`; opened at the file's first Trust-HUD-flagged line if any, else line 1 (`+N`). |
| Tech | Hand-rolled raw-ANSI TUI (no new deps), mirroring `dashboard.py`. |

## Architecture

Four small, focused, independently testable units in `src/clean/scoring/`:

| Module | Purpose | Pure? |
|--------|---------|-------|
| `treeview.py` | Tree **model**: build from `util/file_tree.build_file_tree`; track expand/collapse + cursor; flatten to an ordered list of visible rows (depth, kind, path, is_last). | yes (no I/O beyond the initial build) |
| `highlight.py` | Dep-free **syntax highlighter**: tokenize Python/JS/TS (keywords, strings, comments, numbers) into ANSI-colored spans. `color=False` → plain text. | yes |
| `navigate.py` | **Reducer** `reduce(state, key) -> state` mapping keypresses (j/k/h/l/g/G/Enter/r/q) to a new explorer state. Keeps input logic testable, separate from terminal side effects. | yes |
| `explorer.py` | TUI **shell**: raw-mode loop, render (sidebar + preview + footer), lazy-score cache, vim launch. Entry point `clean-tree`. | no (terminal + subprocess) |

### Reuse (no new silos)

- ANSI constants + `_paint`, `_color` from `scoring/statusline.py`.
- `build_file_tree` from `util/file_tree.py` (already has the skip-dir set).
- `read_source` from `util/source_reader.py` for preview content.
- **Lazy scores via the warm daemon**: `scoring/daemon.request_score` (the same
  client the hook uses), falling back to the no-model indicators if the daemon
  is down — the explorer never loads the embedding model itself.
- Flagged lines come from each file's `FileScore.offenders`, which already carry
  `line` numbers and the indicator that flagged them.

## Data flow

1. `clean-tree` resolves the repo root for the cwd (git toplevel, else cwd) and
   builds the tree.
2. Render: sidebar (visible rows, trust dots), preview of the highlighted file,
   footer keymap.
3. On cursor move to a **file**: look up its score in the session cache; on a
   miss, request it from the daemon and show a neutral `…` dot until it returns,
   then recolor the row and redraw the preview (highlighted source + offender
   markers `◀ <indicator>` on flagged lines).
4. On `Enter`/`e`: restore the terminal (cooked mode, show cursor, clear),
   `subprocess.call([editor, f"+{line}", path])` where `line` is the file's
   first flagged offender line (else 1), then re-enter raw mode and redraw.
   `editor = os.environ.get("EDITOR") or "vim"`.

## Key bindings

| Keys | Action |
|------|--------|
| `j` / `↓`, `k` / `↑` | move cursor down / up |
| `l` / `→` | expand dir, or open file in vim |
| `h` / `←` | collapse dir / jump to parent |
| `Enter`, `e` | open highlighted file in vim (at the first flagged line, else line 1) |
| `g` / `G` | jump to top / bottom |
| `r` | re-score the highlighted file (bypass cache) |
| `q`, `Ctrl-C` | quit |

## Visual design

btop/tmux feel: rounded box-drawing borders; header `clean ▸ <repo>  ⎇ <branch>`;
trust dots `●` colored green/amber/red (dim `○` when unscored); dim tree guide
lines; a vertical divider to the preview; preview header `file  NN/100 LABEL`;
dim footer keymap. Honors `NO_COLOR`. Under ~80 columns the preview pane hides
and the tree goes full width.

## Error handling / edge cases

- Not a git repo → build the tree from cwd.
- Unreadable / binary file → preview shows "no preview".
- Daemon down → uncolored tree + plain (still-highlighted) preview; fully usable.
- Large/noisy dirs → excluded by `file_tree`'s skip-dir set.
- `vim`/`$EDITOR` missing → footer error, stay in the TUI.
- Empty repo / no files → "nothing to show" placeholder.

## Testing

Unit tests (deterministic, `color=False` where rendering):

- `treeview`: build, expand/collapse, flatten ordering, cursor clamping.
- `highlight`: token classification per language; plain-mode passthrough.
- `navigate`: each key transition on a known state.
- `explorer`: the **pure render** function (fake tree + state + size → expected
  layout string).

The raw-mode input loop and the vim `subprocess.call` stay thin and are not
unit-tested (side-effecting shell). Manual verification: run `clean-tree` in the
repo, browse, open a file in vim, confirm trust colors + flag markers.

## Entry point

Add to `pyproject.toml` `[project.scripts]`:

```toml
clean-tree = "clean.scoring.explorer:main"
```

## Deferred (v2+)

Fuzzy filter, mouse, git-status markers, file operations, configurable
keybindings, preview scroll independent of cursor.
