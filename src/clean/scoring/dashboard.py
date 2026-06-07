"""``clean-hud`` — a full-screen Trust-HUD dashboard for a split terminal pane.

The statusline lives in Claude Code's small bottom strip. This is the "use the
whole screen" surface: a standalone TUI that polls ~/.clean/scoring.json and
draws a wide, colorful panel with per-metric bars, plain-English meanings, and
the specific flagged symbols. Run it in a side pane:

    clean-hud

No third-party dependencies — raw ANSI, redrawn on an interval. Ctrl-C quits.
"""

from __future__ import annotations

import os
import shutil
import sys
import time

from .state import ScoringStateWriter
from .statusline import (
    _BOLD,
    _CYAN,
    _DIM,
    _RESET,
    _WHITE,
    _bar,
    _circle,
    _color,
    _LABELS,
    _MEANING,
    git_context,
)

# Metric order for the dashboard (includes Index — there's room to explain it).
_DASH_ORDER = [
    "grounding",
    "blast_radius",
    "orphan",
    "alignment",
    "duplication",
    "index_trust",
]

_CLEAR = "\033[2J\033[H"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"


def _paint(text: str, c: str, color: bool) -> str:
    return f"{c}{text}{_RESET}" if color else text


def _rule(width: int, color: bool) -> str:
    return _paint("─" * width, _DIM, color)


def _hms(updated_at: str | None) -> str:
    if not updated_at or "T" not in updated_at:
        return "—"
    return updated_at.split("T", 1)[1][:8]


def render_dashboard(
    state: dict | None, git, width: int = 100, color: bool = True
) -> str:
    width = max(48, min(width, 160))
    bar_cells = max(20, min(48, width - 34))
    lines: list[str] = []

    title = _paint(" TRUST-HUD ", _BOLD + _WHITE, color)
    lines.append(title)
    lines.append(_rule(width, color))

    # --- header: repo / branch / file -------------------------------------
    repo = (git.repo if git else None) or "—"
    branch = (git.branch if git else None) or "—"
    lines.append(
        f" {_paint('repo', _DIM, color)}   {_paint(repo, _WHITE + _BOLD, color)}"
        f"    {_paint('branch', _DIM, color)} {_paint(branch, _CYAN + _BOLD, color)}"
    )

    if not state or state.get("skipped"):
        lines.append(_rule(width, color))
        lines.append(_paint(" waiting for an edit to score…", _DIM, color))
        lines.append(_rule(width, color))
        return "\n".join(lines)

    fname = os.path.basename(state.get("file_path", "") or "—")
    meta = (
        f"{fname} · {state.get('entity_count', 0)} entities "
        f"· updated {_hms(state.get('updated_at'))}"
    )
    if state.get("stale"):
        meta += " · " + _paint("● stale", _color(40) + _BOLD, color)
    lines.append(f" {_paint('file', _DIM, color)}   {meta}")
    lines.append(_rule(width, color))

    if not state.get("indexed", True):
        lines.append(
            _paint(f" not indexed — run: index {repo} to enable scoring", _DIM, color)
        )
        lines.append(_rule(width, color))
        return "\n".join(lines)

    # --- overall ----------------------------------------------------------
    overall = int(state.get("overall_score", 100))
    label = state.get("overall_label", "OK")
    oc = _color(overall)
    lines.append(
        f" {_paint('TRUST', _BOLD + _WHITE, color)}  "
        f"{_paint(_circle(overall), oc + _BOLD, color)}  "
        f"{_paint(_bar(overall, bar_cells), oc, color)}  "
        f"{_paint(f'{overall}/100 {label}', oc + _BOLD, color)}"
    )
    lines.append(_rule(width, color))

    # --- per-metric bars + meanings --------------------------------------
    by_key = {i["key"]: i for i in state.get("indicators", [])}
    offenders: list[tuple[str, str]] = []
    for key in _DASH_ORDER:
        ind = by_key.get(key)
        if ind is None or ind.get("skipped"):
            continue
        s = int(ind["score"])
        c = _color(s)
        name = _LABELS.get(key, key)
        lines.append(
            f" {_paint(name.ljust(11), c + _BOLD, color)} "
            f"{_paint(_bar(s, bar_cells), c, color)} "
            f"{_paint(f'{s:>3}', c + _BOLD, color)}  "
            f"{_paint(ind.get('summary', ''), _DIM, color)}"
        )
        lines.append(f"             {_paint(_MEANING.get(key, ''), _DIM, color)}")
        for off in ind.get("offenders", []):
            offenders.append((name, off))

    # --- flagged symbols --------------------------------------------------
    if offenders:
        lines.append(_rule(width, color))
        lines.append(_paint(" Flagged", _BOLD + _color(40), color))
        for metric, off in offenders[:10]:
            loc = f":{off['line']}" if off.get("line") else ""
            lines.append(
                f"   {_paint(off['name'] + loc, _color(40) + _BOLD, color)}"
                f"  {_paint(off.get('detail', ''), _DIM, color)}"
                f"  {_paint(f'({metric})', _DIM, color)}"
            )

    lines.append(_rule(width, color))
    lines.append(_paint(" Ctrl-C to quit · refreshes every 1s", _DIM, color))
    return "\n".join(lines)


def main() -> None:
    writer = ScoringStateWriter()
    color = os.getenv("NO_COLOR") is None
    interval = float(os.getenv("CLEAN_HUD_INTERVAL", "1") or "1")
    sys.stdout.write(_HIDE_CURSOR)
    try:
        while True:
            state = writer.read()
            anchor = os.getcwd()
            if state and state.get("file_path"):
                anchor = os.path.dirname(state["file_path"]) or anchor
            git = git_context(anchor)
            width = shutil.get_terminal_size((100, 30)).columns
            frame = render_dashboard(state, git, width=width, color=color)
            sys.stdout.write(_CLEAR + frame + "\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
