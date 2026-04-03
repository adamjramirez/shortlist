# International Support

Make Shortlist work for users in any country — UK, EU, India, Australia, Canada, etc.

## Current state

| Area | Now | Target |
|------|-----|--------|
| LinkedIn location | Hardcoded `"United States"` in `_run_search()` | User's `country` from profile |
| LinkedIn work type | Hardcoded `f_WT=2` (remote only) per search | Derived from user's `remote` + `local_cities` |
| Scorer prompt | `$` prefix, hardcoded `$250,000` default | Currency-aware (`{amount} {currency}`) |
| Location config | `local_cities`, `local_zip` | Add `country` field |
| Frontend profile | No country or currency UI | Country dropdown + currency dropdown |

## What stays the same

- HN collector (already global)
- NextPlay collector (ATS fetchers are global — Greenhouse/Lever/Ashby serve all geographies)
- Enricher prompt (already geography-neutral, uses freeform `hq_location`)
- Cover letter prompt (no currency/location assumptions)
- Filter logic (already geography-agnostic)
- DB schema (country/currency stored in profile JSON blob, no migration needed)
- Score thresholds

## Verified

- LinkedIn guest API returns 200 with real results for: United Kingdom, Germany, France, India, Australia, Canada, Netherlands, Singapore, Ireland
- `f_WT` filter works with non-US locations
- `f_E` experience level codes are LinkedIn-global

---

## Task 1: Add `country` to `LocationFilter`

**File:** `shortlist/config.py` (modify)

Add `country: str = ""` to `LocationFilter` dataclass. Empty string = backward compat (treated as "United States" downstream).

**Test:** `tests/test_config.py` — round-trip a config with `country` set, verify it survives `_build_dataclass`.

---

## Task 2: Make LinkedIn collector location-configurable

**File:** `shortlist/collectors/linkedin.py` (modify)

Two separate concerns:

### 2a: Collector owns `location`

- Add `location: str = "United States"` param to `LinkedInCollector.__init__()`
- Store as `self.location`
- `_run_search()` line 73: replace hardcoded `"United States"` with `self.location`

### 2b: `searches_from_config()` derives `f_WT` from user prefs

Current: every search gets `"f_WT": "2"` (remote only).

New logic based on `config.filters.location`:

| `remote` | `local_cities` | `f_WT` | Meaning |
|----------|---------------|--------|---------|
| `True` | empty | `"2"` | Remote only (current behavior) |
| `True` | has cities | `"2,3"` | Remote + hybrid near them |
| `False` | has cities | `"1,3"` | On-site + hybrid |
| `False` | empty | omit `f_WT` | All work types |

Signature change: `searches_from_config(config)` already takes full config — just read `config.filters.location` inside it.

**Tests:** `tests/test_linkedin.py`
- `searches_from_config` with `remote=True, local_cities=[]` → `f_WT="2"`
- `searches_from_config` with `remote=True, local_cities=["London"]` → `f_WT="2,3"`
- `searches_from_config` with `remote=False, local_cities=["London"]` → `f_WT="1,3"`
- `searches_from_config` with `remote=False, local_cities=[]` → no `f_WT` key
- `LinkedInCollector(location="United Kingdom")` passes location to `_run_search`

---

## Task 3: Wire country through pipeline to LinkedIn collector

**File:** `shortlist/pipeline.py` (modify)

In `_get_collectors()`:
- Read `config.filters.location.country` — if empty, use `"United States"`
- Pass as `location=` to `LinkedInCollector(...)`

```python
country = config.filters.location.country if config else ""
linkedin_location = country or "United States"
# ...
collectors["linkedin"] = LinkedInCollector(
    searches=searches, time_filter="r604800", location=linkedin_location
)
```

**Test:** `tests/test_pipeline.py` — verify collector constructed with correct location from config.

---

## Task 4: Make scorer prompt currency-aware

**File:** `shortlist/processors/scorer.py` (modify)

### 4a: Location requirement includes country

`_build_location_requirement(config)` — if `config.filters.location.country` is set, include it:
- `"Remote in United Kingdom"` or `"Remote or near London, Manchester in United Kingdom"`

### 4b: Salary line uses currency

Current:
```
- Salary: Minimum ${min_salary:,} base
```

New:
```
- Salary: Minimum {min_salary:,} {currency} base. If the job lists salary in a different currency, convert approximately.
```

### 4c: Salary estimate format uses currency

Current:
```
"salary_estimate": "<format as $XXXk-$XXXk, e.g. $200k-$300k>"
```

New:
```
"salary_estimate": "<format as XXXk-XXXk {currency}, e.g. 200k-300k USD>"
```

Pass `currency` into `build_scoring_prompt()` from `config.filters.salary.currency`.

**Tests:** `tests/test_scorer.py`
- Prompt with `currency="GBP"` contains `GBP` not `$`
- Prompt with `country="United Kingdom"` includes country in location requirement
- Prompt with default config still works (USD, no country)

---

## Task 5: Wire country through worker.py

**File:** `shortlist/api/worker.py` (modify)

In the `LocationFilter` construction (~line 98), add:
```python
country=loc.get("country", ""),
```

Already reads `remote`, `local_cities`, etc. Just add the new field.

**Test:** Verify existing worker tests still pass. Add one test that config built from profile JSON with `country: "Germany"` produces `LocationFilter(country="Germany")`.

---

## Task 6: Frontend — country and currency in profile form

### 6a: Types

**File:** `web/src/lib/profile-types.ts` (modify)

- Add `country: string` to `FiltersForm.location`
- `defaultFilters()`: `country: ""`
- `jsonToFilters()`: read `loc.country`, default `""`
- `filtersToJson()`: already spreads `f.location` — `country` included automatically

### 6b: Profile page UI

**File:** `web/src/app/profile/page.tsx` (modify)

In the Location section (alongside remote toggle and local_cities):
- Country `<select>` with common options:
  - `""` = "United States (default)"
  - `"United States"`
  - `"United Kingdom"`
  - `"Canada"`
  - `"Germany"`
  - `"France"`
  - `"Netherlands"`
  - `"Ireland"`
  - `"India"`
  - `"Australia"`
  - `"Singapore"`
  - `"Other"` → shows text input for freeform country name

- Currency `<select>` (in salary section):
  - Already has currency field — just need to add a dropdown if not present
  - Options: USD, GBP, EUR, CAD, AUD, SGD, INR

**Test:** `cd web && npm run build` — type check passes.

---

## Edge cases

| Case | Handling |
|------|----------|
| Existing users with no `country` in profile JSON | `loc.get("country", "")` → empty → pipeline treats as "United States" |
| Country set, no local_cities | LinkedIn searches that country, remote-only |
| Currency mismatch (user=GBP, job lists USD) | Scorer prompt says "convert approximately" — LLM handles |
| Empty country + empty local_cities | Current behavior preserved exactly |

## Verification

After all tasks:
1. `pytest tests/ -q` — all pass
2. `cd web && npm run build` — no type errors
3. Manual: profile with country=UK, currency=GBP → LinkedIn searches UK, scorer prompt mentions GBP, salary format correct
