"""Orphan-risk indicator — newly written code that nothing references.

Flags functions/methods that are not referenced anywhere (in the edited file
or the indexed codebase) and are not of an entry-point kind (exported,
decorated handler, test, dunder, class, ``main``).
"""

from __future__ import annotations

from ...core.models import CodeEntity
from ...core.types import EntityKind
from ..base import Indicator, IndicatorResult, Offender, ScoringContext
from ..registry import register_indicator

# Decorator name fragments that mark a callback/entry-point — never an orphan.
_ENTRYPOINT_DECORATORS = (
    "route",
    "router",
    "app.",
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "websocket",
    "on_event",
    "fixture",
    "command",
    "cli",
    "click",
    "task",
    "handler",
    "callback",
    "listener",
    "subscribe",
    "test",
)
_ENTRYPOINT_NAMES = {"main", "__main__"}


def _is_exempt(entity: CodeEntity) -> bool:
    if entity.exported:
        return True
    if entity.kind in (EntityKind.CLASS, EntityKind.INTERFACE, EntityKind.TYPE):
        return True
    segment = entity.name.split(".")[-1]
    if segment in _ENTRYPOINT_NAMES or segment.startswith("test_"):
        return True
    if segment.startswith("__") and segment.endswith("__"):
        return True
    deco = " ".join(entity.decorators).lower()
    return any(frag in deco for frag in _ENTRYPOINT_DECORATORS)


@register_indicator
class OrphanIndicator(Indicator):
    key = "orphan"
    label = "Orphan"
    requires_embedding = False

    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        assert entity is not None
        if not ctx.indexed:
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "no index — references unknown",
                skipped=True,
                confidence=0.0,
            )
        if _is_exempt(entity):
            return IndicatorResult(self.key, self.label, 100, "entry point / exported")

        segment = entity.name.split(".")[-1]

        # In-file references: does any *other* edited entity call this one?
        referenced_in_file = any(
            call == entity.name or call.split(".")[-1] == segment
            for other in ctx.edited_entities
            if other.id != entity.id
            for call in other.calls
        )
        if referenced_in_file:
            return IndicatorResult(self.key, self.label, 100, "referenced in file")

        # Cross-file references via the precomputed reverse call graph.
        stored = ctx.lookup_names([entity.name]).get(entity.name, [])
        if any(s.called_by for s in stored):
            return IndicatorResult(self.key, self.label, 100, "referenced in codebase")

        confidence = 0.5 if not stored else (0.7 if ctx.stale else 1.0)
        return IndicatorResult(
            self.key,
            self.label,
            40,
            "no references found",
            offenders=(
                Offender(entity.name, "nothing calls this symbol", entity.line_start),
            ),
            confidence=confidence,
        )
