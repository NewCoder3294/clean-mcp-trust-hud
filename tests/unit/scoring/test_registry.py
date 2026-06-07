"""Tests for the indicator registry."""

from clean.scoring.base import Indicator, IndicatorResult
from clean.scoring.registry import IndicatorRegistry, register_indicator


def test_default_registry_has_all_six():
    reg = IndicatorRegistry()
    keys = set(reg.available())
    assert {
        "grounding",
        "blast_radius",
        "index_trust",
        "orphan",
        "alignment",
        "duplication",
    } <= keys


def test_build_enabled_respects_order_and_subset():
    reg = IndicatorRegistry()
    built = reg.build_enabled(["blast_radius", "grounding"])
    assert [i.key for i in built] == ["blast_radius", "grounding"]


def test_build_enabled_none_returns_all():
    reg = IndicatorRegistry()
    assert len(reg.build_enabled(None)) == len(reg.available())


def test_unknown_keys_are_skipped():
    reg = IndicatorRegistry()
    built = reg.build_enabled(["nope", "grounding", "also_missing"])
    assert [i.key for i in built] == ["grounding"]


def test_register_indicator_adds_to_custom_registry():
    @register_indicator
    class _Dummy(Indicator):
        key = "dummy_test_only"
        label = "Dummy"

        def score(self, entity, ctx):
            return IndicatorResult(self.key, self.label, 100, "ok")

    # register_indicator writes to the global registry; confirm it is visible.
    reg = IndicatorRegistry()
    assert "dummy_test_only" in reg.available()
