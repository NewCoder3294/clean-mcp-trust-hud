"""Shared fixtures/helpers for scoring unit tests (deterministic, no model)."""

from __future__ import annotations

from collections import defaultdict

from clean.core.config import ScoringConfig
from clean.core.models import CodeEntity, SearchResult
from clean.core.types import EntityKind, Language
from clean.scoring.base import ScoringContext


def make_entity(
    name: str,
    *,
    calls: tuple[str, ...] = (),
    called_by: tuple[str, ...] = (),
    kind: EntityKind = EntityKind.FUNCTION,
    decorators: tuple[str, ...] = (),
    exported: bool = False,
    class_name: str | None = None,
    file_path: str = "/tmp/proj/mod.py",
    line_start: int = 1,
    embedding: list[float] | None = None,
    language: Language = Language.PYTHON,
) -> CodeEntity:
    return CodeEntity(
        name=name,
        file_path=file_path,
        code=f"def {name}(): pass",
        line_start=line_start,
        line_end=line_start,
        language=language,
        kind=kind,
        calls=calls,
        called_by=called_by,
        class_name=class_name,
        exported=exported,
        decorators=decorators,
        embedding=embedding,
    )


class FakeStore:
    """Minimal VectorStore stand-in driven by in-memory entities."""

    def __init__(
        self,
        entities: list[CodeEntity] | None = None,
        search_results: list[SearchResult] | None = None,
        count: int | None = None,
    ) -> None:
        self._by_name: dict[str, list[CodeEntity]] = defaultdict(list)
        for e in entities or []:
            self._by_name[e.name].append(e)
        self._search_results = search_results or []
        self._count = len(entities or []) if count is None else count

    def count(self, project_id: str) -> int:
        return self._count

    def get_by_names(self, project_id, names):
        out: list[CodeEntity] = []
        for n in names:
            out.extend(self._by_name.get(n, []))
        return out

    def get_by_name(self, project_id, name, file_path=None):
        return list(self._by_name.get(name, []))

    def get_by_name_substring(self, project_id, pattern, limit=20):
        matches = [
            e for ents in self._by_name.values() for e in ents if pattern in e.name
        ]
        return matches[:limit]

    def search(self, project_id, embedding, top_k):
        return self._search_results[:top_k]

    def get_project_state(self, project_id):
        return None


class FakeEmbedder:
    dimension = 3

    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector or [1.0, 0.0, 0.0]

    def embed_query(self, text: str) -> list[float]:
        return list(self._vector)

    def embed_batch(self, texts):
        return [list(self._vector) for _ in texts]


def make_ctx(
    edited: list[CodeEntity],
    *,
    store: FakeStore | None = None,
    indexed: bool = True,
    stale: bool = False,
    embedder=None,
    config: ScoringConfig | None = None,
) -> ScoringContext:
    store = store if store is not None else FakeStore()
    return ScoringContext(
        project_id="proj",
        project_root="/tmp/proj",
        file_path="/tmp/proj/mod.py",
        store=store,
        embedder=embedder,
        config=config or ScoringConfig(),
        edited_entities=tuple(edited),
        same_file_names=frozenset(e.name for e in edited),
        stale=stale,
        indexed=indexed,
    )
