"""LaTeX → PDF compilation using tectonic."""
import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILE_TIMEOUT = 30  # seconds


def make_portable(tex: str) -> str:
    """Strip fontspec/custom font commands and substitute pdflatex-compatible fonts.

    Preserves document structure and content. Replaces custom fonts with
    Latin Modern (lmodern) which tectonic always has available.
    """
    if "fontspec" not in tex:
        return tex

    # Normalize double-escaped backslashes (from JSON fallback parser)
    # Only unescape \\X where X is a letter (LaTeX commands), preserving
    # \\ (line break), \\[ (display math / line break with spacing), etc.
    if "\\\\documentclass" in tex or "\\\\usepackage" in tex:
        tex = re.sub(r"\\\\([a-zA-Z])", r"\\\1", tex)

    # Fix split commands from bad \\n unescaping:
    # \\<newline>noindent → \noindent  (double-escaped backslash before newline)
    tex = re.sub(r"\\\\\n([a-z]+)", r"\\\1", tex)
    # \<newline>noindent → \noindent  (single backslash before newline)
    tex = re.sub(r"\\\n([a-z]+)", r"\\\1", tex)

    # Remove \usepackage{fontspec} (with optional options)
    tex = re.sub(r"\\usepackage(\[.*?\])?\{fontspec\}\s*\n?", "", tex)

    # Remove \setmainfont, \setsansfont, \setmonofont, \newfontfamily
    # These can have [...] options before OR after {FontName}, spanning multiple lines
    for cmd in (r"\\setmainfont", r"\\setsansfont", r"\\setmonofont", r"\\newfontfamily\s*\\[a-zA-Z]+"):
        tex = re.sub(
            cmd + r"\s*(?:\[.*?\])?\s*\{[^}]*\}\s*(?:\[.*?\])?\s*\n?",
            "",
            tex,
            flags=re.DOTALL,
        )

    # Remove \defaultfontfeatures{...} and \addfontfeatures{...}
    tex = re.sub(r"\\defaultfontfeatures\s*(?:\[.*?\])?\s*\{[^}]*\}\s*\n?", "", tex, flags=re.DOTALL)
    tex = re.sub(r"\\addfontfeatures\s*\{[^}]*\}", "", tex)

    # Remove inline \fontspec{FontName} calls (used in document body)
    tex = re.sub(r"\\fontspec\s*\{[^}]*\}", "", tex)

    # Add fontspec back with Latin Modern OTF files (always available in tectonic)
    if r"\usepackage{fontspec}" not in tex:
        lm_block = (
            "\\usepackage{fontspec}\n"
            "\\setmainfont{lmroman10-regular.otf}["
            "BoldFont=lmroman10-bold.otf,"
            "ItalicFont=lmroman10-italic.otf,"
            "BoldItalicFont=lmroman10-bolditalic.otf]\n"
            "\\setsansfont{lmsans10-regular.otf}[BoldFont=lmsans10-bold.otf]\n"
            "\\setmonofont{lmmono10-regular.otf}\n"
        )
        tex = re.sub(
            r"(\\documentclass(?:\[.*?\])?\{[^}]*\}\s*\n)",
            r"\1" + lm_block.replace("\\", "\\\\"),
            tex,
        )

    return tex


def _run_tectonic(tex_path: Path) -> bytes | None:
    """Run tectonic on a .tex file. Returns PDF bytes or None."""
    try:
        result = subprocess.run(
            ["tectonic", str(tex_path)],
            capture_output=True, timeout=COMPILE_TIMEOUT,
        )
        if result.returncode != 0:
            logger.warning(
                f"tectonic failed (rc={result.returncode}): "
                f"{result.stderr.decode('utf-8', errors='replace')[:500]}"
            )
            return None

        pdf_path = tex_path.with_suffix(".pdf")
        if pdf_path.exists():
            return pdf_path.read_bytes()

        logger.warning("tectonic succeeded but no PDF file produced")
        return None
    except FileNotFoundError:
        logger.error("tectonic not installed — cannot compile LaTeX to PDF")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"tectonic timed out after {COMPILE_TIMEOUT}s")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during LaTeX compilation: {e}")
        return None


def compile_latex(tex_content: str) -> bytes | None:
    """Compile LaTeX string to PDF bytes. Returns None on failure.

    Uses tectonic (pdflatex-compatible). Writes to a temp directory,
    compiles, reads PDF bytes, and cleans up.
    """
    if not tex_content or not tex_content.strip():
        return None

    portable = make_portable(tex_content)

    with tempfile.TemporaryDirectory(prefix="shortlist-tex-") as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        tex_path.write_text(portable)
        return _run_tectonic(tex_path)
