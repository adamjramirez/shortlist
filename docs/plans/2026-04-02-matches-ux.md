# Plan: Matches Page UX Improvements

## Fixes

### 1. Stronger hover on rows
**File:** `web/src/components/JobCard.tsx`
- Change `hover:bg-gray-50/80` → `hover:bg-gray-100` — visible contrast on gray-50 canvas
- This sets up fix 2 — the hover state is the container for quick-action buttons appearing

### 2. Quick-action buttons on collapsed rows
**File:** `web/src/components/JobCard.tsx`

**Nested button fix (blocker):**
- Change outer `<button onClick={handleExpand}>` to `<div role="button" tabIndex={0} onClick={handleExpand} onKeyDown={handleEnterKey}>`
- Add `handleEnterKey` that calls `handleExpand` on Enter/Space
- Inner quick-action `<button>` elements are now valid HTML

**Quick actions:**
- Add Save (bookmark) and Skip (x) icon buttons on the right side of the collapsed row
- Style: `opacity-0 group-hover:opacity-100 transition-opacity` — fade in on hover
- Add `group` class to the row wrapper
- Small ghost buttons: `w-7 h-7 rounded-full hover:bg-gray-200 flex items-center justify-center`
- SVG icons, no text — compact
- Click calls `handleStatus()` with `e.stopPropagation()` — no expand
- If already saved/applied/skipped, don't show quick actions (badge on row is enough)
- Mobile fallback: no hover on touch — users expand to act. Acceptable.

### 3. Compact action bar at top of expanded view
**File:** `web/src/components/JobCard.tsx`
- Move actions (View listing + Apply direct + Save/Applied/Skip + source) to first position in expanded view
- **No section label, no extra padding** — just one line of buttons, `mb-4`
- Interest note stays the star, immediately below the compact bar
- Total height cost: ~32px — barely delays content

### 4. Merge resume + cover letter into one Tools section
**File:** `web/src/components/JobCard.tsx`
- Replace two `pt-4 border-t` sections with one `pt-4 border-t` section labeled "Tools"
- Both "Tailor resume" and "Generate cover letter" buttons on the same line
- Generated content (cover letter text, download buttons) renders below when present
- Removes one visual divider — less noise

### 5. Status filter pills + backend support
**File:** `shortlist/api/routes/jobs.py`
- Add `user_status` query param to list endpoint
- `"new"` → `WHERE user_status IS NULL`
- `"saved"` / `"applied"` / `"skipped"` → `WHERE user_status = ?`
- `None` / `"all"` → no filter (current behavior)

**File:** `shortlist/api/schemas.py`
- Add `counts` to `JobListResponse`: `{ new: int, saved: int, applied: int, skipped: int }`

**File:** `shortlist/api/routes/jobs.py`
- Compute counts in the same query: `COUNT(*) FILTER (WHERE user_status IS NULL)` etc.
- Return alongside existing `jobs` and `total`

**File:** `web/src/lib/types.ts`
- Add `counts` to job list response type

**File:** `web/src/lib/api.ts`
- Add `status` param to job list request

**File:** `web/src/app/page.tsx`
- Add `status` state: `"all" | "new" | "saved" | "applied" | "skipped"`
- Render as pill buttons: `All · New (12) · Saved (8) · Applied (3) · Skipped`
- Active pill: `bg-gray-900 text-white`
- Inactive pill: `border border-gray-300 text-gray-600`
- Skipped pill: same style but at the end, less prominent
- Counts from API response shown in parentheses

### 6. Summary stats in header
**File:** `web/src/app/page.tsx`
- Use the `counts` from fix 5's API response
- Replace the `Across hn, linkedin...` line with: `12 new · 8 saved · 3 applied`
- New count in `text-emerald-600` if > 0
- This replaces the source summary (sources are visible per-job in expanded view)

**Test:** Unit test for the counts in the API response

---

## Execution order
```
1 (hover CSS)
  → 2 (quick actions + div refactor)
    → 3 (compact action bar)
      → 4 (merge tools)
        → 5 (status filter + backend counts)
          → 6 (header stats)
```

Steps 1-4: frontend only, no tests needed beyond `npm run build`.
Steps 5-6: backend change, needs pytest.

## Verification
- `cd web && npm run build` — clean after each step
- `source .venv/bin/activate && pytest tests/ -q` — all pass after step 5
- Manual: hover rows, see Save/Skip buttons fade in
- Manual: click Save on collapsed row — badge appears, no expand
- Manual: filter by Saved — only saved jobs shown, count matches
- Manual: expand job — action bar is first thing, interest note below
