"""Cover letter generation using job context + profile + company intel."""
import logging

from shortlist import llm

logger = logging.getLogger("shortlist.cover_letter")

COVER_LETTER_PROMPT = """Write a cover letter for a {title} role at {company}.

## The job of a cover letter

A cover letter answers one question the resume can't: "Why you, why here, why now?" It is NOT a summary of the resume. The hiring manager already has the resume. They want to know the story behind the bullet points — the judgment calls, the hard parts, the reason you're reaching out to THEM.

## Structure (4 paragraphs, 250-350 words total)

**Paragraph 1 — The connection (2-3 sentences):**
Open with something specific about {company} that connects to your own experience. Not a compliment about the company — a SHARED problem or belief. Show you understand where they are and why it's hard. Then bridge naturally to why you've been in that exact situation.

**Paragraph 2 — One real story (4-6 sentences):**
Pick the single most relevant experience from the resume. Tell it as a STORY, not a summary:
- What was the situation BEFORE you got involved?
- What made it hard? (The obstacle, not just the task.)
- What did YOU specifically decide or do that someone else in the role wouldn't have?
- What changed as a result? (Use the real numbers from the resume.)
This paragraph should make the reader think "Tell me more."

**Paragraph 3 — The pattern (3-4 sentences):**
Reference at least one OTHER company from the resume by its exact name. For example, if the resume lists "BigCo" then write "At BigCo, I..." — never "at a previous role" or "at another company." Show this is a repeatable pattern across multiple organizations. One sentence per example, each with a specific number or outcome taken directly from the resume.

**Paragraph 4 — Why this, why now (2-3 sentences):**
Name a specific challenge or opportunity at {company} based on the company intel provided — not a vague "contribute to growth." Say what you'd focus on in the first 90 days concretely enough that the reader thinks "that's the right priority." End with a specific topic you'd want to discuss, not a generic "I'd love to chat."

## Tone

Write like you're talking to a smart peer — not a form letter, not a LinkedIn post. Short sentences are good. So are longer ones that build an idea. Vary the rhythm.

Confidence comes from specifics, not from adjectives. "We cut deploy time from 2 weeks to 4 hours" beats "I am a proven leader in engineering transformation."

## ABSOLUTE RULES — violating ANY of these means starting over

1. NEVER use these words or phrases (no exceptions, no variations):
   excited, passionate, spearheaded, championed, forward-thinking, leverage,
   "caught my attention", "great fit", "business outcomes", "key initiatives",
   "shaped my understanding", "at my previous company", "at another company",
   "resonates deeply", "resonates strongly", "operational excellence"

2. NEVER invent company names. The resume below contains real company names.
   Use ONLY those names. If only one company is listed, only reference one.
   Do not create fictional companies like "DataCo" or "InnovateTech."

3. NEVER invent numbers or metrics. Use ONLY the specific numbers that appear
   in the resume data below. If the resume says "40%" then use "40%."
   Do not fabricate figures like "50% improvement" if that number isn't in the resume.

4. No bullet points. No placeholders. No "Dear Hiring Manager." Max 350 words.

---

## Candidate background
{fit_context}

## Resume (use ONLY the company names and numbers below — nothing invented)
The following is the candidate's actual resume. Every company name and number is real.
Reference them by name. Do not substitute with vague phrases like "another company."

{resume_summary}

## Role
**Title:** {title}
**Company:** {company}
**Description:**
{description}

## What we know about {company}
{company_intel}

## Why this is a strong match
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

    # QA pass — second LLM call to catch issues the prompt couldn't prevent
    text = _qa_pass(text, title, company, resume_summary[:2000])
    return _clean_banned_phrases(text)


QA_PROMPT = """You are a strict editor reviewing a cover letter. Fix ALL of the following issues and return the corrected letter. If nothing needs fixing, return the letter unchanged.

## Check each of these (fix every one you find):

1. **Banned phrases** — replace if present:
   excited, passionate, spearheaded, championed, forward-thinking, leverage,
   "resonates deeply", "resonates strongly", "operational excellence",
   "caught my attention", "great fit", "business outcomes", "key initiatives",
   "shaped my understanding", eager, "at my previous company", "at another company"

2. **Placeholder company names** — the letter must use REAL company names from the resume below.
   If you see generic names like "Company Name", "Previous Company", "DataCo", "TechCorp",
   "InnovateTech", or similar, replace them with the actual company name from the resume.
   If the letter says "at my previous company" or avoids naming a company, insert the real name.

3. **Invented numbers** — every number/metric must appear in the resume below.
   If you see a percentage or metric NOT in the resume, remove that claim or replace it
   with one that IS in the resume.

4. **Repeated sentences or ideas** — if the same point is made twice, cut the duplicate.

5. **Grammar and typos** — fix any errors ("interested in discuss" → "interested in discussing").

6. **Vague paragraphs** — if paragraph 3 (the pattern paragraph) only references one company
   or has no specific numbers, add a reference to another company from the resume with a
   real metric.

## Resume (source of truth for names and numbers):
{resume_summary}

## Cover letter to review:
{draft}

Return ONLY the corrected cover letter text. No commentary, no explanation."""


def _qa_pass(draft: str, title: str, company: str, resume_summary: str) -> str:
    """Second LLM pass to catch quality issues in the generated letter."""
    prompt = QA_PROMPT.format(
        resume_summary=resume_summary,
        draft=draft,
    )
    try:
        result = llm.call_llm(prompt)
        if result and len(result.strip()) > 50:
            return result.strip().strip('"').strip()
    except Exception as e:
        logger.warning(f"QA pass failed, using original: {e}")
    return draft


# Phrases to strip or replace in post-processing if the model ignores instructions
_BANNED_REPLACEMENTS = [
    # Eagerness / excitement
    ("I'm eager to", "I'd welcome the chance to"),
    ("I am eager to", "I'd welcome the chance to"),
    ("eager to", "interested in"),
    ("excited by the opportunity", "drawn to the chance"),
    ("excited about the opportunity", "drawn to the chance"),
    ("excited to", "looking forward to"),
    ("I'm excited", "I'm drawn"),
    ("I am excited", "I'm drawn"),
    # Corporate filler
    ("caught my attention", "stood out to me"),
    ("resonates deeply", "connects with my experience"),
    ("resonates strongly", "connects with my experience"),
    ("leverage my", "apply my"),
    ("leverage our", "use our"),
    ("leverage the", "use the"),
    ("leverage ", "use "),
    ("championed a", "drove a"),
    ("championed the", "drove the"),
    ("I championed", "I drove"),
    ("championed", "drove"),
    ("Championed", "Drove"),
    ("spearheaded", "led"),
    ("Spearheaded", "Led"),
    ("forward-thinking", "thoughtful"),
    ("passionate about", "drawn to"),
    ("Passionate about", "Drawn to"),
    ("operational excellence", "strong operations"),
]


def _clean_banned_phrases(text: str) -> str:
    """Post-process to catch banned phrases the model ignored."""
    for old, new in _BANNED_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _extract_resume_summary(tex: str) -> str:
    """Extract readable text from LaTeX resume, handling real-world templates.

    Strategy: strip LaTeX commands progressively, keeping text content.
    Handles fontspec, tabular*, custom commands, etc.
    """
    import re

    text = tex

    # 1. Remove everything before \begin{document}
    doc_start = text.find(r'\begin{document}')
    if doc_start >= 0:
        text = text[doc_start + len(r'\begin{document}'):]
    doc_end = text.find(r'\end{document}')
    if doc_end >= 0:
        text = text[:doc_end]

    # 2. Remove comments
    text = re.sub(r'%.*$', '', text, flags=re.MULTILINE)

    # 3. Remove tabular environments but keep cell content
    # \begin{tabular*}{...}{...} ... \end{tabular*}
    text = re.sub(r'\\begin\{tabular\*?\}[^}]*\}(?:\{[^}]*\})?', '', text)
    text = re.sub(r'\\end\{tabular\*?\}', '', text)

    # 4. Remove column separators and alignment
    text = text.replace('&', ' | ')
    text = re.sub(r'\\\\(?:\[.*?\])?', '\n', text)

    # 5. Strip font commands — \fontspec{...} \fontsize{...}{...} \selectfont etc.
    text = re.sub(r'\\fontspec\{[^}]*\}', '', text)
    text = re.sub(r'\\fontsize\{[^}]*\}\{[^}]*\}', '', text)
    text = re.sub(r'\\selectfont', '', text)
    text = re.sub(r'\\addfontfeatures\{[^}]*\}', '', text)

    # 6. Strip color/formatting commands, keep content
    text = re.sub(r'\\color\{[^}]*\}', '', text)
    text = re.sub(r'\\textcolor\{[^}]*\}\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\(?:textbf|textit|emph|underline|textsc)\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\(?:small|footnotesize|tiny|large|Large|LARGE|huge|Huge|normalsize)\b', '', text)

    # 7. Convert \href{url}{text} → text
    text = re.sub(r'\\href\{[^}]*\}\{([^}]*)\}', r'\1', text)

    # 8. Strip layout commands
    for cmd in ['vspace', 'hspace', 'hfill', 'vfill', 'noindent', 'centering',
                'raggedright', 'raggedleft', 'newpage', 'clearpage', 'pagebreak',
                'item', 'enspace', 'quad', 'qquad']:
        text = re.sub(rf'\\{cmd}(?:\{{[^}}]*\}}|\[[^\]]*\])?', ' ', text)

    # 9. Remove environments we don't need
    text = re.sub(r'\\begin\{(?:center|itemize|enumerate|description)\}', '', text)
    text = re.sub(r'\\end\{(?:center|itemize|enumerate|description)\}', '', text)

    # 10. Any remaining \command{content} → content
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)

    # 11. Any remaining bare \commands → remove
    text = re.sub(r'\\[a-zA-Z]+(?:\[[^\]]*\])?', '', text)

    # 12. Clean up
    text = re.sub(r'[{}]', '', text)
    text = re.sub(r'@[^@\s]*@', '', text)  # tabular @ expressions
    text = re.sub(r'\|(?:\s*\|)+', '|', text)  # collapse multiple pipes
    text = re.sub(r'(?m)^\s*[lr]\s*$', '', text)  # stray tabular column specs
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\| *', ' | ', text)
    text = re.sub(r'(?m)^\s+$', '', text)  # blank-ish lines
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()
