"""E2E: the score_file MCP tool handler renders a report from a real file."""

from collections import defaultdict
from types import SimpleNamespace

from clean.core.config import ScoringConfig
from clean.local.mcp_server import _handle_score_change, _handle_score_file
from clean.parsing.registry import ParserRegistry
from clean.scoring.service import ScoringService

SAMPLE = b"""\
def helper():
    return 1


def main():
    helper()
    ghost_call()
"""


class _Store:
    def __init__(self):
        self._by_name = defaultdict(list)

    def count(self, project_id):
        return 1

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


def _container():
    config = ScoringConfig(
        enabled_indicators=["grounding", "blast_radius", "orphan", "index_trust"]
    )
    scoring = ScoringService(
        store=_Store(), embedder=None, parser_registry=ParserRegistry(), config=config
    )
    return SimpleNamespace(scoring=scoring)


def test_score_file_tool_returns_report(tmp_path):
    f = tmp_path / "mod.py"
    f.write_bytes(SAMPLE)

    result = _handle_score_file({"path": str(f)}, _container())

    assert isinstance(result, list)
    text = result[0].text
    assert "Trust score" in text
    assert "Grounding" in text
    assert "ghost_call" in text  # the hallucinated call is listed as an offender


def test_score_change_tool_scores_in_memory_source():
    result = _handle_score_change(
        {"path": "/tmp/whatever/mod.py", "source": SAMPLE.decode()}, _container()
    )
    text = result[0].text
    assert "Trust score" in text


def test_score_file_tool_requires_path():
    result = _handle_score_file({}, _container())
    assert "required" in result[0].text
