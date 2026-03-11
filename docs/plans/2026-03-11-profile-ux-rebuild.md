# Profile Page UX Rebuild

**Goal:** Replace developer-facing JSON/key inputs with an intuitive, structured UI. A human with zero technical context should be able to set up their job search in under 5 minutes.

**Scope:** Profile page, supporting components, minor fixes to dashboard track filter. Backend is unchanged — frontend converts structured form ↔ JSON blobs transparently.

---

## Architecture

```
lib/profile-types.ts    — structured types + JSON converters (exists, needs cleanup)
components/TagInput.tsx  — reusable tag input (exists, needs polish)
components/TrackEditor.tsx — complete rewrite
components/FiltersEditor.tsx — complete rewrite
components/SectionCard.tsx — new shared layout component
app/profile/page.tsx    — complete rewrite
app/page.tsx            — fix track filter to show titles not keys
components/OnboardingChecklist.tsx — improve copy
```

---

## Task 1: SectionCard layout component

**File:** `web/src/components/SectionCard.tsx` (create)
**Purpose:** Consistent section wrapper with title, subtitle, optional collapse. Replaces ad-hoc `<section>` + label + description pattern used 6 times on profile page.

### Design
```tsx
<SectionCard
  title="What roles are you looking for?"
  subtitle="Add each type of role as a separate track..."
  step={1}        // optional step number
  defaultOpen     // optional collapse control
>
  {children}
</SectionCard>
```

- Numbered step badge (1, 2, 3…) in the header — gives progress feel
- White card with subtle border, consistent padding
- Optional collapsible via chevron toggle

### Verify
- `npm run build` compiles clean

---

## Task 2: Rewrite TagInput with better UX

**File:** `web/src/components/TagInput.tsx` (modify)
**Purpose:** Polish the tag input — it works but needs visual refinement.

### Changes
- Comma-separated paste support (paste "query one, query two" → 2 tags)
- Tab key also adds tag (not just Enter)
- Better empty state: show placeholder only when empty
- Slightly larger click target on × button
- Focus ring on the wrapper matches other inputs

### Verify
- `npm run build` compiles clean

---

## Task 3: Rewrite TrackEditor — no keys, example-driven

**File:** `web/src/components/TrackEditor.tsx` (rewrite)
**Purpose:** Each track is a card the user fills in like a form. No "key" field. Key auto-generated from title in `tracksToJson`.

### Design per track card
```
┌─────────────────────────────────────────────────┐
│  Track 1                                    [×] │
│                                                 │
│  Role Title                                     │
│  ┌─────────────────────────────────────────┐    │
│  │ Senior Backend Engineer                 │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  Search Queries                                 │
│  What would you type into a job board?          │
│  ┌─────────────────────────────────────────┐    │
│  │ [senior python engineer] [backend lead] │    │
│  │ Type and press Enter...                 │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  Resume for this track          ▾ Optional      │
│  ┌─────────────────────────────────────────┐    │
│  │ resume_backend.tex                      │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ▸ Advanced options                             │
│    Target orgs: [any]                           │
│    Min direct reports: [0]                      │
└─────────────────────────────────────────────────┘

              [+ Add another role]
```

### Key decisions
- **No "Key" field.** Auto-slug from title in `tracksToJson`. If title changes, old key is preserved via the `name` field internally (never shown).
- **"Advanced options" collapsed by default.** Target orgs and min reports are power-user fields. 95% of users never touch them.
- **First track auto-added** if tracks array is empty — don't make user click "+ Add" to get started.
- **Resume dropdown says "None — use default" not empty.**
- **Microcopy is human:** "What would you type into a job board?" not "Search queries (press Enter to add)"

### Verify
- `npm run build` compiles clean

---

## Task 4: Rewrite FiltersEditor — toggles and plain fields

**File:** `web/src/components/FiltersEditor.tsx` (rewrite)
**Purpose:** Make filters feel like preferences, not config. Group logically.

### Design
```
┌─ Location ──────────────────────────────────────┐
│                                                 │
│  [✓] Include remote jobs                        │
│                                                 │
│  Your ZIP code          Max commute             │
│  ┌──────────────┐      ┌──────────────┐        │
│  │ 60601        │      │ 30 min       │        │
│  └──────────────┘      └──────────────┘        │
│                                                 │
│  Nearby cities (we'll match jobs in these)      │
│  ┌─────────────────────────────────────────┐    │
│  │ [Chicago] [Evanston]                    │    │
│  └─────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘

┌─ Compensation ──────────────────────────────────┐
│                                                 │
│  Minimum base salary                            │
│  ┌──────────────┐  ┌──────┐                    │
│  │ 150,000      │  │ USD ▾│                    │
│  └──────────────┘  └──────┘                    │
│  Jobs below this are auto-rejected              │
└─────────────────────────────────────────────────┘

┌─ Role preferences ──────────────────────────────┐
│                                                 │
│  [✓] Skip roles explicitly labeled as IC-only   │
│      (e.g. "Individual Contributor — no path    │
│       to management")                           │
└─────────────────────────────────────────────────┘
```

### Key decisions
- **"Compensation" not "Salary"** — more natural
- **"Nearby cities" not "Local cities"** — human language
- **Explanatory line under min salary** — so user knows the consequence
- **IC toggle has example** — so user understands what "explicit IC" means
- **No "Role Type" header** — "Role preferences" is clearer

### Verify
- `npm run build` compiles clean

---

## Task 5: Rewrite profile page — guided flow with sticky save

**File:** `web/src/app/profile/page.tsx` (rewrite)
**Purpose:** Restructure as a guided setup with numbered steps, sticky save bar, unsaved-changes indicator.

### Section order (user's mental model)
1. **About you** — fit context with rich placeholder example
2. **Roles you're searching for** — tracks
3. **Filters** — location, salary, role preferences
4. **AI Provider** — LLM model + API key with "where to get this" link
5. **Resumes** — upload with track assignment

### New behaviors
- **Sticky save bar** at bottom of viewport — shows "Unsaved changes" dot when dirty, Save button always accessible
- **Fit context placeholder** — a real multi-line example: "I'm a senior backend engineer with 8 years of Python experience. Looking for Staff+ roles at Series B-D startups. Strong preference for developer tools, data infra, or ML platforms. Dealbreakers: no defense/gambling, no fully on-site."
- **API key section** has link to provider's API key page (Gemini → ai.google.dev, OpenAI → platform.openai.com, Anthropic → console.anthropic.com)
- **Resume upload** — when uploading, dropdown to assign to a track inline
- **Success toast** fades after 3s instead of persistent green text

### Verify
- `npm run build` compiles clean
- Manual: load page, add track, add filter, save — verify JSON round-trips correctly via API

---

## Task 6: Fix dashboard track filter — show titles not keys

**File:** `web/src/app/page.tsx` (modify)
**Purpose:** Track dropdown shows "Senior Backend Engineer" not "ic_backend".

### Change
```tsx
// Before
const tracks = profileData ? Object.keys(profileData.tracks) : [];

// After  
const tracks = profileData
  ? Object.entries(profileData.tracks).map(([key, val]) => ({
      key,
      title: (val as any)?.title || key,
    }))
  : [];
```

Then in the `<select>`:
```tsx
{tracks.map((t) => (
  <option key={t.key} value={t.key}>{t.title}</option>
))}
```

### Verify
- `npm run build` compiles clean

---

## Task 7: Improve OnboardingChecklist copy

**File:** `web/src/components/OnboardingChecklist.tsx` (modify)
**Purpose:** Match the new profile page language. More encouraging, less technical.

### Changes
- "Write your fit context" → "Describe what you're looking for"
- "Add at least one track with search queries" → "Add a role you're searching for"
- "Upload your resume (.tex file)" → "Upload your resume"
- "Add your LLM API key" → "Connect your AI provider"
- "Set your location filters" → "Set your location and salary preferences"
- CTA: "Set up your profile →" / "You're all set — run your first search →"

### Verify
- `npm run build` compiles clean

---

## Task 8: Update profile-types.ts

**File:** `web/src/lib/profile-types.ts` (modify)
**Purpose:** Ensure `tracksToJson` auto-generates key from title when `name` is empty. Preserve existing names on round-trip so keys don't change on every save.

### Changes
- `tracksToJson`: if `name` is empty, slugify from `title`. If `name` exists, use it.
- Already works this way — verify and add a comment.
- Remove `Track` interface from `types.ts` (no longer used directly; `profile-types.ts` owns the structured types).

### Verify
- `npm run build` compiles clean

---

## Execution order

Tasks 1-4 are independent components (can be done in parallel).
Task 5 depends on 1-4 (profile page uses all of them).
Tasks 6-8 are independent leaf changes.

**Estimated LOC:** ~800 new/rewritten across 8 files. Net change roughly even since we're replacing ~600 LOC of existing components.

---

## Risks

1. **Key stability on round-trip.** If user changes a track title, the slug changes, backend sees it as a new track. Mitigation: `name` field preserved internally, only auto-generated on first create.
2. **Filters schema drift.** If backend adds new filter fields, the structured editor won't show them. Mitigation: `filtersToJson` spreads unknown fields through, and we version the schema.
3. **Mobile layout.** Cards with 2-column grids need to stack on mobile. Will use `grid-cols-1 sm:grid-cols-2`.

---

## Out of scope (for next round)

- Landing page rewrite
- Loading skeletons
- Nav active state
- Pagination on dashboard
- Error boundaries
- Mobile hamburger menu
