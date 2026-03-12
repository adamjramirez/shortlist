"""Tests for LaTeX → PDF compilation."""
import pytest
from unittest.mock import patch, MagicMock
import subprocess

from shortlist.processors.latex_compiler import compile_latex


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
