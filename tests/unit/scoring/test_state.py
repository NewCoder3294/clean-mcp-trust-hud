"""Tests for the scoring state writer (~/.clean/scoring.json)."""

from clean.scoring.base import FileScore, IndicatorResult, Offender
from clean.scoring.state import ScoringStateWriter, file_score_to_dict, read_repo_score, write_repo_score


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


def _skipped_score() -> FileScore:
    return FileScore(
        project_id="proj",
        file_path="/tmp/proj/View.swift",
        overall_score=100,
        overall_label="OK",
        indicators=[],
        entity_count=0,
        stale=False,
        skipped=True,
    )


def _no_project_id_score() -> FileScore:
    score = _sample_score()
    return FileScore(
        project_id="",
        file_path=score.file_path,
        overall_score=score.overall_score,
        overall_label=score.overall_label,
        indicators=score.indicators,
        entity_count=score.entity_count,
        stale=score.stale,
    )


def _exotic_id_score() -> FileScore:
    score = _sample_score()
    return FileScore(
        project_id="///",
        file_path=score.file_path,
        overall_score=score.overall_score,
        overall_label=score.overall_label,
        indicators=score.indicators,
        entity_count=score.entity_count,
        stale=score.stale,
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


def test_write_repo_score_round_trips_by_project_id(tmp_path):
    write_repo_score(_sample_score(), base=tmp_path, updated_at="2026-06-06T00:00:00")
    data = read_repo_score("proj", base=tmp_path)
    assert data is not None
    assert data["overall_score"] == 82
    assert data["indicators"][0]["offenders"][0]["name"] == "frobnicate"


def test_skipped_score_is_not_persisted(tmp_path):
    write_repo_score(_skipped_score(), base=tmp_path)
    assert read_repo_score("proj", base=tmp_path) is None


def test_skipped_score_does_not_overwrite_last_good(tmp_path):
    write_repo_score(_sample_score(), base=tmp_path)
    write_repo_score(_skipped_score(), base=tmp_path)  # must be a no-op
    data = read_repo_score("proj", base=tmp_path)
    assert data is not None and data["overall_score"] == 82


def test_read_missing_repo_returns_none(tmp_path):
    assert read_repo_score("nope", base=tmp_path) is None


def test_empty_project_id_is_ignored(tmp_path):
    write_repo_score(_no_project_id_score(), base=tmp_path)
    assert read_repo_score("", base=tmp_path) is None


def test_exotic_project_id_sanitizes_to_safe_filename(tmp_path):
    write_repo_score(_exotic_id_score(), base=tmp_path, updated_at="2026-06-06T00:00:00")
    data = read_repo_score("///", base=tmp_path)
    assert data is not None and data["overall_score"] == 82
