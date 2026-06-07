"""Tests for the scoring state writer (~/.clean/scoring.json)."""

from clean.scoring.base import FileScore, IndicatorResult, Offender
from clean.scoring.state import ScoringStateWriter, file_score_to_dict


def _sample_score() -> FileScore:
    return FileScore(
        project_id="proj",
        file_path="/tmp/proj/mod.py",
        overall_score=82,
        overall_label="REVIEW",
        indicators=[
            IndicatorResult(
                "grounding",
                "Grounding",
                67,
                "1/3 calls unresolved",
                offenders=(Offender("frobnicate", "no matching definition", 42),),
            ),
            IndicatorResult("index_trust", "Index", 100, "fresh"),
        ],
        entity_count=3,
        stale=False,
    )


def test_to_dict_schema():
    d = file_score_to_dict(_sample_score(), updated_at="2026-06-06T00:00:00")
    assert d["version"] == 1
    assert d["overall_score"] == 82
    assert d["overall_label"] == "REVIEW"
    assert d["indicators"][0]["key"] == "grounding"
    assert d["indicators"][0]["offenders"][0]["name"] == "frobnicate"
    assert d["indicators"][0]["offenders"][0]["line"] == 42


def test_round_trip(tmp_path):
    path = tmp_path / "scoring.json"
    writer = ScoringStateWriter(path)
    writer.write(_sample_score(), updated_at="2026-06-06T00:00:00")
    data = writer.read()
    assert data is not None
    assert data["overall_score"] == 82
    assert data["project_id"] == "proj"


def test_read_missing_file_returns_none(tmp_path):
    writer = ScoringStateWriter(tmp_path / "nope.json")
    assert writer.read() is None
