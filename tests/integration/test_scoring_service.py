"""Integration test: ScoringService over a real parsed file."""

from collections import defaultdict

from clean.core.config import ScoringConfig
from clean.parsing.registry import ParserRegistry
from clean.scoring.service import ScoringService

SAMPLE = b"""\
def helper():
    return 1


def main():
    helper()
    frobnicate()
"""


class _Store:
    """Indexed-but-empty store: project exists, no entities resolve cross-file."""

    def __init__(self):
        self._by_name = defaultdict(list)

    def count(self, project_id):
        return 1  # pretend the project is indexed

    def get_by_names(self, project_id, names):
        return []

    def get_by_name(self, project_id, name, file_path=None):
        return []

    def get_by_name_substring(self, project_id, pattern, limit=20):
        return []

    def search(self, project_id, embedding, top_k):
        return []

    def get_project_state(self, project_id):
        return None


def test_scores_real_file_and_aggregates_worst(tmp_path):
    f = tmp_path / "mod.py"
    f.write_bytes(SAMPLE)

    # Disable embedding indicators so the test needs no model.
    config = ScoringConfig(
        enabled_indicators=["grounding", "blast_radius", "orphan", "index_trust"]
    )
    service = ScoringService(
        store=_Store(), embedder=None, parser_registry=ParserRegistry(), config=config
    )

    score = service.score_file(str(f), with_embeddings=False)

    assert score.skipped is False
    assert score.entity_count == 2  # helper + main

    by_key = {ind.key: ind for ind in score.indicators}
    # main() calls helper (local, resolved) + frobnicate (hallucinated) -> 1/2.
    assert by_key["grounding"].score == 50
    assert any(o.name == "frobnicate" for o in by_key["grounding"].offenders)
    # Overall is pulled down by the hallucination.
    assert score.overall_score < 100
    assert score.overall_label in ("REVIEW", "RISK")
