"""Tests for the blast-radius indicator."""

from clean.scoring.indicators.blast_radius import BlastRadiusIndicator

from helpers import FakeStore, make_ctx, make_entity


def test_more_callers_lowers_score():
    stored = make_entity("target", called_by=("a", "b", "c"))
    edited = make_entity("target")
    ctx = make_ctx([edited], store=FakeStore([stored]))

    result = BlastRadiusIndicator().score(edited, ctx)

    # 3 callers, warn=5 -> step 10 -> 100 - 30 = 70.
    assert result.score == 70
    assert {o.name for o in result.offenders} == {"a", "b", "c"}


def test_no_callers_is_full_score():
    stored = make_entity("target", called_by=())
    edited = make_entity("target")
    ctx = make_ctx([edited], store=FakeStore([stored]))
    assert BlastRadiusIndicator().score(edited, ctx).score == 100


def test_new_symbol_unknown_callers_reduced_confidence():
    edited = make_entity("brand_new")
    ctx = make_ctx([edited], store=FakeStore([]))  # not in index
    result = BlastRadiusIndicator().score(edited, ctx)
    assert result.score == 100
    assert result.confidence == 0.5


def test_unindexed_is_skipped():
    edited = make_entity("target")
    ctx = make_ctx([edited], indexed=False)
    assert BlastRadiusIndicator().score(edited, ctx).skipped is True
