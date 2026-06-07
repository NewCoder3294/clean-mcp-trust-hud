"""Grounding indicator — anti-hallucination.

Scores what fraction of an entity's *verifiable* references actually resolve
to a definition (in the same file or the indexed codebase). Unresolved
references are the agent's hallucinated calls.
"""

from __future__ import annotations

from ...core.models import CodeEntity
from ..base import Indicator, IndicatorResult, Offender, ScoringContext
from ..classify import RefKind, classify
from ..registry import register_indicator


@register_indicator
class GroundingIndicator(Indicator):
    key = "grounding"
    label = "Grounding"
    requires_embedding = False

    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        assert entity is not None  # entity-level indicator
        # Without an index, absence of a symbol is not evidence of hallucination.
        if not ctx.indexed:
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "no index — not checked",
                skipped=True,
                confidence=0.0,
            )

        local_full = ctx.same_file_names
        local_segments = {n.split(".")[-1] for n in local_full}

        # (display, resolved_name, is_self_method)
        checkable: list[tuple[str, str, bool]] = []
        for call in entity.calls:
            kind, resolved = classify(call, entity.language)
            if kind is RefKind.BARE_LOCAL_CANDIDATE:
                checkable.append((call, resolved, False))
            elif kind is RefKind.SELF_METHOD:
                checkable.append((call, resolved, True))

        if not checkable:
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "no checkable calls",
                confidence=0.7 if ctx.stale else 1.0,
            )

        found = ctx.lookup_names([r for _, r, _ in checkable])

        offenders: list[Offender] = []
        for display, resolved, is_method in checkable:
            if is_method:
                ok = (
                    resolved in local_segments
                    or bool(found.get(resolved))
                    or ctx.resolve_method_segment(resolved)
                )
            else:
                ok = resolved in local_full or bool(found.get(resolved))
            if not ok:
                offenders.append(
                    Offender(display, "no matching definition found", entity.line_start)
                )

        score = round(100 * (1 - len(offenders) / len(checkable)))
        if offenders:
            summary = f"{len(offenders)}/{len(checkable)} calls unresolved"
        else:
            summary = f"all {len(checkable)} calls resolved"
        return IndicatorResult(
            self.key,
            self.label,
            score,
            summary,
            offenders=tuple(offenders),
            confidence=0.7 if ctx.stale else 1.0,
        )
