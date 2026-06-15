"""``clean-statusline`` console entry point.

Renders a btop-style, three-panel, color-coded HUD for the Claude Code
statusline. Rows 1-2 come from the Claude Code session payload on stdin; row 3
comes from ~/.clean/scoring.json:

    Opus 4.8   ctx ▕████████▒▒▒▒▏ 58%   ⏵ Wiring the HUD
    repo cleanmcp/clean-mcp      branch feat/trust-hud
    TRUST ◕ ███████████░░░ 82/100 OK │ Real calls ████████░░ 80 · Impact █████ 100

Three stacked panels (empty rows are dropped):
  row 1 — system control: model · btop-style context meter · current task
  row 2 — git control: repo + branch
  row 3 — clean-mcp: overall TRUST gauge + per-metric bars

- a circle gauge (○◔◑◕●) plus a 14-cell bar for the overall trust score
- a 10-cell bar chart per metric, bright green/amber/red by health
- a smooth sub-cell context meter (green→amber→orange→red, 💀 when critical)
- full, plain-English metric names (run `clean-statusline legend` for meanings)
- repo + branch derived from the SCORED file (so the label matches the numbers)
- index freshness shown as a "stale" tag, not its own bar

Claude Code passes a session JSON object on stdin; we read the cwd, model,
context window, and session id from it.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from typing import NamedTuple

from ..mcp.shared import resolve_local_project_id
from .fixes import read_fixes
from .state import ScoringStateWriter, read_repo_score

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
_ORANGE = "\033[38;5;208m"  # 256-color orange for the context meter's warning band

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
_METRIC_SEP = " · "  # between metric chunks on the clean-mcp row
_GROUP_SEP = "   "  # between repo and branch on the git row
_DIVIDER = " │ "  # between the TRUST headline and the metric details

# System row (row 1): btop-style smooth context meter + model + current task.
_METER_BLOCKS = "▏▎▍▌▋▊▉█"  # 1..8 eighths, for sub-cell-precise fills
_METER_L = "▕"  # meter left border
_METER_R = "▏"  # meter right border
_METER_TRACK = "▒"  # unfilled portion of the meter
_SYS_SEP = "   "  # between segments on the system row
_TASK_GLYPH = "⏵"  # marks the current task
_AUTO_COMPACT_BUFFER_PCT = 16.5  # Claude Code's default autocompact reserve

_REPO_RE = re.compile(r"[:/]([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?$")


class GitContext(NamedTuple):
    repo: str | None  # "owner/repo"
    branch: str | None
    project_id: str | None  # matches index_repo via resolve_local_project_id(root)


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
    # Claude Code captures the statusline over a pipe (not a TTY) but DOES render
    # ANSI color — so emit color by default; only honor an explicit NO_COLOR.
    return os.getenv("NO_COLOR") is None


# --- system context (row 1: model · context meter · current task) ------------


class SystemContext(NamedTuple):
    model: str | None  # e.g. "Opus 4.8"
    ctx_used: int | None  # 0-100 percent of *usable* context consumed
    task: str | None  # the in-progress todo's active form, if any


def _ctx_used_pct(cw: dict) -> int | None:
    """Percent of *usable* context consumed, mirroring the GSD statusline.

    Claude Code reserves a slice of the window for autocompact (≈16.5% by
    default, overridable via ``CLAUDE_CODE_AUTO_COMPACT_WINDOW`` as a token
    count). We scale ``remaining_percentage`` to the usable range so the meter
    reads 100% exactly when autocompact is about to fire.
    """
    remaining = cw.get("remaining_percentage")
    if remaining is None:
        return None
    total = cw.get("total_tokens") or 1_000_000
    try:
        acw = int(os.getenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "0") or 0)
    except ValueError:
        acw = 0
    buffer_pct = min(100.0, acw / total * 100) if acw > 0 else _AUTO_COMPACT_BUFFER_PCT
    usable_remaining = max(0.0, ((remaining - buffer_pct) / (100 - buffer_pct)) * 100)
    return max(0, min(100, round(100 - usable_remaining)))


def _current_task(session: str | None) -> str | None:
    """The active in-progress todo for *session*, read from the todos dir.

    Generic to Claude Code — no GSD coupling. Returns ``None`` on any miss.
    """
    if not session or re.search(r"[/\\]|\.\.", session):
        return None
    config_dir = os.getenv("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude"
    )
    todos_dir = os.path.join(config_dir, "todos")
    try:
        files = [
            f
            for f in os.listdir(todos_dir)
            if f.startswith(session) and "-agent-" in f and f.endswith(".json")
        ]
    except OSError:
        return None
    if not files:
        return None
    files.sort(key=lambda f: os.path.getmtime(os.path.join(todos_dir, f)), reverse=True)
    try:
        with open(os.path.join(todos_dir, files[0]), encoding="utf-8") as fh:
            todos = json.load(fh)
    except (OSError, ValueError):
        return None
    for t in todos if isinstance(todos, list) else []:
        if isinstance(t, dict) and t.get("status") == "in_progress":
            return t.get("activeForm") or t.get("content") or None
    return None


def system_context(data: dict) -> SystemContext:
    """Derive the row-1 system segments from the Claude Code statusline payload."""
    model = (data.get("model") or {}).get("display_name")
    ctx_used = _ctx_used_pct(data.get("context_window") or {})
    task = _current_task(data.get("session_id"))
    return SystemContext(model=model, ctx_used=ctx_used, task=task)


def _ctx_color(used: int) -> str:
    if used < 50:
        return _GREEN
    if used < 65:
        return _YELLOW
    if used < 80:
        return _ORANGE
    return _RED


def _ctx_meter(used: int, color: bool, cells: int = 12) -> str:
    """A btop-style smooth context meter: ``ctx ▕████████▒▒▒▒▏ 58%``."""
    used = max(0, min(100, used))
    eighths = round(used / 100 * cells * 8)
    full, rem = divmod(eighths, 8)
    fill = "█" * full + (_METER_BLOCKS[rem - 1] if rem else "")
    track = _METER_TRACK * (cells - len(fill))
    c = _ctx_color(used)
    skull = "💀 " if used >= 80 else ""
    body = _paint(fill, c, color) + _paint(track, _DIM, color)
    return (
        f"{_paint('ctx', _DIM, color)} {skull}"
        f"{_paint(_METER_L, _DIM, color)}{body}{_paint(_METER_R, _DIM, color)} "
        f"{_paint(f'{used}%', c + _BOLD, color)}"
    )


def _system_line(system: SystemContext, color: bool) -> str:
    parts = []
    if system.model:
        parts.append(_paint(system.model, _WHITE + _BOLD, color))
    if system.ctx_used is not None:
        parts.append(_ctx_meter(system.ctx_used, color))
    if system.task:
        task = system.task if len(system.task) <= 48 else system.task[:47] + "…"
        parts.append(
            _paint(f"{_TASK_GLYPH} ", _DIM, color) + _paint(task, _BLUE + _BOLD, color)
        )
    return _SYS_SEP.join(parts)


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
    # Resolve the project_id the same way index_repo / the scoring service do,
    # so the mismatch check below compares like with like. Using the bare
    # basename here silently failed to match git-backed indexes and showed
    # "no recent score for this repo" even when a fresh score existed.
    project_id = resolve_local_project_id(root)
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


_METRIC_PHRASE = {
    "blast_radius": "high blast radius",
    "orphan": "low reuse",
    "alignment": "off-pattern",
    "duplication": "near-duplicate",
}


# Pure helper; wired into row 3 by build_clean_row / render in a later task.
def _select_reason(state: dict) -> str:
    """The ` · …` suffix for row 3. Grounding offenders win; else the weakest
    displayed metric as a plain phrase; else empty when everything is healthy."""
    by_key = {i["key"]: i for i in state.get("indicators", [])}
    g = by_key.get("grounding")
    if g and g.get("offenders"):
        names = [o["name"] for o in g["offenders"]]
        shown = ", ".join(names[:2])
        extra = f" +{len(names) - 2}" if len(names) > 2 else ""
        raw = state.get("overall_score")
        score = 100 if raw is None else int(raw)
        if score < 60:
            return f" · likely hallucinated: {shown}{extra}"
        n = len(names)
        return f" · check {n} call{'s' if n != 1 else ''}: {shown}{extra}"
    candidates = [
        (int(i["score"]), i["key"])
        for i in state.get("indicators", [])
        if i["key"] in _METRIC_PHRASE and not i.get("skipped")
    ]
    if candidates:
        worst_score, worst_key = min(candidates)
        if worst_score < 85:
            return f" · {_METRIC_PHRASE[worst_key]}"
    return ""


_LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".swift": "Swift",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".java": "Java",
    ".c": "C", ".cpp": "C++", ".cs": "C#", ".kt": "Kotlin",
}


def _lang_from_path(path: str | None) -> str | None:
    """Human language name from a file extension (best-effort)."""
    if not path:
        return None
    _, ext = os.path.splitext(path)
    if not ext:
        return None
    return _LANG_BY_EXT.get(ext.lower()) or ext.lstrip(".").upper()


def _project_indexed(project_id: str) -> bool:
    """True if the index metadata has a row for this project_id. Cheap, best-effort."""
    if not project_id:
        return False
    db = os.getenv("CLEAN_DB_PATH") or os.path.join(
        os.path.expanduser("~"), ".clean", "metadata.db"
    )
    try:
        con = sqlite3.connect(db, timeout=0.5)
        try:
            row = con.execute(
                "select 1 from projects where project_id=? limit 1", (project_id,)
            ).fetchone()
        finally:
            con.close()
        return row is not None
    except Exception:
        return False


def build_clean_row(
    repo_state: dict | None, recent: dict | None, git: GitContext | None, color: bool
) -> str:
    """Resolve and render row 3 (the clean-mcp layer) for the *current* repo."""
    if git is None or not (git.repo or git.branch):
        return ""  # not a git repo -> drop row 3

    if repo_state is not None and not repo_state.get("skipped"):
        score = int(repo_state.get("overall_score", 100))
        label = repo_state.get("overall_label", "OK")
        recent_pid = recent.get("project_id") if recent else None
        just_skipped_here = bool(
            recent and recent.get("skipped") and recent_pid and recent_pid == git.project_id
        )
        if just_skipped_here:
            lang = _lang_from_path(recent.get("file_path"))
            note = f" · {lang} not scored" if lang else ""
            dot = _paint("○", _DIM, color)
            body = _paint(f"{score} {label} · last good{note}", _DIM, color)
            return f"{dot} {body}"
        c = _color(score)
        dot = _paint("●", c + _BOLD, color)
        verdict = _paint(f"{label} {score}", c + _BOLD, color)
        reason = _select_reason(repo_state)
        fixes = read_fixes(git.project_id) if git.project_id else []
        fix_suffix = ""
        if fixes:
            n = len(fixes)
            fix_suffix = f" · {n} fix{'es' if n != 1 else ''} ready"
        return f"{dot} {verdict}{_paint(reason, _DIM, color)}{_paint(fix_suffix, _DIM, color)}"

    if repo_state is not None or _project_indexed(git.project_id):
        return _paint("clean · edit a Py/JS/TS file to score", _DIM, color)
    repo = git.repo or git.project_id or "this repo"
    return _paint(f"clean · not indexed — index {repo}", _DIM, color)


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
    return _paint(_METRIC_SEP, _DIM, color).join(chunks)


def render(
    repo_state: dict | None,
    recent: dict | None = None,
    git: GitContext | None = None,
    system: SystemContext | None = None,
    color: bool = True,
) -> str:
    """Assemble the stacked HUD: row 1 system, row 2 git, row 3 clean-mcp.

    ``repo_state`` is the current repo's last good score (or None). ``recent`` is
    the most-recent-event marker, used only to flag a just-skipped file. Empty
    rows are dropped.
    """
    rows = []
    if system is not None and (
        system.model or system.ctx_used is not None or system.task
    ):
        rows.append(_system_line(system, color))
    if git is not None and (git.repo or git.branch):
        rows.append(_git_line(git, color))
    clean_row = build_clean_row(repo_state, recent, git, color)
    if clean_row:
        rows.append(clean_row)
    return "\n".join(r for r in rows if r)


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


def _read_payload() -> dict:
    """Parse the Claude Code statusline JSON from stdin (best-effort)."""
    if not sys.stdin.isatty():
        try:
            return json.loads(sys.stdin.read() or "{}")
        except Exception:
            pass
    return {}


def _cwd_from_payload(data: dict) -> str:
    ws = data.get("workspace") or {}
    return ws.get("current_dir") or data.get("cwd") or os.getcwd()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "legend":
        print(legend())
        return
    payload = _read_payload()
    cwd = _cwd_from_payload(payload)
    git = git_context(cwd)  # follow me: anchor to where you are, not what you scored
    repo_state = read_repo_score(git.project_id) if git.project_id else None
    recent = ScoringStateWriter().read()
    system = system_context(payload)
    line = render(repo_state, recent, git, system, color=_use_color())
    if line:
        print(line)


if __name__ == "__main__":
    main()
