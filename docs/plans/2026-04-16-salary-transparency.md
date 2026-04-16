# 2026-04-16 — Salary transparency

## Problem

Every visible job card shows a salary (e.g. "300k-450k USD") with no indication that it's LLM-inferred. 99.8% of scored jobs have `salary_text IS NULL` (no source data); 100% of visible jobs (fit_score ≥75) are unlisted. Gemini infers the range from title + company + location + its own training data. Users anchor on fabricated numbers for triage decisions.

## Goal

Make it instantly obvious on the card whether a salary is **listed** (from the posting) or **estimated** (by an AI). Give skeptics one tap to see how the estimate was produced.

## Approach

Lean on typography to do the work. No labels, no chips, no icons on the card at rest.

- **Listed** salaries: bold, full-weight, no prefix.
- **Estimated** salaries: `~` prefix, muted (gray-500), lighter weight, dotted underline → popover on click.
- **Popover**: confidence + 1-sentence methodology + link to `/about/estimates`.

### Corrections from initial design (post-advisor)

- **Dropped range-width-encodes-confidence.** The prompt doesn't instruct Gemini to widen ranges at lower confidence. Confidence is LLM self-assessed and weakly correlated with accuracy. Relying on range width in the UI would be a lie. Show confidence explicitly in the popover instead.
- **Dropped per-job `salary_basis` field.** The basis is static: always "title + company + location + Gemini's training data." A single methodology page says it once. No migration needed.
- **Added sanity filter for `salary_text`.** Current DB has 7 "listed" rows that are HN parsing noise (`$13`, `$32`, `$135`). `salary_text IS NOT NULL` is not a clean "listed" signal. Filter to `parsed_max_usd >= $50k` before treating as authoritative.
- **Correct PROJECT_LOG.md.** The claim that `salary_confidence` is dropped at `pipeline.py:192` is wrong — it's persisted at line 193 (SQLite) and line 688 (PG). Must fix so future sessions don't re-chase.

## File-by-file plan

### 1. Correct the log

**`PROJECT_LOG.md`** — remove the false "pre-existing quiet data-loss bug" claim. Replace with: "`salary_confidence` is persisted but not exposed through the API."

### 2. Backend — expose what's already in the DB

**`shortlist/api/schemas.py`** (`JobSummary`, line 102):
- Add `salary_text: str | None = None`
- Add `salary_confidence: str | None = None`
- Add `salary_listed: bool = False` — computed server-side, true iff `salary_text` passes sanity filter

**`shortlist/api/routes/jobs.py`** (wherever `JobSummary` is constructed from the ORM row):
- Pass `salary_text=job.salary_text`
- Pass `salary_confidence=job.salary_confidence`
- Compute `salary_listed = is_listed_salary(job.salary_text)` using the sanity filter

**`shortlist/processors/filter.py`** (already has `_parse_max_salary` at line 367):
- Export a new helper `is_listed_salary(salary_text: str | None) -> bool` that returns `True` iff `salary_text` parses to a USD value ≥ $50,000. Reuse `_parse_max_salary`. Annual-only (skip monthly).
- The helper lives in `filter.py` because the parsing logic is there; re-export from `shortlist.api.routes.jobs` or import directly.

### 3. Frontend types

**`web/src/lib/types.ts`**:
- Add `salary_text: string | null;`
- Add `salary_confidence: string | null;`
- Add `salary_listed: boolean;`

### 4. Frontend — JobCard

**`web/src/components/JobCard.tsx`** (line 180-182, the salary span):

Replace the single `<span>` with conditional logic:

```tsx
{/* Listed: bold, full color */}
{job.salary_listed && job.salary_text && (
  <span className="font-mono text-sm font-semibold text-gray-900 shrink-0">
    {formatListedSalary(job.salary_text)}
  </span>
)}

{/* Estimated: tilde, muted, dotted underline, click → popover */}
{!job.salary_listed && salary && (
  <SalaryEstimate
    value={salary}
    confidence={job.salary_confidence}
  />
)}
```

**New component: `web/src/components/SalaryEstimate.tsx`**:
- Renders `~{value}` with `font-mono text-sm font-normal text-gray-500 decoration-dotted underline underline-offset-2 cursor-help shrink-0`
- On click: opens popover anchored below the span.
- Popover content (3 lines):
  1. "Estimated — not in the job posting"
  2. "Based on role, company, location · {confidence} confidence"
  3. Link: "How we estimate →" (to `/about/estimates`)
- Popover uses the new design-system popover primitive (see DESIGN.md update below).

**New helper: `formatListedSalary(text: string): string`**
- Cheap normalization of source salary text for display.
- Trim whitespace, strip trailing "per year"/"/yr"/"annually", keep as-is otherwise.
- Safe fallback: return raw text if parse fails (the sanity filter already gated).

### 5. Frontend — methodology page

**New: `web/src/app/about/estimates/page.tsx`**
- One screen of prose, matching DESIGN.md container rules.
- Sections: "Listed vs estimated" · "What the AI knows" · "What it doesn't" · "Confidence" · "Why we show estimates anyway."
- Static — no API calls, no state.
- Linked from popover and from footer.

### 6. Design system — add popover primitive

**`web/DESIGN.md`** — add §9 "Popover":
- Trigger: button/span with `cursor-help` or explicit affordance.
- Container: `bg-white border border-gray-200 shadow-lg rounded-lg p-4 text-sm`.
- Max width: `max-w-xs`.
- Anchored below trigger with `absolute top-full mt-2 right-0` (or `left-0` depending on space).
- Close on click-outside or Escape.
- Rule: never use popover for primary actions — only for disclosure/methodology.

### 7. Tests

**`tests/api/test_jobs_salary.py`** (new):
- `salary_text` + `salary_confidence` appear in `JobSummary` response
- `salary_listed=True` when `salary_text="$200k"` (parseable, ≥$50k)
- `salary_listed=False` when `salary_text="$32"` (below threshold)
- `salary_listed=False` when `salary_text=None`
- `salary_listed=False` when `salary_text="$5k/month"` (monthly — skipped)

**`tests/test_filter_is_listed.py`** (new):
- `is_listed_salary(None)` → False
- `is_listed_salary("$200k")` → True
- `is_listed_salary("$200,000")` → True
- `is_listed_salary("$13")` → False (HN noise)
- `is_listed_salary("$40k")` → False (below $50k threshold)
- `is_listed_salary("$5k/month")` → False (monthly)

**`web/src/__tests__/SalaryEstimate.test.tsx`** (if jest-dom is wired — verify first):
- Renders `~` prefix
- Popover opens on click
- Popover closes on Escape
- Link routes to `/about/estimates`

## Non-goals (explicit)

- **No new DB migration.** All fields already exist.
- **No new LLM fields.** `salary_basis` deferred — static methodology covers it.
- **No range-width manipulation.** Deferred until we have ground-truth validation (see below).
- **No range expansion based on confidence.** Same reason.
- **No external comp data (levels.fyi, Glassdoor).** Long-term option C — separate future plan.

## Verification

1. `pytest tests/ -q` → all green, +~10 new tests.
2. `cd web && npm run build` → clean, no type errors.
3. Local E2E: run the API + web locally, sign in, look at the job list:
   - Jobs with no `salary_text` show `~$300–450k` in muted gray.
   - Click → popover appears with methodology link.
   - Escape closes popover.
   - Jobs with `salary_text="$200k"` (if any exist) show "$200k" bold.
4. `/about/estimates` renders.
5. Mobile: popover on tap, dismiss on second tap outside.

## Rollout

- Deploy after all tests pass. No migration, no data backfill, no schema change — safe rollback is a revert.
- Monitor: PostHog event `salary_estimate_expanded` (add to analytics.ts) to see how many users tap for methodology. Gives us a signal for whether the transparency layer actually gets read.

## Future work (not this plan)

- **External comp data (option C):** integrate levels.fyi/Glassdoor/BLS tables. Replaces LLM inference with real ranges. Keeps same UI.
- **Prompt-widened ranges:** instruct Gemini to widen the range at lower confidence, then re-enable "range width encodes confidence" UI. Requires validation against real data.
- **Validation against real listings:** once we have enough rows where `salary_text IS NOT NULL AND is_listed_salary = true`, compare LLM estimates on similar jobs to the listed range. Gives us a real accuracy number.

## Open questions

- Should the popover also appear on hover (desktop) AND click (mobile)? Or click-only everywhere for consistency? → lean click-only; hover popovers are a11y/mobile pain.
- Should listed salaries also get the popover (with "This is from the posting" message)? → lean no, too much for a non-issue.
- Confidence wording in popover: "low confidence" vs "estimate quality: low"? → Adam to pick tone; defaulting to first.
