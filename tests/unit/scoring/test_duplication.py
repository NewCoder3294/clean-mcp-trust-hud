"""Tests for the duplication indicator (embedding-based)."""

from clean.core.models import SearchResult
from clean.scoring.indicators.duplication import DuplicationIndicator

from helpers import FakeEmbedder, FakeStore, make_ctx, make_entity


def test_near_duplicate_is_flagged():
    edited = make_entity("target", file_path="/tmp/proj/a.py")
    existing = make_entity("doSameThing", file_path="/tmp/proj/b.py")
    store = FakeStore([], search_results=[SearchResult(existing, 0.95)], count=5)
    ctx = make_ctx([edited], store=store, embedder=FakeEmbedder())

    result = DuplicationIndicator().score(edited, ctx)

    assert result.score == 5  # round(100 * (1 - 0.95))
    assert {o.name for o in result.offenders} == {"doSameThing"}


def test_below_threshold_is_full_score():
    edited = make_entity("target", file_path="/tmp/proj/a.py")
    existing = make_entity("vaguely_similar", file_path="/tmp/proj/b.py")
    store = FakeStore([], search_results=[SearchResult(existing, 0.5)], count=5)
    ctx = make_ctx([edited], store=store, embedder=FakeEmbedder())
    assert DuplicationIndicator().score(edited, ctx).score == 100


def test_self_match_is_excluded():
    edited = make_entity("target", file_path="/tmp/proj/a.py")
    itself = make_entity("target", file_path="/tmp/proj/a.py")  # same name + file
    store = FakeStore([], search_results=[SearchResult(itself, 0.99)], count=5)
    ctx = make_ctx([edited], store=store, embedder=FakeEmbedder())
    result = DuplicationIndicator().score(edited, ctx)
    assert result.skipped is True  # only self in results -> nothing to compare
