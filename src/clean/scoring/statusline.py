"""``clean-statusline`` console entry point.

Reads ~/.clean/scoring.json and prints a compact, color-banded one-liner for
the Claude Code statusline, e.g.:

    🛡 82 REVIEW · grnd 67 · blast 90 · idx 100

Claude Code passes a session JSON object on stdin; it is ignored.
"""

from __future__ import annotations

import os
import sys

from .state import ScoringStateWriter

_RESET = "\033[0m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_DIM = "\033[2m"

# Short labels for the HUD.
_SHORT = {
    "grounding": "grnd",
    "blast_radius": "blast",
    "index_trust": "idx",
    "orphan": "orph",
    "alignment": "algn",
    "duplication": "dup",
}


def _color(score: int) -> str:
    if score >= 85:
        return _GREEN
    if score >= 60:
        return _YELLOW
    return _RED


def _use_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.getenv("CLEAN_FORCE_COLOR") == "1"


def render(state: dict | None, color: bool = True) -> str:
    if not state:
        return ""
    if state.get("skipped"):
        return ""

    def paint(text: str, c: str) -> str:
        return f"{c}{text}{_RESET}" if color else text

    overall = int(state.get("overall_score", 100))
    label = state.get("overall_label", "OK")
    prefix = "⚠ " if state.get("stale") else ""
    head = paint(f"🛡 {overall} {label}", _color(overall))

    parts = []
    for ind in state.get("indicators", []):
        if ind.get("skipped"):
            continue
        short = _SHORT.get(ind["key"], ind["key"])
        parts.append(paint(f"{short} {ind['score']}", _color(int(ind["score"]))))

    tail = paint(" · ".join(parts), _DIM) if not color else " · ".join(parts)
    body = f"{prefix}{head}"
    if parts:
        body += paint(" · ", _DIM) + tail if color else " · " + tail
    return body


def main() -> None:
    # Drain stdin (Claude Code sends session JSON) so the pipe doesn't block.
    if not sys.stdin.isatty():
        try:
            sys.stdin.read()
        except Exception:
            pass
    state = ScoringStateWriter().read()
    line = render(state, color=_use_color())
    if line:
        print(line)


if __name__ == "__main__":
    main()
