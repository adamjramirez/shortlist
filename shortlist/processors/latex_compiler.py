"""LaTeX → PDF compilation using tectonic."""
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILE_TIMEOUT = 30  # seconds


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

    with tempfile.TemporaryDirectory(prefix="shortlist-tex-") as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        tex_path.write_text(tex_content)
        return _run_tectonic(tex_path)
