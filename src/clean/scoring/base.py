"""Core types for the trust-HUD scoring layer.

An *indicator* inspects a freshly-parsed ``CodeEntity`` (or, when
``file_level`` is set, the whole file once) against the indexed codebase and
returns a normalized 0-100 score where **100 means safest/best**. The
``ScoringService`` runs the enabled indicators and aggregates their results
into a ``FileScore`` that the terminal HUD renders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..core.models import CodeEntity
from ..core.protocols import Embedder, VectorStore


@dataclass(frozen=True, slots=True)
class Offender:
    """A single thing an indicator flagged (a risky/unresolved symbol)."""

    name: str
    detail: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class IndicatorResult:
    """The outcome of running one indicator over one file."""

    key: str
    label: str
    score: int  # 0-100, 100 == safest/best
    summary: str
    offenders: tuple[Offender, ...] = ()
    weight: float = 1.0
    skipped: bool = False  # not enough data (e.g. project not indexed)
    confidence: float = 1.0  # lowered against a stale/missing index


@dataclass
class ScoringContext:
    """Everything an indicator may need; built once per file by the service.

    The ``lookup_names`` and ``embed`` helpers memoize their results so that
    several indicators scoring the same file share a single DB round-trip and
    a single embedding per snippet.
    """

    project_id: str
    project_root: str
    file_path: str
    store: VectorStore
    embedder: Embedder | None
    config: object  # ScoringConfig (avoids a circular import at module load)
    edited_entities: tuple[CodeEntity, ...]
    same_file_names: frozenset[str]
    stale: bool = False
    indexed: bool = True  # does the project have an index to resolve against?
    _name_cache: dict[str, list[CodeEntity]] = field(default_factory=dict)
    _embed_cache: dict[str, list[float]] = field(default_factory=dict)
    _method_cache: dict[str, bool] = field(default_factory=dict)

    def lookup_names(self, names: list[str]) -> dict[str, list[CodeEntity]]:
        """Batched, memoized ``get_by_names`` keyed by entity name."""
        missing = [n for n in names if n not in self._name_cache]
        if missing:
            found: dict[str, list[CodeEntity]] = {n: [] for n in missing}
            for entity in self.store.get_by_names(self.project_id, missing):
                found.setdefault(entity.name, []).append(entity)
            # Cache every requested name, including those with no matches, so
            # repeat lookups never hit the store again.
            self._name_cache.update(found)
        return {n: self._name_cache.get(n, []) for n in names}

    def embed(self, code: str) -> list[float] | None:
        """Memoized single-snippet embedding; ``None`` if no embedder."""
        if self.embedder is None:
            return None
        if code not in self._embed_cache:
            self._embed_cache[code] = self.embedder.embed_query(code)
        return self._embed_cache[code]

    def resolve_method_segment(self, segment: str) -> bool:
        """True if any indexed entity is named ``segment`` or ``...<X>.segment``.

        Methods are stored as ``Class.method``, so an exact-name lookup misses
        them. This does a lenient substring scan (precision-first: we would
        rather treat a method as resolved than wrongly flag it).
        """
        if segment not in self._method_cache:
            try:
                matches = self.store.get_by_name_substring(
                    self.project_id, segment, limit=50
                )
            except Exception:
                matches = []
            self._method_cache[segment] = any(
                m.name == segment or m.name.endswith("." + segment) for m in matches
            )
        return self._method_cache[segment]


@dataclass
class FileScore:
    """Aggregated scores for one scored file."""

    project_id: str
    file_path: str
    overall_score: int
    overall_label: str
    indicators: list[IndicatorResult]
    entity_count: int
    stale: bool
    skipped: bool = False


class Indicator(ABC):
    """Base class for all indicators.

    Subclasses set the class attributes and implement ``score``. File-level
    indicators (``file_level = True``) are invoked once per file with
    ``entity=None``; entity-level indicators are invoked once per edited entity.
    """

    key: str = ""
    label: str = ""
    requires_embedding: bool = False
    file_level: bool = False

    @abstractmethod
    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        """Return the indicator result for ``entity`` (or the file)."""
        ...
