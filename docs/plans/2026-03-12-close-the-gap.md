# Close the Gap: Web UI vs CLI Brief

**Goal:** Ship 4 features to bring the web UI to parity with the CLI brief.  
**Kill criteria:** If interest pitches are generic after 10 samples → revert to reasoning only. If tailored LaTeX doesn't compile → fall back to text-only suggestions.

---

## Migration (shared across all batches)

**File:** `alembic/versions/003_add_columns.py` (create)  
**File:** `shortlist/api/models.py` (modify)

```python
def upgrade():
    op.add_column("jobs", sa.Column("interest_note", sa.Text()))
    op.add_column("jobs", sa.Column("career_page_url", sa.String()))

def downgrade():
    op.drop_column("jobs", "career_page_url")
    op.drop_column("jobs", "interest_note")
```

Model: add `interest_note = Column(Text)` and `career_page_url = Column(String)` to `Job`.

Both nullable, no data migration. Safe on existing data.

**Verify:** `python -m pytest tests/ -x -q` — 412+ pass

---

## Batch 1: Interest Pitch + New/Seen Badges

### Task 1.1: Interest pitch generator

**File:** `shortlist/processors/enricher.py` (modify)

Add function:
```python
def generate_interest_note(company: str, job_title: str, job_description: str,
                           fit_context: str, intel: CompanyIntel | None = None) -> str | None:
```

- Prompt: "Write 3 sentences about why a candidate with this background would be genuinely interested in this role. Be specific to the company and role, not generic."
- Inputs: fit_context, intel.summary() (or "No company intel available" if None), title, company, description[:500]
- Returns plain text string or None on LLM failure
- No JSON schema — free-form text response
- **Works with or without intel** — job-board companies (Jobgether etc.) still get a pitch based on role description alone

**Test:** `tests/test_enricher.py` (create) — mock `llm.call_llm`, verify prompt includes fit_context and handles `intel=None`.

**Verify:** Local smoke test with real LLM for Loom VP Eng and Jobgether Director role.

---

### Task 1.2: Wire interest pitch into pipeline

**File:** `shortlist/pipeline.py` (modify) — inside `_enrich_scored_jobs()`

After the enrichment loop, generate interest notes for all scored jobs that don't have one yet:

```python
# Generate interest notes for scored jobs missing one
unenriched_notes = pgdb.fetch_jobs(
    conn, user_id, "scored",
    extra_where="AND interest_note IS NULL AND fit_score >= %s",
    extra_params=[SCORE_VISIBLE],
    order="fit_score DESC", limit=config.brief.top_n,
)
for row in unenriched_notes:
    _check_cancel()
    intel_json = row.get("enrichment")
    intel = CompanyIntel.from_json(row["company"], intel_json) if intel_json else None
    note = generate_interest_note(
        row["company"], row["title"], row["description"] or "",
        config.fit_context, intel,
    )
    if note:
        pgdb.update_job(conn, row["id"], interest_note=note)
conn.commit()
```

This runs after enrichment, so enriched jobs already have intel. Job-board companies that were skipped by enrichment still get interest notes with `intel=None`.

**LLM cost:** ~1 call per match. ~30 matches × ~1.5s = ~45s extra per run. Sequential is fine — runs during enrichment phase which is already per-source.

**Verify:** `python -m pytest tests/ -x -q` — all pass

---

### Task 1.3: Expose interest_note in API

**File:** `shortlist/api/schemas.py` (modify)  
**File:** `shortlist/api/routes/jobs.py` (modify)

- Add `interest_note: str | None = None` to `JobDetail`
- In `_job_to_detail()`: `interest_note=job.interest_note`

**Test:** `tests/api/test_jobs.py` — add test: create job with interest_note, GET detail, verify field present.

**Verify:** `python -m pytest tests/api/test_jobs.py -x -q`

---

### Task 1.4: Show interest pitch in JobCard

**File:** `web/src/lib/types.ts` (modify) — add `interest_note?: string` to JobDetail  
**File:** `web/src/components/JobCard.tsx` (modify)

In expanded detail view, after score reasoning, before Company Intel:
```tsx
{detail.interest_note && (
  <div>
    <p className="text-xs font-medium uppercase text-gray-400 mb-1">
      Why you might be interested
    </p>
    <p className="text-sm text-gray-600 italic">{detail.interest_note}</p>
  </div>
)}
```

**Verify:** `cd web && npm run build` — compiles clean

---

### Task 1.5: New/seen badges on JobCard

**File:** `shortlist/api/schemas.py` (modify) — add `is_new: bool` to `JobSummary`  
**File:** `shortlist/api/routes/jobs.py` (modify)  
**File:** `web/src/components/JobCard.tsx` (modify)

Backend — use `brief_count` (already in model, already in initial migration):
```python
is_new=(job.brief_count or 0) == 0,
```

After a run completes, increment `brief_count` for all displayed jobs. Add to worker `execute_run()` after setting status to "completed":
```python
# Mark scored jobs as "briefed"
with conn.cursor() as cur:
    cur.execute(
        "UPDATE jobs SET brief_count = brief_count + 1 "
        "WHERE user_id = %s AND status = 'scored' AND fit_score >= %s",
        (user_id, SCORE_VISIBLE),
    )
conn.commit()
```

Frontend:
```tsx
{job.is_new && (
  <span className="rounded bg-green-100 px-1.5 py-0.5 text-green-700 text-xs font-medium">
    New
  </span>
)}
```

**Verify:** `npm run build` clean + `python -m pytest tests/ -x -q` all pass

---

### Batch 1 deploy checkpoint

```bash
python -m pytest tests/ -x -q  # 412+ pass
cd web && npm run build         # clean
git commit + push + fly deploy
```

**E2E test:** Clear jobs, start run. After HN scores + enriches:
- Job cards show "Why you might be interested" section (including Jobgether-sourced)
- All jobs show "New" badge on first run
- Run again → previous jobs lose "New" badge, only new finds show it

---

## Batch 2: Direct ATS Links

### Task 2.1: ATS URL lookup during enrichment

**File:** `shortlist/pipeline.py` (modify) — inside `_enrich_scored_jobs()`, after enrichment  
**File:** `shortlist/pgdb.py` (modify) — add helper

During enrichment, if we have a `website_domain` from intel, check the `nextplay_cache` for a known ATS:

```python
def get_career_url_for_domain(conn, domain: str) -> str | None:
    """Look up cached ATS URL for a company domain."""
    # Normalize: strip www., try both
    clean = domain.lower().removeprefix("www.")
    for d in [clean, f"www.{clean}"]:
        cached = get_cached_ats_discovery(conn, d)
        if cached and cached["ats"] and cached["slug"]:
            return _build_ats_url(cached["ats"], cached["slug"])
    return None

def _build_ats_url(ats: str, slug: str) -> str:
    if ats == "greenhouse":
        return f"https://boards.greenhouse.io/{slug}"
    elif ats == "lever":
        return f"https://jobs.lever.co/{slug}"
    elif ats == "ashby":
        return f"https://jobs.ashbyhq.com/{slug}"
    return ""
```

In pipeline `_enrich_scored_jobs()`, after enrichment:
```python
if intel and intel.website_domain and not row.get("career_page_url"):
    ats_url = pgdb.get_career_url_for_domain(conn, intel.website_domain)
    if ats_url:
        pgdb.update_job(conn, row["id"], career_page_url=ats_url)
```

**Verify:** `python -m pytest tests/ -x -q`

---

### Task 2.2: Expose career_page_url in API + frontend

**File:** `shortlist/api/schemas.py` (modify) — add `career_page_url: str | None = None` to `JobDetail`  
**File:** `shortlist/api/routes/jobs.py` (modify) — populate in `_job_to_detail()`  
**File:** `web/src/lib/types.ts` (modify) — add to JobDetail type  
**File:** `web/src/components/JobCard.tsx` (modify)

Frontend — in expanded detail view, next to "View Listing" button:
```tsx
{detail.career_page_url && detail.career_page_url !== job.url && (
  <a href={detail.career_page_url} target="_blank" rel="noopener noreferrer"
     className="inline-flex items-center rounded border border-blue-300 bg-blue-50 px-3 py-1 text-sm text-blue-700 hover:bg-blue-100">
    Apply Direct →
  </a>
)}
```

**Verify:** `npm run build` clean + tests pass

---

### Batch 2 deploy checkpoint

```bash
python -m pytest tests/ -x -q
cd web && npm run build
git commit + push + fly deploy
```

**E2E test:** Open a LinkedIn-sourced job where we know the company has a Greenhouse board (e.g., GitLab). Should show both "View Listing" (LinkedIn) and "Apply Direct →" (Greenhouse).

---

## Batch 3: Tailored Resume Download

### Task 3.1: Resume tailor endpoint

**File:** `shortlist/api/routes/tailor.py` (create)

New router mounted at `/api/jobs`.

`POST /api/jobs/{job_id}/tailor`:
- Auth required, verify `job.user_id == user.id`
- If `job.tailored_resume_key` already exists → return existing (don't re-tailor)
- Fetch user's resumes from DB, pick by `matched_track` (fallback: first available)
- Download .tex content from Tigris into memory (not tempfile — pass content directly)
- Run in background via `asyncio.to_thread` to avoid blocking:
  ```python
  tailored = await asyncio.to_thread(
      _tailor_job, tex_content, job.title, job.company, job.description
  )
  ```
- **Adapt `tailor_resume()`** to accept `resume_tex: str` directly instead of only `Path`. Add a new wrapper:
  ```python
  def tailor_resume_from_text(resume_tex: str, job_title: str, 
                               job_company: str, job_description: str) -> TailoredResume | None:
  ```
  This avoids the tempfile dance entirely — the existing `tailor_resume` reads the file then passes text to the LLM. The wrapper just skips the file read.
- Store tailored .tex in Tigris at `{user_id}/tailored/{job_id}.tex`
- Update `job.tailored_resume_key` in DB
- Return: `{"changes_made": [...], "interest_note": "...", "filename": "..."}`

**Error handling:**
- 404 if job not found or not user's
- 400 if no resumes uploaded
- 500 if LLM fails (with message)

**Test:** `tests/api/test_tailor.py` (create):
- Mock storage (put/get), mock LLM
- Test happy path: upload resume, create job, POST tailor → 200, key stored
- Test no resume → 400
- Test wrong user → 404
- Test already tailored → returns existing without re-calling LLM

**Verify:** `python -m pytest tests/api/test_tailor.py -x -q`

---

### Task 3.2: Resume download endpoint

**File:** `shortlist/api/routes/tailor.py` (same file)

`GET /api/jobs/{job_id}/resume`:
- Auth required, verify ownership
- Check `job.tailored_resume_key` exists → 404 if not
- Fetch .tex bytes from Tigris
- Return as `Response(content=data, media_type="application/x-tex", headers={"Content-Disposition": f"attachment; filename={filename}"})`

**Test:** Add to `tests/api/test_tailor.py`:
- Test download after tailor → 200 with .tex content
- Test download without tailor → 404

**Verify:** `python -m pytest tests/api/test_tailor.py -x -q`

---

### Task 3.3: Frontend tailor button

**File:** `web/src/lib/api.ts` (modify) — add:
```typescript
tailor: async (id: number) => fetchApi(`/api/jobs/${id}/tailor`, { method: "POST" }),
downloadResume: (id: number) => `/api/jobs/${id}/resume`,  // URL for <a href>
```

**File:** `web/src/components/JobCard.tsx` (modify)

In expanded detail view, below action buttons:
```tsx
// State
const [tailoring, setTailoring] = useState(false);
const [tailorResult, setTailorResult] = useState<{changes_made: string[]} | null>(null);

// If not yet tailored
{!job.has_tailored_resume && !tailoring && (
  <button onClick={handleTailor} className="...">
    ✨ Generate Tailored Resume
  </button>
)}

// Spinner during tailoring
{tailoring && (
  <div className="flex items-center gap-2 text-sm text-gray-500">
    <span className="animate-spin">⏳</span> Tailoring resume (~15s)...
  </div>
)}

// After tailoring / already tailored
{job.has_tailored_resume && (
  <a href={api.jobs.downloadResume(job.id)} className="...">
    📄 Download Tailored Resume (.tex)
  </a>
)}

// Show changes
{tailorResult?.changes_made && (
  <ul className="text-xs text-gray-500 mt-1">
    {tailorResult.changes_made.map((c, i) => <li key={i}>• {c}</li>)}
  </ul>
)}
```

`handleTailor`:
```typescript
async function handleTailor() {
  setTailoring(true);
  try {
    const result = await api.jobs.tailor(job.id);
    setTailorResult(result);
    onStatusChange?.(); // refresh card to update has_tailored_resume
  } catch (e) {
    // show error
  } finally {
    setTailoring(false);
  }
}
```

**Verify:** `npm run build` — compiles clean

---

### Task 3.4: Adapt tailor_resume for web

**File:** `shortlist/processors/resume.py` (modify)

Add wrapper that accepts text instead of Path:
```python
def tailor_resume_from_text(resume_tex: str, job_title: str, 
                             job_company: str, job_description: str) -> TailoredResume | None:
    """Tailor a resume from raw LaTeX text (for web — no file on disk)."""
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
            base_resume_path="(uploaded)",
            tailored_tex=data.get("tailored_tex", resume_tex),
            changes_made=data.get("changes_made", []),
            interest_note=data.get("interest_note", ""),
        )
    except Exception as e:
        logger.error(f"Failed to parse tailor response: {e}")
        return None
```

**Test:** `tests/test_resume.py` — mock LLM, verify `tailor_resume_from_text` parses response correctly.

**Verify:** `python -m pytest tests/ -x -q`

---

### Batch 3 deploy checkpoint

```bash
python -m pytest tests/ -x -q
cd web && npm run build
git commit + push + fly deploy
```

**E2E test:** 
1. Upload a .tex resume on profile page
2. Open a scored job → click "Generate Tailored Resume" → wait ~15s
3. Download .tex → verify it has the same structure as original with targeted changes
4. Refresh page → button shows "Download" (not "Generate" again)

---

## Execution Order

| Step | What | Est. | Deploy? |
|------|------|------|---------|
| 0 | Migration `003_add_columns.py` + model updates | 10m | — |
| 1.1 | Interest pitch generator + test | 20m | — |
| 1.2 | Wire into pipeline | 15m | — |
| 1.3 | API schema + route + test | 10m | — |
| 1.4 | JobCard interest section | 10m | — |
| 1.5 | New/seen badges (backend + frontend) | 15m | — |
| **CP1** | **Test + deploy Batch 1** | 10m | **✅** |
| 2.1 | ATS URL lookup + pgdb helper | 20m | — |
| 2.2 | API + frontend ATS link | 15m | — |
| **CP2** | **Test + deploy Batch 2** | 10m | **✅** |
| 3.1 | `tailor_resume_from_text` wrapper + test | 15m | — |
| 3.2 | Tailor endpoint + test | 30m | — |
| 3.3 | Download endpoint + test | 15m | — |
| 3.4 | Frontend tailor button | 20m | — |
| **CP3** | **Test + deploy Batch 3** | 10m | **✅** |

**Total: ~3.5 hours**

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Interest pitches are generic | Kill criteria: check 10 samples. Prompt includes fit_context + company intel for specificity. |
| Gemini returns bad JSON for tailor (LaTeX escapes) | `_parse_tailor_json` has regex fallback. Test with Gemini specifically before shipping. |
| Tailor endpoint slow (15s) | `asyncio.to_thread` prevents blocking. Frontend shows spinner with time estimate. |
| `nextplay_cache` domain mismatch | Normalize: strip `www.`, try both variants. |
| LLM call from tailor endpoint hangs on Fly | Same subprocess+curl approach as scorer. Already proven. |
