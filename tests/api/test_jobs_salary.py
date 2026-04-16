"""Tests for salary_text, salary_confidence, and salary_listed in JobSummary."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from shortlist.api.models import Job


@pytest_asyncio.fixture
async def user_id(client, auth_headers):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    return resp.json()["id"]


@pytest_asyncio.fixture
async def salary_jobs(client, auth_headers, session_factory, user_id):
    """Create jobs with different salary_text values for testing."""
    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            jobs = [
                Job(
                    user_id=user_id, title="VP Engineering", company="Acme Corp",
                    description_hash="hash-sal-1", fit_score=90, matched_track="vp",
                    salary_estimate="$300k-$400k",
                    salary_text="$200k", salary_confidence="high",
                    url="https://acme.com/jobs/1", status="new",
                    first_seen=now, last_seen=now, sources_seen=["linkedin"],
                ),
                Job(
                    user_id=user_id, title="Engineering Manager", company="Beta Inc",
                    description_hash="hash-sal-2", fit_score=85, matched_track="em",
                    salary_estimate="$220k-$260k",
                    salary_text="$32", salary_confidence="low",
                    url="https://beta.com/jobs/2", status="new",
                    first_seen=now, last_seen=now, sources_seen=["hn"],
                ),
                Job(
                    user_id=user_id, title="Director of Engineering", company="Gamma LLC",
                    description_hash="hash-sal-3", fit_score=80, matched_track="vp",
                    salary_estimate="$250k-$300k",
                    salary_text=None, salary_confidence=None,
                    url="https://gamma.com/jobs/3", status="new",
                    first_seen=now, last_seen=now, sources_seen=["hn"],
                ),
                Job(
                    user_id=user_id, title="CTO", company="Delta LLC",
                    description_hash="hash-sal-4", fit_score=78, matched_track="vp",
                    salary_estimate="$120k-$180k",
                    salary_text="$5k/month", salary_confidence="medium",
                    url="https://delta.com/jobs/4", status="new",
                    first_seen=now, last_seen=now, sources_seen=["hn"],
                ),
            ]
            for j in jobs:
                s.add(j)
    return user_id


@pytest.mark.asyncio
async def test_salary_fields_present_in_response(client, auth_headers, salary_jobs):
    """salary_text and salary_confidence appear in JobSummary response."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) > 0
    # Every job has these keys
    for job in jobs:
        assert "salary_text" in job
        assert "salary_confidence" in job
        assert "salary_listed" in job


@pytest.mark.asyncio
async def test_salary_listed_true_for_200k(client, auth_headers, salary_jobs):
    """salary_listed=True when salary_text='$200k' (parseable, >= $50k)."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = {j["title"]: j for j in resp.json()["jobs"]}
    vp = jobs["VP Engineering"]
    assert vp["salary_text"] == "$200k"
    assert vp["salary_confidence"] == "high"
    assert vp["salary_listed"] is True


@pytest.mark.asyncio
async def test_salary_listed_false_for_low_value(client, auth_headers, salary_jobs):
    """salary_listed=False when salary_text='$32' (below $50k threshold)."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = {j["title"]: j for j in resp.json()["jobs"]}
    em = jobs["Engineering Manager"]
    assert em["salary_text"] == "$32"
    assert em["salary_listed"] is False


@pytest.mark.asyncio
async def test_salary_listed_false_for_none(client, auth_headers, salary_jobs):
    """salary_listed=False when salary_text=None."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = {j["title"]: j for j in resp.json()["jobs"]}
    director = jobs["Director of Engineering"]
    assert director["salary_text"] is None
    assert director["salary_listed"] is False


@pytest.mark.asyncio
async def test_salary_listed_false_for_monthly(client, auth_headers, salary_jobs):
    """salary_listed=False when salary_text='$5k/month' (monthly rate)."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = {j["title"]: j for j in resp.json()["jobs"]}
    cto = jobs["CTO"]
    assert cto["salary_text"] == "$5k/month"
    assert cto["salary_listed"] is False
