# Shortlist Web UI — Implementation Plan

## Goal

Turn Shortlist from a CLI tool into a web product. Users sign up, configure their profile in-browser, and get daily job briefs — no repo clone, no terminal, no source code visible.

## Architecture

Proven pattern from resonance + creatomap: single Docker container, supervisord manages FastAPI + Next.js. Pipeline runs on ephemeral Fly Machines.

```
Browser (Next.js)                    ← port 3000, public
    ↕ /api/* proxied
FastAPI backend                      ← port 8001, internal only
    ↕ 
PostgreSQL (Fly Postgres)            ← per-user job data
    
Ephemeral Fly Machines               ← one per pipeline run, auto-destroyed
    ↕                                   spawned via Fly Machines API
Existing pipeline (collectors, scorers, enricher, resume tailoring)
```

Everything on Fly.io. No split infra. Pipeline scales horizontally — 20 users clicking "Run now" = 20 machines, no queue.

### Learned from resonance + creatomap

| Lesson | Source | Applied here |
|--------|--------|-------------|
| **supervisord priorities + health check wait loop** | resonance Session 30 | Next.js waits for FastAPI health before starting |
| **IPv6 monkey-patch for Google APIs** | resonance D098, creatomap C014 | Worker patches `socket.getaddrinfo` — Gemini calls hang on IPv6 from Fly |
| **`startretries=999`** | resonance Session 43 | Worker never gives up on crash |
| **Task-level timeouts** | resonance Session 44 | All pipeline steps wrapped in timeout — hangs don't deadlock |
| **`NEXT_PUBLIC_` vars need build-time injection** | creatomap C013 | Docker ARG + ENV in Dockerfile, `[build.args]` in fly.toml |
| **1024MB minimum VM** | creatomap C012 | Pipeline + FastAPI + Next.js in one container needs memory |
| **Alembic for migrations** | creatomap start.sh | `alembic upgrade head` on startup, not raw SQL |
| **Connection pooling from day 1** | resonance CLAUDE.md | SQLAlchemy async engine with `pool_size=10`, `pool_pre_ping=True` |
| **Fly internal networking doesn't use SSL** | creatomap db.py | Detect `flycast`/`internal` in DB URL, skip SSL |
| **Atomic transaction per pipeline phase** | creatomap D027 | Crash between phases doesn't corrupt data |
| **Rate limit everything** | resonance Rule 6, creatomap C009 | Existing `shortlist/http.py` already does this — keep it |
| **Worker restart loop** | resonance Session 43 | `while/try/except` in worker — individual run crash doesn't kill daemon |
| **Stale job cleanup** | resonance CLAUDE.md | Main app sweeps every 5 min — any run `running` for >35 min marked `failed` |
| **DB disk monitoring** | resonance Session 43 | 3GB volume minimum, alert at 90% |

---

## Phase 1: Backend API (2-3 days)

### 1.1 Database (PostgreSQL + SQLAlchemy + Alembic)

**Schema — new tables:**

```sql
-- Users
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Profiles (one per user, stores the full profile.yaml as JSON)
CREATE TABLE profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    config JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Pipeline runs
CREATE TABLE runs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    progress JSONB DEFAULT '{}',
    error TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Resume files (metadata — actual files on Fly volume)
CREATE TABLE resumes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename TEXT NOT NULL,
    track TEXT,  -- which track this resume is for
    path TEXT NOT NULL,  -- path on volume: /data/{user_id}/resumes/{filename}
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Existing tables get `user_id`:**

```sql
ALTER TABLE jobs ADD COLUMN user_id INTEGER REFERENCES users(id);
ALTER TABLE companies ADD COLUMN user_id INTEGER REFERENCES users(id);
CREATE INDEX idx_jobs_user ON jobs(user_id);
CREATE INDEX idx_companies_user ON companies(user_id);
```

**DB setup:**
- SQLAlchemy async engine (same pattern as creatomap: `pool_size=10`, `pool_pre_ping=True`, `pool_recycle=300`)
- Alembic for migrations
- `start.sh` runs `alembic upgrade head` before supervisord
- Fly Postgres, `ord` region (same as resonance + creatomap)

**LLM key storage:**
- User's API key stored encrypted in `profiles.config` JSONB
- Encrypt with Fernet (symmetric, from `ENCRYPTION_KEY` env var)
- Decrypt only when running pipeline — never returned to frontend

### 1.2 Auth

Simple JWT. No OAuth, no magic links — keep it minimal.

```
POST /api/auth/signup     { email, password } → { token }
POST /api/auth/login      { email, password } → { token }
GET  /api/auth/me         → { id, email }
```

- Passwords: bcrypt via `passlib`
- Tokens: PyJWT, 30-day expiry
- Every `/api/*` endpoint except signup/login requires `Authorization: Bearer <token>`

### 1.3 Profile management

```
GET  /api/profile         → current profile config (or empty template)
PUT  /api/profile         { fit_context, tracks, filters, llm } → saved
```

Profile stored as JSONB — same shape as `profile.yaml`. Frontend sends JSON, backend validates structure, stores directly. No YAML on the server.

### 1.4 Resume upload

```
POST /api/resumes         multipart file upload (.tex, max 1MB) → { id, filename }
GET  /api/resumes         → list of uploaded resumes
DELETE /api/resumes/:id   → deleted
GET  /api/resumes/:id/download → .tex file
```

Files stored in **Tigris object storage** (Fly's S3-compatible service, same as creatomap images): `s3://shortlist-resumes/{user_id}/resumes/{filename}`
Tailored resumes: `s3://shortlist-resumes/{user_id}/resumes/drafts/{date}-{company}-{track}.tex`

**Why not Fly volumes:** Ephemeral worker machines can't mount the main app's volume. Object storage is accessible from any machine via S3 API. Workers download the user's resume at pipeline start, upload tailored resumes on completion.

### 1.5 Pipeline runs (ephemeral Fly Machines)

```
POST /api/runs            → { run_id } (spawns a Fly Machine to run pipeline)
GET  /api/runs            → list of past runs (most recent first)
GET  /api/runs/:id        → { status, progress, started_at, finished_at, error }
```

- **One active run per user.** POST /runs returns 409 if already running.
- **Each run gets its own Fly Machine.** API calls the Fly Machines REST API to spawn an ephemeral worker. The machine boots (~3s), runs the pipeline, writes results to Postgres, and self-stops. 20 concurrent users = 20 machines running in parallel, no queue.
- Pipeline updates `runs.progress` JSONB as it goes: `{ "phase": "scoring", "scored": 142, "total": 410 }`
- Frontend polls `GET /runs/:id` every 3s for progress.
- **Timeout: 30 minutes per run.** Machine auto-stops after this regardless.
- **Cost:** ~$0.01 per run (shared-cpu-1x for 20 min). 100 users/day = ~$1/day.
- **On machine crash:** Run stays in `running` state. A cleanup sweep in the main app (every 5 min) marks any run that's been `running` for >35 min as `failed`.

**How it works:**

```
User clicks "Run now"
    → API inserts run record (status: pending)
    → API calls Fly Machines API:
        POST /v1/apps/shortlist-workers/machines
        {
          "config": {
            "image": "registry.fly.io/shortlist-web:latest",
            "env": {
              "RUN_ID": "123",
              "DATABASE_URL": "...",
              "ENCRYPTION_KEY": "...",
              "MODE": "worker"
            },
            "auto_destroy": true,
            "restart": { "policy": "no" },
            "guest": { "cpu_kind": "shared", "cpus": 1, "memory_mb": 1024 }
          }
        }
    → Machine boots, detects MODE=worker, runs pipeline for RUN_ID
    → Updates runs.progress in Postgres as it goes
    → Pipeline completes → sets status=completed → machine exits → auto-destroyed
    → User's browser was polling /runs/:id, sees completion
```

**The main app's `worker.py` becomes the ephemeral entry point:**

```python
# worker.py
import os, sys

def main():
    run_id = os.environ.get("RUN_ID")
    if not run_id:
        print("No RUN_ID set, exiting")
        sys.exit(1)
    
    # Connect to Postgres, load run + user profile
    # Decrypt user's LLM API key
    # Run pipeline with user_id scoping
    # Update run status on completion/failure
    
if __name__ == "__main__":
    main()
```

**Fly Machines setup:**
```bash
# Create a separate app for worker machines (shares the same Docker image)
fly apps create shortlist-workers
# Workers need DB access
fly postgres attach shortlist-db --app shortlist-workers
# Workers need the same secrets
fly secrets set ENCRYPTION_KEY=... --app shortlist-workers
# The main app needs a Fly API token to spawn machines
fly tokens create deploy --app shortlist-workers
# Set that token as a secret on the main app
fly secrets set FLY_WORKER_TOKEN=... --app shortlist-web
```

### 1.6 Brief + jobs API

```
GET  /api/brief/today     → today's brief as JSON
GET  /api/brief/:date     → brief for a specific date
GET  /api/jobs            → paginated jobs (query: min_score, track, status, source, page)
GET  /api/jobs/:id        → single job with full details
PUT  /api/jobs/:id/status { status: "applied" | "skipped" | "saved" } → updated
GET  /api/jobs/:id/resume → download tailored resume (.tex)
```

Brief JSON:
```json
{
  "date": "2026-03-11",
  "summary": { "total_scored": 410, "top_matches": 28, "new_today": 12 },
  "jobs": [
    {
      "id": 123,
      "title": "VP Engineering",
      "company": "Acme Corp",
      "score": 87,
      "track": "vp",
      "reasoning": "Strong match — Series B fintech...",
      "yellow_flags": ["Series A"],
      "salary_estimate": "$280k-$320k",
      "apply_url": "https://...",
      "alt_urls": [],
      "company_intel": { "stage": "Series B", "headcount": 120 },
      "marker": "new",
      "has_tailored_resume": true,
      "status": null
    }
  ]
}
```

### 1.7 File structure

```
shortlist/
├── api/
│   ├── __init__.py
│   ├── app.py              # FastAPI app, CORS, lifespan
│   ├── auth.py             # signup, login, JWT, get_current_user
│   ├── db.py               # SQLAlchemy async engine, get_session
│   ├── models.py           # SQLAlchemy models
│   ├── crypto.py           # Fernet encrypt/decrypt for API keys
│   └── routes/
│       ├── profile.py
│       ├── runs.py
│       ├── brief.py
│       ├── jobs.py
│       └── resumes.py
├── worker.py               # Ephemeral entry point — Fly Machine runs one pipeline, then exits
├── alembic/                # Migrations
├── alembic.ini
├── pipeline.py             # Existing (add user_id scoping)
├── db.py                   # Existing (extend for PostgreSQL)
└── ... (existing code unchanged)
```

---

## Phase 2: Frontend (2-3 days)

Next.js 14+ App Router, Tailwind, same patterns as creatomap.

### 2.1 Pages

**`/` (logged out)** — Landing page.
- What it is, how it works (3 steps), example brief screenshot
- "Get started" → signup

**`/` (logged in)** — Dashboard. Today's brief as job cards.
- Score badge (color-coded), title, company, reasoning snippet
- Click to expand: full reasoning, yellow flags, company intel, tailored resume download, apply link
- Status buttons: Applied / Skipped / Saved
- "Run now" button → progress bar while running
- Filter bar: min score, track, source, status
- Empty state: onboarding checklist (see 2.3)

**`/profile`** — Profile setup.
- `fit_context` textarea with helper text + link to AI prompt for generating it
- Tracks as repeatable sections (title, search queries, resume file picker)
- Filters (location, salary, role type)
- LLM config: provider dropdown (Gemini/OpenAI/Anthropic), API key (masked input)
- Resume upload area (drag & drop .tex files)
- Save button with validation

**`/history`** — Past briefs. List of dates, click to see that day's brief.

**`/login` + `/signup`** — Email/password forms.

### 2.2 Stack

- Next.js 14+ (App Router)
- Tailwind CSS
- No component library
- `revalidate: 60` on API fetches (same pattern as resonance/creatomap)
- `Promise.all()` for independent API calls in server components (resonance lesson)

### 2.3 Onboarding checklist

Empty dashboard shows:
```
Welcome to Shortlist! Complete these steps to run your first search:

☐ Write your fit context (profile)
☐ Add at least one track with search queries
☐ Upload your resume (.tex file)
☐ Add your LLM API key
☐ Set your location and salary filters

[Go to Profile Setup →]
```

Each item checks against the profile API. When all complete, "Run your first search" button appears.

### 2.4 File structure

```
web/
├── app/
│   ├── layout.tsx
│   ├── page.tsx            # Landing (logged out) / Dashboard (logged in)
│   ├── login/page.tsx
│   ├── signup/page.tsx
│   ├── profile/page.tsx
│   └── history/page.tsx
├── components/
│   ├── JobCard.tsx
│   ├── BriefView.tsx
│   ├── ProfileForm.tsx
│   ├── RunProgress.tsx
│   ├── OnboardingChecklist.tsx
│   └── Nav.tsx
├── lib/
│   ├── api.ts              # fetch wrapper with auth headers
│   └── types.ts            # TypeScript types matching API responses
├── tailwind.config.ts
├── next.config.ts
└── package.json
```

---

## Phase 3: Deploy (1 day)

### Dockerfile (proven pattern)

```dockerfile
# Stage 1: Build Next.js
FROM node:20-alpine AS web-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

# Stage 2: Production
FROM python:3.13-slim
WORKDIR /app

# Node.js + supervisor + curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl supervisor && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Backend
COPY shortlist/ /app/shortlist/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/
COPY worker.py /app/

# Next.js standalone build
COPY --from=web-builder /app/web/.next/standalone /app/web
COPY --from=web-builder /app/web/.next/static /app/web/.next/static
COPY --from=web-builder /app/web/public /app/web/public

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s \
  CMD curl -f http://localhost:3000/api/health || exit 1

CMD ["/app/start.sh"]
```

### supervisord.conf

No persistent worker — pipeline runs are ephemeral Fly Machines. Main app only runs FastAPI + Next.js.

```ini
[supervisord]
nodaemon=true
logfile=/dev/stdout
logfile_maxbytes=0

[program:fastapi]
command=python3 -m uvicorn shortlist.api.app:app --host 127.0.0.1 --port 8001
directory=/app
priority=10
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:nextjs]
command=bash -c "until curl -sf http://127.0.0.1:8001/api/health; do sleep 1; done; exec node /app/web/server.js"
directory=/app/web
environment=PORT="3000",HOSTNAME="0.0.0.0"
priority=20
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
```

### start.sh

```bash
#!/bin/bash
set -e

echo "Running database migrations..."
cd /app
python3 -c "
import time, psycopg
for attempt in range(10):
    try:
        import subprocess
        subprocess.run(['python3', '-m', 'alembic', 'upgrade', 'head'], check=True)
        print('Migrations complete.')
        break
    except Exception as e:
        if attempt < 9:
            wait = min(2 ** attempt, 10)
            print(f'DB not ready, retrying in {wait}s (attempt {attempt + 1}/10)')
            time.sleep(wait)
        else:
            raise
"

mkdir -p /data
echo "Starting services..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
```

### fly.toml

```toml
app = "shortlist-web"
primary_region = "ord"

[build]
  [build.args]
    NEXT_PUBLIC_API_URL = ""  # same origin, proxied through Next.js

[http_service]
  internal_port = 3000
  force_https = true
  auto_stop_machines = "off"
  auto_start_machines = true
  min_machines_running = 1

  [[http_service.checks]]
    interval = "10s"
    timeout = "3s"
    grace_period = "20s"
    method = "GET"
    path = "/api/health"

[[vm]]
  size = "shared-cpu-1x"
  memory = "1024mb"
```

### DNS

Add CNAME: `shortlist.addslift.com` → `shortlist-web.fly.dev`

### Fly setup commands

```bash
# Main app
fly apps create shortlist-web
fly postgres create --name shortlist-db --region ord --vm-size shared-cpu-1x --initial-cluster-size 1 --volume-size 3
fly postgres attach shortlist-db --app shortlist-web
fly secrets set JWT_SECRET=$(openssl rand -hex 32) ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())") --app shortlist-web

# Object storage for resumes (Tigris, Fly's S3-compatible service)
fly storage create --name shortlist-resumes --app shortlist-web
# This auto-sets AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, BUCKET_NAME as secrets

# Worker app (ephemeral machines, shares DB + secrets)
fly apps create shortlist-workers
fly postgres attach shortlist-db --app shortlist-workers
fly secrets set ENCRYPTION_KEY=... --app shortlist-workers
# Main app needs token to spawn worker machines
fly tokens create deploy --app shortlist-workers
fly secrets set FLY_WORKER_TOKEN=... --app shortlist-web

# Deploy
fly deploy --app shortlist-web
```

---

## Phase 4: Polish + launch (1-2 days)

- **Landing page copy** — what it does, who it's for, example brief, "get started"
- **Email notifications** — "Your daily brief is ready" with top 3 matches summary (optional, later)
- **Mobile responsive** — people check job briefs on their phone
- **OG meta tags** for sharing
- **Error surfaces** — source failures, LLM key invalid, rate limits → user-visible toast/banner
- **PDF export** — add Tectonic (small LaTeX compiler, ~30MB) to Docker image for .tex → .pdf. Not v1.

---

## What changes in existing code

Minimal. The pipeline is the product.

| File | Change |
|------|--------|
| `db.py` | Add PostgreSQL support alongside SQLite. Environment variable switches: `DATABASE_URL` → Postgres, else SQLite. |
| `pipeline.py` | Accept `user_id` param. Pass to all DB operations. |
| `config.py` | Accept config dict (from API) in addition to YAML file. |
| `brief.py` | Add `to_json()` alongside markdown output. |
| `processors/scorer.py` | Accept API key param instead of reading from `.env`. |
| `processors/enricher.py` | Same — accept API key. |
| `processors/resume.py` | Same — accept API key. Accept resume paths from DB instead of filesystem. |
| `llm.py` | Accept API key param instead of env var. |

**Everything else untouched:** collectors, filters, HTTP client, all business logic.

---

## Scope summary

| Phase | What | Time | Milestone |
|-------|------|------|-----------|
| 1 | Backend API + DB | 2-3 days | Pipeline runs via HTTP, curl-testable |
| 2 | Frontend | 2-3 days | Users can sign up, configure, run, read briefs |
| 3 | Deploy | 1 day | Live at shortlist.addslift.com |
| 4 | Polish + launch | 1-2 days | Landing page, mobile, error handling |
| **Total** | | **~1 week** | |

---

## Decisions made

1. **Domain:** `shortlist.addslift.com` (subdomain for now)
2. **Repo:** ✅ Made private (was public at github.com/adamjramirez/shortlist)
3. **Pricing:** Free tier, user provides their own LLM API key
4. **Resume format:** LaTeX only. Users generate their CV with AI, upload .tex file. Server compiles to PDF for download (Phase 4).
5. **Database:** PostgreSQL from day 1 (learned from resonance — multi-user needs it)
6. **ORM:** SQLAlchemy async (same pattern as creatomap)
7. **Migrations:** Alembic (same pattern as creatomap)
8. **Infra:** All Fly.io — single container, supervisord, `ord` region
9. **No scheduled runs for v1.** Users click "Run now." Add scheduling when usage patterns are clear.
10. **Ephemeral Fly Machines for pipeline runs.** One machine per run, auto-destroyed on completion. Scales horizontally — no queue, no shared worker state. ~$0.01/run.

## Kill criteria

- If fewer than 20 users sign up in the first 2 weeks after launch → re-evaluate distribution, not features.
- If pipeline runs take >30 min per user → optimize or add parallel workers before adding users.
- If LLM costs per run exceed $5 on the cheapest model → something is wrong with the pipeline.
