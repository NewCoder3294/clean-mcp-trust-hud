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
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
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


def _candidate_names(store, project_id: str, bad_symbol: str, per_token_limit: int = 100) -> list[str]:
    """Indexed names sharing a >=3-char token with the bad symbol's final segment."""
    seg = bad_symbol.split(".")[-1]
    tokens = [t for t in re.split(r"[._]|(?<=[a-z])(?=[A-Z])", seg) if len(t) >= 3] or [seg]
    names: list[str] = []
    for tok in tokens:
        try:
            names.extend(e.name for e in store.get_by_name_substring(project_id, tok, limit=per_token_limit))
        except Exception:
            continue
    return names


def apply_fix(entry: dict, pick: int = 0) -> str:
    """Apply a queued fix. Returns 'applied', 'stale', or 'error'.

    Safe contract: replace the bad symbol only if it occurs **exactly once** in
    the file as a whole identifier token. Zero or multiple occurrences -> 'stale'
    (never guess which one). The file is left untouched unless exactly one match.
    """
    candidates = entry.get("candidates") or []
    if not isinstance(pick, int) or pick < 0 or pick >= len(candidates):
        return "error"
    replacement = candidates[pick]
    bad = entry.get("bad_symbol") or ""
    path = entry.get("file_path") or ""
    if not bad:
        return "error"
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
    except OSError:
        return "stale"
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(bad)}(?![A-Za-z0-9_])")
    if len(pattern.findall(src)) != 1:
        return "stale"
    new_src = pattern.sub(replacement, src)  # guard above ensures exactly one match
    # Atomic write: write a sibling temp file, preserve mode, then os.replace
    # (atomic on POSIX) — so a crash mid-write can never corrupt the source file.
    target = Path(path)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".clean-fix.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new_src)
            os.chmod(tmp, os.stat(path).st_mode & 0o777)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError:
        return "error"
    return "applied"


def propose_fixes(score, store, base: Path = FIX_INBOX_DIR) -> None:
    """Queue fixes for high-confidence hallucinated symbols. Best-effort; never raises.

    Trigger: the score is real (not skipped, project indexed) and the grounding
    indicator is fresh (confidence == 1.0) with offenders. For each offender with
    a near-match real symbol, write an inbox entry. Re-running for a file replaces
    that file's entries, so resolved hallucinations are pruned.
    """
    try:
        if score.skipped or not score.indexed or not score.project_id:
            return
        grounding = next((i for i in score.indicators if i.key == "grounding"), None)
        if grounding is None or grounding.confidence < 1.0:
            return
        new_entries: list[dict] = []
        for off in grounding.offenders:
            cands = suggest_candidates(off.name, _candidate_names(store, score.project_id, off.name))
            if not cands:
                continue
            seg = off.name.split(".")[-1]
            new_entries.append(
                asdict(
                    FixSuggestion(
                        id=_fix_id(score.file_path, off.name),
                        file_path=score.file_path,
                        line=off.line,
                        bad_symbol=seg,
                        candidates=cands,
                        created_at=datetime.now().isoformat(),
                    )
                )
            )
        kept = [e for e in read_fixes(score.project_id, base) if e.get("file_path") != score.file_path]
        write_fixes(score.project_id, kept + new_entries, base)
    except Exception:
        pass
