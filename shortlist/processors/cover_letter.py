"""Cover letter generation using job context + profile + company intel."""
import logging

from shortlist import llm

logger = logging.getLogger("shortlist.cover_letter")

COVER_LETTER_PROMPT = """Write a compelling, professional cover letter for this specific role. The letter should feel personal and genuine — not templated. Draw on the candidate's actual experience and connect it to what this company specifically needs.

## Rules
- 3-4 paragraphs, ~300 words
- Opening: Hook that shows you understand the company's mission/challenge — NOT "I am writing to apply for..."
- Middle: 2-3 specific achievements from the resume that map directly to this role's requirements. Use numbers and outcomes.
- Closing: Why THIS company at THIS moment in their journey. What you'd do in the first 90 days.
- Tone: Confident but not arrogant. Specific, not generic. Executive-level if senior role.
- Do NOT use filler phrases like "I believe I would be a great fit" or "I am excited about the opportunity"
- Do NOT repeat the job posting back to them
- Output ONLY the cover letter text (no subject line, no "Dear Hiring Manager" unless it fits naturally, no "[Your Name]" placeholder)

## Candidate Background
{fit_context}

## Resume Summary
{resume_summary}

## Job Details
**Title:** {title}
**Company:** {company}
**Description:**
{description}

## Company Intelligence
{company_intel}

## What Makes This a Match
{match_reasoning}

## Why the Candidate Would Be Interested
{interest_note}

Write the cover letter now."""


def generate_cover_letter(
    title: str,
    company: str,
    description: str,
    fit_context: str,
    resume_tex: str,
    company_intel: str = "",
    match_reasoning: str = "",
    interest_note: str = "",
) -> str | None:
    """Generate a tailored cover letter using all available context.

    Returns plain text cover letter or None on failure.
    """
    # Extract a readable summary from LaTeX (strip commands, keep content)
    resume_summary = _extract_resume_summary(resume_tex)

    prompt = COVER_LETTER_PROMPT.format(
        fit_context=fit_context or "Engineering leader seeking senior roles.",
        resume_summary=resume_summary[:2000],
        title=title,
        company=company,
        description=description[:3000],
        company_intel=company_intel or "No company intel available.",
        match_reasoning=match_reasoning or "No match reasoning available.",
        interest_note=interest_note or "No interest note available.",
    )

    result = llm.call_llm(prompt)
    if not result:
        return None

    text = result.strip().strip('"').strip()
    if len(text) < 50:
        return None
    return text


def _extract_resume_summary(tex: str) -> str:
    """Pull readable content from LaTeX, stripping commands."""
    import re
    # Remove common LaTeX commands but keep their content
    text = re.sub(r'\\(?:textbf|textit|emph|underline)\{([^}]*)\}', r'\1', tex)
    text = re.sub(r'\\(?:section|subsection|subsubsection)\*?\{([^}]*)\}', r'\n\1\n', text)
    text = re.sub(r'\\(?:begin|end)\{[^}]*\}', '', text)
    text = re.sub(r'\\[a-zA-Z]+(?:\[[^\]]*\])?\{[^}]*\}', '', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
