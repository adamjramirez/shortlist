"""Cover letter generation using job context + profile + company intel."""
import logging

from shortlist import llm

logger = logging.getLogger("shortlist.cover_letter")

COVER_LETTER_PROMPT = """Write a cover letter for a {title} role at {company}. It should read like a thoughtful note from a real person — not a template, not a second resume.

## What makes a great cover letter

A cover letter answers one question the resume can't: "Why you, why here, why now?"

It's NOT a list of achievements (they already have the resume). It's the *context* around those achievements — the judgment calls, the motivation, the thread connecting your past to their future.

## Structure (4 paragraphs, 250-350 words total)

**Paragraph 1 — The connection (2-3 sentences):**
Open with something specific about the company that connects to your own experience or values. Show you understand a challenge they face or a direction they're heading. Then bridge: "That's exactly the kind of problem I've been solving."

**Paragraph 2 — Your strongest story (4-5 sentences):**
Pick ONE achievement from the resume that's most relevant to this role. Don't summarize it — tell the story. What was the situation? What was hard about it? What did you do that someone else wouldn't have? What was the outcome? This paragraph should make them think "I want to hear more about that."

**Paragraph 3 — The pattern (3-4 sentences):**
Zoom out. Connect 2-3 other experiences briefly (one sentence each) to show this wasn't a one-off — it's a pattern. You consistently do X that they need. Use specific numbers but don't just list them. Weave them into a narrative: "That same approach at [Company] led to..."

**Paragraph 4 — Why now (2-3 sentences):**
Why this company at this point in their journey, and what specifically you'd want to dig into in the first 90 days. Name a real challenge or opportunity, not a generic "contribute to growth." End with a concrete conversation starter: "I'd love to discuss how..." about a specific topic.

## Tone rules
- Write like you'd talk to a peer over coffee, then tighten it up one notch.
- Confidence comes from specifics, not adjectives. "I led" beats "I am a proven leader."
- Match the seniority — VP roles get strategic voice, IC roles get craft voice.
- Vary sentence length. Short sentences punch. Longer ones build context.

## Hard rules
- Do NOT use: "excited about the opportunity," "passionate about," "I believe I would be a great fit," "leverage my experience"
- Do NOT repeat the job posting requirements back to them
- Do NOT include [Your Name], placeholders, or "Dear Hiring Manager"
- Do NOT write bullet points — this is a letter, not a list
- Do NOT exceed 350 words

---

## Candidate Background
{fit_context}

## Resume (key details to draw from)
{resume_summary}

## Role
**Title:** {title}
**Company:** {company}
**Description:**
{description}

## What we know about {company}
{company_intel}

## Why this is a match
{match_reasoning}

## What would genuinely interest this candidate
{interest_note}

Write the cover letter. Output ONLY the letter text, nothing else."""


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
