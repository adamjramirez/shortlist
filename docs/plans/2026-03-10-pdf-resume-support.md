# Plan: PDF Resume Support

## Goal

Accept PDF resumes in addition to LaTeX. PDF users get the full experience: profile generation, scoring, cover letters, and tailored resumes. Tailored resumes are generated as LaTeX from a built-in template, compiled to PDF for download.

## Current State

- Upload accepts `.tex` only
- Profile generation reads raw `.tex` text
- Scoring uses `fit_context` (not the resume file directly) — no change needed
- Cover letters extract text from `.tex` via `_extract_resume_summary()` which strips LaTeX commands
- Resume tailoring edits `.tex` source — needs a new path for PDF users
- Download serves `.tex` file — needs to also serve `.pdf`

## Approach

PDF users get a different tailoring path:
1. On upload: extract text from PDF via `pdfplumber`, store both raw PDF and extracted text
2. Profile generation + cover letters: use extracted text (same as `.tex` text)
3. Tailoring: LLM generates a **complete** LaTeX resume from extracted text + job description using a built-in template, rather than surgically editing the user's file
4. Download: compile LaTeX → PDF via `tectonic`, serve PDF (with `.tex` also available)
5. Show caution label on tailored resume (same pattern as cover letter warning)

LaTeX users keep their current flow unchanged. PDF compilation for LaTeX users is a follow-up (their resumes use `fontspec`/XeLaTeX which needs separate font handling).

## Kill Criterion

If `pdfplumber` text extraction is garbled on >30% of test PDFs, stop and reconsider (try `pymupdf` or require LaTeX).

---

## Checkpoint 1: Database migration + PDF upload

**Goal:** Accept `.pdf` uploads, extract text, store both. Single migration for all new columns.

### Task 1.1: Add `pdfplumber` dependency

**File:** `requirements.txt` (modify)
**Steps:**
- Add `pdfplumber` to requirements.txt
- `uv pip install pdfplumber`

### Task 1.2: Single migration — all new columns

**File:** `shortlist/api/models.py` (modify)
**File:** `alembic/versions/xxx_pdf_resume_support.py` (create)
**Purpose:** All schema changes in one migration to avoid multiple deploys.

Resume model:
- `resume_type = Column(String, default="tex")` — `"tex"` or `"pdf"`
- `extracted_text_key = Column(String)` — S3 key for extracted text from PDFs

Job model:
- `tailored_resume_pdf_key = Column(String)` — S3 key for compiled PDF

### Task 1.3: Add `resume_type` to API response schema

**File:** `shortlist/api/schemas.py` (modify)
**File:** `shortlist/api/routes/resumes.py` (modify)
**File:** `web/src/lib/types.ts` (modify)
**Purpose:** Frontend needs `resume_type` to show PDF-specific messaging and choose download format.

- Add `resume_type: str = "tex"` to `ResumeResponse` Pydantic schema
- Include `resume_type` in `_resume_to_response()`
- Add `resume_type: string` to frontend `Resume` type

### Task 1.4: Add `has_tailored_pdf` to job schemas

**File:** `shortlist/api/schemas.py` (modify)
**File:** `shortlist/api/routes/jobs.py` (modify)
**File:** `web/src/lib/types.ts` (modify)
**Purpose:** Frontend needs to know whether to request PDF or `.tex` download.

- Add `has_tailored_pdf: bool = False` to `JobSummary` Pydantic schema
- Populate in `_job_to_summary()`: `has_tailored_pdf=bool(job.tailored_resume_pdf_key)`
- Add `has_tailored_pdf: boolean` to frontend `JobSummary` type

### Task 1.5: Update upload endpoint to accept PDF

**File:** `shortlist/api/routes/resumes.py` (modify)
**Purpose:** Accept `.pdf` files, extract text, store both.

**Steps:**
- Change file validation: accept `.tex` or `.pdf`
- If `.pdf`: lazy-import `pdfplumber` inside the handler (defensive — keeps app working if import fails), extract text, store PDF to S3 at `{user_id}/resumes/{filename}`, store extracted text to S3 at `{user_id}/resumes/{filename}.txt`
- Set `resume_type = "pdf"` and `extracted_text_key` on the Resume record
- If `.tex`: same as today, `resume_type = "tex"`
- If extraction returns empty/whitespace: return 400 "Could not extract text from this PDF"

**Test:**
- Upload a `.pdf` → 201, resume_type="pdf", extracted_text_key set
- Upload a `.tex` → 201, resume_type="tex" (unchanged)
- Upload a `.doc` → 400 (rejected)
- Upload empty/garbled PDF → 400

### Task 1.6: Update frontend upload to accept PDF

**File:** `web/src/app/profile/page.tsx` (modify)
**Steps:**
- Change `accept=".tex"` to `accept=".tex,.pdf"`
- Change label from "Upload .tex file" to "Upload resume (.tex or .pdf)"

**Verify:** Frontend build passes, can select PDF in file picker.

---

## Checkpoint 2: Profile generation + cover letters with PDF text

**Goal:** Profile generation and cover letters work with extracted PDF text.

### Task 2.1: Split `_get_best_resume()` into selection + fetching

**File:** `shortlist/api/routes/tailor.py` (modify)
**Purpose:** The function is overloaded (selection + storage fetch + size heuristic). Split into two:

- `_pick_best_resume(user, matched_track, session) -> Resume` — selection logic only. Prefer track match first, then recency. Remove the file-size heuristic (it was for distinguishing LaTeX templates from real resumes, but PDF files are always large and would always win over a better-matched `.tex` file).
- `_fetch_resume_text(resume, storage) -> tuple[str, str, str]` — fetches text from storage. Returns `(resume_text, filename, resume_type)`. If `resume.resume_type == "pdf"`: fetch from `resume.extracted_text_key`. If `"tex"`: fetch from `resume.s3_key`.

Update all callers:
- `tailor_job()` — needs all three return values (uses `resume_type` to choose tailoring path)
- `generate_cover_letter_endpoint()` — uses `resume_text` and can ignore `resume_type`

**Test:** With both a `.tex` and `.pdf` resume uploaded, track-matched `.tex` is preferred over unmatched `.pdf`.

### Task 2.2: Update `_extract_resume_summary()` for plain text input

**File:** `shortlist/processors/cover_letter.py` (modify)
**Purpose:** Currently strips LaTeX commands (`\begin{document}`, `\fontspec`, `\textbf{}` etc.). When called with extracted PDF text (plain text), it won't break but wastes work and could mangle text containing backslashes.

**Steps:**
- Add a quick check at the top: if the text doesn't contain `\begin{document}` or `\documentclass`, it's plain text — return it with only whitespace cleanup (collapse blank lines, strip leading/trailing whitespace)
- LaTeX path unchanged

**Test:** Plain text input passes through without mangling. LaTeX input still gets stripped.

### Task 2.3: Update profile generation to use extracted text

**File:** `shortlist/api/routes/profile.py` (modify)
**Purpose:** When resume is PDF, read extracted text instead of raw bytes.

**Steps:**
- After fetching resume, check `resume.resume_type`
- If `"pdf"`: fetch from `resume.extracted_text_key` instead of `resume.s3_key`
- If `"tex"`: unchanged

**Test:** Profile generation with a PDF resume returns valid fit_context + tracks.

---

## Checkpoint 3: LaTeX resume template + generation

**Goal:** A clean, ATS-friendly LaTeX template that the LLM can populate for PDF users.

### Task 3.1: Create built-in resume template

**File:** `shortlist/templates/resume_template.tex` (create)
**Purpose:** A professional, single-column LaTeX template. Simple enough that LLM output compiles reliably.

**Requirements:**
- Single column, clean hierarchy
- Sections: header (name, contact), summary, experience (company/title/dates/bullets), education, skills
- No `fontspec` (requires XeLaTeX) — use standard `pdflatex`-compatible fonts only
- No tables for layout, no graphics — ATS-friendly
- Packages limited to: `article`, `geometry`, `enumitem`, `hyperref`, `titlesec`

### Task 3.2: Create PDF-to-tailored-resume prompt

**File:** `shortlist/processors/resume.py` (modify)
**Purpose:** New prompt for generating a complete LaTeX resume from extracted text.

Add `GENERATE_RESUME_PROMPT`:
- Input: extracted resume text + job description + template
- Output: complete LaTeX document using the template structure
- Instructions: use ONLY facts from the original resume, reorder/emphasize for the job, fill in the template sections
- Same guardrails as current tailoring: no invented experience, no fake metrics

### Task 3.3: Add `generate_resume_from_text()` function

**File:** `shortlist/processors/resume.py` (modify)
**Purpose:** New function for PDF users — generates complete LaTeX from text.

```python
def generate_resume_from_text(resume_text: str, job_title: str, 
                               job_company: str, job_description: str) -> TailoredResume | None:
```

- Loads template from `shortlist/templates/resume_template.tex`
- Calls LLM with `GENERATE_RESUME_PROMPT`
- Returns `TailoredResume` with complete LaTeX

**Test:** Given sample resume text + job description, returns valid LaTeX that includes key facts from the original.

---

## Checkpoint 4: LaTeX → PDF compilation

**Goal:** Compile generated LaTeX to PDF for download.

### Task 4.1: Add `tectonic` to Docker image with pre-cache

**File:** `Dockerfile` (modify)
**Purpose:** Install tectonic and pre-cache TeX packages so first user compilation isn't slow.

**Steps:**
- Download tectonic static binary (~25MB)
- Add a dummy compile step in the Docker build to force package download:
  ```dockerfile
  RUN echo '\documentclass{article}\begin{document}hello\end{document}' > /tmp/test.tex && \
      tectonic /tmp/test.tex && rm /tmp/test.tex /tmp/test.pdf
  ```
- This caches ~100MB of TeX packages into the image layer, eliminating runtime cold start

**Verify:** `tectonic --version` works in container, and compiling a simple doc doesn't trigger downloads.

### Task 4.2: Create LaTeX compilation utility

**File:** `shortlist/processors/latex_compiler.py` (create)
**Purpose:** Compile `.tex` → `.pdf` using tectonic.

```python
def compile_latex(tex_content: str) -> bytes | None:
    """Compile LaTeX string to PDF bytes. Returns None on failure."""
```

- Write tex to temp file
- Run `tectonic` in subprocess with timeout (30s)
- Read PDF bytes
- Clean up temp files
- Return None + log on failure (don't crash)

**Test:** Given valid LaTeX, returns PDF bytes starting with `%PDF`. Given invalid LaTeX, returns None.

### Task 4.3: Update tailor endpoint for PDF users

**File:** `shortlist/api/routes/tailor.py` (modify)
**Purpose:** For PDF users, use `generate_resume_from_text()` instead of `tailor_resume_from_text()`, compile to PDF, store both.

**Steps:**
- In `tailor_job()`, call `_pick_best_resume()` then `_fetch_resume_text()` to get `(resume_text, filename, resume_type)`
- If `resume_type == "pdf"`: call `generate_resume_from_text()` with extracted text
- If `resume_type == "tex"`: existing `tailor_resume_from_text()` path (unchanged)
- For PDF users only: attempt `compile_latex()` on the generated LaTeX
  - If compilation succeeds: store `.pdf` to S3 at `{user_id}/tailored/{job_id}.pdf`, set `tailored_resume_pdf_key`
  - If compilation fails: still store `.tex`, set `tailored_resume_key`, log warning. **Don't fail the request.** User gets `.tex` download with a note that PDF compilation failed
- LaTeX users: no compilation (their resumes use `fontspec`/XeLaTeX — follow-up)

**Note:** Compilation should stay on-demand (user clicks button). Don't add it to batch pipeline runs — adds ~5-15s per resume.

### Task 4.4: Update download endpoint

**File:** `shortlist/api/routes/tailor.py` (modify)
**Purpose:** Serve PDF by default when available, with option to download `.tex`.

**Steps:**
- Add `format` query param: `?format=pdf` (default) or `?format=tex`
- If `tailored_resume_pdf_key` exists and format=pdf: serve PDF with `application/pdf` content type
- If format=tex or no PDF available: serve `.tex` (existing behavior)
- Return 404 if neither exists

### Task 4.5: Update frontend download button

**File:** `web/src/components/JobCard.tsx` (modify)
**File:** `web/src/lib/api.ts` (modify)
**Purpose:** Download PDF by default when available, show both options.

**Steps:**
- Primary button: "📄 Download Tailored Resume" — requests `?format=pdf` if `job.has_tailored_pdf`, else `?format=tex`
- Secondary link below: "Download .tex source" (always available when tailored)
- For PDF downloads: filename ends in `.pdf`
- When `has_tailored_pdf` is true: remove the "paste it into Overleaf" helper text (they have a PDF)
- When `has_tailored_pdf` is false and `has_tailored_resume` is true: keep existing Overleaf text (LaTeX users, or PDF compilation failed)

### Task 4.6: Integration test for PDF tailoring path

**File:** `tests/test_api_tailor.py` (modify or create)
**Purpose:** End-to-end test through the tailor endpoint with a PDF resume.

**Steps:**
- Upload a PDF resume (mock `pdfplumber` extraction in test)
- Create a scored job
- Call POST `/{job_id}/tailor`
- Verify: `tailored_resume_key` is set (`.tex` stored)
- Verify: `tailored_resume_pdf_key` is set if compilation succeeded (mock `compile_latex` to return fake PDF bytes)
- Verify: GET `/{job_id}/resume?format=pdf` returns PDF content type
- Verify: GET `/{job_id}/resume?format=tex` returns tex content type

---

## Checkpoint 5: Caution labels + UX

**Goal:** Show appropriate warnings on generated resumes, update copy throughout.

### Task 5.1: Add caution label to tailored resume section

**File:** `web/src/components/JobCard.tsx` (modify)
**Purpose:** Same pattern as cover letter warning. Applies to all users, not just PDF.

Add after the download button:
```
⚠️ Review before sending
This resume was adjusted by AI to better match this role. It only uses facts from
your original resume — nothing is invented — but always verify the final version.
```

### Task 5.2: Update upload UX with LaTeX preference messaging

**File:** `web/src/app/profile/page.tsx` (modify)
**File:** `web/src/components/OnboardingChecklist.tsx` (modify)
**Steps:**
- Change file input `accept=".tex,.pdf"` and label to "Upload resume (.tex or .pdf)"
- Below the upload button, add: "LaTeX (.tex) recommended for best results"
- Add a hoverable/expandable info tooltip or `<details>` element explaining why:
  ```
  Why LaTeX?
  With a .tex resume, Shortlist can surgically edit your actual resume — reordering 
  bullets and adjusting emphasis while preserving your exact formatting. With a PDF, 
  we generate a new tailored resume using a standard template, which won't match your 
  original design.
  ```
- After a PDF is uploaded, show a subtle note on the resume row: "PDF — tailored resumes will use a standard template"
- Onboarding checklist: "Upload your resume" (already generic, just verify)

### Task 5.3: Update landing page

**File:** `web/src/app/page.tsx` (modify)
**Steps:**
- Change "Your resume in LaTeX" to "Your resume" with note: "LaTeX preferred, PDF also works"

---

## Checkpoint 6: Review + deploy

- Run full test suite (`uv run pytest tests/ -q`)
- Build frontend (`cd web && npm run build`)
- Read all changed files
- Deploy to Fly.io (`fly deploy --app shortlist-web`)
- Manual test: upload PDF → generate profile → run → tailor → download PDF

---

## Follow-up (not in this plan)

- **PDF compilation for LaTeX users** — with tectonic in the image, LaTeX users could also get PDF downloads instead of going to Overleaf. Requires: font handling for `fontspec`/XeLaTeX, pre-caching additional packages. Separate plan.
- **Show extracted text for review** — if PDF extraction quality is spotty, let users see/edit what was extracted before profile generation.
- **Batch compilation in pipeline** — currently compilation is on-demand only (user clicks tailor button). Adding to pipeline runs would add ~5-15s per resume and isn't worth it until we have scheduled runs.

---

## Risks

1. **PDF text extraction quality** — Two-column resumes, tables, fancy formatting may extract poorly. Mitigation: test on 5+ real PDFs before shipping. If bad, show extracted text to user for review (follow-up).
2. **tectonic package cache in Docker** — Pre-cache adds ~100MB to image (169MB → ~295MB). Acceptable for Fly.io shared-cpu-2x.
3. **LLM generating invalid LaTeX** — Template is simple but LLM could still break it. Mitigation: compilation step catches this gracefully — user gets `.tex` with error message, not a 500.
4. **`_get_best_resume()` refactor** — Splitting into two functions changes calling convention. All callers explicitly listed in Task 2.1. Low risk since there are only two: `tailor_job()` and `generate_cover_letter_endpoint()`.

## Dependencies

- `pdfplumber` (Python, pure — lazy-imported in upload handler)
- `tectonic` (static binary, ~25MB + ~100MB package cache)
- One Alembic migration (three new columns: `resume_type`, `extracted_text_key`, `tailored_resume_pdf_key`)
