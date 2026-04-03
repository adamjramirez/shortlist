# Getting Started Page — API Key Guidance

**Date:** 2026-04-02  
**Goal:** Help new users understand they need an API key, which provider to pick, and how to get one. Reduce the activation cliff at profile analysis.

---

## Context

**The problem:** 4 of 6 users bounced at or before profile analysis. Users don't understand:
- What an API key is or why they need one
- Which provider to pick
- That Gemini is free and the others cost money
- How many steps are involved

**Current flow:**
```
Signup → "/" → OnboardingChecklist → Profile page (API key field with a "Get a key →" link)
```

The only guidance is a dropdown label ("recommended — fast & cheap") and a link. No explanation of what an API key is, what it costs, or step-by-step instructions.

**Proposed flow:**
```
Signup → "/getting-started" → Profile page → OnboardingChecklist → Run
         ↑                                    ↑
         "Need help?" links from              "How to get a key →" link
         profile page + checklist
```

---

## Design

### Getting Started Page

Static page. No auth required (useful as a shareable link too). Three sections:

**1. Hero — What & Why (3 sentences)**

> Shortlist uses AI to analyze your resume, score jobs, and write cover letters.
> You bring your own API key from Google, OpenAI, or Anthropic — your data goes directly to the provider, and you control costs.
> Most users spend **$0/month** using Google's free tier.

**2. Provider Comparison — Which to Pick (3 cards)**

Each card shows: provider name, recommended model, free tier (yes/no), typical cost, "best for" one-liner, step-by-step instructions (expanded by default for Gemini, collapsed for others).

**Gemini (recommended):**
- Model: Gemini 2.0 Flash
- Free tier: ✅ 1,500 requests/day
- Typical cost: $0/month
- Best for: Most users — fast, free, great quality
- Steps:
  1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
  2. Sign in with your Google account
  3. Click **Create API Key** — select any project (or create one)
  4. Copy the key → paste it on your [profile page](/profile)

**OpenAI:**
- Model: GPT-4o Mini
- Free tier: ❌ Pay-as-you-go ($5 minimum deposit)
- Typical cost: ~$1-3/month
- Best for: Users who already have an OpenAI account
- Steps:
  1. Go to [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
  2. Sign up or log in
  3. Go to Settings → Billing → add a payment method ($5 minimum)
  4. Click **Create new secret key** — copy it → paste on your [profile page](/profile)

**Anthropic (Claude):**
- Model: Claude 3.5 Haiku
- Free tier: ❌ Pay-as-you-go ($5 minimum deposit)
- Typical cost: ~$1-3/month
- Best for: Best writing quality for cover letters
- Steps:
  1. Go to [console.anthropic.com](https://console.anthropic.com)
  2. Sign up or log in
  3. Go to Settings → Billing → add credits ($5 minimum)
  4. Go to Settings → API Keys → **Create Key** — copy it → paste on your [profile page](/profile)

**3. Bottom CTA**

> Got your key? → **Set up your profile** (button linking to /profile)

**4. FAQ (collapsed)**

- **Is my API key safe?** Your key is encrypted at rest and never shared. Shortlist sends your resume and job descriptions directly to the AI provider you choose — we never see the content.
- **How much will it cost?** A typical run scores ~50 jobs. With Gemini 2.0 Flash, that's free. With OpenAI or Anthropic, roughly $0.01-0.05 per run.
- **Can I switch providers later?** Yes, anytime from your profile page. You can also add keys for multiple providers to use different models for cover letters.

---

## Tasks

### Task 1: Create Getting Started page

**File:** `web/src/app/getting-started/page.tsx` (create)  
**Purpose:** Static page with provider comparison, step-by-step guides, and FAQ.

Page component with:
- No auth required (no `useRequireAuth`)
- Standalone header with "Shortlist" link to `/` (Nav component returns null for logged-out users)
- Three provider cards using a `ProviderCard` local component
- Gemini card expanded by default, others collapsed
- FAQ as `<details>` elements
- CTA button to `/profile`
- Responsive — cards stack on mobile

**Verify:**
```bash
cd web && npm run build
```

### Task 2: Redirect signup to /getting-started

**File:** `web/src/components/AuthForm.tsx` (modify)  
**Purpose:** New users see getting-started before the profile page.

Change:
```typescript
router.push("/");
```

To:
```typescript
router.push(mode === "signup" ? "/getting-started" : "/");
```

Login still goes to `/` (returning users don't need the guide).

**Verify:**
```bash
cd web && npm run build
```

### Task 3: Add guide link on profile page

**File:** `web/src/app/profile/page.tsx` (modify)  
**Purpose:** Users who skip getting-started or forget can find it from the profile page.

Change the AI Provider section subtitle from:
```
"We use your API key to analyze your resume and score jobs. You pay the provider directly — typical cost is ~$0.01 per run."
```

To:
```
"We use your API key to analyze your resume and score jobs. You pay the provider directly — typical cost is ~$0.01 per run."
```

Add `import Link from "next/link"` to the file imports.

And add below the subtitle (inside SectionCard, before the model select):
```tsx
{!hasApiKey && (
  <p className="mb-4 rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-800">
    <strong>Not sure which to pick?</strong>{" "}
    <Link href="/getting-started" className="underline hover:text-blue-900">
      See our setup guide
    </Link>
    {" "}— most users choose Gemini (free).
  </p>
)}
```

Only shows when they haven't saved a key yet.

**Verify:**
```bash
cd web && npm run build
```

### Task 4: Add guide link in OnboardingChecklist

**File:** `web/src/components/OnboardingChecklist.tsx` (modify)  
**Purpose:** The checklist step "Connect your AI provider" should link to the guide.

Change the label for the API provider check from:
```typescript
label: "Connect your AI provider",
```

To include a description that renders as a link:
```typescript
label: "Connect your AI provider",
href: "/getting-started",
```

Add `href?: string` to the `CheckItem` interface, and render the label as a link when `href` is present and the step is not done.

**Verify:**
```bash
cd web && npm run build
```

### Task 5: Track analytics events

**File:** `web/src/lib/analytics.ts` (modify)  
**Purpose:** Track getting-started page engagement.

Add:
```typescript
gettingStartedViewed: () =>
  trackEvent("getting_started_viewed"),

gettingStartedProviderExpanded: (provider: string) =>
  trackEvent("getting_started_provider_expanded", { provider }),

gettingStartedCtaClicked: () =>
  trackEvent("getting_started_cta_clicked"),
```

Fire `gettingStartedViewed` on page mount.
Fire `gettingStartedProviderExpanded` when a collapsed provider card is expanded.
Fire `gettingStartedCtaClicked` when the CTA button is clicked.

**Verify:**
```bash
cd web && npm run build
```

---

## Edge Cases

- **Returning users:** Login goes to `/`, not getting-started. The page is still accessible via URL or links if they need it later.
- **No auth:** Page works without login — shareable link, useful for pre-signup evaluation.
- **Mobile:** Cards stack vertically. Step-by-step text wraps cleanly.
- **Already has key:** Profile page guide link only shows when `!hasApiKey`.

## Files Changed

| File | Action |
|------|--------|
| `web/src/app/getting-started/page.tsx` | **Create** — new page |
| `web/src/components/AuthForm.tsx` | Modify — signup redirects to /getting-started |
| `web/src/app/profile/page.tsx` | Modify — add guide link callout |
| `web/src/components/OnboardingChecklist.tsx` | Modify — add href to API provider step |
| `web/src/lib/analytics.ts` | Modify — 3 new events |
