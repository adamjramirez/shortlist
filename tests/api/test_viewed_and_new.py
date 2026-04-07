"""Tests for viewed_at and run_id-based is_new."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from shortlist.api.models import Job, Run, User


@pytest_asyncio.fixture
async def user_id(client, auth_headers):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    return resp.json()["id"]


@pytest_asyncio.fixture
async def user_with_run_and_jobs(client, auth_headers, session_factory, user_id):
    """Create a user with a completed run and jobs from that run."""
    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            run = Run(
                user_id=user_id, status="completed",
                started_at=now, finished_at=now, created_at=now,
            )
            s.add(run)
            await s.flush()  # get run.id

            # Job from this run
            s.add(Job(
                user_id=user_id, title="VP Engineering", company="Acme",
                description_hash="hash1", fit_score=90, matched_track="vp",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["linkedin"], run_id=run.id,
            ))
            # Job from no run (legacy)
            s.add(Job(
                user_id=user_id, title="EM", company="Beta",
                description_hash="hash2", fit_score=80, matched_track="em",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"], run_id=None,
            ))
    return user_id


# --- is_new based on run_id ---

@pytest.mark.asyncio
async def test_is_new_based_on_run_id(client, auth_headers, user_with_run_and_jobs):
    """Job from latest run is_new=True, job without run_id is_new=False."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    assert resp.status_code == 200
    jobs = {j["company"]: j for j in resp.json()["jobs"]}
    assert jobs["Acme"]["is_new"] is True
    assert jobs["Beta"]["is_new"] is False


@pytest.mark.asyncio
async def test_is_new_older_run(client, auth_headers, session_factory, user_id):
    """Job from an older run is not new when a newer run exists."""
    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            run1 = Run(user_id=user_id, status="completed", created_at=now)
            s.add(run1)
            await s.flush()
            run1_id = run1.id

            run2 = Run(user_id=user_id, status="completed", created_at=now)
            s.add(run2)
            await s.flush()
            run2_id = run2.id

            s.add(Job(
                user_id=user_id, title="Old Job", company="OldCo",
                description_hash="old1", fit_score=85, matched_track="vp",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"], run_id=run1_id,
            ))
            s.add(Job(
                user_id=user_id, title="New Job", company="NewCo",
                description_hash="new1", fit_score=88, matched_track="vp",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"], run_id=run2_id,
            ))

    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = {j["company"]: j for j in resp.json()["jobs"]}
    assert jobs["OldCo"]["is_new"] is False
    assert jobs["NewCo"]["is_new"] is True


@pytest.mark.asyncio
async def test_is_new_no_runs(client, auth_headers, session_factory, user_id):
    """When no runs exist, all jobs have is_new=False."""
    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            s.add(Job(
                user_id=user_id, title="Orphan Job", company="OrphanCo",
                description_hash="orph1", fit_score=82, matched_track="em",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"],
            ))

    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["is_new"] is False


@pytest.mark.asyncio
async def test_is_new_running_run(client, auth_headers, session_factory, user_id):
    """Job scored in an in-progress run still shows as new."""
    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            run = Run(user_id=user_id, status="running", started_at=now, created_at=now)
            s.add(run)
            await s.flush()

            s.add(Job(
                user_id=user_id, title="In Progress", company="RunningCo",
                description_hash="run1", fit_score=91, matched_track="vp",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"], run_id=run.id,
            ))

    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["is_new"] is True


@pytest.mark.asyncio
async def test_is_new_ignores_failed_runs(client, auth_headers, session_factory, user_id):
    """Failed/cancelled runs don't count as 'latest'."""
    async with session_factory() as s:
        async with s.begin():
            now = datetime.now(timezone.utc)
            good_run = Run(user_id=user_id, status="completed", created_at=now)
            s.add(good_run)
            await s.flush()
            good_id = good_run.id

            bad_run = Run(user_id=user_id, status="failed", created_at=now)
            s.add(bad_run)
            await s.flush()
            bad_id = bad_run.id

            s.add(Job(
                user_id=user_id, title="Good Run Job", company="GoodCo",
                description_hash="g1", fit_score=85, matched_track="vp",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"], run_id=good_id,
            ))
            s.add(Job(
                user_id=user_id, title="Bad Run Job", company="BadCo",
                description_hash="b1", fit_score=80, matched_track="em",
                status="scored", first_seen=now, last_seen=now,
                sources_seen=["hn"], run_id=bad_id,
            ))

    resp = await client.get("/api/jobs", headers=auth_headers)
    jobs = {j["company"]: j for j in resp.json()["jobs"]}
    assert jobs["GoodCo"]["is_new"] is True
    assert jobs["BadCo"]["is_new"] is False


# --- viewed_at ---

@pytest.mark.asyncio
async def test_viewed_at_in_job_response(client, auth_headers, user_with_run_and_jobs):
    """Jobs include viewed_at field."""
    resp = await client.get("/api/jobs", headers=auth_headers)
    for job in resp.json()["jobs"]:
        assert "viewed_at" in job
        assert job["viewed_at"] is None  # not viewed yet


@pytest.mark.asyncio
async def test_viewed_at_set_on_view(client, auth_headers, user_with_run_and_jobs):
    """PATCH /api/jobs/{id}/view sets viewed_at."""
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    resp = await client.patch(f"/api/jobs/{job_id}/view", headers=auth_headers)
    assert resp.status_code == 204

    # Verify it was set
    detail = await client.get(f"/api/jobs/{job_id}", headers=auth_headers)
    assert detail.json()["viewed_at"] is not None


@pytest.mark.asyncio
async def test_viewed_at_idempotent(client, auth_headers, user_with_run_and_jobs):
    """Second PATCH doesn't change the timestamp."""
    listing = await client.get("/api/jobs", headers=auth_headers)
    job_id = listing.json()["jobs"][0]["id"]

    await client.patch(f"/api/jobs/{job_id}/view", headers=auth_headers)
    detail1 = await client.get(f"/api/jobs/{job_id}", headers=auth_headers)
    ts1 = detail1.json()["viewed_at"]

    await client.patch(f"/api/jobs/{job_id}/view", headers=auth_headers)
    detail2 = await client.get(f"/api/jobs/{job_id}", headers=auth_headers)
    ts2 = detail2.json()["viewed_at"]

    assert ts1 == ts2


@pytest.mark.asyncio
async def test_view_requires_auth(client):
    resp = await client.patch("/api/jobs/1/view")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_view_not_found(client, auth_headers):
    resp = await client.patch("/api/jobs/99999/view", headers=auth_headers)
    assert resp.status_code == 404
