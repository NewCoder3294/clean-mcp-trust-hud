"""ScoringService — parse an edited file, run indicators, aggregate a FileScore."""

from __future__ import annotations

import os
import subprocess

from ..util.hashing import hash_file_content
from ..util.logging import get_logger
from .base import FileScore, Indicator, IndicatorResult, Offender, ScoringContext
from .imports import extract_imported_names
from .registry import IndicatorRegistry

logger = get_logger(__name__)


def _git_toplevel(path: str) -> str | None:
    """Return the git working-tree root containing *path*, or None."""
    start = path if os.path.isdir(path) else os.path.dirname(path)
    try:
        result = subprocess.run(
            ["git", "-C", start, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            top = result.stdout.strip()
            return top or None
    except Exception:
        pass
    return None


def _project_id_for(root: str) -> str:
    """Mirror CodebaseIndexer._project_id so lookups hit the indexed table."""
    return os.path.basename(os.path.abspath(root)).lower().replace(" ", "_")


def _band(score: int) -> str:
    if score >= 85:
        return "OK"
    if score >= 60:
        return "REVIEW"
    return "RISK"


class ScoringService:
    """Scores a single edited file against the indexed codebase."""

    def __init__(
        self,
        store,
        embedder,
        parser_registry,
        config,
        registry: IndicatorRegistry | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._parsers = parser_registry
        self._config = config
        self._registry = registry or IndicatorRegistry()

    # -- public API ---------------------------------------------------------

    def score_file(
        self,
        file_path: str,
        *,
        project_root: str | None = None,
        project_id: str | None = None,
        with_embeddings: bool = True,
    ) -> FileScore:
        """Score the file currently on disk at *file_path*."""
        return self.score_change(
            file_path,
            None,
            project_root=project_root,
            project_id=project_id,
            with_embeddings=with_embeddings,
        )

    def score_change(
        self,
        file_path: str,
        new_source: bytes | None,
        *,
        project_root: str | None = None,
        project_id: str | None = None,
        with_embeddings: bool = True,
    ) -> FileScore:
        """Score *new_source* (or the on-disk file when None) for *file_path*."""
        abs_file = os.path.abspath(file_path)
        ext = os.path.splitext(abs_file)[1]

        if not getattr(self._config, "enabled", True):
            return self._skipped(project_id or "", abs_file, "scoring disabled")

        parser = self._parsers.get_parser(ext)
        if parser is None:
            return self._skipped(project_id or "", abs_file, "unsupported file type")

        source = new_source
        if source is None:
            try:
                with open(abs_file, "rb") as fh:
                    source = fh.read()
            except OSError as exc:
                return self._skipped(project_id or "", abs_file, f"unreadable: {exc}")

        try:
            edited = tuple(parser.parse_file(abs_file, source))
        except Exception:
            logger.exception("parse failed for %s", abs_file)
            return self._skipped(project_id or "", abs_file, "parse error")

        if not edited:
            return self._skipped(project_id or "", abs_file, "no entities to score")

        root = project_root or _git_toplevel(abs_file) or os.path.dirname(abs_file)
        pid = project_id or _project_id_for(root)

        try:
            indexed = self._store.count(pid) > 0
        except Exception:
            indexed = False
        # Per-file staleness: is THIS file's indexed copy current? (Unlike a
        # repo-wide git-dirty check, this clears once the file is re-indexed —
        # which the warm daemon does before each score.)
        stale = self._file_is_stale(pid, abs_file, source) if indexed else True

        imported, wildcard = extract_imported_names(parser.language, source)

        ctx = ScoringContext(
            project_id=pid,
            project_root=root,
            file_path=abs_file,
            store=self._store,
            embedder=self._embedder if with_embeddings else None,
            config=self._config,
            edited_entities=edited,
            same_file_names=frozenset(e.name for e in edited),
            imported_names=imported,
            import_wildcard=wildcard,
            stale=stale,
            indexed=indexed,
        )

        enabled = getattr(self._config, "enabled_indicators", None)
        indicators = self._registry.build_enabled(enabled)

        results: list[IndicatorResult] = []
        for indicator in indicators:
            if indicator.requires_embedding and ctx.embedder is None:
                continue  # daemon/model unavailable — skip silently in the hud
            results.append(self._run_indicator(indicator, ctx))

        overall, label = self._aggregate_overall(results)
        if not indexed:
            # Nothing to resolve against — report "unmeasured", not "risky".
            label = "NO INDEX"
        return FileScore(
            project_id=pid,
            file_path=abs_file,
            overall_score=overall,
            overall_label=label,
            indicators=results,
            entity_count=len(edited),
            stale=stale,
            indexed=indexed,
        )

    # -- internals ----------------------------------------------------------

    def _file_is_stale(self, pid: str, abs_file: str, source: bytes) -> bool:
        """True if the file's indexed copy differs from *source* (or is absent)."""
        try:
            state = self._store.get_project_state(pid)
        except Exception:
            return True
        if state is None:
            return True
        fs = state.files.get(abs_file)
        if fs is None:
            return True
        try:
            return hash_file_content(source) != fs.content_hash
        except Exception:
            return True

    def _run_indicator(
        self, indicator: Indicator, ctx: ScoringContext
    ) -> IndicatorResult:
        try:
            if indicator.file_level:
                return indicator.score(None, ctx)
            per_entity = [indicator.score(e, ctx) for e in ctx.edited_entities]
            return self._aggregate_entity_results(per_entity)
        except Exception:
            logger.exception("indicator %s failed", indicator.key)
            return IndicatorResult(
                indicator.key,
                indicator.label,
                100,
                "error",
                skipped=True,
                confidence=0.0,
            )

    @staticmethod
    def _aggregate_entity_results(rs: list[IndicatorResult]) -> IndicatorResult:
        """Collapse per-entity results into one: worst score, union of offenders."""
        live = [r for r in rs if not r.skipped]
        if not live:
            return rs[0]  # all skipped — surface the skip
        worst = min(live, key=lambda r: r.score)
        seen: set[tuple[str, int | None]] = set()
        offenders: list[Offender] = []
        for r in live:
            for off in r.offenders:
                key = (off.name, off.line)
                if key not in seen:
                    seen.add(key)
                    offenders.append(off)
        return IndicatorResult(
            key=worst.key,
            label=worst.label,
            score=worst.score,
            summary=worst.summary,
            offenders=tuple(offenders),
            weight=worst.weight,
            skipped=False,
            confidence=min(r.confidence for r in live),
        )

    def _aggregate_overall(self, results: list[IndicatorResult]) -> tuple[int, str]:
        weights_cfg = getattr(self._config, "weights", {}) or {}
        num = 0.0
        den = 0.0
        for r in results:
            if r.skipped:
                continue
            w = float(weights_cfg.get(r.key, 1.0)) * r.weight * r.confidence
            num += r.score * w
            den += w
        overall = round(num / den) if den > 0 else 100
        return overall, _band(overall)

    @staticmethod
    def _skipped(project_id: str, file_path: str, why: str) -> FileScore:
        return FileScore(
            project_id=project_id,
            file_path=file_path,
            overall_score=100,
            overall_label="OK",
            indicators=[],
            entity_count=0,
            stale=False,
            skipped=True,
        )
