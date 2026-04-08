"""Tests for collection efficiency improvements."""
from unittest.mock import patch, MagicMock


def _make_config():
    from shortlist.config import Config, Track, Filters, LocationFilter, SalaryFilter
    return Config(
        tracks={"vp": Track(title="VP Engineering", search_queries=["VP Engineering"])},
        filters=Filters(location=LocationFilter(remote=True), salary=SalaryFilter()),
    )


def _capture_linkedin_time_filter(config, li_time_filter):
    """Call _get_collectors with a capturing subclass, return list of time_filter values used."""
    import shortlist.pipeline as pm
    from shortlist.collectors.linkedin import LinkedInCollector

    created = []

    class CapturingLinkedIn(LinkedInCollector):
        def __init__(self, *args, **kwargs):
            created.append(kwargs.get("time_filter"))
            # Don't call super — avoids real network setup

    with patch.object(pm, "LinkedInCollector", CapturingLinkedIn):
        pm._get_collectors(config=config, db=None, pg_db_url=None,
                           li_time_filter=li_time_filter)
    return created


def test_linkedin_uses_24h_filter_on_recurring_runs():
    """Recurring runs use r86400 (24h) — no re-fetching jobs from the past week."""
    config = _make_config()
    created = _capture_linkedin_time_filter(config, li_time_filter="r86400")
    assert created, "LinkedInCollector was never instantiated"
    assert all(t == "r86400" for t in created), f"Expected r86400, got {created}"


def test_linkedin_uses_week_filter_on_first_run():
    """First run uses r604800 (1 week) to populate the user's initial inbox."""
    config = _make_config()
    created = _capture_linkedin_time_filter(config, li_time_filter="r604800")
    assert created, "LinkedInCollector was never instantiated"
    assert all(t == "r604800" for t in created), f"Expected r604800, got {created}"


def test_split_known_new_separates_by_url():
    """Known URLs are split from new jobs for nextplay source."""
    import shortlist.pipeline as pm
    import shortlist.pgdb as pgdb_mod
    from shortlist.collectors.base import RawJob

    job_known = RawJob(title="VP Eng", company="Acme", url="https://acme.com/1",
                       description="d1", source="greenhouse", location="Remote")
    job_new = RawJob(title="Dir Eng", company="Corp", url="https://corp.com/1",
                     description="d2", source="greenhouse", location="Remote")

    conn = MagicMock()
    with patch.object(pgdb_mod, "get_existing_urls",
                      return_value={"https://acme.com/1"}):
        known_urls, new_jobs = pm._split_known_new(
            conn, user_id=1, name="nextplay", jobs=[job_known, job_new]
        )

    assert known_urls == ["https://acme.com/1"]
    assert len(new_jobs) == 1
    assert new_jobs[0].url == "https://corp.com/1"


def test_split_known_new_linkedin_bypasses_check():
    """LinkedIn source skips the DB check — all jobs returned as new."""
    import shortlist.pipeline as pm
    import shortlist.pgdb as pgdb_mod
    from shortlist.collectors.base import RawJob

    job = RawJob(title="VP Eng", company="Acme", url="https://linkedin.com/1",
                 description="d1", source="linkedin", location="Remote")
    conn = MagicMock()
    with patch.object(pgdb_mod, "get_existing_urls") as mock_get:
        known_urls, new_jobs = pm._split_known_new(
            conn, user_id=1, name="linkedin", jobs=[job]
        )

    mock_get.assert_not_called()
    assert known_urls == []
    assert len(new_jobs) == 1


def test_split_known_new_null_url_treated_as_new():
    """Jobs with no URL bypass the check and are treated as new."""
    import shortlist.pipeline as pm
    import shortlist.pgdb as pgdb_mod
    from shortlist.collectors.base import RawJob

    job = RawJob(title="VP Eng", company="Acme", url=None,
                 description="d1", source="greenhouse", location="Remote")
    conn = MagicMock()
    with patch.object(pgdb_mod, "get_existing_urls", return_value=set()):
        known_urls, new_jobs = pm._split_known_new(
            conn, user_id=1, name="nextplay", jobs=[job]
        )

    assert known_urls == []
    assert len(new_jobs) == 1
