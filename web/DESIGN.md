# Design System: Shortlist

## 1. Visual Theme & Atmosphere

A restrained, editorial interface. The product is about curation — cutting 127 jobs down to 4 worth your time. The design reflects that: high signal, low noise, confident typography, generous space. Feels like a well-edited magazine, not a SaaS dashboard.

- **DESIGN_VARIANCE: 8** — Asymmetric layouts, left-aligned heroes. Centered layouts banned.
- **MOTION_INTENSITY: 6** — CSS cubic-bezier transitions, staggered fade-up on load. No framer-motion (512MB VM constraint).
- **VISUAL_DENSITY: 4** — Airy. Data breathes. Cards used sparingly — prefer `divide-y` and negative space.

## 2. Color Palette & Roles

Single accent: **Emerald**. The color of "this one's worth your time."

| Token | Hex | Role |
|-------|-----|------|
| **Canvas** | `gray-50` · #FAFAFA | Page background, all surfaces |
| **Surface** | `white` · #FFFFFF | Hover states, elevated containers (rare) |
| **Ink** | `gray-900` · #18181B | Primary text, titles, names, high-value content |
| **Body** | `gray-700` · #3F3F46 | Descriptions, reasoning, intel values, expanded content |
| **Secondary** | `gray-600` · #52525B | Hero body, collapsed reasoning, subtitles |
| **Meta** | `gray-500` · #71717A | Pipeline stats, salary, location, fine print, timestamps |
| **Label** | `gray-400` · #A1A1AA | Section labels, structural text ("Stage", "Team"), step numbers |
| **Faint** | `gray-300` · #D4D4D8 | Arrows, decorative elements, divider hints |
| **Border** | `gray-200/60` | Dividers, section borders. Use `divide-y divide-gray-200/60`. |
| **Accent** | `emerald-600` · #059669 | CTAs, active states, score highlights, section labels |
| **Score High** | `emerald-600` · #059669 | Scores >= 85 |
| **Score OK** | `gray-900` · #18181B | Scores < 85 (readable, not highlighted) |

### Banned Colors
- No purple, no neon, no gradients on text
- No pure black (`#000000`) — use gray-900 (#18181B)
- No blue-600 (previous accent — replaced by emerald)
- No warm grays (stone) — zinc palette only, cool and consistent

## 3. Typography Rules

| Role | Font | Classes |
|------|------|---------|
| **Display** | Outfit | `text-4xl md:text-6xl font-bold tracking-tighter leading-none` |
| **H2** | Outfit | `text-2xl md:text-3xl font-bold tracking-tighter` |
| **H3/Card title** | Outfit | `text-lg font-semibold` or `font-medium text-gray-900` |
| **Body** | Outfit | `text-base text-gray-600 leading-relaxed max-w-[65ch]` |
| **Small body** | Outfit | `text-sm text-gray-700 leading-relaxed` |
| **Mono label** | JetBrains Mono | `font-mono text-[10px] uppercase tracking-widest text-gray-400` |
| **Mono data** | JetBrains Mono | `font-mono text-xs text-gray-500` |
| **Mono accent label** | JetBrains Mono | `font-mono text-xs tracking-widest uppercase text-emerald-600` |
| **Score (inline)** | JetBrains Mono | `font-mono text-sm font-semibold` |
| **Score (dashboard)** | JetBrains Mono | `font-mono text-lg font-semibold` (needs prominence in job list) |

### Banned
- Inter font
- Serif fonts anywhere
- Oversized H1s that scream — control hierarchy with weight and color
- Gradient text fills

## 4. Component Behaviors

### Buttons
- **Primary:** `rounded-full bg-gray-900 px-7 py-3 text-sm font-medium text-white`
  - Hover: `hover:-translate-y-[1px]`
  - Active: `active:translate-y-0 active:scale-[0.98]` (tactile push)
- **Secondary:** `rounded-full border border-gray-300 px-7 py-3 text-sm font-medium text-gray-600 hover:bg-white`
- **Accent:** `rounded-full bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white`
- **Card-level actions:** `rounded-full px-4 py-1.5 text-xs font-medium` — smaller than page CTAs. Used inside expanded cards for tools (tailor, download, cover letter).
- All `<button>` elements: explicit `cursor-pointer` (Tailwind v4 reset removes it). Disabled buttons: `disabled:cursor-not-allowed`.
- No outer glows, no neon shadows, no custom cursors

### Navigation
- **Frosted glass:** `backdrop-blur-xl bg-gray-50/80 border-b border-gray-200/50`
- **Liquid refraction:** `shadow-[inset_0_-1px_0_rgba(255,255,255,0.8)]`
- Fixed position, z-40
- Max-width 1200px centered

### Interactive Rows (Jobs, Providers)
- No card containers — use `divide-y divide-gray-200/60`
- Grid layout: `grid grid-cols-[2.5rem_1fr_1rem] gap-x-4 items-baseline`
- Hover: `hover:bg-gray-100/50 -mx-3 px-3 rounded-lg transition-colors`
- Expand/collapse: chevron rotates 180deg, content uses `animate-fade-up` with `animationDuration: 0.2s`

### Selects / Filters
- `rounded-full border border-gray-300 px-4 py-1.5 text-sm bg-white`

### Empty States
- Composed, centered text. No generic "No data" — explain what to do next.
- Use the same typography hierarchy (gray-900 title, gray-600 body).

### Loading
- Skeleton shimmer matching layout dimensions (existing `Skeleton.tsx`)
- No circular spinners

## 5. Container & Grouping Rules

These are the rules for when to use cards vs flat layouts. Getting this wrong is the #1 design mistake.

| Situation | Treatment | Example |
|-----------|-----------|--------|
| List of items (jobs, runs, steps) | `divide-y divide-gray-200/60` on parent | Dashboard job list, onboarding checklist |
| Editable sub-group within a form | `rounded-xl border border-gray-200 bg-white p-5 shadow-sm` | FiltersEditor Location/Compensation/Role cards, TrackEditor role cards |
| A self-contained setup/wizard block | Same card treatment as sub-group | Profile page Phase A setup card |
| Major page phases or sections | Centered divider label: `font-mono text-[10px] uppercase tracking-widest text-gray-400` between `h-px bg-gray-200` rules | Profile page "Search profile" divider |
| Items within a card | `border-t border-gray-100` (lighter than page dividers) | Between steps inside the setup card |
| Sections on a flat page | `pt-8 first:pt-0` with `divide-y divide-gray-200/60` on parent | Profile page Phase B sections |

**Anti-pattern: cards wrapping cards.** If a `SectionCard` contains a `FiltersEditor` that has its own cards, the `SectionCard` must NOT also be a card. Use flat `SectionCard` + card children, or card `SectionCard` + flat children. Never both.

**Step numbers** use `font-mono text-sm font-semibold text-gray-300` — visible but not dominant. Never filled circles, badges, or colored backgrounds on step indicators.

## 6. Layout Principles

- **Max width:** `max-w-[1200px] mx-auto` for full-width sections, `max-w-[900px]` for content
- **Hero:** Asymmetric `grid md:grid-cols-[3fr_2fr]` — left text, right data/breathing space
- **CTA sections:** Same asymmetric grid as hero for visual consistency
- **Content sections:** Single column, max-w-[900px]
- **Responsive:** Single column below `md:` breakpoint. No exceptions.
- **Padding:** `px-6` horizontal, `py-24 md:py-32` for major sections
- **Body padding in providers.tsx:** `pt-20 pb-6` (accounts for fixed nav)
- **No h-screen** — always `min-h-[100dvh]`
- **Grid over flex-math** — no `calc()` percentage hacks

### Section Dividers
- Between major sections: `border-t border-gray-200/60`
- Between items in a list: `divide-y divide-gray-200/60`
- No cards unless elevation is functionally required

## 7. Motion & Interaction

- **Entrance:** `animate-fade-up` — `translateY(12px)` to `0`, `opacity 0` to `1`, `0.5s cubic-bezier(0.16, 1, 0.3, 1)`
- **Stagger:** `animationDelay` in increments of `0.05s` to `0.1s`
- **Transitions:** `transition-colors` for hovers, `transition-transform duration-200` for chevrons
- **Tactile buttons:** `-translate-y-[1px]` on hover, `scale-[0.98]` on active
- **No framer-motion** — 512MB VM, CSS is sufficient at MOTION_INTENSITY 6
- **Hardware only:** Animate `transform` and `opacity` exclusively

## 8. Interaction Patterns

### Optimistic by default
All user actions update the UI immediately. API calls fire in the background. On failure, revert and refetch.

A job search tool is used in rapid triage mode — save, skip, save, skip. Any latency between click and response breaks flow.

| Pattern | When | Example |
|---------|------|--------|
| Optimistic update | User actions on existing data | Save/skip/applied → local state → API → revert on error |
| Fire-and-forget | Low-stakes tracking | Mark viewed → no await, silent failure OK |
| Blocking + spinner | Slow generation (10-15s) | Tailor resume, generate cover letter |
| Skeleton shimmer | Initial page load | Job list, profile sections |

### Job card state axes
Jobs have independent axes of state. Each must be visually distinct and never confused with another.

| Axis | States | Signal |
|------|--------|--------|
| **Freshness** | New (latest run) / Old | `New` pill badge |
| **Read status** | Unread / Read | Font weight + text darkness |
| **Triage** | Inbox / Saved / Applied / Skipped | Status badge |
| **Availability** | Open / Closed | `opacity-40` wash |

**Read/unread treatment:**

| Element | Unread | Read |
|---------|--------|------|
| Title | `font-semibold text-gray-900` | `font-normal text-gray-700` |
| Company/location | `text-gray-600` | `text-gray-500` |
| Score number | `font-bold` | `font-semibold` |
| Condensed intel | `text-gray-400` | `text-gray-400` |

**Key rule:** Read ≠ Closed. Read items stay fully visible with reduced weight. Only closed/skipped get `opacity-40`.

### Badge progression
Visual weight matches commitment level:

`New` (info fill) → `Saved` (outlined) → `Applied` (solid fill) → `Skipped` (ghost text only)

### Clearable badges
Two kinds of badges: **system** (informational) and **user-set** (actionable).

| Badge | Type | On hover | Treatment |
|-------|------|----------|-----------|
| New | System | Nothing | `text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded` — fill, no border |
| Recruiter | System | Nothing | `text-amber-600` — plain text only, no bg, no border |
| Tier A | System | Nothing | `bg-gray-900 text-white px-1.5 py-0.5 rounded` — dark fill. Ink color = high-value signal. Distinct from all emerald badges. |
| Tier B | System | — | Not shown. Most jobs are B — displaying it adds noise without signal. |
| Source | System | Nothing | `text-gray-400` — plain text only, no bg, no border |
| Saved | User-set | Shows × , click clears | `text-emerald-600 border border-emerald-300 bg-emerald-50` — outlined |
| Applied | User-set | Shows × , click clears | `text-white bg-emerald-600` — solid fill |
| Skipped | User-set | Shows × , click clears | `text-gray-400` — ghost text only |
| Closed | User-set | Shows × , click toggles | `text-red-500 border border-red-300 bg-red-50` — outlined red |

**The key rule: system badges use plain text only (no border, no background). User-set badges use borders or fills.**
This makes the functional difference immediately clear — if it has a border or background, it's interactive.

**Pattern:** User-set badges are `<button>` not `<span>`. On hover, label fades to `×` and colors shift to red. Click clears/toggles. Uses `group/badge` with:
- Label: `group-hover/badge:invisible` (keeps layout width, prevents jump)
- ×: `absolute inset-0 flex items-center justify-center opacity-0 group-hover/badge:opacity-100 transition-opacity`

**Never use `hidden`/`inline` swap for hover content** — it causes layout shift. Always `invisible` + absolute overlay.

**Why:** Users need to undo triage decisions without opening the card. The × appears only on hover — zero visual clutter at rest.

## 9. Anti-Patterns (Banned)

### Interaction
- No blocking UI on status changes (save/skip) — always optimistic
- No refetching entire list after single-item action — update local state
- No using opacity for "read" state — reserved for closed/skipped
- No color as the only differentiator — always pair with weight, border, or icon

### Visual
- No emojis in UI — use Phosphor icons or plain text
- No Inter font
- No pure black (#000000)
- No purple/blue neon accent
- No outer glow shadows
- No 3-column equal card grids
- No centered hero layouts
- No cards where `divide-y` or negative space works
- No cards wrapping cards (double nesting)
- No filled-circle step indicators or colored step badges
- No "Elevate", "Seamless", "Unleash", "Next-Gen" copy
- No generic circular spinners
- No `h-screen`
- No broken Unsplash links
- No custom mouse cursors
- No framer-motion (VM constraint)
- No warm grays (stone palette) — zinc only

## 10. Page Inventory

| Page | Layout | Status |
|------|--------|--------|
| Landing (`/`) | Full-width, asymmetric hero + interactive demo | Done |
| Getting Started (`/getting-started`) | Content column, expandable providers | Done |
| Login/Signup (`/login`, `/signup`) | Auth form | Needs restyle |
| Dashboard (`/` authenticated) | Job list with filters + run button | Needs restyle |
| Profile (`/profile`) | Setup card (Phase A) + flat divide-y sections (Phase B) | Done |
| History (`/history`) | Run history with stats, duration, per-source expansion | Done |
| Onboarding Checklist | Step-by-step setup | Needs restyle |
| JobCard component | Expandable job result | Needs restyle |
| RunButton component | Pipeline trigger | Needs restyle |
