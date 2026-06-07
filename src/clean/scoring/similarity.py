"""Helpers shared by the embedding-based indicators (alignment, duplication)."""

from __future__ import annotations

import math
import os

from ..core.models import CodeEntity


def is_self_match(stored: CodeEntity, target: CodeEntity) -> bool:
    """True if ``stored`` is (a chunk of) the entity we are scoring.

    Used to exclude the entity's own indexed copy from neighbor searches.
    """
    if stored.id == target.id:
        return True
    if stored.parent_id and stored.parent_id == target.parent_id:
        return True
    same_file = os.path.basename(stored.file_path) == os.path.basename(target.file_path)
    return stored.name == target.name and same_file


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 on degenerate input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
