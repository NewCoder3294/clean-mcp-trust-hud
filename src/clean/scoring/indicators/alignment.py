"""Alignment / drift indicator (embedding-based).

For an edited entity that already exists in the index, measures how far its
behavior drifted from the indexed version (a large drift on an existing
function is a rewrite worth review). For brand-new code, measures how well it
fits the surrounding codebase's patterns (a mild outlier penalty only).
"""

from __future__ import annotations

import os

from ...core.models import CodeEntity
from ..base import Indicator, IndicatorResult, Offender, ScoringContext
from ..registry import register_indicator
from ..similarity import cosine, is_self_match


def _skip(key: str, label: str, why: str) -> IndicatorResult:
    return IndicatorResult(key, label, 100, why, skipped=True, confidence=0.0)


@register_indicator
class AlignmentIndicator(Indicator):
    key = "alignment"
    label = "Alignment"
    requires_embedding = True

    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        assert entity is not None
        if not ctx.indexed:
            return _skip(self.key, self.label, "no index")
        emb_new = ctx.embed(entity.code)
        if emb_new is None:
            return _skip(self.key, self.label, "embedding unavailable")

        # Prior indexed version of the same symbol in the same file?
        prior = [
            e
            for e in ctx.lookup_names([entity.name]).get(entity.name, [])
            if e.embedding
            and e.id != entity.id
            and os.path.basename(e.file_path) == os.path.basename(entity.file_path)
        ]
        confidence = 0.7 if ctx.stale else 1.0

        if prior:
            cos = cosine(prior[0].embedding or [], emb_new)
            drift = max(0.0, 1.0 - cos)
            score = round(max(0.0, cos) * 100)
            thr = float(getattr(ctx.config, "drift_threshold", 0.35) or 0.35)
            if drift > thr:
                return IndicatorResult(
                    self.key,
                    self.label,
                    score,
                    f"rewritten ({drift * 100:.0f}% drift)",
                    offenders=(
                        Offender(
                            entity.name,
                            "behavior changed from indexed version",
                            entity.line_start,
                        ),
                    ),
                    confidence=confidence,
                )
            return IndicatorResult(
                self.key,
                self.label,
                score,
                "consistent with prior",
                confidence=confidence,
            )

        # New code: conformity to nearest existing neighbors.
        try:
            results = ctx.store.search(ctx.project_id, emb_new, top_k=6)
        except Exception:
            results = []
        others = [r for r in results if not is_self_match(r.entity, entity)]
        if not others:
            return _skip(self.key, self.label, "no comparable code")

        best = max(r.similarity for r in others)
        # Mild: best>=0.5 -> 100; best 0 -> 60. Novelty is not heavily punished.
        score = round(60 + 40 * min(1.0, best / 0.5))
        summary = "fits existing patterns" if best >= 0.5 else "stylistic outlier"
        return IndicatorResult(
            self.key, self.label, score, summary, confidence=confidence
        )
