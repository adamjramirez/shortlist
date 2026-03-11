# AI Profile Generation

**Goal:** User uploads resume + connects AI provider → clicks one button → AI fills in everything else. User reviews and saves.

## New flow

```
┌─────────────────────────────────────────────┐
│  1. Upload your resume                      │
│     [resume_backend.tex] ✓                  │
│                                             │
│  2. Connect your AI provider                │
│     [Gemini 2.5 Flash ▾]  [paste key]      │
│     Don't have one? Get a Gemini key →      │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  ✨ Analyze my resume               │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  ─ ─ ─ ─ everything below is generated ─ ─ │
│                                             │
│  3. Review your profile (AI-suggested)      │
│     [fit context - editable]                │
│                                             │
│  4. Roles to search for (AI-suggested)      │
│     [Track 1: Senior Backend Engineer]      │
│     [Track 2: Staff Platform Engineer]      │
│                                             │
│  5. Filters (AI-suggested)                  │
│     Location / Compensation / Preferences   │
│                                             │
│  ──────────────────── [Save profile] ────── │
└─────────────────────────────────────────────┘
```

## Architecture

### Backend: `POST /api/profile/generate`

**Input:** `{ resume_id: int }` — which resume to analyze
**Process:**
1. Fetch resume .tex content from storage
2. Decrypt user's API key
3. Call LLM with structured prompt
4. Return suggested profile fields

**Output:**
```json
{
  "fit_context": "Senior backend engineer with 8 years...",
  "tracks": {
    "senior_backend": {
      "title": "Senior Backend Engineer",
      "search_queries": ["senior python engineer", "backend lead python"]
    },
    "staff_platform": {
      "title": "Staff Platform Engineer", 
      "search_queries": ["staff platform engineer", "infrastructure lead"]
    }
  },
  "filters": {
    "location": { "remote": true, "local_cities": ["Chicago"] },
    "salary": { "min_base": 180000, "currency": "USD" },
    "role_type": { "reject_explicit_ic": false }
  }
}
```

**LLM protocol:** Same pattern as everything else — `LLMClient` protocol with production impl (httpx to provider APIs) and `FakeLLMClient` for tests. Use `get_llm_client` dependency.

Actually simpler: since users bring their own key and we already have httpx, just make a thin async function that takes (model, api_key, prompt) → response. No need for a full protocol — the test can just mock the endpoint or inject a fake function.

**Even simpler:** Use a `ProfileGenerator` protocol:
- `generate(resume_text: str) -> dict` 
- Production: calls LLM API
- Test: returns canned response
- Injected via `get_profile_generator` dependency

### Frontend changes

Profile page becomes two phases:
- **Phase A (setup):** Resume + AI provider — always visible
- **Phase B (profile):** Generated/editable fields — shown after generation or if profile already exists
- "Analyze my resume" button between phases
- Loading state with "Analyzing..." during generation
- Generated sections show a subtle "✨ AI-suggested" badge — user knows they can edit
- Re-analyze button to regenerate if they upload a new resume

## Tasks

### Task 1: `ProfileGenerator` protocol + LLM call

**Files:** 
- `shortlist/api/llm_client.py` (create)
- `shortlist/api/schemas.py` (modify — add GenerateRequest/Response)
- `shortlist/api/routes/profile.py` (modify — add POST /generate endpoint)

**`llm_client.py`:**
- `ProfileGenerator` protocol: `async def generate_profile(resume_text: str) -> dict`
- `LLMProfileGenerator`: takes model + api_key, calls provider API, parses JSON response
- `FakeProfileGenerator`: returns canned profile for tests
- `get_profile_generator` dependency: wired up in app, overridden in tests

**Prompt design:**
```
You are analyzing a resume to set up a job search profile.

Given this resume, generate:
1. fit_context: A 2-3 paragraph description of what this person is looking for
2. tracks: 1-3 role types they should search for, each with a title and 3-5 search queries
3. filters: Location preferences, minimum salary estimate, role type preferences

Resume:
{resume_text}

Respond in JSON matching this schema: ...
```

**Route: `POST /api/profile/generate`**
- Requires auth
- Takes `{ resume_id: int }`
- Fetches resume from storage
- Decrypts user's API key from profile config
- Calls profile generator
- Returns suggested profile (does NOT save — user reviews first)

### Task 2: Tests for generate endpoint

**File:** `tests/api/test_profile_generate.py` (create)

- Test: generate returns suggested profile
- Test: 400 if no API key configured
- Test: 404 if resume not found
- Test: 400 if resume belongs to different user

### Task 3: Frontend — reorder profile page

**File:** `web/src/app/profile/page.tsx` (rewrite)

Two-phase layout:
- Phase A: Resume upload + AI provider (steps 1-2)
- "Analyze my resume" button (disabled until both resume + key exist)
- Phase B: Generated sections (steps 3-5) — pre-filled from generate response or existing profile
- Sticky save bar

### Task 4: Frontend — analyze button + loading state

**File:** `web/src/components/AnalyzeButton.tsx` (create)
**File:** `web/src/lib/api.ts` (modify — add `profile.generate()`)

- Button calls `POST /api/profile/generate`
- Shows spinner + "Analyzing your resume..." during call
- On success, populates form fields
- On error, shows message

### Task 5: Polish — AI-suggested badges, re-analyze

- Subtle "✨ suggested" label on generated sections
- "Re-analyze" link if user wants to regenerate
- Clear generated flag when user edits (badge disappears)

## Verify

- `pytest tests/ -x` — all pass including new generate tests
- `npm run build` — clean
- Manual: upload resume → set key → analyze → see pre-filled profile → edit → save

## Risks

1. **LLM response parsing.** LLMs don't always return valid JSON. Mitigation: retry once, fallback to partial extraction.
2. **Cost transparency.** One LLM call to analyze resume costs ~$0.01-0.05. Should show this. Mitigation: note in UI "This will use ~1 API call".
3. **Latency.** LLM call takes 3-10 seconds. Mitigation: good loading state.
4. **Resume is LaTeX.** LLMs handle LaTeX fine — they can read through the markup. No preprocessing needed.
