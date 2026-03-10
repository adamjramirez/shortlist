"""Tests for resume matching and tailoring."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from shortlist.processors.resume import (
    select_resume, tailor_resume, save_tailored_resume,
    TailoredResume, _extract_summary, _parse_json,
)
from shortlist.config import Config, Track


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    monkeypatch.setattr("shortlist.http._wait", lambda _: None)


@pytest.fixture
def config_single_resume():
    return Config(
        name="Adam",
        tracks={
            "em": Track(title="Engineering Manager", resume="resumes/em.tex"),
            "ai": Track(title="AI Engineering", resume="resumes/ai.tex"),
        },
    )


@pytest.fixture
def config_multi_resume():
    return Config(
        name="Adam",
        tracks={
            "vp": Track(
                title="VP Engineering",
                resumes=["resumes/vp_enterprise.tex", "resumes/vp_growth.tex"],
            ),
        },
    )


@pytest.fixture
def mock_resume(tmp_path):
    """Create a mock resume file."""
    resume = tmp_path / "resumes" / "em.tex"
    resume.parent.mkdir(parents=True)
    resume.write_text(r"""
\begin{document}
EXECUTIVE SUMMARY
\noindent{\fontspec{Lato Light}\small Engineering leader who builds things.}
\begin{itemize}
\item Led team of 20 engineers
\item Shipped platform to production
\end{itemize}
\end{document}
""")
    return resume


class TestExtractSummary:
    def test_extracts_summary_text(self):
        tex = r"""
EXECUTIVE SUMMARY
\noindent{\fontspec{Lato Light}\small Engineering leader who builds AI products. Based in Dallas.}
"""
        result = _extract_summary(tex)
        assert "Engineering leader" in result
        assert "Dallas" in result

    def test_empty_on_no_match(self):
        assert _extract_summary("no summary here") == ""


class TestParseJson:
    def test_parses_raw_json(self):
        result = _parse_json('{"key": "value"}')
        assert result["key"] == "value"

    def test_parses_markdown_block(self):
        result = _parse_json('```json\n{"key": "value"}\n```')
        assert result["key"] == "value"

    def test_finds_json_in_text(self):
        result = _parse_json('Here is the result: {"key": "value"} done.')
        assert result["key"] == "value"

    def test_raises_on_garbage(self):
        with pytest.raises((json.JSONDecodeError, ValueError)):
            _parse_json("no json here at all")


class TestSelectResume:
    def test_single_resume_returns_directly(self, config_single_resume, tmp_path):
        resume = tmp_path / "resumes" / "em.tex"
        resume.parent.mkdir(parents=True)
        resume.write_text("content")

        result = select_resume(
            "em", config_single_resume, "EM", "Acme", "Lead team",
            project_root=tmp_path,
        )
        assert result == tmp_path / "resumes/em.tex"

    @patch("shortlist.processors.resume._call_gemini")
    def test_multi_resume_calls_llm(self, mock_gemini, config_multi_resume, tmp_path):
        for name in ["vp_enterprise.tex", "vp_growth.tex"]:
            p = tmp_path / "resumes" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("EXECUTIVE SUMMARY\n\\small Test summary}")

        mock_gemini.return_value = '{"selected_index": 1, "reason": "growth focus"}'

        result = select_resume(
            "vp", config_multi_resume, "VP Eng", "FastCo", "Series B startup",
            project_root=tmp_path,
        )
        assert "vp_growth" in str(result)

    @patch("shortlist.processors.resume._call_gemini")
    def test_multi_resume_defaults_to_first_on_failure(self, mock_gemini,
                                                        config_multi_resume, tmp_path):
        for name in ["vp_enterprise.tex", "vp_growth.tex"]:
            p = tmp_path / "resumes" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("content")

        mock_gemini.return_value = None

        result = select_resume(
            "vp", config_multi_resume, "VP Eng", "BigCo", "Enterprise scale",
            project_root=tmp_path,
        )
        assert "vp_enterprise" in str(result)

    def test_unknown_track_raises(self, config_single_resume, tmp_path):
        with pytest.raises(ValueError, match="Unknown track"):
            select_resume("unknown", config_single_resume, "X", "Y", "Z",
                         project_root=tmp_path)


class TestTailorResume:
    @patch("shortlist.processors.resume._call_gemini")
    def test_returns_tailored_result(self, mock_gemini, mock_resume):
        mock_gemini.return_value = json.dumps({
            "tailored_tex": r"\begin{document}tailored\end{document}",
            "changes_made": ["Reordered bullets", "Adjusted summary"],
            "interest_note": "I'm excited about this role because...",
        })

        result = tailor_resume(mock_resume, "VP Eng", "Acme", "Lead 50 engineers")
        assert result is not None
        assert "tailored" in result.tailored_tex
        assert len(result.changes_made) == 2
        assert "excited" in result.interest_note

    @patch("shortlist.processors.resume._call_gemini")
    def test_returns_none_on_api_failure(self, mock_gemini, mock_resume):
        mock_gemini.return_value = None
        result = tailor_resume(mock_resume, "VP Eng", "Acme", "desc")
        assert result is None

    def test_returns_none_for_missing_file(self, tmp_path):
        result = tailor_resume(tmp_path / "nonexistent.tex", "VP", "X", "Y")
        assert result is None


class TestSaveTailoredResume:
    def test_saves_tex_file(self, tmp_path):
        tailored = TailoredResume(
            base_resume_path="resumes/em.tex",
            tailored_tex=r"\begin{document}tailored\end{document}",
            changes_made=["Reordered bullets"],
            interest_note="Excited about this role.",
        )

        output = save_tailored_resume(
            tailored, tmp_path / "drafts", "Acme Corp", "em", "2026-03-10"
        )

        assert output.exists()
        assert output.name == "2026-03-10-acme-corp-em.tex"
        assert "tailored" in output.read_text()

    def test_saves_note_file(self, tmp_path):
        tailored = TailoredResume(
            base_resume_path="resumes/em.tex",
            tailored_tex="tex content",
            changes_made=["Change 1", "Change 2"],
            interest_note="I'm interested because...",
        )

        output = save_tailored_resume(
            tailored, tmp_path / "drafts", "BigCo", "vp", "2026-03-10"
        )

        note_path = output.with_suffix(".note.md")
        assert note_path.exists()
        note = note_path.read_text()
        assert "I'm interested because" in note
        assert "Change 1" in note
        assert "Change 2" in note

    def test_sanitizes_company_name(self, tmp_path):
        tailored = TailoredResume(
            base_resume_path="x", tailored_tex="x",
            changes_made=[], interest_note="x",
        )

        output = save_tailored_resume(
            tailored, tmp_path / "drafts",
            "Acme Corp & Sons, Inc.", "em", "2026-03-10"
        )
        assert "acme-corp-sons-inc" in output.name
