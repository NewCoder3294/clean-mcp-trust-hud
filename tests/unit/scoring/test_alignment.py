"""Tests for the alignment/drift indicator (embedding-based)."""

from clean.core.models import SearchResult
from clean.scoring.indicators.alignment import AlignmentIndicator

from helpers import FakeEmbedder, FakeStore, make_ctx, make_entity


def test_rewrite_of_existing_symbol_flags_drift():
    prior = make_entity("target", line_start=1, embedding=[1.0, 0.0, 0.0])
    edited = make_entity("target", line_start=5)  # different id -> not self
    ctx = make_ctx(
        [edited],
        store=FakeStore([prior]),
        embedder=FakeEmbedder([0.0, 1.0, 0.0]),  # orthogonal -> max drift
    )
    result = AlignmentIndicator().score(edited, ctx)
    assert result.score == 0
    assert "rewritten" in result.summary
    assert {o.name for o in result.offenders} == {"target"}


def test_consistent_edit_scores_high():
    prior = make_entity("target", line_start=1, embedding=[1.0, 0.0, 0.0])
    edited = make_entity("target", line_start=5)
    ctx = make_ctx(
        [edited], store=FakeStore([prior]), embedder=FakeEmbedder([1.0, 0.0, 0.0])
    )
    result = AlignmentIndicator().score(edited, ctx)
    assert result.score == 100
    assert "consistent" in result.summary


def test_new_code_fitting_patterns_scores_high():
    edited = make_entity("fresh", line_start=1)
    neighbor = make_entity("other", file_path="/tmp/proj/other.py")
    store = FakeStore([], search_results=[SearchResult(neighbor, 0.8)], count=5)
    ctx = make_ctx([edited], store=store, embedder=FakeEmbedder())
    result = AlignmentIndicator().score(edited, ctx)
    assert result.score == 100
    assert "fits" in result.summary


def test_no_embedder_is_skipped():
    edited = make_entity("fresh")
    ctx = make_ctx([edited], store=FakeStore([], count=5), embedder=None)
    assert AlignmentIndicator().score(edited, ctx).skipped is True
