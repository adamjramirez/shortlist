# Design Overhaul — Taste Skill Redesign

**Date:** 2026-04-02  
**Goal:** Redesign the entire Shortlist frontend to a high-end, consistent design language aligned with AWW's aesthetic. Highlight the AWW integration as a first-class feature.

---

## Design System (DESIGN.md)

### 1. Visual Theme & Atmosphere

A restrained, gallery-airy interface with confident asymmetric layouts and fluid spring-physics motion. The atmosphere matches AWW — warm neutrals, single blue accent, generous whitespace, and premium typography. Shortlist feels like a sibling product to AWW: same DNA, different purpose.

- **DESIGN_VARIANCE:** 7 (Offset asymmetric — no centered heroes, no 3-column equal grids)
- **MOTION_INTENSITY:** 5 (Fluid CSS transitions, spring-physics on interactive elements, staggered reveals on scroll — no heavy choreography that kills 512MB VM)
- **VISUAL_DENSITY:** 4 (Art gallery mode for landing/marketing, daily app mode for dashboard)

### 2. Color Palette & Roles (aligned with AWW)

| Name | Hex | Role |
|------|-----|------|
| Canvas Warm | `#fafaf9` | Primary background (Stone-50, matches AWW) |
| Pure Surface | `#ffffff` | Cards, containers, elevated surfaces |
| Charcoal Ink | `#1c1917` | Primary text (Stone-900, matches AWW) |
| Warm Steel | `#57534e` | Secondary text, descriptions (Stone-600) |
| Muted Stone | `#a8a29e` | Tertiary text, metadata (Stone-400) |
| Whisper Border | `#e7e5e4` | Card borders, dividers (Stone-300) |
| Soft Border | `#f5f5f4` | Subtle separators (Stone-100) |
| Signal Blue | `#2563eb` | Single accent — CTAs, links, active states (Blue-600, matches AWW) |
| Blue Soft | `#dbeafe` | Accent backgrounds, highlights (Blue-100) |

**Banned:** Purple/neon glows. Pure black `#000000`. Oversaturated accents. Warm/cool gray mixing.

### 3. Typography Rules

| Role | Font | Spec |
|------|------|------|
| Display/Headlines | Outfit | `tracking-tight leading-tight`, weight-driven hierarchy, not screaming size |
| Body | Outfit | `text-base leading-relaxed max-w-[65ch]`, Stone-600 color |
| Mono | JetBrains Mono | Code, metadata, API keys, scores, timestamps |

**Matches AWW** which uses Outfit + JetBrains Mono.

**Banned:** Inter (current — must replace). Generic serif. Oversized H1s. Gradient text.

### 4. Component Stylings

- **Buttons:** Flat, no outer glow. Dark fill (`bg-stone-900 text-white`) for primary, ghost for secondary. `rounded-full` pill shape (matches AWW). Active state: `-translate-y-[1px]` tactile push. Transitions: `cubic-bezier(0.16, 1, 0.3, 1)`.
- **Cards:** `rounded-2xl` (1.25rem, matches AWW `--radius`). `border border-stone-200/50`. Diffused shadow `shadow-[0_20px_40px_-15px_rgba(0,0,0,0.05)]`. Used only when elevation communicates hierarchy.
- **Inputs:** Label above, Stone-600 color. Focus ring in Signal Blue. `rounded-xl` borders. No floating labels.
- **Score badges:** Mono font, colored background (green 85+, blue 75+, stone below).
- **Nav:** Frosted glass (`backdrop-blur-xl bg-stone-50/85`), fixed top. Pill CTA matching AWW nav style.
- **Skeletons:** Shimmer matching layout dimensions. No spinners.

### 5. Layout Principles

- **Landing:** Asymmetric split hero (text left, visual right). Zig-zag feature sections (alternating left/right). No centered H1. No 3-column equal cards.
- **Dashboard:** Clean data layout. Cards only for job results. Dividers (`border-t`) for section separation.
- **Profile:** Stacked sections with generous padding. No numbered step circles — use subtle labels.
- **Max-width:** `max-w-[1200px] mx-auto` (matches AWW container).
- **Full-height:** `min-h-[100dvh]` never `h-screen`.
- **Grid over flex math.** Responsive: single-column below `md:`.

### 6. Motion & Interaction

- **Spring physics:** `transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1)` on all interactive elements.
- **Staggered reveals:** CSS `animation-delay: calc(var(--index) * 80ms)` for list/grid items on load.
- **Hover states:** Cards lift slightly (`-translate-y-0.5`). Buttons push down on active.
- **Page transitions:** Fade-in on mount via CSS animation.
- **No framer-motion** — the motion intensity is 5, CSS transitions are sufficient and save ~40KB + RAM on the 512MB VM. If we need it later for specific effects, add it then.

### 7. Anti-Patterns (Banned)

- No emojis in UI (replace with Phosphor icons or SVG)
- No Inter font
- No pure black `#000000`
- No neon/outer glow shadows
- No 3-column equal card grids
- No centered hero sections
- No AI copywriting ("Elevate", "Seamless", "Unleash", "Next-Gen")
- No generic "scroll to explore" / bouncing chevrons
- No `h-screen`
- No circular loading spinners

---

## Scope — 3100 lines across 15 files

### Phase 1: Foundation (font, colors, globals, layout, nav)
### Phase 2: Landing page (hero, features, AWW integration, CTA)
### Phase 3: Auth pages + Getting Started
### Phase 4: Dashboard (job cards, run button, onboarding)
### Phase 5: Profile page
### Phase 6: History page

---

## Phase 1: Foundation

### Task 1.1: Install Outfit + JetBrains Mono, replace Inter

**File:** `web/src/app/layout.tsx` (modify)  
**Purpose:** Switch from Inter to Outfit (matches AWW). Add JetBrains Mono for code/numbers.

```tsx
import { Outfit, JetBrains_Mono } from "next/font/google";

const outfit = Outfit({ subsets: ["latin"], variable: "--font-outfit" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

// body className:
`${outfit.variable} ${jetbrains.variable} font-sans bg-stone-50 text-stone-900 antialiased`
```

**Verify:** `cd web && npm run build`

### Task 1.2: Update globals.css with design tokens

**File:** `web/src/app/globals.css` (modify)  
**Purpose:** Set CSS custom properties matching the design system. Configure Tailwind v4 font family.

```css
@import "tailwindcss";

@theme {
  --font-sans: var(--font-outfit), system-ui, sans-serif;
  --font-mono: var(--font-mono), "JetBrains Mono", monospace;

  /* Remap gray → stone values globally.
     All existing gray-xxx classes render as warm stone tones
     without touching any component files (187 occurrences). */
  --color-gray-50: #fafaf9;
  --color-gray-100: #f5f5f4;
  --color-gray-200: #e7e5e4;
  --color-gray-300: #d6d3d1;
  --color-gray-400: #a8a29e;
  --color-gray-500: #78716c;
  --color-gray-600: #57534e;
  --color-gray-700: #44403c;
  --color-gray-800: #292524;
  --color-gray-900: #1c1917;
  --color-gray-950: #0c0a09;
}

/* Stagger animation utility */
@keyframes fade-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-up {
  animation: fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) both;
}
```

This remaps all 187 existing `gray-*` classes to warm stone values in one place. No component file changes needed for the color migration.

**Verify:** `cd web && npm run build`

### Task 1.3: Install Phosphor Icons

**File:** `web/package.json` (modify via npm)  
**Purpose:** Replace emoji usage with clean icons. Phosphor is lightweight (~tree-shakeable).

```bash
cd web && npm install @phosphor-icons/react
```

**Verify:** `cd web && npm run build`

### Task 1.4: Redesign Nav component

**File:** `web/src/components/Nav.tsx` (rewrite)  
**Purpose:** Frosted glass nav matching AWW's style. Pill-shaped CTA. Clean mobile menu.

Key changes:
- `fixed top-0 inset-x-0 z-50` with `backdrop-blur-xl bg-stone-50/85 border-b border-stone-200/50`
- Logo: `font-semibold tracking-tight text-stone-900`
- CTA: `rounded-full bg-stone-900 text-white px-4 py-1.5` (matches AWW nav-cta)
- Mobile: slide-down menu, not inline expand
- Update `providers.tsx` main wrapper: `py-6` → `pt-20 pb-6` to offset fixed nav (Landing breaks out with `-mx-4 -mt-6` so unaffected)

**Verify:** `cd web && npm run build`

### Task 1.5: Update Skeleton component

**File:** `web/src/components/Skeleton.tsx` (modify)  
**Purpose:** Shimmer animation instead of pulse. Stone-200 base matching new palette.

**Verify:** `cd web && npm run build`

---

## Phase 2: Landing Page

### Task 2.1: Rewrite Landing component — Hero section

**File:** `web/src/app/page.tsx` (modify — `Landing` function)  
**Purpose:** Asymmetric split hero. Text left, visual/illustration right. No centered layout.

Structure:
```
┌──────────────────────────────────────────────┐
│ Nav (frosted glass, fixed)                   │
├──────────────────────┬───────────────────────┤
│                      │                       │
│  Stop scrolling      │   [Visual: mock       │
│  job boards.         │    dashboard showing   │
│                      │    scored job cards    │
│  Shortlist collects, │    with scores]        │
│  scores, and shows   │                       │
│  you only what fits. │                       │
│                      │                       │
│  [Get started] pill  │                       │
│  [GitHub] ghost      │                       │
│                      │                       │
├──────────────────────┴───────────────────────┤
```

- H1: `text-4xl md:text-5xl font-bold tracking-tight` — not text-5xl, not screaming
- Accent on key phrase via `text-blue-600`
- Subtitle: `text-lg text-stone-600 leading-relaxed max-w-[50ch]`
- Buttons: pill-shaped, dark primary (`bg-stone-900 text-white rounded-full`) + ghost secondary
- Sub-note: `text-sm text-stone-400` — "Free. Bring your own API key."
- Grid: `grid md:grid-cols-[1fr_1fr] gap-12 items-center`
- Right column visual: CSS-rendered mock of a scored job card (score badge, company, title, reasoning line). No external images — self-contained, responsive, demonstrates the product.

**Verify:** `cd web && npm run build` + visual check at localhost:3000

### Task 2.2: Landing — "How it works" zig-zag sections

**File:** `web/src/app/page.tsx` (continue modifying `Landing`)  
**Purpose:** Replace 3-column equal cards with alternating left/right feature sections.

Three sections, alternating layout:

**Section 1: Upload & Analyze** (text left, visual right)
- "Upload your resume. Shortlist builds your search profile."
- Visual: mock of the profile analysis result

**Section 2: One-click search** (visual left, text right)  
- "One click. Hundreds of jobs collected, filtered, scored."
- Visual: mock of the run progress UI

**Section 3: Review matches** (text left, visual right)
- "Scored results with reasoning, company intel, tailored resumes."
- Visual: mock of a job card with score + reasoning

Each section: `grid md:grid-cols-2 gap-12 items-center`, alternating order via `md:order-2`.

Staggered reveal: `.animate-fade-up` with `animation-delay` per element.

**Verify:** `cd web && npm run build` + visual check

### Task 2.3: Landing — AWW Integration section

**File:** `web/src/app/page.tsx` (continue modifying `Landing`)  
**Purpose:** Highlight the AWW connection as a premium differentiator. This is a dedicated section, not a footnote.

Structure:
```
┌──────────────────────────────────────────────┐
│  Powered by your real context                │
│                                              │
│  ┌─────────────────┐    ┌─────────────────┐  │
│  │ AWW              │    │ Shortlist        │  │
│  │ Builds a living  │───>│ Scores jobs      │  │
│  │ profile from     │    │ against your     │  │
│  │ your email,      │    │ real experience  │  │
│  │ Slack, calendar  │    │                  │  │
│  └─────────────────┘    └─────────────────┘  │
│                                              │
│  "Not keywords on a resume. Real context."   │
│                                              │
│  [Learn about AWW →] link to aww.addslift.com│
└──────────────────────────────────────────────┘
```

- Section label: `font-mono text-xs uppercase tracking-widest text-blue-600` (matches AWW's section labels)
- Two cards connected with an arrow/line
- AWW card: warm stone background, Phosphor `UserCircle` icon
- Shortlist card: white background, Phosphor `Target` icon
- Flow arrow: SVG or CSS border with `-->` feel
- CTA: text link to `https://aww.addslift.com`

**Verify:** `cd web && npm run build` + visual check

### Task 2.4: Landing — "What you need" + Final CTA

**File:** `web/src/app/page.tsx` (continue modifying `Landing`)  
**Purpose:** Replace current "What you need" list + CTA with styled version.

Two items with Phosphor icons (not arrow emoji):
- `Key` icon — "An LLM API key — Gemini is free, OpenAI and Anthropic ~$1-3/month"
- `FileText` icon — "Your resume — LaTeX or PDF"

Final CTA section: clean, generous padding. Single pill button. No secondary CTA.

**Verify:** `cd web && npm run build` + visual check

---

## Phase 3: Auth Pages + Getting Started

### Task 3.1: Restyle AuthForm

**File:** `web/src/components/AuthForm.tsx` (modify)  
**Purpose:** Match the new design language. Centered form, stone palette, pill button.

- Card: `rounded-2xl border border-stone-200/50 bg-white shadow-sm p-8`
- Inputs: `rounded-xl border-stone-300 focus:ring-blue-600`
- Button: `rounded-full bg-stone-900 text-white`
- Error: `text-sm text-red-600` (no change needed)
- Logo at top linking to `/`

**Verify:** `cd web && npm run build`

### Task 3.2: Restyle Getting Started page

**File:** `web/src/app/getting-started/page.tsx` (rewrite)  
**Purpose:** Apply design system to the provider cards and FAQ.

- Use same `ProviderCard` pattern but with new card styles (`rounded-2xl border-stone-200/50`)
- Recommended card: `ring-2 ring-blue-100 border-blue-200`
- Replace emoji checkmarks/crosses with Phosphor `Check`/`X` icons
- Steps: numbered with mono font, not plain `<ol>`
- FAQ: `<details>` with stone borders, Phosphor `CaretDown` icon

**Verify:** `cd web && npm run build`

---

## Phase 4: Dashboard

### Task 4.1: Restyle Dashboard layout and header

**File:** `web/src/app/page.tsx` (modify — `Dashboard` function)  
**Purpose:** Clean header with stats. Stone palette. No blue-600 backgrounds.

- Header: job count + filter controls on one line
- Stats in mono font: "142 matches / 23 strong / 3 runs"
- Score filter: pill-shaped toggle buttons, not a dropdown

**Verify:** `cd web && npm run build`

### Task 4.2: Redesign JobCard

**File:** `web/src/components/JobCard.tsx` (modify)  
**Purpose:** Premium card design. Score badge in mono. Clean hierarchy.

- Card: `rounded-2xl border border-stone-200/50 bg-white` with diffused shadow on hover
- Score badge: `font-mono font-semibold` with colored background (green-100/green-700 for 85+, blue-100/blue-700 for 75+)
- Company: `font-semibold text-stone-900`
- Title: `text-stone-600`
- Score reasoning: `text-stone-500 text-sm font-mono`
- Tags (track, source): `rounded-full bg-stone-100 text-stone-600 text-xs px-2 py-0.5`
- Expand/detail: clean divider, no heavy borders
- Replace all emoji in status badges, intel, etc. with Phosphor icons

**Verify:** `cd web && npm run build`

### Task 4.3: Restyle RunButton

**File:** `web/src/components/RunButton.tsx` (modify)  
**Purpose:** Pill-shaped, dark fill when idle, animated when running.

- Idle: `rounded-full bg-stone-900 text-white px-6 py-2.5`
- Running: animated border or subtle pulse (CSS only)
- Progress text: mono font
- Cancel: ghost button

**Verify:** `cd web && npm run build`

### Task 4.4: Restyle OnboardingChecklist

**File:** `web/src/components/OnboardingChecklist.tsx` (modify)  
**Purpose:** Card-based checklist matching new design. No numbered circles.

- Card: `rounded-2xl border border-stone-200/50 bg-white p-6`
- Check items: Phosphor `CheckCircle` (filled, blue) / `Circle` (empty, stone-300)
- Progress bar: `bg-blue-600 rounded-full`
- CTA: pill button

**Verify:** `cd web && npm run build`

---

## Phase 5: Profile Page

### Task 5.1: Restyle SectionCard

**File:** `web/src/components/SectionCard.tsx` (modify)  
**Purpose:** Update to new card style. Remove numbered step circles.

- `rounded-2xl border border-stone-200/50 bg-white shadow-sm`
- Title: `font-semibold text-stone-900`
- Subtitle: `text-sm text-stone-500`
- Step numbers: keep but restyle to editorial mono format — `font-mono text-xs text-stone-400` showing "01", "02" etc. instead of blue filled circles

**Verify:** `cd web && npm run build`

### Task 5.2: Restyle Profile page inputs and sections

**File:** `web/src/app/profile/page.tsx` (modify)  
**Purpose:** Stone palette throughout. Pill buttons. Updated API key section with guide link.

- All inputs: `rounded-xl border-stone-300 focus:ring-blue-600`
- Save button: `rounded-full bg-stone-900 text-white`
- Toast/success: green with Phosphor `Check` icon
- Guide callout: `bg-blue-50 border border-blue-100 rounded-xl` (update from rounded-lg)
- Model selector dropdown: styled to match

**Verify:** `cd web && npm run build`

### Task 5.3: Restyle TrackEditor, FiltersEditor, TagInput

**Files:** `web/src/components/TrackEditor.tsx`, `FiltersEditor.tsx`, `TagInput.tsx` (modify)  
**Purpose:** Consistent input styling, pill tags, stone palette.

- Tags: `rounded-full bg-stone-100 text-stone-700 text-sm`
- Remove buttons: Phosphor `X` icon, not text "x"
- Add buttons: ghost style with `+` icon

**Verify:** `cd web && npm run build`

---

## Phase 6: History Page

### Task 6.1: Restyle History page

**File:** `web/src/app/history/page.tsx` (modify)  
**Purpose:** Clean table/list of runs. Mono timestamps. Status pills.

- Status badges: `rounded-full text-xs font-medium px-2.5 py-0.5`
  - completed: `bg-green-100 text-green-700`
  - running: `bg-blue-100 text-blue-700`
  - failed: `bg-red-100 text-red-700`
- Timestamps: mono font
- Table: no heavy borders, use `divide-y divide-stone-100`

**Verify:** `cd web && npm run build`

---

## Execution Strategy

This is ~3100 lines across 15 files. Rewriting everything at once is risky. Approach:

1. **Phase 1 first** (foundation) — this affects every page via layout/globals/nav. Get this right, verify visually.
2. **Phase 2** (landing) — highest-impact, public-facing page. This is what users + investors see.
3. **Phase 3-6** in order — progressively restyle the authenticated experience.
4. **Visual review after each phase** — `npm run dev` and check localhost.
5. **Full test suite after Phase 6** — ensure no functionality broke.

### Dependencies to install

```bash
cd web && npm install @phosphor-icons/react
```

No framer-motion — CSS transitions at MOTION_INTENSITY 5 are sufficient and save RAM on the 512MB VM. Can add later for specific effects if needed.

### Files Changed

| Phase | Files | Lines (approx) |
|-------|-------|-----------------|
| 1 | layout.tsx, globals.css, Nav.tsx, Skeleton.tsx + npm install | ~250 |
| 2 | page.tsx (Landing component) | ~300 |
| 3 | AuthForm.tsx, getting-started/page.tsx | ~400 |
| 4 | page.tsx (Dashboard), JobCard.tsx, RunButton.tsx, OnboardingChecklist.tsx | ~1000 |
| 5 | SectionCard.tsx, profile/page.tsx, TrackEditor.tsx, FiltersEditor.tsx, TagInput.tsx | ~900 |
| 6 | history/page.tsx | ~80 |

### Risk Mitigation

- **No functionality changes** — this is purely visual. All API calls, state management, analytics stay identical.
- **Test suite validates** — 527 backend tests ensure no API changes. `npm run build` catches type errors.
- **Feature branch** — all work on a branch, deploy only after full visual review.
