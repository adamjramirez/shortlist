"""Tests for resume routes."""
import pytest


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
async def test_upload_non_tex_rejected(client, auth_headers):
    resp = await client.post(
        "/api/resumes",
        files={"file": ("resume.pdf", b"fake pdf", "application/pdf")},
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
