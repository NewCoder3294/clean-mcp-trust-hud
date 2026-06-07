"""Blast-radius indicator — how risky is changing this symbol.

Uses the precomputed reverse call graph (``CodeEntity.called_by``) from the
index: the more existing callers a changed symbol has, the wider the blast
radius and the lower the score.
"""

from __future__ import annotations

from ...core.models import CodeEntity
from ..base import Indicator, IndicatorResult, Offender, ScoringContext
from ..registry import register_indicator


@register_indicator
class BlastRadiusIndicator(Indicator):
    key = "blast_radius"
    label = "Blast"
    requires_embedding = False

    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        assert entity is not None
        if not ctx.indexed:
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "no index — callers unknown",
                skipped=True,
                confidence=0.0,
            )

        # Look the symbol up in the index to read its precomputed callers.
        stored = ctx.lookup_names([entity.name]).get(entity.name, [])
        if not stored:
            # Newly added symbol not yet indexed: no callers *yet*, but we
            # cannot be sure — report safe with reduced confidence.
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "new symbol — callers unknown",
                confidence=0.5,
            )

        callers: set[str] = set()
        for s in stored:
            callers.update(s.called_by)
        n = len(callers)

        warn = int(getattr(ctx.config, "blast_warn", 5) or 5)
        # Each caller above zero chips away; reaching ``warn`` callers ~ score 50.
        step = 50 / warn if warn > 0 else 50
        score = max(0, round(100 - n * step))

        if n == 0:
            summary = "no callers"
        else:
            summary = f"{n} caller{'s' if n != 1 else ''}"
        offenders = tuple(
            Offender(c, "calls this symbol", None) for c in sorted(callers)[:10]
        )
        return IndicatorResult(
            self.key,
            self.label,
            score,
            summary,
            offenders=offenders,
            confidence=0.7 if ctx.stale else 1.0,
        )
