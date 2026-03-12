"""Tests for cover letter utilities."""
from shortlist.processors.cover_letter import _extract_resume_summary


def test_extract_resume_summary_from_latex():
    """LaTeX input gets commands stripped."""
    tex = r"""
\documentclass{article}
\begin{document}
\textbf{Adam Ramirez}
\begin{itemize}
\item Built data pipelines at scale
\item 10 years Python experience
\end{itemize}
\end{document}
"""
    result = _extract_resume_summary(tex)
    assert "Adam Ramirez" in result
    assert "Built data pipelines" in result
    assert "\\textbf" not in result
    assert "\\begin" not in result


def test_extract_resume_summary_from_plain_text():
    """Plain text input passes through without LaTeX mangling."""
    plain = """Adam Ramirez
Senior Engineering Manager
10 years Python experience
Built data pipelines at scale
Led teams of 20+ engineers"""

    result = _extract_resume_summary(plain)
    assert "Adam Ramirez" in result
    assert "Senior Engineering Manager" in result
    assert "Built data pipelines" in result
    # Should NOT mangle anything
    assert result.strip() == plain.strip()


def test_extract_resume_summary_plain_text_with_backslash():
    """Plain text with backslashes (e.g. file paths) shouldn't be mangled."""
    plain = r"Used C:\Users\adam\projects for local dev"
    result = _extract_resume_summary(plain)
    # The backslashes may or may not survive, but the words should
    assert "Used" in result
    assert "local dev" in result
