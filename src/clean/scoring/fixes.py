"""Self-healing fix inbox.

Detects a high-confidence hallucinated symbol (via the grounding indicator),
finds the nearest real symbol in the index with stdlib ``difflib`` (no model,
no API), and queues a ready-to-apply fix in a per-repo inbox the user reviews
with the ``clean-fixes`` CLI. Fully decoupled from the user's coding session.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable


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
