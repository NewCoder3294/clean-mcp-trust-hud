"""``clean-score`` console entry point.

Usage:
  clean-score serve     # run the persistent scoring daemon
  clean-score hook      # score the file from a Claude Code PostToolUse payload
  clean-score <path>    # score a path directly (manual / testing)

The hook reads the PostToolUse JSON payload on stdin, scores the edited file,
and writes ~/.clean/scoring.json. It prefers a running daemon (so embedding
indicators run warm); if none is up it falls back to the fast, no-model
indicators inline. It always exits 0 so it can never block the agent.
"""

from __future__ import annotations

import json
import sys

from ..services.container import ServiceContainer
from .daemon import request_score, serve
from .fixes import propose_fixes
from .state import ScoringStateWriter, write_repo_score


def _extract_file_path(payload: dict) -> tuple[str | None, str | None]:
    """Pull (file_path, cwd) out of a Claude Code PostToolUse payload."""
    cwd = payload.get("cwd")
    tool_input = payload.get("tool_input") or {}
    fp = tool_input.get("file_path") or tool_input.get("path")
    return fp, cwd


def _score_inline(file_path: str, cwd: str | None) -> None:
    """Fallback: score without the daemon (no model load, fast indicators)."""
    container = ServiceContainer()
    score = container.scoring.score_file(file_path, with_embeddings=False)
    ScoringStateWriter().write(score)
    write_repo_score(score)
    propose_fixes(score, container.store)


def run_hook(stdin_text: str) -> int:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    file_path, cwd = _extract_file_path(payload)
    if not file_path:
        return 0
    try:
        result = request_score(file_path, cwd=cwd)
        if result is None or result.get("error"):
            _score_inline(file_path, cwd)
    except Exception:
        # Never surface errors to the agent.
        pass
    return 0


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "serve":
        serve()
        return
    if argv and argv[0] not in ("hook",):
        # Treat a bare argument as a path to score directly.
        container = ServiceContainer()
        score = container.scoring.score_file(argv[0], with_embeddings=True)
        ScoringStateWriter().write(score)
        write_repo_score(score)
        propose_fixes(score, container.store)
        print(
            json.dumps(
                {"overall_score": score.overall_score, "label": score.overall_label}
            )
        )
        return
    # Default: hook mode.
    stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
    sys.exit(run_hook(stdin_text))


if __name__ == "__main__":
    main()
