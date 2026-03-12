"""End-to-end tests for PDF resume support.

Tests the full user journey:
1. Sign up → upload PDF resume → verify extraction
2. Generate profile from PDF → verify extracted text used (not raw bytes)
3. Tailor resume for a job → verify generate_resume_from_text called (not tailor_resume_from_text)
4. Download tailored resume as PDF and .tex
5. Cover letter uses extracted PDF text
6. LaTeX user parallel path → verify tailor_resume_from_text called, no compilation

Also tests edge cases:
- Upload PDF with no extractable text → 400
- Upload .doc → 400
- Track-matched .tex preferred over unmatched .pdf
- Compilation failure → graceful degradation to .tex
"""
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch, MagicMock

from cryptography.fernet import Fernet

from shortlist.api.llm_client import FakeProfileGenerator
from shortlist.api.models import Job, Profile
from shortlist.api.routes.profile import get_profile_generator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf(text: str) -> bytes:
    """Create a real PDF with extractable text."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.split("\n"):
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


RESUME_TEXT = """Jane Smith
Senior Software Engineer
jane@example.com | 555-0123 | San Francisco, CA

Experience:
Staff Engineer at ScaleCo (2021-2024)
- Architected distributed event processing system handling 50M events/day
- Led migration from monolith to microservices, reducing deploy time 80%
- Mentored 6 junior engineers, 3 promoted within 18 months

Senior Engineer at DataCorp (2018-2021)
- Built real-time analytics pipeline processing 2TB/day
- Reduced infrastructure costs 40% through query optimization

Education:
BS Computer Science, Stanford University, 2018

Skills: Python, Go, Kubernetes, PostgreSQL, Redis, Kafka, AWS"""

SAMPLE_TEX = rb"""\documentclass{article}
\begin{document}
\textbf{John Doe} --- Staff Engineer

\section{Experience}
\textbf{Principal Engineer at MegaCorp (2019-2024)}
\begin{itemize}
\item Led platform team of 12 engineers
\item Shipped zero-downtime deployment system
\end{itemize}

\section{Skills}
Python, Java, Terraform, AWS
\end{document}"""

JOB_DESCRIPTION = """We're looking for a Senior Backend Engineer to lead our
data platform team. You'll architect distributed systems processing millions
of events per day, mentor junior engineers, and drive technical strategy.
Requirements: 5+ years Python, distributed systems experience, team leadership."""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from shortlist.api.crypto import _get_fernet
    _get_fernet.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture()
def fake_generator():
    return FakeProfileGenerator()


@pytest.fixture(autouse=True)
def override_generator(app, fake_generator):
    app.dependency_overrides[get_profile_generator] = lambda: fake_generator
    yield
    app.dependency_overrides.pop(get_profile_generator, None)


async def _create_job(session_factory, user_id: int, title: str = "Senior Backend Engineer",
                      company: str = "EventCo", track: str = "backend_engineer") -> int:
    """Insert a scored job and return its ID."""
    async with session_factory() as s:
        async with s.begin():
            job = Job(
                user_id=user_id, title=title, company=company,
                description_hash=f"hash_{company}_{title}".replace(" ", "_"),
                description=JOB_DESCRIPTION,
                fit_score=88, matched_track=track,
                score_reasoning="Strong match on distributed systems and leadership",
                status="new",
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                sources_seen=["hn"],
            )
            s.add(job)
    return 1  # first job in test DB


async def _save_profile(session_factory, user_id: int,
                        tracks: dict | None = None):
    """Save a profile with API key so tailor/cover-letter endpoints work."""
    async with session_factory() as s:
        async with s.begin():
            profile = Profile(
                user_id=user_id,
                config={
                    "fit_context": "Senior engineer with distributed systems expertise",
                    "tracks": tracks or {
                        "backend_engineer": {
                            "title": "Backend Engineer",
                            "search_queries": ["backend engineer"],
                        }
                    },
                    "llm": {"model": "gemini-2.0-flash", "encrypted_api_key": "fake-key"},
                },
            )
            s.add(profile)


# ---------------------------------------------------------------------------
# E2E: PDF user full journey
# ---------------------------------------------------------------------------

class TestPDFUserJourney:
    """Full journey: signup → upload PDF → generate profile → tailor → download."""

    @pytest_asyncio.fixture
    async def setup(self, client, auth_headers, session_factory, monkeypatch, test_storage):
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

        # Get user ID
        resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = resp.json()["id"]

        return {
            "client": client,
            "headers": auth_headers,
            "user_id": user_id,
            "session_factory": session_factory,
            "storage": test_storage,
        }

    @pytest.mark.asyncio
    async def test_step1_upload_pdf(self, setup):
        """Upload PDF resume → 201, resume_type=pdf, text extracted."""
        c, h = setup["client"], setup["headers"]

        pdf_bytes = _make_pdf(RESUME_TEXT)
        resp = await c.post(
            "/api/resumes",
            files={"file": ("jane-smith-resume.pdf", pdf_bytes, "application/pdf")},
            data={"track": "backend_engineer"},
            headers=h,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "jane-smith-resume.pdf"
        assert data["resume_type"] == "pdf"
        assert data["track"] == "backend_engineer"

    @pytest.mark.asyncio
    async def test_step2_profile_from_pdf(self, setup, fake_generator):
        """Generate profile from PDF → uses extracted text, not raw bytes."""
        c, h = setup["client"], setup["headers"]

        # Upload
        pdf_bytes = _make_pdf(RESUME_TEXT)
        resp = await c.post(
            "/api/resumes",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            headers=h,
        )
        resume_id = resp.json()["id"]

        # Save profile with API key
        await _save_profile(setup["session_factory"], setup["user_id"])

        # Generate
        resp = await c.post(
            "/api/profile/generate",
            json={"resume_id": resume_id},
            headers=h,
        )
        assert resp.status_code == 200

        # Verify extracted text was used
        assert fake_generator.last_resume_text is not None
        assert "Jane Smith" in fake_generator.last_resume_text
        assert "ScaleCo" in fake_generator.last_resume_text
        assert "%PDF" not in fake_generator.last_resume_text

    @pytest.mark.asyncio
    async def test_step3_tailor_pdf_resume(self, setup):
        """Tailor for PDF user → generate_resume_from_text, compile to PDF."""
        c, h = setup["client"], setup["headers"]

        # Upload PDF
        pdf_bytes = _make_pdf(RESUME_TEXT)
        resp = await c.post(
            "/api/resumes",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            data={"track": "backend_engineer"},
            headers=h,
        )
        assert resp.status_code == 201

        # Create job + profile
        await _save_profile(setup["session_factory"], setup["user_id"])
        job_id = await _create_job(setup["session_factory"], setup["user_id"])

        # Tailor with mocked LLM + compiler
        with patch("shortlist.api.routes.tailor._configure_llm"), \
             patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:

            mock_gen.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}Tailored for EventCo\end{document}",
                changes_made=["Emphasized distributed systems", "Led with event processing experience"],
                interest_note="Jane's experience with 50M events/day directly applies.",
            )
            mock_compile.return_value = b"%PDF-1.5 compiled resume for EventCo"

            resp = await c.post(f"/api/jobs/{job_id}/tailor", headers=h)

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".pdf")
        assert len(data["changes_made"]) == 2
        assert "distributed systems" in data["changes_made"][0].lower()

        # Verify generate was called with extracted text (not tailor)
        assert mock_gen.called
        text_arg = mock_gen.call_args[0][0]
        assert "Jane Smith" in text_arg
        assert "50M events" in text_arg

    @pytest.mark.asyncio
    async def test_step4_download_pdf_and_tex(self, setup):
        """After tailoring, download as PDF (default) and .tex (fallback)."""
        c, h = setup["client"], setup["headers"]

        # Upload + create job + profile
        pdf_bytes = _make_pdf(RESUME_TEXT)
        await c.post(
            "/api/resumes",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            data={"track": "backend_engineer"},
            headers=h,
        )
        await _save_profile(setup["session_factory"], setup["user_id"])
        job_id = await _create_job(setup["session_factory"], setup["user_id"])

        # Tailor
        with patch("shortlist.api.routes.tailor._configure_llm"), \
             patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
            mock_gen.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}Tailored\end{document}",
                changes_made=[], interest_note="",
            )
            mock_compile.return_value = b"%PDF-1.5 the compiled PDF content"
            await c.post(f"/api/jobs/{job_id}/tailor", headers=h)

        # Download PDF (default)
        resp = await c.get(f"/api/jobs/{job_id}/resume", headers=h)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert b"%PDF-1.5" in resp.content
        assert "tailored-eventco.pdf" in resp.headers["content-disposition"]

        # Download .tex
        resp = await c.get(f"/api/jobs/{job_id}/resume?format=tex", headers=h)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-tex"
        assert b"\\documentclass" in resp.content

    @pytest.mark.asyncio
    async def test_step5_cover_letter_uses_extracted_text(self, setup):
        """Cover letter endpoint uses extracted PDF text, not raw bytes."""
        c, h = setup["client"], setup["headers"]

        # Upload PDF
        pdf_bytes = _make_pdf(RESUME_TEXT)
        await c.post(
            "/api/resumes",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            data={"track": "backend_engineer"},
            headers=h,
        )
        await _save_profile(setup["session_factory"], setup["user_id"])
        job_id = await _create_job(setup["session_factory"], setup["user_id"])

        with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
             patch("shortlist.processors.cover_letter.generate_cover_letter") as mock_cl:
            mock_cl.return_value = "Dear Hiring Manager,\n\nI am excited about this role..."

            resp = await c.post(f"/api/jobs/{job_id}/cover-letter", headers=h)

        assert resp.status_code == 200
        assert mock_cl.called
        # resume_tex kwarg should be extracted text
        resume_arg = mock_cl.call_args.kwargs.get("resume_tex", "")
        assert "Jane Smith" in resume_arg
        assert "%PDF" not in resume_arg


# ---------------------------------------------------------------------------
# E2E: LaTeX user parallel path
# ---------------------------------------------------------------------------

class TestLaTeXUserJourney:
    """LaTeX users get surgical edits, no compilation."""

    @pytest_asyncio.fixture
    async def setup(self, client, auth_headers, session_factory, monkeypatch, test_storage):
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
        resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = resp.json()["id"]
        return {
            "client": client, "headers": auth_headers,
            "user_id": user_id, "session_factory": session_factory,
        }

    @pytest.mark.asyncio
    async def test_tex_upload_and_tailor(self, setup):
        """LaTeX user: surgical edit via tailor_resume_from_text, no compilation."""
        c, h = setup["client"], setup["headers"]

        # Upload .tex
        resp = await c.post(
            "/api/resumes",
            files={"file": ("resume.tex", SAMPLE_TEX, "application/x-tex")},
            data={"track": "backend_engineer"},
            headers=h,
        )
        assert resp.status_code == 201
        assert resp.json()["resume_type"] == "tex"

        await _save_profile(setup["session_factory"], setup["user_id"])
        job_id = await _create_job(setup["session_factory"], setup["user_id"])

        with patch("shortlist.api.routes.tailor._configure_llm"), \
             patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
            mock_tailor.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}Surgically edited\end{document}",
                changes_made=["Reordered bullets to lead with platform work"],
                interest_note="John's platform experience is a perfect fit.",
            )

            resp = await c.post(f"/api/jobs/{job_id}/tailor", headers=h)

        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".tex")  # Not .pdf

        # tailor_resume_from_text was called (not generate_resume_from_text)
        assert mock_tailor.called
        tex_arg = mock_tailor.call_args[0][0]
        assert "\\documentclass" in tex_arg
        assert "John Doe" in tex_arg

        # compile_latex was NOT called
        mock_compile.assert_not_called()

        # Download serves .tex
        resp = await c.get(f"/api/jobs/{job_id}/resume", headers=h)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-tex"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestPDFEdgeCases:

    @pytest.mark.asyncio
    async def test_empty_pdf_rejected(self, client, auth_headers, monkeypatch):
        """PDF with no extractable text → 400."""
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
        # Minimal valid PDF with no text content
        from fpdf import FPDF
        pdf = FPDF()
        pdf.add_page()  # blank page
        empty_pdf = bytes(pdf.output())

        resp = await client.post(
            "/api/resumes",
            files={"file": ("empty.pdf", empty_pdf, "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "extract" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_doc_file_rejected(self, client, auth_headers, monkeypatch):
        """.doc files are rejected."""
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
        resp = await client.post(
            "/api/resumes",
            files={"file": ("resume.doc", b"fake doc", "application/msword")},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert ".tex and .pdf" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_docx_file_rejected(self, client, auth_headers, monkeypatch):
        """.docx files are rejected."""
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
        resp = await client.post(
            "/api/resumes",
            files={"file": ("resume.docx", b"fake docx", "application/vnd.openxmlformats")},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_compilation_failure_graceful(self, client, auth_headers, session_factory,
                                                 monkeypatch, test_storage):
        """PDF compile fails → .tex still available, no 500."""
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

        # Upload PDF
        pdf_bytes = _make_pdf("Jane Smith\nEngineer")
        resp = await client.post(
            "/api/resumes",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            data={"track": "be"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = resp.json()["id"]
        await _save_profile(session_factory, user_id, tracks={
            "be": {"title": "BE", "search_queries": ["be"]}
        })
        job_id = await _create_job(session_factory, user_id, track="be")

        with patch("shortlist.api.routes.tailor._configure_llm"), \
             patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
            mock_gen.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}X\end{document}",
                changes_made=[], interest_note="",
            )
            mock_compile.return_value = None  # Compilation fails!

            resp = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)

        # Should still succeed
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"].endswith(".tex")  # Fallback to .tex

        # .tex download works
        resp = await client.get(f"/api/jobs/{job_id}/resume?format=tex", headers=auth_headers)
        assert resp.status_code == 200
        assert b"\\documentclass" in resp.content

        # PDF download falls back to .tex
        resp = await client.get(f"/api/jobs/{job_id}/resume?format=pdf", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/x-tex"

    @pytest.mark.asyncio
    async def test_track_match_prefers_tex_over_pdf(self, client, auth_headers,
                                                      session_factory, monkeypatch, test_storage):
        """With track-matched .tex and unmatched .pdf, .tex wins."""
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

        # Upload .tex with track
        await client.post(
            "/api/resumes",
            files={"file": ("backend.tex", SAMPLE_TEX, "application/x-tex")},
            data={"track": "backend_engineer"},
            headers=auth_headers,
        )

        # Upload .pdf without track
        pdf_bytes = _make_pdf("Jane Smith\nGeneric Resume")
        await client.post(
            "/api/resumes",
            files={"file": ("generic.pdf", pdf_bytes, "application/pdf")},
            headers=auth_headers,
        )

        resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = resp.json()["id"]
        await _save_profile(session_factory, user_id)
        job_id = await _create_job(session_factory, user_id)

        with patch("shortlist.api.routes.tailor._configure_llm"), \
             patch("shortlist.processors.resume.tailor_resume_from_text") as mock_tailor, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
            mock_tailor.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}Tailored TeX\end{document}",
                changes_made=[], interest_note="",
            )

            resp = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)

        assert resp.status_code == 200
        # Should have used tailor (tex path), not generate (pdf path)
        assert mock_tailor.called
        tex_arg = mock_tailor.call_args[0][0]
        assert "John Doe" in tex_arg  # From SAMPLE_TEX
        mock_compile.assert_not_called()

    @pytest.mark.asyncio
    async def test_retailor_returns_cached(self, client, auth_headers, session_factory,
                                            monkeypatch, test_storage):
        """Calling tailor twice returns cached result, doesn't re-generate."""
        monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

        pdf_bytes = _make_pdf(RESUME_TEXT)
        await client.post(
            "/api/resumes",
            files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
            data={"track": "backend_engineer"},
            headers=auth_headers,
        )

        resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = resp.json()["id"]
        await _save_profile(session_factory, user_id)
        job_id = await _create_job(session_factory, user_id)

        # First tailor
        with patch("shortlist.api.routes.tailor._configure_llm"), \
             patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
            mock_gen.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}Tailored\end{document}",
                changes_made=["change"], interest_note="note",
            )
            mock_compile.return_value = b"%PDF-1.5 compiled"
            resp1 = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)

        assert resp1.status_code == 200
        assert mock_gen.call_count == 1

        # Second tailor — should be cached
        with patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen2:
            resp2 = await client.post(f"/api/jobs/{job_id}/tailor", headers=auth_headers)

        assert resp2.status_code == 200
        mock_gen2.assert_not_called()  # Cached, no re-generation
        assert resp2.json()["filename"].endswith(".pdf")  # Still knows it has PDF
