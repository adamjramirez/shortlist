# PostHog Analytics Overhaul

**Date:** 2026-04-02  
**Goal:** Proper PostHog initialization, user identification, CJ tracking, and fix the #1 user-killer (profile analysis 429s).

**Context from data:**
- 4 signups → 3 uploaded resume → 1 profile analyzed → 1 ran pipeline
- User `eb087338` hit OpenAI 429 4x and churned forever (the only real churn we can fix)
- `run_completed` never fires (user likely closed tab during long pipeline run)
- `logged_in` = 0 (nobody has returned and logged back in)
- All users are anonymous — can't connect PostHog person IDs to DB users

---

## Phase 1: PostHog Init + Identify (frontend, ~15 min)

### Task 1: Add PostHog initialization

**File:** `web/src/lib/posthog.ts` (create)  
**Purpose:** Single place for PostHog init. Token is a public client-side key — hardcode it (no build-time env var needed, avoids Dockerfile changes).

```typescript
import posthog from "posthog-js";

export function initPostHog() {
  if (typeof window === "undefined") return;
  if (posthog.__loaded) return; // already initialized

  posthog.init("phc_NPhbB68CFkI7dXVAacRN60tnc4ADmH5dWnOVZBEkwS1", {
    api_host: "/ingest",               // reverse proxy in next.config.ts
    ui_host: "https://eu.posthog.com",
    capture_pageview: "history_change", // auto-tracks SPA route changes via pushState
    capture_pageleave: true,
    persistence: "localStorage+cookie",
    autocapture: true,
    session_recording: {
      maskAllInputs: true,              // passwords, API keys
    },
  });
}
```

**File:** `web/src/app/providers.tsx` (modify)  
**Purpose:** Call `initPostHog()` on mount. No manual pageview tracking — `"history_change"` handles SPA transitions automatically.

```typescript
"use client";

import { useEffect } from "react";
import { AuthProvider } from "@/lib/auth-context";
import { initPostHog } from "@/lib/posthog";
import Nav from "@/components/Nav";

export function Providers({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    initPostHog();
  }, []);

  return (
    <AuthProvider>
      <Nav />
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </AuthProvider>
  );
}
```

**Verify:**
```bash
cd web && npm run build
```

---

### Task 2: Identify users on auth

**File:** `web/src/lib/auth-context.tsx` (modify)  
**Purpose:** Call `posthog.identify()` on login/signup/hydration, `posthog.reset()` on logout.

Changes:
1. Add `import posthog from "posthog-js"` to imports
2. In `login()` — after `setUser()`:
   ```typescript
   posthog.identify(String(resp.user_id), { email: resp.email });
   ```
3. In `signup()` — after `setUser()`:
   ```typescript
   posthog.identify(String(resp.user_id), { email: resp.email });
   ```
4. In `useEffect` `/me` hydration — replace `.then(setUser)` with:
   ```typescript
   .then((u) => {
     setUser(u);
     posthog.identify(String(u.id), { email: u.email });
   })
   ```
5. In `logout()` — add before `setUser(null)`:
   ```typescript
   posthog.reset();
   ```

**Verify:**
```bash
cd web && npm run build
```

---

### Task 3: Set user properties on key activation actions

**File:** `web/src/lib/analytics.ts` (modify)  
**Purpose:** Use `posthog.setPersonProperties()` (modern API, replaces deprecated `posthog.people.set()`) to track activation state as persistent user properties for segmentation.

Add after the existing `trackEvent` call in each function:
- `resumeUploaded`: `posthog.setPersonProperties({ has_resume: true })`
- `apiKeySaved`: `posthog.setPersonProperties({ has_api_key: true, api_provider: provider })`
- `profileSaved`: `posthog.setPersonProperties({ profile_complete: true })`
- `runStarted`: `posthog.setPersonProperties({ has_run: true })`
- `runCompleted`: `posthog.setPersonProperties({ has_completed_run: true })`

Wrap each `setPersonProperties` in the same try/catch pattern as `trackEvent` for SSR safety.

**Verify:**
```bash
cd web && npm run build
```

---

## Phase 2: Fix run_completed tracking (frontend, ~10 min)

### Task 4: Fix silent polling failure + retroactive completion

**Problem:** Client-side `run_completed` never fires because users close the tab during long pipeline runs. The polling catch block also silently swallows errors.

**File:** `web/src/components/RunButton.tsx` (modify)  
**Purpose:** Two fixes:

**Fix A — Log `run_failed` when polling errors (not silent swallow):**

Change polling catch block from:
```typescript
} catch {
  if (intervalRef.current) clearInterval(intervalRef.current);
}
```
To:
```typescript
} catch (err) {
  if (intervalRef.current) clearInterval(intervalRef.current);
  const msg = err instanceof Error ? err.message : "Polling failed";
  track.runFailed(msg);
}
```

**Fix B — Retroactive completion with sessionStorage dedup guard:**

Change initial `useEffect` from:
```typescript
useEffect(() => {
  runsApi.list().then((runs) => {
    const active = runs.find(
      (r) => r.status === "pending" || r.status === "running",
    );
    if (active) setRun(active);
  });
}, []);
```
To:
```typescript
useEffect(() => {
  runsApi.list().then((runs) => {
    const active = runs.find(
      (r) => r.status === "pending" || r.status === "running",
    );
    if (active) {
      setRun(active);
    } else if (runs.length > 0 && runs[0].status === "completed") {
      const firedKey = `run_completed_${runs[0].id}`;
      if (!sessionStorage.getItem(firedKey)) {
        track.runCompleted((runs[0].progress?.matches as number) ?? 0);
        sessionStorage.setItem(firedKey, "1");
      }
    }
  });
}, []);
```

**Verify:**
```bash
cd web && npm run build
```

---

## Phase 3: Profile analysis resilience (backend, ~30 min)

### Task 5: Add retry with backoff to LLM profile generator

**File:** `shortlist/api/llm_client.py` (modify)  
**Purpose:** Retry on 429/5xx with exponential backoff. Single retry point in `LLMProfileGenerator.generate_profile()` — all providers get retry automatically without each caller needing to remember.

Add helper and modify generator:

```python
import asyncio
import logging

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_BACKOFF_BASE = 2.0  # seconds: 2s, 4s


async def _retry_on_transient(coro_factory, description: str = "LLM call"):
    """Retry an async callable on 429/5xx with exponential backoff."""
    last_exc = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await coro_factory()
        except httpx.HTTPStatusError as e:
            last_exc = e
            status = e.response.status_code
            if status == 429 or status >= 500:
                if attempt < _MAX_RETRIES:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "%s got %d, retrying in %.0fs (attempt %d/%d)",
                        description, status, wait, attempt + 1, _MAX_RETRIES + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
            raise  # non-retryable status (4xx other than 429)
    raise last_exc  # exhausted retries
```

Modify `LLMProfileGenerator.generate_profile()`:
```python
class LLMProfileGenerator:
    """Production implementation — calls real LLM APIs."""

    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key

    async def generate_profile(self, resume_text: str) -> dict:
        caller = _CALLERS.get(self.model)
        if not caller:
            raise ValueError(f"Unsupported model: {self.model}")
        raw = await _retry_on_transient(
            lambda: caller(self.api_key, self.model, resume_text),
            f"Profile generation ({self.model})",
        )
        return _extract_json(raw)
```

Individual callers (`_call_openai`, `_call_gemini`, `_call_anthropic`) remain unchanged — no wrapping needed.

**Verify:**
```bash
pytest tests/api/test_profile_generate.py -q
```

---

### Task 6: Test retry behavior

**File:** `tests/api/test_llm_client.py` (create)  
**Purpose:** Unit test retry logic at the `_retry_on_transient` level with mock callables — no httpx internals mocking needed.

```python
"""Tests for LLM client retry logic."""
import pytest
import httpx

from shortlist.api.llm_client import _retry_on_transient


def _make_status_error(status: int) -> httpx.HTTPStatusError:
    resp = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
    return httpx.HTTPStatusError(f"HTTP {status}", request=resp.request, response=resp)


@pytest.mark.asyncio
async def test_retry_on_429_succeeds_second_attempt():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_status_error(429)
        return "ok"

    result = await _retry_on_transient(flaky, "test")
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_on_500_succeeds():
    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _make_status_error(500)
        return "ok"

    result = await _retry_on_transient(flaky, "test")
    assert result == "ok"
    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_exhausted_raises():
    async def always_429():
        raise _make_status_error(429)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _retry_on_transient(always_429, "test")
    assert exc_info.value.response.status_code == 429


@pytest.mark.asyncio
async def test_no_retry_on_400():
    call_count = 0

    async def bad_request():
        nonlocal call_count
        call_count += 1
        raise _make_status_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        await _retry_on_transient(bad_request, "test")
    assert call_count == 1  # no retry on 400


@pytest.mark.asyncio
async def test_no_retry_on_success():
    call_count = 0

    async def ok():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await _retry_on_transient(ok, "test")
    assert result == "ok"
    assert call_count == 1
```

**Verify:**
```bash
pytest tests/api/test_llm_client.py -q
```

---

### Task 7: Better error messages for 429

**File:** `shortlist/api/routes/profile.py` (modify)  
**Purpose:** Catch `httpx.HTTPStatusError` specifically and return actionable error messages.

Add `import httpx` to the imports at top of file.

Replace the existing exception handler:
```python
    try:
        result = await generator.generate_profile(resume_text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {str(e)}",
        )
```

With:
```python
    try:
        result = await generator.generate_profile(resume_text)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Your API key hit rate limits. Wait a minute and try again. "
                    "Tip: Gemini keys have generous free-tier limits — "
                    "switch to Gemini 2.0 Flash in your profile settings."
                ),
            )
        raise HTTPException(
            status_code=502,
            detail=f"AI provider error ({e.response.status_code}). Try again shortly.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {str(e)}",
        )
```

**Verify:**
```bash
pytest tests/api/test_profile_generate.py -q
```

---

### Task 8: Test 429 error message at API level

**File:** `tests/api/test_profile_generate.py` (modify)  
**Purpose:** Test that 429 from the LLM returns an actionable error via dependency override.

```python
@pytest.mark.asyncio
async def test_generate_profile_429_error(client, auth_headers, resume_id, profile_with_key, app):
    """429 from LLM returns a helpful error message suggesting Gemini."""
    import httpx as httpx_mod

    class RateLimitedGenerator:
        async def generate_profile(self, resume_text: str) -> dict:
            resp = httpx_mod.Response(
                429, request=httpx_mod.Request("POST", "https://example.com")
            )
            raise httpx_mod.HTTPStatusError(
                "rate limited", request=resp.request, response=resp
            )

    app.dependency_overrides[get_profile_generator] = lambda: RateLimitedGenerator()
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 429
    detail = resp.json()["detail"].lower()
    assert "rate limit" in detail
    assert "gemini" in detail


@pytest.mark.asyncio
async def test_generate_profile_502_error(client, auth_headers, resume_id, profile_with_key, app):
    """Non-429 HTTP error from LLM returns 502 with status code."""
    import httpx as httpx_mod

    class ServerErrorGenerator:
        async def generate_profile(self, resume_text: str) -> dict:
            resp = httpx_mod.Response(
                503, request=httpx_mod.Request("POST", "https://example.com")
            )
            raise httpx_mod.HTTPStatusError(
                "service unavailable", request=resp.request, response=resp
            )

    app.dependency_overrides[get_profile_generator] = lambda: ServerErrorGenerator()
    resp = await client.post(
        "/api/profile/generate",
        json={"resume_id": resume_id},
        headers=auth_headers,
    )
    assert resp.status_code == 502
    assert "503" in resp.json()["detail"]
```

**Verify:**
```bash
pytest tests/api/test_profile_generate.py -q
```

---

### Task 9: Visual hint for recoverable errors on profile page

**File:** `web/src/app/profile/page.tsx` (modify)  
**Purpose:** Show 429/rate-limit errors as amber warning (recoverable) instead of red error (fatal).

Find the error display near the analyze button. Change from:
```tsx
{error && <p className="text-sm text-red-600">{error}</p>}
```
To:
```tsx
{error && (
  <p className={`text-sm ${error.toLowerCase().includes("rate limit") ? "text-amber-600" : "text-red-600"}`}>
    {error}
  </p>
)}
```

**Verify:**
```bash
cd web && npm run build
```

---

## Phase 4: Investigations (manual, ~15 min)

### Task 10: Verify run completion in DB

**Purpose:** Confirm whether user 523b57ea's run actually completed server-side.

```bash
fly postgres connect --app shortlist-db --database shortlist_web
```
```sql
SELECT id, user_id, status, created_at, updated_at FROM runs ORDER BY created_at DESC LIMIT 5;
```

If status = `'completed'` but `run_completed` was never fired → confirms the client-side gap (Task 4 fix).

### Task 11: Check return login patterns in DB

**Purpose:** Verify whether `logged_in = 0` means nobody returned, or if the event is broken.

```sql
SELECT id, email, created_at FROM users ORDER BY created_at;
SELECT u.email, r.created_at as run_at
FROM runs r JOIN users u ON r.user_id = u.id
ORDER BY r.created_at;
```

### Task 12: Verify filter_changed fires locally

**Purpose:** `filter_changed` is called in `page.tsx` but has 0 events. Likely nobody changed filters, but verify.

Manual test:
1. Run locally (`cd web && npm run dev`)
2. Open browser console: `posthog.debug()`
3. Change the min score dropdown
4. Confirm `filter_changed` event fires in console

If it fires → no bug, just no usage. No code fix needed.

---

## Phase 5: Deploy + Verify

### Task 13: Run all tests

```bash
pytest tests/ -q
cd web && npm run build
```

### Task 14: Deploy

```bash
fly deploy --app shortlist-web
fly logs --app shortlist-web --no-tail | head -30
```

### Task 15: Verify PostHog init in production

1. Open https://shortlist.addslift.com in incognito
2. Open browser devtools → Network → filter "ingest"
3. Confirm PostHog requests flowing through reverse proxy
4. Log in → check PostHog dashboard → verify user shows with email as identified user
5. Expand a job → confirm `job_expanded` event in PostHog live view

### Task 16: Update posthog_report.py with funnel section

**File:** `~/Code/adamlab/scripts/posthog_report.py` (modify)  
**Purpose:** Add `report_funnel()` function showing activation funnel with percentages.

```
=== ACTIVATION FUNNEL ===
  Signed Up         →  4  (100%)
  Uploaded Resume   →  3  ( 75%)
  Profile Analyzed  →  1  ( 25%)  ← cliff
  API Key Saved     →  2  ( 50%)
  First Run         →  1  ( 25%)
  Expanded a Job    →  2  ( 50%)
```

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| `posthog.init()` conflicts with existing auto-init | Guard with `posthog.__loaded` check |
| Hardcoded token in source | Public client-side token — standard PostHog practice |
| Retry in llm_client adds latency | Max 2 retries, exponential backoff (2s, 4s). User sees spinner anyway |
| Session recording bandwidth on 512MB VM | `maskAllInputs: true` keeps payloads small. Disable if memory issues |
| Retroactive `run_completed` | `sessionStorage` guard prevents double-counting on refresh |

---

## Files Changed Summary

| File | Action | Phase |
|------|--------|-------|
| `web/src/lib/posthog.ts` | Create | 1 |
| `web/src/app/providers.tsx` | Modify | 1 |
| `web/src/lib/auth-context.tsx` | Modify | 1 |
| `web/src/lib/analytics.ts` | Modify | 1 |
| `web/src/components/RunButton.tsx` | Modify | 2 |
| `shortlist/api/llm_client.py` | Modify | 3 |
| `tests/api/test_llm_client.py` | Create | 3 |
| `shortlist/api/routes/profile.py` | Modify | 3 |
| `tests/api/test_profile_generate.py` | Modify | 3 |
| `web/src/app/profile/page.tsx` | Modify | 3 |
| `~/Code/adamlab/scripts/posthog_report.py` | Modify | 5 |

---

## Review Fixes Applied

All 6 issues from review addressed:

1. ~~`capture_pageview: false` + manual capture~~ → `capture_pageview: "history_change"`, removed manual `$pageview` from providers
2. ~~`posthog.people.set()`~~ → `posthog.setPersonProperties()` (modern API)
3. ~~Retroactive `run_completed` on every refresh~~ → `sessionStorage` dedup guard
4. ~~Retry in each caller~~ → Single retry in `LLMProfileGenerator.generate_profile()`
5. ~~Test retry via httpx mocking~~ → Test at `_retry_on_transient` level with mock callables
6. ~~Missing `import httpx`~~ → Added to `routes/profile.py`
