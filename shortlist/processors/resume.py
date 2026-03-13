"""Resume matching and tailoring.

For each top-scored job:
1. Select the best base resume based on matched_track
2. Use the configured LLM to suggest emphasis changes (NOT rewriting)
3. Save tailored .tex file + "why I'm interested" note
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from shortlist import llm
from shortlist.config import Config

logger = logging.getLogger(__name__)


@dataclass
class TailoredResume:
    base_resume_path: str
    tailored_tex: str
    changes_made: list[str]
    interest_note: str  # 3-sentence "why I'm interested"
    output_path: str = ""


SELECT_RESUME_PROMPT = """You are helping select which resume variant to use for a job application.

## Job
**Title:** {title}
**Company:** {company}
**Description excerpt:** {description_excerpt}

## Resume Options
{resume_options}

## Instructions
Which resume is the best fit for this job? Consider:
- Does the role emphasize scale/enterprise/transformation → enterprise resume
- Does the role emphasize growth/shipping/startups → growth resume
- Is there only one option → use it

Return ONLY a JSON object:
```json
{{"selected_index": <0-based index>, "reason": "<one sentence>"}}
```"""


TAILOR_PROMPT = """You are tailoring a resume for a specific job application.

## Job Description
**Title:** {title}
**Company:** {company}
**Description:**
{description}

## Current Resume (LaTeX)
{resume_tex}

## Instructions
Suggest specific changes to tailor this resume for the job. You must:
1. KEEP all facts true — don't invent experience or metrics
2. REORDER bullet points to lead with what's most relevant to this role
3. ADJUST the executive summary to emphasize relevant aspects
4. HIGHLIGHT existing experience that matches what the JD values

DO NOT:
- Add fake experience or skills
- Change job titles or dates
- Keyword-stuff
- Rewrite the whole thing — make surgical changes

Return a JSON object:
```json
{{
    "tailored_tex": "<the full modified LaTeX document>",
    "changes_made": ["<list of specific changes>"],
    "interest_note": "<3 sentences: why the candidate is genuinely interested in this role, based on their real background and what the company does. Personal, specific, not generic.>"
}}
```"""


GENERATE_RESUME_PROMPT = """You are generating a tailored LaTeX resume from extracted text.

## Original Resume Text
{resume_text}

## Job Description
**Title:** {title}
**Company:** {company}
**Description:**
{description}

## LaTeX Template
{template}

## Instructions
Generate a COMPLETE LaTeX document using the template above, populated with facts from the original resume.

You MUST:
1. Use ONLY facts from the original resume — no invented experience, skills, or metrics
2. Reorder and emphasize content that's most relevant to this specific job
3. Write a 2-3 sentence summary tailored to this role
4. Keep all job titles, companies, dates, and education exactly as stated
5. Output a complete, compilable LaTeX document

You MUST NOT:
- Invent experience, projects, or metrics not in the original
- Add skills the candidate doesn't have
- Change job titles, dates, or company names
- Use packages beyond: article, geometry, enumitem, hyperref, titlesec

Return a JSON object:
```json
{{
    "tailored_tex": "<the full LaTeX document>",
    "changes_made": ["<list of what was emphasized/reordered>"],
    "interest_note": "<3 sentences: why the candidate is genuinely interested in this role, based on their real background>"
}}
```"""


def _load_resume_template() -> str:
    """Load the built-in resume template."""
    template_path = Path(__file__).parent.parent / "templates" / "resume_template.tex"
    return template_path.read_text()


def generate_resume_from_text(resume_text: str, job_title: str, job_company: str,
                               job_description: str) -> TailoredResume | None:
    """Generate a complete LaTeX resume from extracted text (for PDF users).

    Uses the built-in template + LLM to create a compilable LaTeX document
    tailored to the target job.
    """
    template = _load_resume_template()

    prompt = GENERATE_RESUME_PROMPT.format(
        resume_text=resume_text,
        title=job_title,
        company=job_company,
        description=job_description[:3000],
        template=template,
    )

    result = llm.call_llm(prompt)
    if not result:
        return None

    try:
        data = _parse_tailor_json(result)
        return TailoredResume(
            base_resume_path="(generated from text)",
            tailored_tex=data.get("tailored_tex", ""),
            changes_made=data.get("changes_made", []),
            interest_note=data.get("interest_note", ""),
        )
    except Exception as e:
        logger.error(f"Failed to parse generate response: {e}")
        return None


def select_resume(track_key: str, config: Config, job_title: str,
                  job_company: str, job_description: str,
                  project_root: Path) -> Path:
    """Select the best resume for a job based on track and job description.

    For tracks with one resume, returns it directly.
    For tracks with multiple (e.g., VP), uses the LLM to pick.
    """
    track = config.tracks.get(track_key) or config.tracks.get(track_key.lower())
    if not track:
        # Fall back to first available track
        if config.tracks:
            track = next(iter(config.tracks.values()))
            logger.warning(f"Unknown track '{track_key}', falling back to '{track.title}'")
        else:
            raise ValueError(f"Unknown track: {track_key} (no tracks configured)")

    paths = track.get_resume_paths()
    if not paths:
        raise ValueError(f"No resumes configured for track: {track_key}")

    if len(paths) == 1:
        return project_root / paths[0]

    # Multiple resumes — use LLM to pick
    options = []
    for i, p in enumerate(paths):
        full_path = project_root / p
        if full_path.exists():
            content = full_path.read_text()
            # Extract executive summary for context
            summary = _extract_summary(content)
            options.append(f"[{i}] {p}\nSummary: {summary}")
        else:
            options.append(f"[{i}] {p}\n(file not found)")

    prompt = SELECT_RESUME_PROMPT.format(
        title=job_title,
        company=job_company,
        description_excerpt=job_description[:500],
        resume_options="\n\n".join(options),
    )

    result = llm.call_llm(prompt)
    if result:
        try:
            data = llm.parse_json(result)
            idx = int(data.get("selected_index", 0))
            idx = max(0, min(idx, len(paths) - 1))
            logger.info(f"Resume selected: {paths[idx]} — {data.get('reason', '')}")
            return project_root / paths[idx]
        except (ValueError, KeyError, json.JSONDecodeError):
            pass

    # Default to first
    return project_root / paths[0]


def _tailor_from_tex(resume_tex: str, job_title: str, job_company: str,
                     job_description: str, base_path: str = "(uploaded)") -> TailoredResume | None:
    """Core tailoring logic — takes LaTeX text, returns TailoredResume or None."""
    prompt = TAILOR_PROMPT.format(
        title=job_title,
        company=job_company,
        description=job_description[:3000],
        resume_tex=resume_tex,
    )

    result = llm.call_llm(prompt)
    if not result:
        return None

    try:
        data = _parse_tailor_json(result)
        return TailoredResume(
            base_resume_path=base_path,
            tailored_tex=data.get("tailored_tex", resume_tex),
            changes_made=data.get("changes_made", []),
            interest_note=data.get("interest_note", ""),
        )
    except Exception as e:
        logger.error(f"Failed to parse tailor response: {e}")
        return None


def tailor_resume(resume_path: Path, job_title: str, job_company: str,
                  job_description: str) -> TailoredResume | None:
    """Tailor a resume from a file path (CLI). Returns TailoredResume or None."""
    if not resume_path.exists():
        logger.error(f"Resume not found: {resume_path}")
        return None
    return _tailor_from_tex(
        resume_path.read_text(), job_title, job_company, job_description,
        base_path=str(resume_path),
    )


def tailor_resume_from_text(resume_tex: str, job_title: str, job_company: str,
                            job_description: str) -> TailoredResume | None:
    """Tailor a resume from raw LaTeX text (web — no file on disk)."""
    return _tailor_from_tex(resume_tex, job_title, job_company, job_description)


def save_tailored_resume(tailored: TailoredResume, output_dir: Path,
                         company: str, track: str, date: str) -> Path:
    """Save a tailored resume to disk. Returns the output path."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize company name for filename
    safe_company = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")
    filename = f"{date}-{safe_company}-{track}.tex"
    output_path = output_dir / filename

    output_path.write_text(tailored.tailored_tex)
    tailored.output_path = str(output_path)

    # Save interest note alongside
    note_path = output_path.with_suffix(".note.md")
    note_path.write_text(
        f"# Why I'm interested — {company}\n\n{tailored.interest_note}\n\n"
        f"## Changes from base resume\n\n"
        + "\n".join(f"- {c}" for c in tailored.changes_made)
        + "\n"
    )

    logger.info(f"Saved tailored resume: {output_path}")
    return output_path


def _extract_summary(tex: str) -> str:
    """Extract the executive summary text from a LaTeX resume."""
    match = re.search(
        r"EXECUTIVE SUMMARY.*?\\small\s*(.*?)\}",
        tex, re.DOTALL,
    )
    if match:
        text = match.group(1)
        # Clean LaTeX commands
        text = re.sub(r"\\[a-zA-Z]+\{[^}]*\}", "", text)
        text = re.sub(r"\\[$\\]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()[:300]
    return ""


def _parse_tailor_json(text: str) -> dict:
    """Parse JSON from tailor LLM response, handling LaTeX escapes."""
    text = text.strip()
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # LaTeX backslashes break JSON — extract fields manually
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            raw = json_match.group(0)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass

            # Try fixing LaTeX escapes: double-escape lone backslashes
            fixed = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', raw)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

            # Last resort: extract fields by regex
            return _extract_tailor_fields(text)
        raise


def _extract_tailor_fields(text: str) -> dict:
    """Extract tailored resume fields when JSON parsing fails due to LaTeX."""
    result = {}

    # Extract tailored_tex between the first and last occurrence markers
    tex_match = re.search(
        r'"tailored_tex"\s*:\s*"(.*?)(?:"\s*,\s*"changes_made")',
        text, re.DOTALL,
    )
    if tex_match:
        raw = tex_match.group(1)
        # Unescape JSON string escapes — order matters!
        # 1. \\\\ → \\ first (so \\noindent doesn't become \+newline+oindent)
        raw = raw.replace("\\\\", "\\")
        # 2. \\n → newline (after backslash unescape, only real \n remain)
        raw = raw.replace("\\n", "\n")
        raw = raw.replace('\\"', '"')
        result["tailored_tex"] = raw

    # Extract changes_made
    changes_match = re.search(r'"changes_made"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if changes_match:
        changes = re.findall(r'"([^"]+)"', changes_match.group(1))
        result["changes_made"] = changes

    # Extract interest_note
    note_match = re.search(r'"interest_note"\s*:\s*"(.*?)"(?:\s*\})', text, re.DOTALL)
    if note_match:
        raw = note_match.group(1)
        raw = raw.replace("\\n", "\n")
        raw = raw.replace("\\\\", "\\")
        raw = raw.replace('\\"', '"')
        result["interest_note"] = raw

    if not result.get("tailored_tex"):
        raise json.JSONDecodeError("Could not extract tailored_tex", text, 0)

    return result


def tailor_job_parallel(
    job_id: int,
    track: str,
    title: str,
    company: str,
    description: str,
    config: Config,
    project_root: Path,
    drafts_dir: Path,
    today: str,
) -> tuple[int, TailoredResume | None, Path | None]:
    """Tailor a single job — designed for use in ThreadPoolExecutor.

    Returns (job_id, tailored_result, output_path) or (job_id, None, None).
    """
    try:
        resume_path = select_resume(
            track, config, title, company, description, project_root,
        )
        tailored = tailor_resume(resume_path, title, company, description)
        if tailored:
            output = save_tailored_resume(tailored, drafts_dir, company, track, today)
            return (job_id, tailored, output)
    except Exception as e:
        logger.warning(f"Resume tailoring failed for {company}/{title}: {e}")
    return (job_id, None, None)


def tailor_jobs_parallel(
    jobs: list[tuple[int, str, str, str, str]],
    config: Config,
    project_root: Path,
    drafts_dir: Path,
    today: str,
    max_workers: int = 10,
) -> list[tuple[int, TailoredResume | None, Path | None]]:
    """Tailor resumes in parallel.

    jobs: list of (job_id, track, title, company, description)
    Returns list of (job_id, tailored_result, output_path).
    """
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                tailor_job_parallel,
                job_id, track, title, company, description,
                config, project_root, drafts_dir, today,
            ): job_id
            for job_id, track, title, company, description in jobs
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                job_id = futures[future]
                logger.warning(f"Resume tailoring thread failed for job {job_id}: {e}")
                results.append((job_id, None, None))
    return results
