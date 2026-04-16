# New-User Analyze Fix + Step 3/4 UX

**Date:** 2026-04-16
**Goal:** Unblock the silent analyze failure for new users, make step 3 visibly critical, and let users regenerate step 4 tracks from their edited fit_context.

**Context (reported by a new user):**
1. Clicked "Analyze my resume" — spinner started, then stopped, and the rest of the page (steps 3–7) never appeared.
2. Step 3 (fit_context) is the most important input to the scorer but visually looks like any other step.
3. Step 4 (tracks) feels like it should stay in sync with what the user writes in step 3 — right now it only reflects the CV.

**Root cause for (1):**
When analyze fails, `handleAnalyze` sets `error` state, but the error UI lives inside `SaveBar`, which is only rendered when `hasProfile || generated` is true (`web/src/app/profile/page.tsx:450`). For a new user whose very first analyze just failed, both flags are false — so the error is set in state but never rendered. The user sees the spinner stop, no error, and no new sections. Two known paths reach this silent failure:
- `handleAnalyze` calls `saveApiKey()` first, which swallows its own error silently; then `generate()` 400s with "Set up your AI provider and API key first."
- `/api/profile/generate` itself fails (Gemini timeout, 502, bad JSON response).

---

## Problem 1: Silent analyze failure for new users

### Task 1.1: Render a visible error banner near AnalyzeButton when no profile exists yet

**File:** `web/src/app/profile/page.tsx` (modify)
**Purpose:** Surface `error` to new users who have not yet generated or saved a profile. Without this, every failure mode of analyze is invisible and they have nothing to act on.

Insert immediately after the `<div className="py-6">…<AnalyzeButton /></div>` block (around line 303), before the `{(hasProfile || generated) && <>` fragment:

```tsx
{error && !hasProfile && !generated && (
  <div className="pb-6 pl-8">
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5">
      <p className="text-sm text-red-700">{error}</p>
      <p className="mt-1 text-xs text-red-600/70">
        If this keeps happening, double-check your API key and model selection in step 2, then try again.
      </p>
    </div>
  </div>
)}
```

The `pl-8` matches the indent of step content (`SectionCard` uses `pl-8` when `step` is present) so the banner aligns with the step bodies.

**Verify (manual — requires running the web app):**
```bash
cd web && npm run dev                                                           # :3000
uvicorn shortlist.api.app:create_app --factory --port 8001                      # in another terminal
```
- Sign up as a brand-new user.
- Upload a resume.
- Type an obviously-invalid API key (e.g. `sk-invalid`) in step 2.
- Click "Analyze my resume."
- **Expected:** Spinner runs ~1–3s, then a red banner appears under the button with the server's error message ("AI analysis failed: …" or similar). Steps 3–7 stay hidden.
- Now click "Remove" on the key, paste a valid Gemini key, click Analyze again. **Expected:** banner disappears, steps 3–7 render, green "Profile generated…" callout appears above step 3.

### Task 1.2: Make `saveApiKey` re-throw on failure inside `handleAnalyze`

**File:** `web/src/app/profile/page.tsx` (modify)
**Purpose:** Today `handleAnalyze` awaits `saveApiKey()` and then calls `generate()` regardless of whether the key actually saved. If save failed, `generate()` fails with a less-informative 400 and the user sees the wrong error. Make analyze abort early if key-save failed, so the banner from 1.1 shows the real reason (bad key, server error, etc.).

Concrete refactor — extract the core save into an inner that throws, wrap it for the Save button path:

```tsx
// New inner — throws on error. Used by handleAnalyze.
const saveApiKeyOrThrow = async () => {
  if (!apiKey && !llmModel && Object.keys(extraKeys).length === 0) return;
  const llm: Record<string, unknown> = { model: llmModel };
  if (apiKey) llm.api_key = apiKey;
  const nonEmpty = Object.fromEntries(
    Object.entries(extraKeys).filter(([, v]) => v.trim())
  );
  if (Object.keys(nonEmpty).length > 0) llm.provider_keys = nonEmpty;
  const updated = await profileApi.update({ llm });
  setProfile(updated);
  setHasApiKey(!!updated.llm?.has_api_key);
  setProvidersWithKeys(updated.llm?.providers_with_keys || []);
  setApiKey("");
  setExtraKeys({});
  const mainProvider = llmModel.startsWith("gemini") ? "gemini"
    : llmModel.startsWith("gpt-") || llmModel.startsWith("o1-") ? "openai"
    : llmModel.startsWith("claude-") ? "anthropic" : "unknown";
  if (apiKey) track.apiKeySaved(mainProvider);
  for (const p of Object.keys(nonEmpty)) track.apiKeySaved(p);
};

// Existing outer — catches for the Save button path.
const saveApiKey = async () => {
  try {
    await saveApiKeyOrThrow();
    showToast("API key saved ✓");
  } catch (err) {
    setError(err instanceof ApiError ? err.detail : "Failed to save key");
  }
};
```

In `handleAnalyze`, replace `if (apiKey) await saveApiKey();` with:

```tsx
if (apiKey) {
  try {
    await saveApiKeyOrThrow();
  } catch (err) {
    const msg = err instanceof ApiError ? err.detail : "Failed to save API key";
    setError(msg);
    track.profileAnalysisFailed(msg);
    setAnalyzing(false);
    return;
  }
}
```

**Verify:**
- Type a syntactically-invalid key (e.g. empty string with model set, or a key that triggers a 4xx on first request). The banner from 1.1 shows the save error, not a generic "AI analysis failed."

---

## Problem 2: Step 3 does not look critical

### Task 2.1: Add a "Most important step" emphasis to the step 3 header

**File:** `web/src/app/profile/page.tsx` (modify)
**Purpose:** Signal that step 3 is the single biggest lever on scoring quality, so users actually edit it instead of skimming past.

Replace the `SectionCard step={3}` block with a version that (a) tightens the subtitle and (b) adds a small **amber** inline callout under the subtitle. **Do not use emerald** — the post-analyze "Profile generated" success callout is already emerald and renders directly above step 3 (line 308). Two stacked emerald callouts = visual mush. Amber is already used in `SaveBar` for "Unsaved changes" and rate-limit warnings, so it reads as "pay attention" without colliding with the user-set status color system.

Do **not** change `SectionCard.tsx` — one-off emphasis belongs in the consumer.

```tsx
<SectionCard
  step={3}
  title="What you're looking for"
  subtitle="This is the single biggest lever on match quality. The AI reads it before scoring every job."
>
  <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2">
    <p className="text-xs text-amber-800">
      <span className="font-semibold">Most important step.</span>{" "}
      Be specific: seniority, industries, company stages, what you want to build, and hard dealbreakers.
    </p>
  </div>
  <textarea …/>   {/* unchanged */}
</SectionCard>
```

Matches `web/DESIGN.md`: zinc neutrals for structure, emerald reserved for user-action/accent, no emoji, flat callout inside a flat SectionCard (not a nested card container).

**Verify:**
- Load `/profile` as an existing user; step 3 now has an emerald callout under the subtitle.
- Load as a new user after a successful analyze; step 3 shows the emerald callout above the auto-generated fit_context textarea.
- Visual regression pass on `web/DESIGN.md` anti-patterns: no double border (callout is `rounded-md`, lives inside the step body `pl-8`, not a nested `SectionCard`).

---

## Problem 3: Step 4 should regenerate from CV + current step 3

### Task 3.1: Add optional `fit_context` to `GenerateProfileRequest`

**File:** `shortlist/api/schemas.py` (modify)
**Purpose:** Let the client ask for track generation anchored to the fit_context the user just wrote, not only the raw resume.

```python
class GenerateProfileRequest(BaseModel):
    resume_id: int
    fit_context: str | None = None
```

### Task 3.2: Pass `fit_context` through the generator

**File:** `shortlist/api/llm_client.py` (modify)
**Purpose:** Extend the generator protocol + prompt to accept an optional fit_context anchor. When provided, instruct the model to generate tracks consistent with this context; still derive filters from the resume.

**Hard constraint: do NOT modify `SYSTEM_PROMPT`.** The system prompt must stay byte-identical so future prompt-caching (or existing prompt hashes) are not disturbed. The fit_context is injected as an **additional user-turn message/part**, omitted entirely when `fit_context` is None or empty-after-strip.

Add a module-level constant used identically across all three providers:

```python
FIT_CONTEXT_ADDENDUM = """The candidate has ALSO written the following description of what they want. Use it as the authoritative source for "fit_context" and as a strong prior for "tracks". If this conflicts with the resume, prefer what the candidate wrote.

<candidate_fit_context>
{fit_context}
</candidate_fit_context>"""
```

Changes:

- `ProfileGenerator` Protocol:
  ```python
  class ProfileGenerator(Protocol):
      async def generate_profile(self, resume_text: str, fit_context: str | None = None) -> dict: ...
  ```
- `_call_gemini(api_key, model, resume_text, fit_context=None)` — if `fit_context and fit_context.strip()`, prepend a second user turn to `contents` (so the ordering is: fit_context turn → resume turn). Concrete JSON shape:
  ```python
  contents = []
  if fit_context and fit_context.strip():
      contents.append({"parts": [{"text": FIT_CONTEXT_ADDENDUM.format(fit_context=fit_context)}]})
  contents.append({"parts": [{"text": USER_PROMPT_TEMPLATE.format(resume_text=resume_text)}]})
  ```
  then pass `"contents": contents` in the body. `system_instruction` stays untouched.
- `_call_openai(api_key, model, resume_text, fit_context=None)` — insert a user message between the existing system and resume-user messages when `fit_context` present:
  ```python
  messages = [{"role": "system", "content": SYSTEM_PROMPT}]
  if fit_context and fit_context.strip():
      messages.append({"role": "user", "content": FIT_CONTEXT_ADDENDUM.format(fit_context=fit_context)})
  messages.append({"role": "user", "content": USER_PROMPT_TEMPLATE.format(resume_text=resume_text)})
  ```
- `_call_anthropic(api_key, model, resume_text, fit_context=None)` — Anthropic requires alternating roles, so we cannot append two consecutive user messages. Combine both into a single user message when fit_context is present:
  ```python
  user_content = (
      FIT_CONTEXT_ADDENDUM.format(fit_context=fit_context) + "\n\n"
      if fit_context and fit_context.strip() else ""
  ) + USER_PROMPT_TEMPLATE.format(resume_text=resume_text)
  # then: "messages": [{"role": "user", "content": user_content}]
  ```
  `system` field stays the untouched `SYSTEM_PROMPT`.
- `LLMProfileGenerator.generate_profile(self, resume_text, fit_context=None)` forwards `fit_context` to the caller lambda.
- `FakeProfileGenerator.generate_profile(self, resume_text, fit_context: str | None = None)` — default `None`, stores `self.last_fit_context = fit_context`. Existing `test_generate_profile` uses no kwarg and must keep passing.

### Task 3.3: Wire `fit_context` through the `/profile/generate` route

**File:** `shortlist/api/routes/profile.py` (modify)
**Purpose:** Pass the optional `fit_context` from the request body into the generator.

Change:
```python
result = await generator.generate_profile(resume_text)
```
to:
```python
result = await generator.generate_profile(resume_text, fit_context=req.fit_context)
```

### Task 3.4: "Regenerate roles from your context" button on step 4

**File:** `web/src/app/profile/page.tsx` (modify)
**Purpose:** Let users regenerate tracks (and only tracks) after they've edited step 3, without touching their filters or fit_context.

- Add a `regenerating` state boolean.
- Add `handleRegenerateTracks`:
  ```tsx
  const handleRegenerateTracks = async () => {
    if (resumeList.length === 0) return;
    setRegenerating(true);
    setError("");
    try {
      const result = await profileApi.generate(resumeList[0].id, fitContext);
      setTracks(jsonToTracks(result.tracks));
      setDirty(true);
      showToast("Roles regenerated ✓");
      track.profileAnalyzed(resumeList[0].id);   // reuse existing event, add a reason later if needed
    } catch (err) {
      const msg = err instanceof ApiError ? err.detail : "Regeneration failed";
      setError(msg);
    } finally {
      setRegenerating(false);
    }
  };
  ```
- Update `SectionCard step={4}` body to render a compact button above `<TrackEditor>`:
  ```tsx
  <div className="mb-3 flex items-center justify-between gap-3">
    <p className="text-xs text-gray-500">
      Generated from your resume and step 3. Edit or regenerate as you refine your context.
    </p>
    <button
      type="button"
      onClick={handleRegenerateTracks}
      disabled={regenerating || resumeList.length === 0 || !fitContext.trim() || (!hasApiKey && !apiKey)}
      className="shrink-0 rounded-full border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:border-emerald-500 hover:text-emerald-700 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
    >
      {regenerating ? "Regenerating…" : "Regenerate roles"}
    </button>
  </div>
  <TrackEditor … />
  ```

  Note: `/profile/generate` returns `{fit_context, tracks, filters}`. `handleRegenerateTracks` intentionally reads **only** `result.tracks` and discards the regenerated `fit_context` and `filters`. A comment above the `setTracks(...)` call should say so — we don't want a future edit to silently overwrite the user's hand-edited step 3 or their filters.

### Task 3.5: Update the frontend API client

**File:** `web/src/lib/api.ts` (modify)
**Purpose:** `profileApi.generate` needs to pass the optional fit_context.

Change the signature:
```ts
generate(resumeId: number, fitContext?: string): Promise<GenerateProfileResponse> {
  return request("/profile/generate", {
    method: "POST",
    body: JSON.stringify({ resume_id: resumeId, fit_context: fitContext ?? null }),
  });
}
```

Existing call sites (`handleAnalyze`) pass only `resumeId` — backward compatible because `fit_context` is optional.

---

## Tests

### Task 4.1: API test — generate accepts optional fit_context and forwards it to generator

**File:** `tests/api/test_profile_generate.py` (modify)
**Purpose:** Prove `fit_context` reaches the generator and doesn't break when omitted.

Add two tests:
- `test_generate_profile_without_fit_context_unchanged` — POST without `fit_context` in the body; `fake_generator.last_fit_context is None`; response shape unchanged.
- `test_generate_profile_with_fit_context_forwarded` — POST with `{"resume_id": r, "fit_context": "I want infra roles"}`; assert `fake_generator.last_fit_context == "I want infra roles"`.

Update `FakeProfileGenerator` to accept+record `fit_context` (kwarg with default `None`). Existing `test_generate_profile` (line 54) must keep passing unchanged — it calls without the kwarg.

### Task 4.2: (cut)

The failure-path assertion I originally planned is already covered by the existing `test_generate_no_api_key` at `tests/api/test_profile_generate.py:70`. Don't add a duplicate. If we want to sharpen the detail-string assertion, edit the existing test — not a separate one.

### Task 4.3: Frontend behavior — no automated test (manual only)

React behavior is easier to verify manually than to unit-test here. Capture the manual verification steps from tasks 1.1, 2.1, 3.4 above in a checklist at PR time.

---

## Deploy + verify

1. `pytest tests/ -q` — 644+ tests pass (existing count was 644 per CLAUDE.md; expect 646+ after this plan).
2. `cd web && npm run build` — type check passes.
3. `fly deploy --app shortlist-web`.
4. Sign up as a fresh user in prod, walk through the three UX paths from tasks 1.1, 2.1, 3.4.
5. Update `PROJECT_LOG.md` with outcome and any surprises.

---

## Out of scope

- Full-profile diffing / undo on Regenerate (just overwrites tracks; user has Save/Cancel via `SaveBar`).
- Restructuring `SaveBar` to host errors when no profile exists — the targeted banner in 1.1 is smaller surface and doesn't force all error UX through one component.
- Auto-regeneration on fit_context change (noisy; would re-hit Gemini on every keystroke debounce). Explicit button only.
