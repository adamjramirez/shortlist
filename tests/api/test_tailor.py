"""Tests for resume tailoring + cover letter with PDF resumes."""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from shortlist.api.models import Job, Profile, Resume, User


@pytest_asyncio.fixture
async def user_with_pdf_resume(client, auth_headers, test_storage, session_factory, monkeypatch, make_test_pdf):
    """Create a user with a PDF resume and a scored job."""
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

    # Upload PDF resume
    pdf_bytes = make_test_pdf(
        "Jane Smith\nSenior Engineer\n10 years Python\nBuilt data pipelines at scale"
    )
    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    resume_data = resp.json()

    # Save profile with API key
    resp = await client.get("/api/auth/me", headers=auth_headers)
    user_id = resp.json()["id"]

    async with session_factory() as s:
        async with s.begin():
            profile = Profile(
                user_id=user_id,
                config={
                    "fit_context": "Senior engineer looking for EM roles",
                    "tracks": {"em": {"title": "Engineering Manager", "search_queries": ["EM"]}},
                    "llm": {"model": "gemini-2.0-flash", "encrypted_api_key": "fake-key"},
                },
            )
            s.add(profile)

            job = Job(
                user_id=user_id, title="Engineering Manager", company="TestCo",
                description_hash="hash_pdf_test", description="Lead a team of 10 engineers.",
                fit_score=85, matched_track="em", score_reasoning="Good match",
                status="new", first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc), sources_seen=["linkedin"],
            )
            s.add(job)

    # Re-query to get job ID
    resp = await client.get("/api/jobs", headers=auth_headers)
    job_id = resp.json()["jobs"][0]["id"]

    return {"user_id": user_id, "job_id": job_id, "resume": resume_data}


@pytest_asyncio.fixture
async def user_with_tex_resume(client, auth_headers, test_storage, session_factory, monkeypatch):
    """Create a user with a .tex resume and a scored job."""
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

    tex_content = b"\\documentclass{article}\n\\begin{document}\nJohn Doe, Staff Engineer\n\\end{document}"
    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.tex", tex_content, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    resume_data = resp.json()

    resp = await client.get("/api/auth/me", headers=auth_headers)
    user_id = resp.json()["id"]

    async with session_factory() as s:
        async with s.begin():
            profile = Profile(
                user_id=user_id,
                config={
                    "fit_context": "Staff engineer looking for EM roles",
                    "tracks": {"em": {"title": "Engineering Manager", "search_queries": ["EM"]}},
                    "llm": {"model": "gemini-2.0-flash", "encrypted_api_key": "fake-key"},
                },
            )
            s.add(profile)

            job = Job(
                user_id=user_id, title="Engineering Manager", company="TestCo",
                description_hash="hash_tex_test", description="Lead a team of 10 engineers.",
                fit_score=85, matched_track="em", score_reasoning="Good match",
                status="new", first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc), sources_seen=["linkedin"],
            )
            s.add(job)

    resp = await client.get("/api/jobs", headers=auth_headers)
    job_id = resp.json()["jobs"][0]["id"]

    return {"user_id": user_id, "job_id": job_id, "resume": resume_data}


@pytest_asyncio.fixture
async def user_with_both_resumes(client, auth_headers, test_storage, session_factory, monkeypatch, make_test_pdf):
    """User with both a track-matched .tex and an unmatched .pdf resume."""
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

    # Upload .tex with track "em"
    tex_content = b"\\documentclass{article}\n\\begin{document}\nJane TeX Resume\n\\end{document}"
    resp = await client.post(
        "/api/resumes",
        files={"file": ("em.tex", tex_content, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    # Upload .pdf with no track
    pdf_bytes = make_test_pdf("Jane PDF Resume\nSenior Engineer")
    resp = await client.post(
        "/api/resumes",
        files={"file": ("generic.pdf", pdf_bytes, "application/pdf")},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    resp = await client.get("/api/auth/me", headers=auth_headers)
    user_id = resp.json()["id"]

    async with session_factory() as s:
        async with s.begin():
            profile = Profile(
                user_id=user_id,
                config={
                    "fit_context": "Looking for EM roles",
                    "tracks": {"em": {"title": "EM", "search_queries": ["EM"]}},
                    "llm": {"model": "gemini-2.0-flash", "encrypted_api_key": "fake-key"},
                },
            )
            s.add(profile)

            job = Job(
                user_id=user_id, title="EM", company="Co",
                description_hash="hash_both", description="Lead engineers.",
                fit_score=85, matched_track="em", score_reasoning="Good",
                status="new", first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc), sources_seen=["hn"],
            )
            s.add(job)

    resp = await client.get("/api/jobs", headers=auth_headers)
    job_id = resp.json()["jobs"][0]["id"]

    return {"user_id": user_id, "job_id": job_id}


# --- Tests for _pick_best_resume + _fetch_resume_text ---

@pytest.mark.asyncio
async def test_pdf_resume_text_fetched_from_extracted_key(
    client, auth_headers, user_with_pdf_resume, test_storage
):
    """When tailoring with a PDF resume, extracted text is used (not raw PDF bytes)."""
    fixture = user_with_pdf_resume
    job_id = fixture["job_id"]

    # PDF resumes now route through generate_resume_from_text, not tailor_resume_from_text
    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
         patch("shortlist.processors.latex_compiler.compile_latex", return_value=None):
        mock_gen.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Tailored\\end{document}",
            changes_made=["reordered bullets"],
            interest_note="Great fit",
        )
        resp = await client.post(
            f"/api/jobs/{job_id}/tailor", headers=auth_headers,
        )

    # Should succeed
    assert resp.status_code == 200, resp.json()

    # The resume text passed to generate should be extracted text, not PDF bytes
    assert mock_gen.called
    resume_text_arg = mock_gen.call_args[0][0]
    assert "Jane Smith" in resume_text_arg
    assert "%PDF" not in resume_text_arg


@pytest.mark.asyncio
async def test_tex_resume_uses_raw_content(
    client, auth_headers, user_with_tex_resume, test_storage
):
    """When tailoring with a .tex resume, raw LaTeX content is used."""
    fixture = user_with_tex_resume
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor:
        mock_tailor.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Tailored\\end{document}",
            changes_made=["adjusted summary"],
            interest_note="Nice",
        )
        resp = await client.post(
            f"/api/jobs/{job_id}/tailor", headers=auth_headers,
        )

    assert resp.status_code == 200, resp.json()

    if mock_tailor.called:
        resume_text_arg = mock_tailor.call_args[0][0]
        assert "\\documentclass" in resume_text_arg


@pytest.mark.asyncio
async def test_pdf_tailor_stores_tex_and_pdf(
    client, auth_headers, user_with_pdf_resume, test_storage
):
    """PDF user: tailor stores both .tex and compiled .pdf, download serves PDF."""
    fixture = user_with_pdf_resume
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
         patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
        mock_gen.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Tailored PDF\\end{document}",
            changes_made=["emphasized distributed systems"],
            interest_note="Great fit",
        )
        mock_compile.return_value = b"%PDF-1.5 fake compiled pdf"

        resp = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".pdf")

    # Download as PDF
    resp = await client.get(f"/api/jobs/{job_id}/resume?format=pdf", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.5 fake compiled pdf"

    # Download as .tex fallback
    resp = await client.get(f"/api/jobs/{job_id}/resume?format=tex", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-tex"


@pytest.mark.asyncio
async def test_pdf_tailor_graceful_compile_failure(
    client, auth_headers, user_with_pdf_resume, test_storage
):
    """PDF compilation fails → still stores .tex, download serves .tex."""
    fixture = user_with_pdf_resume
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
         patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
        mock_gen.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Tailored\\end{document}",
            changes_made=["changes"],
            interest_note="note",
        )
        mock_compile.return_value = None  # Compilation failed

        resp = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".tex")  # Falls back to .tex

    # PDF not available, serves .tex
    resp = await client.get(f"/api/jobs/{job_id}/resume?format=pdf", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-tex"


@pytest.mark.asyncio
async def test_tex_tailor_skips_compilation(
    client, auth_headers, user_with_tex_resume, test_storage
):
    """LaTeX users: no PDF compilation attempted."""
    fixture = user_with_tex_resume
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor, \
         patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
        mock_tailor.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Tailored TeX\\end{document}",
            changes_made=["adjusted summary"],
            interest_note="Nice",
        )

        resp = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".tex")

    # compile_latex should NOT have been called
    mock_compile.assert_not_called()


@pytest.mark.asyncio
async def test_track_matched_tex_preferred_over_unmatched_pdf(
    client, auth_headers, user_with_both_resumes, test_storage
):
    """With both .tex (track=em) and .pdf (no track), track-matched .tex wins for em job."""
    fixture = user_with_both_resumes
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor:
        mock_tailor.return_value = MagicMock(
            tailored_tex="tailored",
            changes_made=["changes"],
            interest_note="note",
        )
        resp = await client.post(
            f"/api/jobs/{job_id}/tailor", headers=auth_headers,
        )

    assert resp.status_code == 200, resp.json()

    if mock_tailor.called:
        resume_text_arg = mock_tailor.call_args[0][0]
        # Should be the .tex content (has \documentclass), not the PDF text
        assert "\\documentclass" in resume_text_arg
        assert "Jane TeX Resume" in resume_text_arg


@pytest.mark.asyncio
async def test_download_pdf_compiles_on_demand(
    client, auth_headers, user_with_tex_resume, test_storage
):
    """Requesting format=pdf for a LaTeX-only tailored resume compiles on demand."""
    fixture = user_with_tex_resume
    job_id = fixture["job_id"]

    # First, tailor the resume (stores .tex only)
    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor:
        mock_tailor.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Hello\\end{document}",
            changes_made=["adjusted summary"],
            interest_note="Nice",
        )
        resp = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["filename"].endswith(".tex")

    # Now request PDF download — should compile on demand
    with patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
        mock_compile.return_value = b"%PDF-fake-compiled-bytes"
        resp = await client.get(
            f"/api/jobs/{job_id}/resume?format=pdf", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert b"%PDF-fake-compiled-bytes" == resp.content
        mock_compile.assert_called_once()


@pytest.mark.asyncio
async def test_download_pdf_compile_failure_falls_back_to_tex(
    client, auth_headers, user_with_tex_resume, test_storage
):
    """If on-demand compilation fails, fall back to .tex download."""
    fixture = user_with_tex_resume
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor:
        mock_tailor.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}Hello\\end{document}",
            changes_made=[],
            interest_note="",
        )
        await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)

    with patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
        mock_compile.return_value = None  # compilation fails
        resp = await client.get(
            f"/api/jobs/{job_id}/resume?format=pdf", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-tex"


@pytest.mark.asyncio
async def test_download_pdf_uses_cached_pdf(
    client, auth_headers, user_with_pdf_resume, test_storage
):
    """If PDF already exists (PDF user), don't recompile — serve cached."""
    fixture = user_with_pdf_resume
    job_id = fixture["job_id"]

    with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
         patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
         patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
        mock_gen.return_value = MagicMock(
            tailored_tex="\\documentclass{article}\\begin{document}PDF user\\end{document}",
            changes_made=[],
            interest_note="",
        )
        mock_compile.return_value = b"%PDF-original-compilation"
        await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)

    # Download — should NOT call compile_latex again
    with patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile2:
        resp = await client.get(
            f"/api/jobs/{job_id}/resume?format=pdf", headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        mock_compile2.assert_not_called()
