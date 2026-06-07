"""Duplication indicator (embedding-based).

Flags edited code that is near-identical to code already in the index — a sign
the agent re-implemented something that already exists instead of reusing it.
"""

from __future__ import annotations

import os

from ...core.models import CodeEntity
from ..base import Indicator, IndicatorResult, Offender, ScoringContext
from ..registry import register_indicator
from ..similarity import is_self_match


@register_indicator
class DuplicationIndicator(Indicator):
    key = "duplication"
    label = "Dup"
    requires_embedding = True

    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        assert entity is not None
        if not ctx.indexed:
            return IndicatorResult(
                self.key, self.label, 100, "no index", skipped=True, confidence=0.0
            )
        emb = ctx.embed(entity.code)
        if emb is None:
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "embedding unavailable",
                skipped=True,
                confidence=0.0,
            )

        try:
            results = ctx.store.search(ctx.project_id, emb, top_k=6)
        except Exception:
            results = []
        others = [r for r in results if not is_self_match(r.entity, entity)]
        if not others:
            return IndicatorResult(
                self.key,
                self.label,
                100,
                "no comparable code",
                skipped=True,
                confidence=0.0,
            )

        thr = float(getattr(ctx.config, "dup_threshold", 0.92) or 0.92)
        flagged = [r for r in others if r.similarity >= thr]
        confidence = 0.7 if ctx.stale else 1.0
        if not flagged:
            return IndicatorResult(
                self.key, self.label, 100, "no near-duplicates", confidence=confidence
            )

        max_sim = max(r.similarity for r in flagged)
        score = max(0, round(100 * (1.0 - max_sim)))
        offenders = tuple(
            Offender(
                r.entity.name,
                f"{r.similarity:.2f} similar @ {os.path.basename(r.entity.file_path)}",
                entity.line_start,
            )
            for r in sorted(flagged, key=lambda r: r.similarity, reverse=True)[:5]
        )
        plural = "s" if len(flagged) != 1 else ""
        return IndicatorResult(
            self.key,
            self.label,
            score,
            f"{len(flagged)} near-duplicate{plural}",
            offenders=offenders,
            confidence=confidence,
        )
