"""Tests for PDF extraction quality across diverse resume formats.

Tests real PDFs compiled from LaTeX (XeLaTeX + custom fonts) and
synthetic PDFs simulating common resume layouts:
- Single column, clean formatting
- Minimal/prose style (paragraphs, not bullets)
- Dense, information-heavy (ML engineer, multi-role)
- Two-column layout (skills sidebar + experience)
- XeLaTeX with custom fonts (EB Garamond, Lato) — known spacing issues

Each PDF is tested for:
1. Upload succeeds (201, text extracted)
2. Extracted text contains key facts (name, companies, skills)
3. Profile generation receives extracted text (not raw bytes)
4. Tailoring works end-to-end
"""
import os
from pathlib import Path

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from cryptography.fernet import Fernet

from shortlist.api.llm_client import FakeProfileGenerator
from shortlist.api.models import Job, Profile
from shortlist.api.routes.profile import get_profile_generator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "cv-pdfs"


# ---------------------------------------------------------------------------
# Expected content per PDF — what we expect extraction to capture
# ---------------------------------------------------------------------------

PDF_EXPECTATIONS = {
    # Real XeLaTeX CVs — PyMuPDF handles custom fonts (EB Garamond, Lato) cleanly
    "adam_ramirez_cv_ai_builder.pdf": {
        "min_chars": 1500,
        "must_contain": ["Adam Joseph Ramirez", "Universal Music Group", "Engineering leader"],
        "should_contain": ["Dallas", "YOLOv8", "AI", "FAISS", "FishML"],
        "known_issues": [],
    },
    "adam_ramirez_cv_enterprise.pdf": {
        "min_chars": 1500,
        "must_contain": ["Adam Joseph Ramirez", "Universal Music Group", "Engineering leader"],
        "should_contain": ["Dallas", "AWS migration", "budget"],
        "known_issues": [],
    },
    "adam_ramirez_cv_growth.pdf": {
        "min_chars": 1500,
        "must_contain": ["Adam Joseph Ramirez", "Universal Music Group"],
        "should_contain": ["App Store", "FishML", "Dallas"],
        "known_issues": [],
    },
    "adam_ramirez_cv_technical.pdf": {
        "min_chars": 1500,
        "must_contain": ["Adam Joseph Ramirez", "Universal Music Group"],
        "should_contain": ["YOLOv8", "FAISS", "RAG"],
        "known_issues": [],
    },
    # Synthetic PDFs — clean extraction expected
    "simple_single_column.pdf": {
        "min_chars": 400,
        "must_contain": ["Sarah Chen", "DataFlow", "100M events", "Staff Engineer"],
        "should_contain": ["Kubernetes", "PostgreSQL", "UC Berkeley"],
        "known_issues": [],
    },
    "minimal_prose.pdf": {
        "min_chars": 500,
        "must_contain": ["Marcus Johnson", "RocketData", "VP Engineering"],
        "should_contain": ["distributed systems", "Austin"],
        "known_issues": [],
    },
    "dense_ml_engineer.pdf": {
        "min_chars": 1200,
        "must_contain": ["Priya Patel", "PhD", "MetaSearch", "CMU"],
        "should_contain": ["PyTorch", "NeurIPS", "500M", "transformer"],
        "known_issues": [],
    },
    "two_column_simulated.pdf": {
        "min_chars": 600,
        "must_contain": ["Alex Rivera", "TechFlow", "Python"],
        "should_contain": ["Kubernetes", "event-driven", "Seattle"],
        "known_issues": ["columns merge into single lines"],
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    from shortlist.api.crypto import _get_fernet
    _get_fernet.cache_clear()
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")


@pytest.fixture()
def fake_generator():
    return FakeProfileGenerator()


@pytest.fixture(autouse=True)
def override_generator(app, fake_generator):
    app.dependency_overrides[get_profile_generator] = lambda: fake_generator
    yield
    app.dependency_overrides.pop(get_profile_generator, None)


def _load_pdf(name: str) -> bytes:
    path = FIXTURES_DIR / name
    assert path.exists(), f"Fixture not found: {path}"
    return path.read_bytes()


async def _create_job(session_factory, user_id, track="backend_engineer"):
    async with session_factory() as s:
        async with s.begin():
            job = Job(
                user_id=user_id, title="Senior Backend Engineer", company="TestCo",
                description_hash=f"hash_{user_id}_{track}",
                description="Build distributed systems. 5+ years Python required.",
                fit_score=85, matched_track=track,
                score_reasoning="Strong match", status="new",
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                sources_seen=["test"],
            )
            s.add(job)


async def _save_profile(session_factory, user_id):
    async with session_factory() as s:
        async with s.begin():
            profile = Profile(
                user_id=user_id,
                config={
                    "fit_context": "Senior engineer",
                    "tracks": {"backend_engineer": {"title": "BE", "search_queries": ["be"]}},
                    "llm": {"model": "gemini-2.0-flash", "encrypted_api_key": "fake"},
                },
            )
            s.add(profile)


# ---------------------------------------------------------------------------
# Parametrized: upload + extraction quality for every PDF
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_name", list(PDF_EXPECTATIONS.keys()))
class TestPDFUploadAndExtraction:

    @pytest.mark.asyncio
    async def test_upload_succeeds(self, pdf_name, client, auth_headers):
        """Every PDF format uploads successfully."""
        pdf_bytes = _load_pdf(pdf_name)
        resp = await client.post(
            "/api/resumes",
            files={"file": (pdf_name, pdf_bytes, "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"{pdf_name}: {resp.json()}"
        data = resp.json()
        assert data["resume_type"] == "pdf"
        assert data["filename"] == pdf_name

    @pytest.mark.asyncio
    async def test_extraction_quality(self, pdf_name, client, auth_headers, test_storage):
        """Extracted text meets minimum quality bar for each format."""
        expect = PDF_EXPECTATIONS[pdf_name]
        pdf_bytes = _load_pdf(pdf_name)

        resp = await client.post(
            "/api/resumes",
            files={"file": (pdf_name, pdf_bytes, "application/pdf")},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # Read extracted text from storage
        resp_data = resp.json()
        user_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = user_resp.json()["id"]
        txt_key = f"{user_id}/resumes/{pdf_name}.txt"
        extracted_bytes = await test_storage.get(txt_key)
        text = extracted_bytes.decode("utf-8")

        # Minimum length
        assert len(text) >= expect["min_chars"], (
            f"{pdf_name}: extracted only {len(text)} chars, expected >= {expect['min_chars']}"
        )

        # Must-have content (case-insensitive search to handle spacing issues)
        text_lower = text.lower()
        for term in expect["must_contain"]:
            assert term.lower() in text_lower, (
                f"{pdf_name}: must_contain '{term}' not found in extracted text"
            )

        # Should-have content (warn but don't fail — may be glued)
        missing_should = []
        for term in expect.get("should_contain", []):
            # Check both with and without spaces (handles glued text)
            term_nospace = term.lower().replace(" ", "")
            if term.lower() not in text_lower and term_nospace not in text_lower:
                missing_should.append(term)

        if missing_should and not expect.get("known_issues"):
            pytest.fail(
                f"{pdf_name}: should_contain terms missing: {missing_should}"
            )


# ---------------------------------------------------------------------------
# Parametrized: full tailor pipeline for every PDF
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pdf_name", list(PDF_EXPECTATIONS.keys()))
class TestPDFTailorPipeline:

    @pytest.mark.asyncio
    async def test_tailor_with_format(self, pdf_name, client, auth_headers,
                                       session_factory, test_storage):
        """Each PDF format can be tailored end-to-end."""
        pdf_bytes = _load_pdf(pdf_name)

        # Upload
        resp = await client.post(
            "/api/resumes",
            files={"file": (pdf_name, pdf_bytes, "application/pdf")},
            data={"track": "backend_engineer"},
            headers=auth_headers,
        )
        assert resp.status_code == 201

        # Setup
        user_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = user_resp.json()["id"]
        await _save_profile(session_factory, user_id)
        await _create_job(session_factory, user_id)

        # Tailor
        with patch("shortlist.api.routes.tailor._configure_llm", return_value="gemini-2.0-flash"), \
             patch("shortlist.processors.resume.generate_resume_from_text") as mock_gen, \
             patch("shortlist.processors.latex_compiler.compile_latex") as mock_compile:
            mock_gen.return_value = MagicMock(
                tailored_tex=r"\documentclass{article}\begin{document}Tailored\end{document}",
                changes_made=["Reordered for relevance"],
                interest_note="Good fit",
            )
            mock_compile.return_value = b"%PDF-1.5 compiled"

            resp = await client.post("/api/jobs/1/tailor", headers=auth_headers)

        assert resp.status_code == 200, f"{pdf_name}: tailor failed: {resp.json()}"

        # Verify generate_resume_from_text got extracted text, not PDF bytes
        assert mock_gen.called, f"{pdf_name}: generate_resume_from_text not called"
        text_arg = mock_gen.call_args[0][0]
        assert "%PDF" not in text_arg, f"{pdf_name}: raw PDF bytes leaked to LLM"
        assert len(text_arg) > 100, f"{pdf_name}: extracted text too short ({len(text_arg)} chars)"

    @pytest.mark.asyncio
    async def test_profile_gen_with_format(self, pdf_name, client, auth_headers,
                                            session_factory, fake_generator):
        """Each PDF format works with profile generation."""
        pdf_bytes = _load_pdf(pdf_name)

        resp = await client.post(
            "/api/resumes",
            files={"file": (pdf_name, pdf_bytes, "application/pdf")},
            headers=auth_headers,
        )
        resume_id = resp.json()["id"]

        user_resp = await client.get("/api/auth/me", headers=auth_headers)
        user_id = user_resp.json()["id"]
        await _save_profile(session_factory, user_id)

        resp = await client.post(
            "/api/profile/generate",
            json={"resume_id": resume_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200, f"{pdf_name}: profile gen failed: {resp.json()}"

        # Verify extracted text was used
        assert fake_generator.last_resume_text is not None
        assert "%PDF" not in fake_generator.last_resume_text
        assert len(fake_generator.last_resume_text) > 100
