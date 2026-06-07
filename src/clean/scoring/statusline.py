"""``clean-statusline`` console entry point.

Renders a two-line, charted, color-coded Trust-HUD for the Claude Code
statusline from ~/.clean/scoring.json:

    repo cleanmcp/clean-mcp   branch feat/trust-hud   Trust ◕ 82/100 OK
       Real calls ████░ 80 · Impact █████ 100 · Used ██░░░ 40 · Index ██░░░ 40

- a circle gauge (○◔◑◕●) for the overall trust score
- a 5-cell bar chart per metric, green/amber/red by health
- full, plain-English metric names (run `clean-statusline legend` for meanings)
- the current GitHub repo (owner/repo) and branch, derived from cwd
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
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"

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

_BARS = "▁▂▃▄▅▆▇█"
_CIRCLES = "○◔◑◕●"
_METRIC_SEP = " · "
_GROUP_SEP = "   "

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


def _bar(score: int, cells: int = 5) -> str:
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
        parts.append(_paint("repo ", _DIM, color) + _paint(git.repo, _BOLD, color))
    if git.branch:
        parts.append(
            _paint("branch ", _DIM, color) + _paint(git.branch, _CYAN + _BOLD, color)
        )
    return _GROUP_SEP.join(parts)


def _overall_chunk(state: dict, color: bool) -> str:
    overall = int(state.get("overall_score", 100))
    label = state.get("overall_label", "OK")
    prefix = _paint("stale ", _YELLOW, color) if state.get("stale") else ""
    circle = _paint(_circle(overall), _color(overall), color)
    text = _paint(f"{overall}/100 {label}", _color(overall) + _BOLD, color)
    return f"{prefix}{_paint('Trust', _BOLD, color)} {circle} {text}"


def _metrics_line(state: dict, color: bool) -> str:
    chunks = []
    for ind in state.get("indicators", []):
        if ind.get("skipped"):
            continue
        name = _LABELS.get(ind["key"], ind["key"])
        s = int(ind["score"])
        chunks.append(
            f"{_paint(name, _BOLD, color)} "
            f"{_paint(_bar(s), _color(s), color)} "
            f"{_paint(str(s), _color(s), color)}"
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
    lines = ["Trust-HUD metrics — overall 'Trust' is a 0-100 weighted blend:", ""]
    for key, name in _LABELS.items():
        lines.append(f"  {name:<11} {_MEANING[key]}")
    lines += [
        "",
        "  Bars/circle: green >=85 OK · amber 60-84 REVIEW · red <60 RISK.",
        "  'stale' = code index is behind the working tree (re-index for accuracy).",
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
    git = git_context(cwd)
    state = ScoringStateWriter().read()
    line = render(state, git, color=_use_color())
    if line:
        print(line)


if __name__ == "__main__":
    main()
