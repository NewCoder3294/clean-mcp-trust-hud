"""Index-trust indicator — how much to trust the other scores.

File-level: runs once. A stale or missing index means the other indicators are
resolving against out-of-date data, so the service also lowers their
confidence (it passes ``ctx.stale`` to every indicator).
"""

from __future__ import annotations

from ...core.models import CodeEntity
from ..base import Indicator, IndicatorResult, ScoringContext
from ..registry import register_indicator


@register_indicator
class IndexTrustIndicator(Indicator):
    key = "index_trust"
    label = "Index"
    requires_embedding = False
    file_level = True

    def score(self, entity: CodeEntity | None, ctx: ScoringContext) -> IndicatorResult:
        if not ctx.indexed:
            return IndicatorResult(
                self.key,
                self.label,
                0,
                "not indexed — scores are degraded",
                confidence=1.0,
            )
        if ctx.stale:
            return IndicatorResult(
                self.key,
                self.label,
                40,
                "index stale — re-index for accurate scores",
                confidence=1.0,
            )
        return IndicatorResult(self.key, self.label, 100, "fresh")
