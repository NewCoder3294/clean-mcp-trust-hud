"""Persist the latest FileScore to ~/.clean/scoring.json for the statusline.

Mirrors ``stats/tracker.py`` — the stdio MCP server cannot push to a terminal,
so the score is written to a small JSON file that the statusline reads.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .base import FileScore

DEFAULT_SCORING_PATH = Path.home() / ".clean" / "scoring.json"
STATE_VERSION = 1


def file_score_to_dict(score: FileScore, updated_at: str | None = None) -> dict:
    """Serialize a FileScore into the on-disk state schema."""
    return {
        "version": STATE_VERSION,
        "updated_at": updated_at or datetime.now().isoformat(),
        "project_id": score.project_id,
        "file_path": score.file_path,
        "overall_score": score.overall_score,
        "overall_label": score.overall_label,
        "stale": score.stale,
        "indexed": score.indexed,
        "skipped": score.skipped,
        "entity_count": score.entity_count,
        "indicators": [
            {
                "key": ind.key,
                "label": ind.label,
                "score": ind.score,
                "summary": ind.summary,
                "skipped": ind.skipped,
                "confidence": round(ind.confidence, 2),
                "offenders": [
                    {"name": o.name, "detail": o.detail, "line": o.line}
                    for o in ind.offenders
                ],
            }
            for ind in score.indicators
        ],
    }


class ScoringStateWriter:
    """Reads/writes the scoring state file. All writes are best-effort."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_SCORING_PATH

    @property
    def path(self) -> Path:
        return self._path

    def write(self, score: FileScore, updated_at: str | None = None) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w") as fh:
                json.dump(file_score_to_dict(score, updated_at), fh, indent=2)
        except Exception:
            pass

    def read(self) -> dict | None:
        try:
            if not self._path.exists():
                return None
            with open(self._path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None


PER_REPO_DIR = Path.home() / ".clean" / "scoring"


def _repo_state_path(project_id: str, base: Path = PER_REPO_DIR) -> Path:
    """Filesystem-safe per-repo state path. project_ids are already dash-safe,
    but sanitize defensively so an exotic id can never escape ``base``."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", project_id) or "_"
    return base / f"{safe}.json"


def write_repo_score(
    score: FileScore, base: Path = PER_REPO_DIR, updated_at: str | None = None
) -> None:
    """Persist the last *good* (non-skipped) score for a repo, keyed by project_id.

    Skipped scores (unsupported language, no entities) are ignored so they can
    never clobber a repo's last good number. Best-effort; never raises.
    """
    if score.skipped or not score.project_id:
        return
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(_repo_state_path(score.project_id, base), "w") as fh:
            json.dump(file_score_to_dict(score, updated_at), fh, indent=2)
    except Exception:
        pass


def read_repo_score(project_id: str, base: Path = PER_REPO_DIR) -> dict | None:
    """Read a repo's last good score, or None if absent/unreadable."""
    if not project_id:
        return None
    path = _repo_state_path(project_id, base)
    try:
        if not path.exists():
            return None
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
