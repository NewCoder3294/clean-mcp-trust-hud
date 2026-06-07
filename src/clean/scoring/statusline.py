"""``clean-statusline`` console entry point.

Renders a two-line, charted, color-coded Trust-HUD for the Claude Code
statusline from ~/.clean/scoring.json:

    repo cleanmcp/clean-mcp   branch feat/trust-hud   TRUST ◕ ███████████░░░ 82/100 OK
       Real calls ████████░░  80    Impact ██████████ 100    Used ████░░░░░░  40

- a circle gauge (○◔◑◕●) plus a 14-cell bar for the overall trust score
- a 10-cell bar chart per metric, bright green/amber/red by health
- full, plain-English metric names (run `clean-statusline legend` for meanings)
- repo + branch derived from the SCORED file (so the label matches the numbers)
- index freshness shown as a "stale" tag, not its own bar
- no emojis — plain colored text plus unicode chart glyphs only

Claude Code passes a session JSON object on stdin; we use it for the cwd.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import NamedTuple

from .state import ScoringStateWriter

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
# Bright (high-intensity) ANSI colors for a more vivid HUD.
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_BLUE = "\033[94m"
_WHITE = "\033[97m"

# Plain-English label + one-line meaning for each indicator.
_LABELS = {
    "grounding": "Real calls",
    "blast_radius": "Impact",
    "orphan": "Used",
    "index_trust": "Index",
    "alignment": "Style",
    "duplication": "Unique",
}
_MEANING = {
    "grounding": "Are the called functions/APIs real? (catches hallucinated calls)",
    "blast_radius": "How many existing callers this change affects (lower = riskier)",
    "orphan": "Is the new code referenced anywhere? (low = dead-on-arrival)",
    "index_trust": "How fresh the code index is — i.e. how much to trust these scores",
    "alignment": "How well the code matches your existing patterns",
    "duplication": "Is this new, or a near-duplicate of existing code?",
}

# Which metrics to SHOW on the bar line, in order. index_trust is intentionally
# omitted — its signal is already the "stale" tag on the overall line.
_DISPLAY_ORDER = ["grounding", "blast_radius", "orphan", "alignment", "duplication"]

_CIRCLES = "○◔◑◕●"
_METRIC_SEP = "    "
_GROUP_SEP = "      "

_REPO_RE = re.compile(r"[:/]([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?$")


class GitContext(NamedTuple):
    repo: str | None  # "owner/repo"
    branch: str | None
    project_id: str | None  # matches CodebaseIndexer._project_id(root)


def _color(score: int) -> str:
    if score >= 85:
        return _GREEN
    if score >= 60:
        return _YELLOW
    return _RED


def _bar(score: int, cells: int = 10) -> str:
    filled = max(0, min(cells, round(score / 100 * cells)))
    return "█" * filled + "░" * (cells - filled)


def _circle(score: int) -> str:
    return _CIRCLES[max(0, min(len(_CIRCLES) - 1, round(score / 25)))]


def _use_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.getenv("CLEAN_FORCE_COLOR") == "1"


# --- git context -------------------------------------------------------------


def _git(args: list[str], cwd: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=2
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except Exception:
        pass
    return None


def git_context(cwd: str) -> GitContext:
    """Derive (owner/repo, branch, project_id) for the repo containing *cwd*."""
    root = _git(["rev-parse", "--show-toplevel"], cwd)
    if root is None:
        return GitContext(None, None, None)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if branch == "HEAD":  # detached
        branch = _git(["rev-parse", "--short", "HEAD"], cwd)
    url = _git(["remote", "get-url", "origin"], cwd)
    repo = None
    if url:
        m = _REPO_RE.search(url)
        repo = m.group(1) if m else None
    if repo is None:
        repo = os.path.basename(root)
    project_id = os.path.basename(root).lower().replace(" ", "_")
    return GitContext(repo, branch, project_id)


# --- rendering ---------------------------------------------------------------


def _paint(text: str, c: str, color: bool) -> str:
    return f"{c}{text}{_RESET}" if color else text


def _git_line(git: GitContext, color: bool) -> str:
    parts = []
    if git.repo:
        parts.append(
            _paint("repo ", _DIM, color) + _paint(git.repo, _WHITE + _BOLD, color)
        )
    if git.branch:
        parts.append(
            _paint("branch ", _DIM, color) + _paint(git.branch, _CYAN + _BOLD, color)
        )
    return _GROUP_SEP.join(parts)


def _overall_chunk(state: dict, color: bool) -> str:
    overall = int(state.get("overall_score", 100))
    label = state.get("overall_label", "OK")
    prefix = (
        _paint("● stale", _YELLOW + _BOLD, color) + "  " if state.get("stale") else ""
    )
    circle = _paint(_circle(overall), _color(overall) + _BOLD, color)
    bar = _paint(_bar(overall, cells=14), _color(overall), color)
    text = _paint(f"{overall}/100 {label}", _color(overall) + _BOLD, color)
    return f"{prefix}{_paint('TRUST', _BOLD + _WHITE, color)} {circle} {bar} {text}"


def _metrics_line(state: dict, color: bool) -> str:
    by_key = {i["key"]: i for i in state.get("indicators", [])}
    chunks = []
    for key in _DISPLAY_ORDER:
        ind = by_key.get(key)
        if ind is None or ind.get("skipped"):
            continue
        name = _LABELS.get(key, key)
        s = int(ind["score"])
        c = _color(s)
        chunks.append(
            f"{_paint(name, c + _BOLD, color)} "
            f"{_paint(_bar(s), c, color)} "
            f"{_paint(f'{s:>3}', c + _BOLD, color)}"
        )
    if not chunks:
        return ""
    return "   " + _paint(_METRIC_SEP, _DIM, color).join(chunks)


def render(
    state: dict | None, git: GitContext | None = None, color: bool = True
) -> str:
    """Return the (possibly two-line) statusline string."""
    state = state or {}
    have_git = git is not None and (git.repo or git.branch)

    # Score availability / special cases.
    score_chunk = ""
    metrics = ""
    if state and not state.get("skipped"):
        mismatch = (
            git is not None
            and git.project_id
            and state.get("project_id")
            and state["project_id"] != git.project_id
        )
        if mismatch:
            score_chunk = _paint("no recent score for this repo", _DIM, color)
        elif not state.get("indexed", True):
            repo = (git.repo if git else None) or state.get("project_id") or "this repo"
            score_chunk = _paint(f"not indexed — run: index {repo}", _DIM, color)
        else:
            score_chunk = _overall_chunk(state, color)
            metrics = _metrics_line(state, color)

    line1_parts = []
    if have_git:
        line1_parts.append(_git_line(git, color))
    if score_chunk:
        line1_parts.append(score_chunk)
    line1 = _GROUP_SEP.join(line1_parts)

    return line1 + ("\n" + metrics if metrics else "")


def legend() -> str:
    """Human-readable explanation of each metric (for `clean-statusline legend`)."""
    lines = ["Trust-HUD metrics — overall TRUST is a 0-100 weighted blend:", ""]
    for key in _DISPLAY_ORDER:
        lines.append(f"  {_LABELS[key]:<11} {_MEANING[key]}")
    lines += [
        "",
        f"  ({_LABELS['index_trust']}: {_MEANING['index_trust']} — shown as the",
        "   'stale' tag rather than its own bar.)",
        "",
        "  Bars/circle: green >=85 OK · amber 60-84 REVIEW · red <60 RISK.",
        "  Style/Unique appear only when the warm daemon runs (clean-score serve).",
    ]
    return "\n".join(lines)


def _cwd_from_stdin() -> str:
    if not sys.stdin.isatty():
        try:
            data = json.loads(sys.stdin.read() or "{}")
            ws = data.get("workspace") or {}
            return ws.get("current_dir") or data.get("cwd") or os.getcwd()
        except Exception:
            pass
    return os.getcwd()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "legend":
        print(legend())
        return
    cwd = _cwd_from_stdin()
    state = ScoringStateWriter().read()
    # Tie the repo/branch to the file that was actually scored, so the label
    # always matches the numbers shown. Fall back to the shell cwd.
    anchor = cwd
    if state and state.get("file_path"):
        anchor = os.path.dirname(state["file_path"]) or cwd
    git = git_context(anchor)
    line = render(state, git, color=_use_color())
    if line:
        print(line)


if __name__ == "__main__":
    main()
