"""Database initialization and helpers."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    url TEXT,
    description TEXT,
    description_hash TEXT NOT NULL,
    salary_text TEXT,
    sources_seen TEXT DEFAULT '[]',
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'new',
    reject_reason TEXT,
    fit_score INTEGER,
    matched_track TEXT,
    score_reasoning TEXT,
    yellow_flags TEXT,
    salary_estimate TEXT,
    salary_confidence TEXT,
    enrichment TEXT,
    enriched_at DATETIME,
    tailored_resume_path TEXT,
    notes TEXT,
    first_briefed DATE,
    brief_count INTEGER DEFAULT 0,
    UNIQUE(description_hash)
);

CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company, title);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    domain TEXT,
    career_page_url TEXT,
    ats_platform TEXT,
    stage TEXT,
    last_funding TEXT,
    headcount INTEGER,
    growth_signals TEXT,
    glassdoor_rating REAL,
    eng_blog_url TEXT,
    enriched_at DATETIME,
    source TEXT,
    UNIQUE(name_normalized, domain)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    config TEXT NOT NULL,
    last_run DATETIME,
    enabled BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    status TEXT NOT NULL,
    jobs_found INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS crawled_articles (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    title TEXT,
    crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    career_urls_found INTEGER DEFAULT 0,
    jobs_found INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_crawled_articles_url ON crawled_articles(url);

CREATE TABLE IF NOT EXISTS probe_cache (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL,
    ats TEXT NOT NULL,
    found BOOLEAN NOT NULL,
    probed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(slug, ats)
);

CREATE TABLE IF NOT EXISTS run_logs (
    id INTEGER PRIMARY KEY,
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    jobs_collected INTEGER DEFAULT 0,
    jobs_filtered INTEGER DEFAULT 0,
    jobs_scored INTEGER DEFAULT 0,
    llm_calls INTEGER DEFAULT 0,
    llm_tokens_used INTEGER DEFAULT 0,
    llm_cost_estimate REAL DEFAULT 0.0,
    brief_path TEXT,
    errors TEXT
);
"""


def init_db(path: Path) -> sqlite3.Connection:
    """Initialize the database with schema. Idempotent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def get_db(path: Path) -> sqlite3.Connection:
    """Get a connection to an existing database."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def upsert_job(conn: sqlite3.Connection, job) -> None:
    """Insert a new job or update an existing one (by description_hash).

    On conflict: updates last_seen, appends source to sources_seen.
    Preserves first_seen and status.
    """
    import json

    # Check if job with this hash already exists
    existing = conn.execute(
        "SELECT id, sources_seen FROM jobs WHERE description_hash = ?",
        (job.description_hash,),
    ).fetchone()

    if existing:
        # Update: append source, bump last_seen
        sources = json.loads(existing["sources_seen"] if existing["sources_seen"] else "[]")
        if job.source not in sources:
            sources.append(job.source)
        conn.execute(
            "UPDATE jobs SET last_seen = CURRENT_TIMESTAMP, sources_seen = ? WHERE id = ?",
            (json.dumps(sources), existing["id"]),
        )
    else:
        # Insert new job
        sources = json.dumps([job.source])
        conn.execute(
            "INSERT INTO jobs (title, company, location, url, description, "
            "description_hash, salary_text, sources_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.title, job.company, job.location, job.url,
                job.description, job.description_hash, job.salary_text, sources,
            ),
        )
    conn.commit()
