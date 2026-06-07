"""Tests for the grounding reference classifier."""

import pytest

from clean.core.types import Language
from clean.scoring.classify import RefKind, classify


@pytest.mark.parametrize(
    "call,language,expected_kind,expected_name",
    [
        ("frobnicate", Language.PYTHON, RefKind.BARE_LOCAL_CANDIDATE, "frobnicate"),
        ("len", Language.PYTHON, RefKind.BUILTIN_OR_GLOBAL, ""),
        ("os.path.join", Language.PYTHON, RefKind.EXTERNAL_DOTTED, ""),
        ("self.run", Language.PYTHON, RefKind.SELF_METHOD, "run"),
        ("cls.make", Language.PYTHON, RefKind.SELF_METHOD, "make"),
        ("doThing", Language.JAVASCRIPT, RefKind.BARE_LOCAL_CANDIDATE, "doThing"),
        ("console.log", Language.JAVASCRIPT, RefKind.EXTERNAL_DOTTED, ""),
        ("this.handle", Language.JAVASCRIPT, RefKind.SELF_METHOD, "handle"),
        ("map", Language.JAVASCRIPT, RefKind.BUILTIN_OR_GLOBAL, ""),
    ],
)
def test_classify(call, language, expected_kind, expected_name):
    kind, name = classify(call, language)
    assert kind is expected_kind
    assert name == expected_name


def test_self_method_with_allowlisted_segment_is_acceptable():
    # self.get -> 'get' is an allowlisted method name, never flagged.
    kind, name = classify("this.get", Language.JAVASCRIPT)
    assert kind is RefKind.BUILTIN_OR_GLOBAL
