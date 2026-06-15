"""Self-healing fix inbox.

Detects a high-confidence hallucinated symbol (via the grounding indicator),
finds the nearest real symbol in the index with stdlib ``difflib`` (no model,
no API), and queues a ready-to-apply fix in a per-repo inbox the user reviews
with the ``clean-fixes`` CLI. Fully decoupled from the user's coding session.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


FIX_INBOX_DIR = Path.home() / ".clean" / "fixes"


@dataclass
class FixSuggestion:
    """One queued fix: swap a hallucinated symbol for a real one."""

    id: str
    file_path: str
    line: int | None
    bad_symbol: str
    candidates: list[str]
    created_at: str


def _fix_id(file_path: str, bad_symbol: str) -> str:
    """Stable short id so the same hallucination is not queued twice."""
    return hashlib.sha1(
        f"{file_path}::{bad_symbol}".encode(), usedforsecurity=False
    ).hexdigest()[:8]


def _inbox_path(project_id: str, base: Path = FIX_INBOX_DIR) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", project_id) or "_"
    return base / f"{safe}.json"


def read_fixes(project_id: str, base: Path = FIX_INBOX_DIR) -> list[dict]:
    """Pending fixes for a repo, or [] if absent/unreadable."""
    if not project_id:
        return []
    path = _inbox_path(project_id, base)
    try:
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_fixes(project_id: str, entries: list[dict], base: Path = FIX_INBOX_DIR) -> None:
    """Replace a repo's inbox. Best-effort; never raises."""
    if not project_id:
        return
    try:
        base.mkdir(parents=True, exist_ok=True)
        with open(_inbox_path(project_id, base), "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
    except Exception:
        pass


def suggest_candidates(
    bad_symbol: str, names: Iterable[str], n: int = 3, cutoff: float = 0.6
) -> list[str]:
    """Up to *n* real symbol names closest to *bad_symbol* (final segment).

    Matching is done on the final dotted segment (so ``self._procss`` matches an
    indexed ``Worker._process`` and yields ``_process``). Below *cutoff* nothing
    is returned — a low-similarity guess is worse than silence.

    Candidates are final segments (the bare token to substitute), deduplicated:
    ``A._process`` and ``B._process`` both yield ``_process`` once. This is by
    design — the apply step swaps the bad bare token for a candidate segment, so
    the fully-qualified name is never needed.
    """
    seg = bad_symbol.split(".")[-1]
    segs = sorted({nm.split(".")[-1] for nm in names if nm})
    return difflib.get_close_matches(seg, segs, n=n, cutoff=cutoff)
