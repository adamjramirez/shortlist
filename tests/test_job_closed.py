"""Test is_closed toggle on jobs."""
import pytest
from pydantic import ValidationError
from shortlist.api.schemas import JobStatusUpdate, JobSummary


def test_status_closed_accepted():
    update = JobStatusUpdate(status="closed")
    assert update.status == "closed"


def test_job_summary_includes_is_closed():
    """JobSummary should have is_closed field, defaulting to False."""
    summary = JobSummary(
        id=1, title="Test", company="Co", location=None,
        fit_score=80, matched_track=None, salary_estimate=None,
        url=None, status="scored", user_status=None, sources_seen=[],
        first_seen=None, posted_at=None, has_tailored_resume=False,
        has_tailored_pdf=False, is_new=False, company_intel=None,
        score_reasoning=None,
    )
    assert summary.is_closed is False


def test_job_summary_is_closed_true():
    summary = JobSummary(
        id=1, title="Test", company="Co", location=None,
        fit_score=80, matched_track=None, salary_estimate=None,
        url=None, status="scored", user_status=None, sources_seen=[],
        first_seen=None, posted_at=None, has_tailored_resume=False,
        has_tailored_pdf=False, is_new=False, company_intel=None,
        score_reasoning=None, is_closed=True,
    )
    assert summary.is_closed is True
