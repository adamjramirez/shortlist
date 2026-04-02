"""Tests for POST /api/profile/generate — AI resume analysis."""
from io import BytesIO

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from shortlist.api.llm_client import FakeProfileGenerator
from shortlist.api.routes.profile import get_profile_generator

SAMPLE_TEX = b"\\documentclass{article}\n\\begin{document}\nSenior engineer with 8 years Python\n\\end{document}"


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


@pytest_asyncio.fixture
async def resume_id(client, auth_headers):
    """Upload a resume and return its ID."""
    files = {"file": ("test.tex", BytesIO(SAMPLE_TEX), "application/x-tex")}
    resp = await client.post("/api/resumes", files=files, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest_asyncio.fixture
async def profile_with_key(client, auth_headers):
    """Save a profile with an API key configured."""
    resp = await client.put(
        "/api/profile",
        json={"llm": {"model": "gemini-2.5-flash", "api_key": "test-key-123"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_generate_profile(client, auth_headers, resume_id, profile_with_key, fake_generator):
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fit_context"] == "Generated fit context from resume."
    assert "backend_engineer" in data["tracks"]
    assert data["filters"]["salary"]["min_base"] == 150000
    assert fake_generator.last_resume_text is not None
    assert "Senior engineer" in fake_generator.last_resume_text


@pytest.mark.asyncio
async def test_generate_no_api_key(client, auth_headers, resume_id, app):
    """Should fail if no API key is configured and no generator injected."""
    app.dependency_overrides[get_profile_generator] = lambda: None

    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_generate_resume_not_found(client, auth_headers, profile_with_key):
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": 999},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_does_not_save(client, auth_headers, resume_id, profile_with_key):
    """Generate returns suggestions without saving them."""
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    profile_resp = await client.get("/api/profile", headers=auth_headers)
    profile = profile_resp.json()
    assert profile["fit_context"] == ""


@pytest.mark.asyncio
async def test_generate_profile_429_error(client, auth_headers, resume_id, profile_with_key, app):
    """429 from LLM returns a helpful error message suggesting Gemini."""
    import httpx as httpx_mod

    class RateLimitedGenerator:
        async def generate_profile(self, resume_text: str) -> dict:
            resp = httpx_mod.Response(
                429, request=httpx_mod.Request("POST", "https://example.com")
            )
            raise httpx_mod.HTTPStatusError(
                "rate limited", request=resp.request, response=resp
            )

    app.dependency_overrides[get_profile_generator] = lambda: RateLimitedGenerator()
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 429
    detail = resp.json()["detail"].lower()
    assert "rate limit" in detail
    assert "gemini" in detail


@pytest.mark.asyncio
async def test_generate_profile_502_error(client, auth_headers, resume_id, profile_with_key, app):
    """Non-429 HTTP error from LLM returns 502 with status code."""
    import httpx as httpx_mod

    class ServerErrorGenerator:
        async def generate_profile(self, resume_text: str) -> dict:
            resp = httpx_mod.Response(
                503, request=httpx_mod.Request("POST", "https://example.com")
            )
            raise httpx_mod.HTTPStatusError(
                "service unavailable", request=resp.request, response=resp
            )

    app.dependency_overrides[get_profile_generator] = lambda: ServerErrorGenerator()
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 502
    assert "503" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_generate_unauthenticated(client):
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": 1},
    )
    assert resp.status_code == 401


@pytest_asyncio.fixture
async def pdf_resume_id(client, auth_headers):
    """Upload a PDF resume and return its ID."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "Senior engineer with 8 years Python", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, "Built data pipelines at scale", new_x="LMARGIN", new_y="NEXT")
    pdf_bytes = bytes(pdf.output())

    files = {"file": ("resume.pdf", BytesIO(pdf_bytes), "application/pdf")}
    resp = await client.post("/api/resumes", files=files, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_generate_profile_from_pdf(client, auth_headers, pdf_resume_id, profile_with_key, fake_generator):
    """Profile generation works with PDF resume — uses extracted text, not raw bytes."""
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": pdf_resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fit_context"] == "Generated fit context from resume."

    # FakeProfileGenerator captures the resume text it received
    assert fake_generator.last_resume_text is not None
    assert "Senior engineer" in fake_generator.last_resume_text
    # Should NOT contain raw PDF bytes
    assert "%PDF" not in fake_generator.last_resume_text
