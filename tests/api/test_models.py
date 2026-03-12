"""Tests for SQLAlchemy models."""
import pytest
from datetime import datetime, timezone

from shortlist.api.models import User, Profile, Run, Resume, Job, Company


@pytest.mark.asyncio
async def test_create_user(session):
    user = User(email="test@example.com", password_hash="hashed123")
    session.add(user)
    await session.flush()

    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_user_email_unique(session):
    user1 = User(email="dupe@example.com", password_hash="hash1")
    user2 = User(email="dupe@example.com", password_hash="hash2")
    session.add(user1)
    await session.flush()
    session.add(user2)
    with pytest.raises(Exception):  # IntegrityError
        await session.flush()


@pytest.mark.asyncio
async def test_create_profile(session):
    user = User(email="profile@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    profile = Profile(
        user_id=user.id,
        config={"fit_context": "Looking for EM roles", "tracks": {}},
    )
    session.add(profile)
    await session.flush()

    assert profile.config["fit_context"] == "Looking for EM roles"


@pytest.mark.asyncio
async def test_create_run(session):
    user = User(email="run@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    run = Run(user_id=user.id, status="pending")
    session.add(run)
    await session.flush()

    assert run.id is not None
    assert run.status == "pending"
    assert run.machine_id is None


@pytest.mark.asyncio
async def test_run_status_lifecycle(session):
    user = User(email="lifecycle@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    run = Run(user_id=user.id, status="pending")
    session.add(run)
    await session.flush()

    run.status = "running"
    run.started_at = datetime.now(timezone.utc)
    run.machine_id = "fly-abc123"
    run.progress = {"phase": "collecting", "jobs_found": 0}
    await session.flush()

    run.progress = {"phase": "scoring", "scored": 142, "total": 410}
    await session.flush()

    run.status = "completed"
    run.finished_at = datetime.now(timezone.utc)
    await session.flush()

    assert run.status == "completed"
    assert run.machine_id == "fly-abc123"


@pytest.mark.asyncio
async def test_create_resume(session):
    user = User(email="resume@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    resume = Resume(
        user_id=user.id,
        filename="my_resume.tex",
        track="em",
        s3_key=f"{user.id}/resumes/my_resume.tex",
    )
    session.add(resume)
    await session.flush()

    assert resume.id is not None
    assert resume.s3_key.endswith("my_resume.tex")


@pytest.mark.asyncio
async def test_resume_type_defaults_to_tex(session):
    user = User(email="rtype@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    resume = Resume(
        user_id=user.id, filename="cv.tex",
        s3_key=f"{user.id}/resumes/cv.tex",
    )
    session.add(resume)
    await session.flush()

    assert resume.resume_type == "tex"
    assert resume.extracted_text_key is None


@pytest.mark.asyncio
async def test_resume_pdf_type_with_extracted_text(session):
    user = User(email="rpdf@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    resume = Resume(
        user_id=user.id, filename="cv.pdf",
        s3_key=f"{user.id}/resumes/cv.pdf",
        resume_type="pdf",
        extracted_text_key=f"{user.id}/resumes/cv.pdf.txt",
    )
    session.add(resume)
    await session.flush()

    assert resume.resume_type == "pdf"
    assert resume.extracted_text_key == f"{user.id}/resumes/cv.pdf.txt"


@pytest.mark.asyncio
async def test_job_tailored_resume_pdf_key(session):
    user = User(email="jpdf@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    job = Job(
        user_id=user.id, title="SRE", company="Co",
        description_hash="hash1",
        tailored_resume_key=f"{user.id}/tailored/1.tex",
        tailored_resume_pdf_key=f"{user.id}/tailored/1.pdf",
    )
    session.add(job)
    await session.flush()

    assert job.tailored_resume_pdf_key == f"{user.id}/tailored/1.pdf"


@pytest.mark.asyncio
async def test_create_job(session):
    user = User(email="job@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    job = Job(
        user_id=user.id,
        title="VP Engineering",
        company="Acme Corp",
        description_hash="abc123",
        fit_score=87,
        matched_track="vp",
        score_reasoning="Strong match",
        sources_seen=["linkedin", "hn"],
    )
    session.add(job)
    await session.flush()

    assert job.id is not None
    assert job.fit_score == 87
    assert job.sources_seen == ["linkedin", "hn"]


@pytest.mark.asyncio
async def test_job_unique_per_user_hash(session):
    user = User(email="unique@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    job1 = Job(user_id=user.id, title="Job 1", company="Co", description_hash="same_hash")
    session.add(job1)
    await session.flush()

    job2 = Job(user_id=user.id, title="Job 2", company="Co", description_hash="same_hash")
    session.add(job2)
    with pytest.raises(Exception):  # IntegrityError
        await session.flush()


@pytest.mark.asyncio
async def test_create_company(session):
    user = User(email="company@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    company = Company(
        user_id=user.id,
        name="Acme Corp",
        name_normalized="acme corp",
        domain="acme.com",
        stage="Series B",
        headcount=120,
    )
    session.add(company)
    await session.flush()

    assert company.id is not None
    assert company.stage == "Series B"


@pytest.mark.asyncio
async def test_user_relationships(session):
    user = User(email="rels@example.com", password_hash="hash")
    session.add(user)
    await session.flush()

    profile = Profile(user_id=user.id, config={"name": "Test"})
    session.add(profile)

    run = Run(user_id=user.id, status="pending")
    session.add(run)

    resume = Resume(
        user_id=user.id, filename="cv.tex", s3_key=f"{user.id}/resumes/cv.tex"
    )
    session.add(resume)
    await session.flush()

    await session.refresh(user, ["profile", "runs", "resumes"])

    assert user.profile is not None
    assert user.profile.config["name"] == "Test"
    assert len(user.runs) == 1
    assert len(user.resumes) == 1
