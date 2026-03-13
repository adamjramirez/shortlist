"""Tests for LaTeX → PDF compilation."""
import pytest
from unittest.mock import patch, MagicMock
import subprocess

from shortlist.processors.latex_compiler import compile_latex, make_portable


VALID_TEX = r"""\documentclass[11pt]{article}
\usepackage[top=0.6in,bottom=0.6in,left=0.7in,right=0.7in]{geometry}
\begin{document}
\textbf{Jane Smith} --- Senior Engineer

Built distributed systems at scale.
\end{document}
"""

INVALID_TEX = r"""\documentclass{article}
\begin{document}
\undefinedcommand{this will fail}
\end{document}
"""


class TestCompileLatex:
    @patch("shortlist.processors.latex_compiler._run_tectonic")
    def test_valid_latex_returns_pdf_bytes(self, mock_run):
        """Valid LaTeX → PDF bytes starting with %PDF."""
        mock_run.return_value = b"%PDF-1.5 fake pdf content"
        result = compile_latex(VALID_TEX)
        assert result is not None
        assert result[:5] == b"%PDF-"

    @patch("shortlist.processors.latex_compiler._run_tectonic")
    def test_invalid_latex_returns_none(self, mock_run):
        """Invalid LaTeX → None, no crash."""
        mock_run.return_value = None
        result = compile_latex(INVALID_TEX)
        assert result is None

    @patch("shortlist.processors.latex_compiler._run_tectonic")
    def test_empty_input_returns_none(self, mock_run):
        """Empty string → None."""
        mock_run.return_value = None
        result = compile_latex("")
        assert result is None


FONTSPEC_TEX = r"""\documentclass[11pt]{article}
\usepackage{fontspec}
\setmainfont{EB Garamond}
\setsansfont{Lato}[
  BoldFont={Lato Bold},
  ItalicFont={Lato Italic},
]
\setmonofont{Fira Code}
\newfontfamily\headingfont{Raleway}[BoldFont={Raleway Bold}]
\begin{document}
\textbf{Jane Smith} --- Senior Engineer
\end{document}
"""

FONTSPEC_MINIMAL = r"""\documentclass{article}
\usepackage{fontspec}
\setmainfont{Inter}
\begin{document}
Hello
\end{document}
"""


class TestMakePortable:
    def test_strips_fontspec(self):
        result = make_portable(FONTSPEC_TEX)
        assert r"\usepackage{fontspec}" not in result
        assert r"\setmainfont" not in result
        assert r"\setsansfont" not in result
        assert r"\setmonofont" not in result
        assert r"\newfontfamily" not in result

    def test_adds_lmodern(self):
        result = make_portable(FONTSPEC_TEX)
        assert r"\usepackage{lmodern}" in result
        assert r"\usepackage[T1]{fontenc}" in result

    def test_preserves_content(self):
        result = make_portable(FONTSPEC_TEX)
        assert r"\textbf{Jane Smith}" in result
        assert r"\begin{document}" in result
        assert r"\documentclass[11pt]{article}" in result

    def test_preserves_other_packages(self):
        tex = r"""\documentclass{article}
\usepackage{fontspec}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\setmainfont{Arial}
\begin{document}Hello\end{document}
"""
        result = make_portable(tex)
        assert r"\usepackage{enumitem}" in result
        assert r"\usepackage[hidelinks]{hyperref}" in result

    def test_noop_for_pdflatex(self):
        """Already pdflatex-compatible → unchanged except lmodern added."""
        result = make_portable(VALID_TEX)
        # Content preserved
        assert r"\textbf{Jane Smith}" in result

    def test_handles_multiline_font_options(self):
        result = make_portable(FONTSPEC_TEX)
        # The multi-line \setsansfont with options should be fully removed
        assert "BoldFont" not in result
        assert "ItalicFont" not in result
        assert "Lato" not in result

    def test_minimal_fontspec(self):
        result = make_portable(FONTSPEC_MINIMAL)
        assert r"\usepackage{fontspec}" not in result
        assert "Inter" not in result
        assert r"\usepackage{lmodern}" in result

    def test_strips_inline_fontspec(self):
        tex = r"""\documentclass{article}
\usepackage{fontspec}
\begin{document}
{\fontspec{Lato Bold}\small SECTION HEADER}
{\fontspec{Lato Light}\small Normal text}
{\fontspec{EB Garamond}Main body text}
\end{document}
"""
        result = make_portable(tex)
        assert r"\fontspec{Lato Bold}" not in result
        assert r"\fontspec{Lato Light}" not in result
        assert r"\fontspec{EB Garamond}" not in result
        # Content preserved
        assert "SECTION HEADER" in result
        assert "Normal text" in result
        assert "Main body text" in result

    def test_handles_double_escaped_backslashes(self):
        """Content with \\\\documentclass (JSON fallback) is normalized."""
        tex = "\\\\documentclass{article}\n\\\\usepackage{fontspec}\n\\\\setmainfont{Arial}\n\\\\begin{document}\n{\\\\fontspec{Lato Bold}Header}\\\\[14pt]\n\\\\end{document}\n"
        result = make_portable(tex)
        assert "fontspec" not in result
        assert r"\usepackage{lmodern}" in result
        assert r"\begin{document}" in result
        assert "Header" in result
        # LaTeX line breaks \\[14pt] must be preserved
        assert "\\\\[14pt]" in result

    def test_strips_addfontfeatures(self):
        tex = r"""\documentclass{article}
\usepackage{fontspec}
\begin{document}
{\fontspec{Lato Bold}\addfontfeatures{LetterSpace=10}HEADER}
\end{document}
"""
        result = make_portable(tex)
        assert r"\addfontfeatures" not in result
        assert "LetterSpace" not in result
        assert "HEADER" in result


class TestCompileLatexIntegration:
    """Integration tests that require tectonic installed."""

    @pytest.fixture(autouse=True)
    def check_tectonic(self):
        try:
            subprocess.run(["tectonic", "--version"], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            pytest.skip("tectonic not installed")

    def test_real_compilation(self):
        """Actually compile LaTeX to PDF with tectonic."""
        result = compile_latex(VALID_TEX)
        assert result is not None
        assert result[:5] == b"%PDF-"
        assert len(result) > 100  # real PDF is at least a few KB

    def test_real_invalid_returns_none(self):
        """Invalid LaTeX returns None, doesn't crash."""
        result = compile_latex(INVALID_TEX)
        assert result is None
