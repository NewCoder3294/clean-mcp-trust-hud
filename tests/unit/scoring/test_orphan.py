"""Tests for the orphan-risk indicator."""

from clean.core.types import EntityKind
from clean.scoring.indicators.orphan import OrphanIndicator

from helpers import FakeStore, make_ctx, make_entity


def test_unreferenced_function_is_flagged():
    helper = make_entity("helper")
    ctx = make_ctx([helper], store=FakeStore([helper]))
    result = OrphanIndicator().score(helper, ctx)
    assert result.score == 40
    assert {o.name for o in result.offenders} == {"helper"}


def test_referenced_in_file_is_full_score():
    helper = make_entity("helper")
    caller = make_entity("caller", calls=("helper",))
    ctx = make_ctx([helper, caller], store=FakeStore([helper, caller]))
    assert OrphanIndicator().score(helper, ctx).score == 100


def test_referenced_in_codebase_is_full_score():
    stored = make_entity("helper", called_by=("somewhere",))
    edited = make_entity("helper")
    ctx = make_ctx([edited], store=FakeStore([stored]))
    assert OrphanIndicator().score(edited, ctx).score == 100


def test_exported_is_exempt():
    e = make_entity("publicApi", exported=True)
    ctx = make_ctx([e], store=FakeStore([e]))
    assert OrphanIndicator().score(e, ctx).score == 100


def test_test_function_is_exempt():
    e = make_entity("test_thing")
    ctx = make_ctx([e], store=FakeStore([e]))
    assert OrphanIndicator().score(e, ctx).score == 100


def test_decorated_handler_is_exempt():
    e = make_entity("handler", decorators=("app.route('/x')",))
    ctx = make_ctx([e], store=FakeStore([e]))
    assert OrphanIndicator().score(e, ctx).score == 100


def test_class_is_exempt():
    e = make_entity("Widget", kind=EntityKind.CLASS)
    ctx = make_ctx([e], store=FakeStore([e]))
    assert OrphanIndicator().score(e, ctx).score == 100
