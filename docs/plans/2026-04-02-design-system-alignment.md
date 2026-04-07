# Plan: Design System Alignment

## Goal

Fix all deviations from `web/DESIGN.md` and apply improvement opportunities found during audit.

## Changes

### Checkpoint 1: Dashboard layout + dividers (page.tsx)

**Deviations 1, 2, 3, 4, 5, 10 + Improvements A, C**

**File:** `web/src/app/page.tsx` (modify)

1. **Job list dividers** (#3, Improvement A): Replace individual `<div className="border-b border-gray-200">` wrappers with `divide-y divide-gray-200/60` on the parent. Remove wrapper divs.

2. **Filter selects** (#1): Change from `text-xs` to `text-sm text-gray-600` on both score and track selects.

3. **Status pills** (#2): Add `cursor-pointer` to all status pill buttons.

4. **Pagination buttons** (#4): Change `text-gray-700` to `text-gray-600`.

5. **Empty state** (#5): When not running, add a profile link: "Check your profile →" if there are no jobs.

6. **Header alignment** (#10): Change filter/run button row from `sm:items-start` to `sm:items-center`.

7. **Filter layout** (Improvement C): Move status pills to their own line. Keep score/track selects + RunButton together on the header row.

**Verify:** `npm run build` clean, visual check that filters and pills render correctly.

### Checkpoint 2: RunButton sizing (RunButton.tsx)

**Deviation 6**

**File:** `web/src/components/RunButton.tsx` (modify)

1. Change "Run now" button from `px-6 py-2.5` to `px-7 py-3` to match primary button spec.

**Verify:** `npm run build` clean.

### Checkpoint 3: History skeleton fix (Skeleton.tsx)

**Deviation 9**

**File:** `web/src/components/Skeleton.tsx` (modify)

1. `HistorySkeleton`: Change `items-baseline` to `items-center`.

**Verify:** `npm run build` clean.

### Checkpoint 4: History empty state (history/page.tsx)

**Improvement D**

**File:** `web/src/app/history/page.tsx` (modify)

1. Replace centered empty state with mono accent label pattern:
   - Add `font-mono text-xs tracking-widest uppercase text-emerald-600` label "No runs yet"
   - Body text in `text-gray-600`
   - Arrow link in `font-mono text-sm text-emerald-600`

**Verify:** `npm run build` clean.

### Checkpoint 5: Pagination tighten (page.tsx)

**Improvement B**

**File:** `web/src/app/page.tsx` (modify)

1. Replace `Prev` / `Next` text with left/right chevron SVG icons inside the existing pill buttons.
2. Keep page counter `1 / 5` in mono between them.

**Verify:** `npm run build` clean.

### Checkpoint 6: Update design system spec

**Deviations 7, 8**

**File:** `web/DESIGN.md` (modify)

1. Add note that dashboard job scores use `text-lg` for prominence (exception to `text-sm` spec).
2. Clarify button sizing: page-level CTAs use `px-7 py-3 text-sm`, card-level inline actions use `px-4 py-1.5 text-xs`.

### Checkpoint 7: Deploy + verify

```bash
npm run build
fly deploy --app shortlist-web
```

## Edge Cases

- Status pills with 0 count should still render (they do — count just not shown).
- Empty state with active run should not show "Check your profile" link.
- Pagination arrows disabled state needs same `disabled:opacity-30` treatment.

## Risk

All frontend-only. No API changes. No test changes needed.
