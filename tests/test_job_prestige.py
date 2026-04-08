"""Tests for prestige_tier — DB persistence and API schema."""
import pytest

from tests.test_pgdb import pg_conn  # noqa: F401 (fixture)


def test_update_job_writes_prestige_tier(pg_conn):
    """update_job can write prestige_tier — kwargs passthrough works."""
    from shortlist.collectors.base import RawJob
    from shortlist.pgdb import upsert_job, update_job

    job = RawJob(
        title="VP Engineering", company="Chainguard",
        url="https://test.example.com/vp1",
        description="desc", source="greenhouse", location="Remote",
    )
    upsert_job(pg_conn, job=job, user_id=1)
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT id FROM jobs WHERE url = ? AND user_id = 1",
                    ("https://test.example.com/vp1",))
        row = cur.fetchone()
    job_id = row["id"]

    update_job(pg_conn, job_id, prestige_tier="A")
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT prestige_tier FROM jobs WHERE id = ?", (job_id,))
        result = cur.fetchone()
    assert result["prestige_tier"] == "A"


def test_update_job_prestige_tier_null_when_not_set(pg_conn):
    """prestige_tier is NULL when job is inserted but not yet scored."""
    from shortlist.collectors.base import RawJob
    from shortlist.pgdb import upsert_job

    job = RawJob(
        title="Director", company="OMG",
        url="https://test.example.com/dir1",
        description="desc", source="greenhouse", location="Remote",
    )
    upsert_job(pg_conn, job=job, user_id=1)
    pg_conn.commit()

    with pg_conn.cursor() as cur:
        cur.execute("SELECT prestige_tier FROM jobs WHERE url = ? AND user_id = 1",
                    ("https://test.example.com/dir1",))
        result = cur.fetchone()
    assert result["prestige_tier"] is None


def test_build_prestige_criteria_includes_track_titles():
    """Criteria string includes track titles from config."""
    from shortlist.processors.scorer import build_prestige_criteria
    from shortlist.config import Config, Track
    config = Config(tracks={
        "vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10),
        "cto": Track(title="CTO", target_orgs="scale-up", min_reports=15),
    })
    result = build_prestige_criteria(config)
    assert "VP of Engineering" in result
    assert "CTO" in result


def test_build_prestige_criteria_includes_min_reports():
    """Criteria string includes the maximum min_reports across tracks."""
    from shortlist.processors.scorer import build_prestige_criteria
    from shortlist.config import Config, Track
    config = Config(tracks={
        "vp": Track(title="VP of Engineering", target_orgs="startup", min_reports=10),
    })
    result = build_prestige_criteria(config)
    assert "10" in result


def test_build_prestige_criteria_empty_tracks():
    """Returns a sensible fallback when no tracks configured."""
    from shortlist.processors.scorer import build_prestige_criteria
    from shortlist.config import Config
    config = Config()
    result = build_prestige_criteria(config)
    assert isinstance(result, str)
    assert len(result) > 0


def test_job_summary_has_prestige_tier():
    """JobSummary schema includes prestige_tier field (Pydantic v2)."""
    from shortlist.api.schemas import JobSummary
    assert 'prestige_tier' in JobSummary.model_fields
