"""Tests for the index-trust (file-level) indicator."""

from clean.scoring.indicators.index_trust import IndexTrustIndicator

from helpers import make_ctx, make_entity


def test_fresh_index_full_score():
    ctx = make_ctx([make_entity("a")], indexed=True, stale=False)
    assert IndexTrustIndicator().score(None, ctx).score == 100


def test_stale_index_low_score():
    ctx = make_ctx([make_entity("a")], indexed=True, stale=True)
    assert IndexTrustIndicator().score(None, ctx).score == 40


def test_unindexed_zero_score():
    ctx = make_ctx([make_entity("a")], indexed=False)
    result = IndexTrustIndicator().score(None, ctx)
    assert result.score == 0


def test_is_file_level():
    assert IndexTrustIndicator.file_level is True
