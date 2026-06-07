"""Classify a call-site reference for the grounding indicator.

The parser (``parsing/call_extractor.py``) extracts call names that are either
bare identifiers (``foo``) or dotted chains (``self.bar``, ``obj.method``,
``a.b.c``). It does *not* extract imports, so the only reference we can verify
with high precision is the **bare, non-builtin identifier** and the
**self/this/cls method**. Everything dotted-and-external is deliberately
treated as acceptable to keep false positives near zero.
"""

from __future__ import annotations

from enum import Enum

from ..core.types import Language
from .allowlists import is_allowlisted

_SELF_PREFIXES = ("self.", "this.", "cls.")


class RefKind(Enum):
    BARE_LOCAL_CANDIDATE = "bare_local_candidate"  # the only thing grounding verifies
    BUILTIN_OR_GLOBAL = "builtin_or_global"  # allowlisted -> acceptable
    SELF_METHOD = "self_method"  # self./this./cls. -> resolve locally, can flag
    EXTERNAL_DOTTED = "external_dotted"  # receiver.method -> acceptable, never flag


def classify(call: str, language: Language) -> tuple[RefKind, str]:
    """Classify a call string.

    Returns ``(kind, resolved_name)`` where ``resolved_name`` is the bare name
    to check for existence (the last segment for self-methods, the identifier
    itself for bare candidates, ``""`` otherwise).
    """
    lowered = call.lower()

    # 1. self./this./cls. method -> verify the trailing segment locally.
    for prefix in _SELF_PREFIXES:
        if lowered.startswith(prefix):
            segment = call.split(".")[-1]
            if is_allowlisted(segment, language):
                return RefKind.BUILTIN_OR_GLOBAL, ""
            return RefKind.SELF_METHOD, segment

    # 2. Any other dotted chain -> external; receiver is an unresolvable
    #    variable/import. Flagging these is the main false-positive source.
    if "." in call:
        return RefKind.EXTERNAL_DOTTED, ""

    # 3. Bare builtin/global -> acceptable.
    if is_allowlisted(call, language):
        return RefKind.BUILTIN_OR_GLOBAL, ""

    # 4. Remaining bare identifier -> the one thing we verify for grounding.
    return RefKind.BARE_LOCAL_CANDIDATE, call
