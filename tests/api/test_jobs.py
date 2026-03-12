"""Tests for jobs + brief routes."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from shortlist.api.models import Job, User


@pytest_asyncio.fixture
async def user_with_jobs(client, auth_headers, session_factory):
    """Create a user with some jobs in the DB for testing."""
    # Get user_id from the auth token
    resp = await client.get("/api/auth/me", headers=auth_headers)
    user_id = resp.json()["id"]

    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            jobs = [
                Job(
                    user_id=user_id, title="VP Engineering", company="Acme Corp",
                    description_hash="hash1", fit_score=92, matched_track="vp",
                    score_reasoning="Excellent match", yellow_flags="Series A",
                    salary_estimate="$280k-$320k", url="https://acme.com/jobs/1",
                    status="new", first_seen=now, last_seen=now,
                    sources_seen=["linkedin"],
                ),
                Job(
                    user_id=user_id, title="Engineering Manager", company="Beta Inc",
                    description_hash="hash2", fit_score=78, matched_track="em",
                    score_reasoning="Good fit", yellow_flags=None,
                    salary_estimate="$220k-$260k", url="https://beta.com/jobs/2",
                    status="new", first_seen=now, last_seen=now,
                    sources_seen=["hn", "linkedin"],
                ),
                Job(
                    user_id=user_id, title="CTO", company="Gamma LLC",
                    description_hash="hash3", fit_score=85, matched_track="vp",
                    score_reasoning="Weak match", yellow_flags="Pre-revenue",
                    status="new", first_seen=now, last_seen=now,
                    sources_seen=["career_page"],
                ),
            ]
            for j in jobs:
                s.add(j)

    return user_id


@pytest.mark.asyncio
async def test_list_jobs(client, auth_headers, user_with_jobs):
    resp = await client.get("/api/jobs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["jobs"]) == 3
    # Default sort: score desc
    assert data["jobs"][0]["fit_score"] == 92


@pytest.mark.asyncio
async def test_list_jobs_min_score(client, auth_headers, user_with_jobs):
    resp = await client.get("/api/jobs?min_score=85", headers=auth_headers)
    jobs = resp.json()["jobs"]
    assert len(jobs) == 2
    assert all(j["fit_score"] >= 85 for j in jobs)


@pytest.mark.asyncio
async def test_list_jobs_by_track(client, auth_headers, user_with_jobs):
    resp = await client.get("/api/jobs?track=em", headers=auth_headers)
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["matched_track"] == "em"


@pytest.mark.asyncio
async def test_list_jobs_pagination(client, auth_headers, user_with_jobs):
    resp = await client.get("/api/jobs?page=1&per_page=2", headers=auth_headers)
    data = resp.json()
    assert len(data["jobs"]) == 2
    assert data["total"] == 3
    assert data["page"] == 1

    resp2 = await client.get("/api/jobs?page=2&per_page=2", headers=auth_headers)
    assert len(resp2.json()["jobs"]) == 1


@pytest.mark.asyncio
async def test_get_job(client, auth_headers, user_with_jobs):
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    resp = await client.get(f"/api/jobs/{job_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "VP Engineering"
    assert resp.json()["score_reasoning"] == "Excellent match"


@pytest.mark.asyncio
async def test_get_other_users_job(client, auth_headers, user_with_jobs):
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    resp = await client.post("/api/auth/signup", json={
        "email": "other@example.com", "password": "pass123",
    })
    other_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    resp = await client.get(f"/api/jobs/{job_id}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_job_status(client, auth_headers, user_with_jobs):
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    resp = await client.put(f"/api/jobs/{job_id}/status", json={
        "status": "applied",
    }, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["user_status"] == "applied"

    # Verify it persisted
    resp = await client.get(f"/api/jobs/{job_id}", headers=auth_headers)
    assert resp.json()["user_status"] == "applied"


@pytest.mark.asyncio
async def test_update_job_status_invalid(client, auth_headers, user_with_jobs):
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    resp = await client.put(f"/api/jobs/{job_id}/status", json={
        "status": "invalid_status",
    }, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_jobs_by_user_status(client, auth_headers, user_with_jobs):
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    await client.put(f"/api/jobs/{job_id}/status", json={
        "status": "applied",
    }, headers=auth_headers)

    resp = await client.get("/api/jobs?user_status=applied", headers=auth_headers)
    assert len(resp.json()["jobs"]) == 1


@pytest.mark.asyncio
async def test_jobs_require_auth(client):
    assert (await client.get("/api/jobs")).status_code == 401
    assert (await client.get("/api/jobs/1")).status_code == 401
