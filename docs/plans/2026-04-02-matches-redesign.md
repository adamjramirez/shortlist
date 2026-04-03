# Plan: Matches Page Redesign

## Problem
The collapsed job rows are hard to scan. Four lines of similar-looking gray text per row, no visual rhythm between rows, and a generic header. Users spend 3-4 seconds per row parsing instead of <1 second.

## Principle
Keep all the data — the user explicitly asked for company intel, source, posting time, and track. The problem is **presentation hierarchy**, not information density.

---

## Tasks

### 1. Header — data-led, filters inline

**Before:**
```
DASHBOARD                        [Run now]
Your matches
47 jobs scored
[75+ (matches) v] [All roles v]
```

**After:**
```
47 matches                       [75+ v] [All roles v] [Run now]
Across hn, linkedin, greenhouse
```

- Kill "DASHBOARD" label — adds nothing
- `47 matches` as `text-2xl font-bold` — the headline IS the data
- Source summary as `font-mono text-xs text-gray-400` underneath
- Filters + Run button on same line, right-aligned on desktop
- Mobile: filters wrap below, Run button stays top-right

**File:** `web/src/app/page.tsx` (Dashboard component)

### 2. Collapsed row — three distinct visual layers

**Current:** 4 lines, all gray, all small, all blending together.

**After:** 3 zones with clear hierarchy.

```
92  VP Engineering, Infrastructure    Acme Corp   [New] [Saved]    ← ZONE 1: identity
    San Francisco (Hybrid)  ·  $280k-$350k        VP ENG · 2d ago  ← ZONE 2: facts
    Stage: Series C · ~120 people · Glassdoor 4.2/5                 ← ZONE 3: intel
```

Reasoning line moves to expanded only. It's editorial content — doesn't help the scan decision, and it's the line that pushes each row from "scannable" to "wall of text."

**Zone 1 — Identity** (unchanged, already works):
- Score: `font-mono text-lg font-semibold` in score color
- Title: `font-semibold text-gray-900`
- Company: `text-sm text-gray-500`
- Badges: as-is (New, Saved, Applied, Skipped, Recruiter)

**Zone 2 — Facts** (split into left/right):
- Left group: `Location · Salary` — the dealbreakers, `font-mono text-xs text-gray-500` (slightly darker than before)
- Right group: `Track · Posted Xd ago` — context, `font-mono text-[11px] text-gray-400` (lighter, pushed right with `ml-auto`)
- Source (`via hn`) moves to expanded only — low scan value, adds clutter

**Zone 3 — Company intel** (visually distinct from Zone 2):
- `mt-2` gap above (breathing room from facts)
- `text-xs text-gray-500` — NOT mono (reads as prose, differentiates from meta)
- Only shows when data exists (already filtered)

**Reasoning** — removed from collapsed, stays in expanded:
- The italic reasoning line was the 4th line making rows too tall
- It's editorial commentary — belongs with the interest note in expanded view
- Score itself + company intel give enough signal to decide "expand or skip"

**File:** `web/src/components/JobCard.tsx`

### 3. Row spacing and rhythm

**Before:** `py-1` wrapper + `py-4` button = rows nearly touch, hard to distinguish.

**After:**
- Outer wrapper: `py-0` (remove extra padding)
- Button: `py-5` (more internal breathing room)
- Border: `border-b border-gray-200` (slightly stronger — drop the `/60` opacity)

The goal: each row is a clear "card" of white space, visually separated by a definitive line.

**File:** `web/src/components/JobCard.tsx` + `web/src/app/page.tsx`

### 4. Widen score column

**Before:** `grid-cols-[2.5rem_1fr_1rem]` — 40px, cramped for 2-digit mono numbers.

**After:** `grid-cols-[3rem_1fr_1rem]` — 48px, comfortable.

**File:** `web/src/components/JobCard.tsx`

### 5. Expanded view — promote reasoning, tighten actions

Since reasoning moved out of collapsed, it needs a good home in expanded:
- Interest note (star, emerald border) — stays first
- Score reasoning — moves to second position, immediately after interest note
- Company intel, flags, actions — stay as-is

Action buttons: combine status buttons (Save/Applied/Skip) + View listing into one compact row with less vertical space. Currently they're split across multiple sections with `pt-4 border-t` dividers that add unnecessary height.

**File:** `web/src/components/JobCard.tsx`

---

## What we're NOT changing
- Expanded view structure (interest note → reasoning → flags → company → actions) — works fine
- Resume tailoring / cover letter sections — no complaints
- Landing page / demo section — already done
- Pagination — functional, not the bottleneck

## Execution order
1 → 2 → 3 → 4 → 5 (sequential, each builds on previous)

## Verification
- `cd web && npm run build` — clean after each step
- Visual check at localhost:3000 with real data
- Confirm scan speed: can you decide "expand or skip" in <1 second per row?
