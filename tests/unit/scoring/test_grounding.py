"""Tests for the grounding (anti-hallucination) indicator."""

from clean.scoring.indicators.grounding import GroundingIndicator

from helpers import FakeStore, make_ctx, make_entity


def test_mixed_calls_scores_unresolved_fraction():
    # helper + run are local; len/os.path.join are acceptable; frobnicate is invented.
    target = make_entity(
        "target",
        calls=("len", "helper", "frobnicate", "os.path.join", "self.run"),
    )
    helper = make_entity("helper")
    run = make_entity("run")
    ctx = make_ctx([target, helper, run], store=FakeStore([helper, run]))

    result = GroundingIndicator().score(target, ctx)

    # checkable = helper, frobnicate, self.run -> 1 of 3 unresolved.
    assert result.score == 67
    assert {o.name for o in result.offenders} == {"frobnicate"}


def test_resolved_via_index_scores_full():
    target = make_entity("target", calls=("frobnicate",))
    indexed = make_entity("frobnicate")
    ctx = make_ctx([target], store=FakeStore([indexed]))

    result = GroundingIndicator().score(target, ctx)

    assert result.score == 100
    assert result.offenders == ()


def test_no_checkable_calls_is_full_score():
    target = make_entity("target", calls=("len", "os.path.join"))
    ctx = make_ctx([target], store=FakeStore([]))
    assert GroundingIndicator().score(target, ctx).score == 100


def test_unindexed_project_is_skipped():
    target = make_entity("target", calls=("frobnicate",))
    ctx = make_ctx([target], indexed=False)
    result = GroundingIndicator().score(target, ctx)
    assert result.skipped is True
    assert result.confidence == 0.0


def test_stale_index_lowers_confidence():
    target = make_entity("target", calls=("helper",))
    helper = make_entity("helper")
    ctx = make_ctx([target, helper], store=FakeStore([helper]), stale=True)
    result = GroundingIndicator().score(target, ctx)
    assert result.confidence == 0.7
