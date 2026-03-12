"""Tests for resume routes."""
import pytest


def _make_test_pdf(text: str) -> bytes:
    """Create a minimal valid PDF with extractable text."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in text.split("\n"):
        pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
    return pdf.output()


@pytest.mark.asyncio
async def test_upload_resume(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
    content = b"\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}"
    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.tex", content, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "resume.tex"
    assert data["track"] == "em"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_resumes(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
    content = b"\\documentclass{article}\n\\begin{document}\nTest\n\\end{document}"
    await client.post(
        "/api/resumes",
        files={"file": ("em.tex", content, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    await client.post(
        "/api/resumes",
        files={"file": ("vp.tex", content, "application/x-tex")},
        data={"track": "vp"},
        headers=auth_headers,
    )

    resp = await client.get("/api/resumes", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_delete_resume(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
    content = b"\\documentclass{article}\n\\begin{document}\nDel\n\\end{document}"
    upload = await client.post(
        "/api/resumes",
        files={"file": ("del.tex", content, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    resume_id = upload.json()["id"]

    resp = await client.delete(f"/api/resumes/{resume_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Should be gone from list
    resp = await client.get("/api/resumes", headers=auth_headers)
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_upload_tex_returns_resume_type(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
    content = b"\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}"
    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.tex", content, "application/x-tex")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["resume_type"] == "tex"


@pytest.mark.asyncio
async def test_upload_pdf_resume(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

    pdf_bytes = bytes(_make_test_pdf("Adam Ramirez\nSenior Engineering Manager\n8 years Python"))

    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", pdf_bytes, "application/pdf")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["filename"] == "resume.pdf"
    assert data["resume_type"] == "pdf"


@pytest.mark.asyncio
async def test_upload_empty_pdf_rejected(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")

    # A PDF with no extractable text (just header bytes)
    resp = await client.post(
        "/api/resumes",
        files={"file": ("empty.pdf", b"%PDF-1.4 empty", "application/pdf")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_non_tex_or_pdf_rejected(client, auth_headers):
    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.doc", b"fake doc", "application/msword")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_too_large_rejected(client, auth_headers):
    big = b"x" * (1024 * 1024 + 1)  # > 1MB
    resp = await client.post(
        "/api/resumes",
        files={"file": ("big.tex", big, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_other_users_resume(client, auth_headers, monkeypatch):
    monkeypatch.setenv("TIGRIS_BUCKET", "test-bucket")
    content = b"\\documentclass{article}\n\\begin{document}\nMine\n\\end{document}"
    upload = await client.post(
        "/api/resumes",
        files={"file": ("mine.tex", content, "application/x-tex")},
        data={"track": "em"},
        headers=auth_headers,
    )
    resume_id = upload.json()["id"]

    # Sign up as different user
    resp = await client.post("/api/auth/signup", json={
        "email": "other@example.com",
        "password": "pass123",
    })
    other_headers = {"Authorization": f"Bearer {resp.json()['token']}"}

    # Should not be able to delete
    resp = await client.delete(f"/api/resumes/{resume_id}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resumes_require_auth(client):
    assert (await client.get("/api/resumes")).status_code == 401
    assert (await client.post("/api/resumes", files={"file": ("x.tex", b"x", "text/plain")})).status_code == 401
