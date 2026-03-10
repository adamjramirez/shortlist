"""Pipeline orchestrator — collect → filter → score → brief."""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from shortlist.collectors.base import RawJob
from shortlist.collectors.hn import HNCollector
from shortlist.collectors.linkedin import LinkedInCollector
from shortlist.collectors.nextplay import NextPlayCollector
from shortlist.config import Config
from shortlist.db import init_db, get_db, upsert_job
from shortlist.processors.filter import apply_hard_filters
from shortlist.processors.scorer import score_job, score_jobs_parallel, ScoreResult
from shortlist.processors.enricher import (
    get_cached_enrichment, enrich_company, cache_enrichment,
    rescore_with_enrichment, CompanyIntel,
)
from shortlist.collectors.career_page import discover_ats_from_domain, FETCHERS
from shortlist.processors.resume import tailor_jobs_parallel
from shortlist.brief import generate_brief

logger = logging.getLogger(__name__)


def run_pipeline(config: Config, project_root: Path, skip_collect: bool = False) -> Path:
    """Run the full pipeline and return the brief path."""
    db_path = project_root / "jobs.db"
    db = init_db(db_path)
    db.row_factory = sqlite3.Row

    run_start = datetime.now().isoformat()
    errors = []
    jobs_collected = 0
    jobs_filtered = 0

    # Step 1: Collect from all sources
    if not skip_collect:
        collectors = _get_collectors(db=db)
        for name, collector in collectors.items():
            source_start = datetime.now().isoformat()
            try:
                jobs = collector.fetch_new()
                for job in jobs:
                    upsert_job(db, job)
                jobs_collected += len(jobs)

                _log_source_run(db, name, source_start, "success", len(jobs))
            except Exception as e:
                error_msg = f"{name}: {str(e)}"
                errors.append(error_msg)
                _log_source_run(db, name, source_start, "failure", 0, str(e))
    else:
        logger.info("Skipping collection (--no-collect)")

    # Step 2: Filter new jobs
    new_jobs = db.execute("SELECT * FROM jobs WHERE status = 'new'").fetchall()
    for row in new_jobs:
        job = _row_to_raw_job(row)
        result = apply_hard_filters(job, config)
        if result.passed:
            db.execute(
                "UPDATE jobs SET status = 'filtered' WHERE id = ?", (row["id"],)
            )
        else:
            db.execute(
                "UPDATE jobs SET status = 'rejected', reject_reason = ? WHERE id = ?",
                (result.reason, row["id"]),
            )
            jobs_filtered += 1
    db.commit()

    # Step 3: Score filtered jobs (parallel)
    llm_calls = 0
    max_jobs = config.llm.max_jobs_per_run
    filtered_jobs = db.execute(
        "SELECT * FROM jobs WHERE status = 'filtered' ORDER BY first_seen DESC LIMIT ?",
        (max_jobs,),
    ).fetchall()

    score_inputs = [(row["id"], _row_to_raw_job(row)) for row in filtered_jobs]
    score_results = score_jobs_parallel(score_inputs, config, max_workers=10)

    for row_id, score_result in score_results:
        if score_result:
            llm_calls += 1
            status = "scored" if score_result.fit_score >= 60 else "low_score"
            db.execute(
                "UPDATE jobs SET status = ?, fit_score = ?, matched_track = ?, "
                "score_reasoning = ?, yellow_flags = ?, salary_estimate = ?, "
                "salary_confidence = ? WHERE id = ?",
                (
                    status, score_result.fit_score, score_result.matched_track,
                    score_result.reasoning, json.dumps(score_result.yellow_flags),
                    score_result.salary_estimate, score_result.salary_confidence,
                    row_id,
                ),
            )
        else:
            logger.warning(f"Failed to score job {row_id}")
    db.commit()

    # Step 4: Enrich companies + re-score
    scored_jobs = db.execute(
        "SELECT * FROM jobs WHERE status = 'scored' AND enrichment IS NULL "
        "ORDER BY fit_score DESC LIMIT ?",
        (config.brief.top_n,),
    ).fetchall()

    for row in scored_jobs:
        company = row["company"]
        intel = get_cached_enrichment(db, company)
        if not intel:
            intel = enrich_company(company, row["description"] or "")
            if intel:
                cache_enrichment(db, company, intel)
                llm_calls += 1

        if intel:
            db.execute(
                "UPDATE jobs SET enrichment = ?, enriched_at = ? WHERE id = ?",
                (intel.to_json(), datetime.now().isoformat(), row["id"]),
            )

            # Re-score if enrichment has material info
            rescore = rescore_with_enrichment(
                row["fit_score"], row["score_reasoning"] or "",
                row["yellow_flags"] or "[]", intel, config,
            )
            if rescore:
                new_score, delta, reason = rescore
                llm_calls += 1
                new_status = "scored" if new_score >= 60 else "low_score"
                db.execute(
                    "UPDATE jobs SET fit_score = ?, status = ?, "
                    "score_reasoning = ? WHERE id = ?",
                    (
                        new_score, new_status,
                        f"{row['score_reasoning']} [Re-scored: {reason}]",
                        row["id"],
                    ),
                )
                logger.info(
                    f"Re-scored {company}/{row['title']}: "
                    f"{row['fit_score']} → {new_score} ({delta:+d})"
                )
    db.commit()

    # Step 4b: Discover career pages for enriched companies
    # Find companies with a website_domain but no ATS/career_page stored yet
    companies_to_probe = db.execute(
        "SELECT id, name, domain FROM companies "
        "WHERE domain IS NOT NULL AND ats_platform IS NULL AND domain != ''"
    ).fetchall()

    for company_row in companies_to_probe:
        domain = company_row["domain"]
        try:
            ats, slug = discover_ats_from_domain(domain)
            if ats and slug:
                db.execute(
                    "UPDATE companies SET ats_platform = ?, career_page_url = ? WHERE id = ?",
                    (ats, f"https://jobs.{'ashbyhq.com' if ats == 'ashby' else 'boards-api.greenhouse.io' if ats == 'greenhouse' else 'api.lever.co'}/{slug}",
                     company_row["id"]),
                )
                # Fetch jobs from the discovered ATS
                fetcher = FETCHERS.get(ats)
                if fetcher:
                    new_jobs = fetcher(slug, company_name=company_row["name"])
                    for job in new_jobs:
                        upsert_job(db, job)
                    if new_jobs:
                        jobs_collected += len(new_jobs)
                        logger.info(
                            f"Company discovery: {company_row['name']} → "
                            f"{ats}/{slug} → {len(new_jobs)} jobs"
                        )
            else:
                # Mark as probed so we don't retry
                db.execute(
                    "UPDATE companies SET ats_platform = 'none' WHERE id = ?",
                    (company_row["id"],),
                )
        except Exception as e:
            logger.warning(f"Career page discovery failed for {company_row['name']}: {e}")
    db.commit()

    # Step 5: Tailor resumes for top scored jobs (parallel)
    top_jobs = db.execute(
        "SELECT * FROM jobs WHERE status = 'scored' AND tailored_resume_path IS NULL "
        "ORDER BY fit_score DESC LIMIT ?",
        (config.brief.top_n,),
    ).fetchall()

    today = datetime.now().strftime("%Y-%m-%d")
    drafts_dir = project_root / "resumes" / "drafts"

    tailor_inputs = [
        (row["id"], row["matched_track"] or "em", row["title"],
         row["company"], row["description"] or "")
        for row in top_jobs
    ]

    if tailor_inputs:
        results = tailor_jobs_parallel(
            tailor_inputs, config, project_root, drafts_dir, today,
            max_workers=10,
        )
        for job_id, tailored, output_path in results:
            if tailored and output_path:
                db.execute(
                    "UPDATE jobs SET tailored_resume_path = ? WHERE id = ?",
                    (str(output_path), job_id),
                )
                llm_calls += 2  # select + tailor

    db.commit()

    # Step 5: Generate brief
    briefs_dir = project_root / config.brief.output_dir
    brief_path = generate_brief(db, briefs_dir)

    # Log run
    db.execute(
        "INSERT INTO run_logs (started_at, finished_at, jobs_collected, jobs_filtered, "
        "jobs_scored, llm_calls, brief_path, errors) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_start, datetime.now().isoformat(), jobs_collected, jobs_filtered,
            len(filtered_jobs), llm_calls, str(brief_path),
            json.dumps(errors) if errors else None,
        ),
    )
    db.commit()
    db.close()

    return brief_path


def run_collect_only(config: Config, project_root: Path) -> int:
    """Run only the collect step. Returns number of jobs collected."""
    db_path = project_root / "jobs.db"
    db = init_db(db_path)
    db.row_factory = sqlite3.Row

    total = 0
    collectors = _get_collectors(db=db)
    for name, collector in collectors.items():
        source_start = datetime.now().isoformat()
        try:
            jobs = collector.fetch_new()
            for job in jobs:
                upsert_job(db, job)
            total += len(jobs)
            _log_source_run(db, name, source_start, "success", len(jobs))
        except Exception as e:
            _log_source_run(db, name, source_start, "failure", 0, str(e))

    db.close()
    return total


def run_brief_only(config: Config, project_root: Path) -> Path:
    """Run only the brief generation step."""
    db_path = project_root / "jobs.db"
    db = init_db(db_path)
    db.row_factory = sqlite3.Row

    briefs_dir = project_root / config.brief.output_dir
    brief_path = generate_brief(db, briefs_dir)
    db.close()
    return brief_path


def _row_to_raw_job(row) -> RawJob:
    """Convert a database row to a RawJob."""
    return RawJob(
        title=row["title"],
        company=row["company"],
        url=row["url"] or "",
        description=row["description"] or "",
        source="db",
        location=row["location"],
        salary_text=row["salary_text"],
        description_hash=row["description_hash"],
    )


def _get_collectors(db: sqlite3.Connection | None = None) -> dict:
    """Get all enabled collectors."""
    return {
        "hn": HNCollector(),
        "linkedin": LinkedInCollector(time_filter="r604800"),  # past week
        "nextplay": NextPlayCollector(db=db),
    }


def _log_source_run(
    db: sqlite3.Connection, name: str, started_at: str,
    status: str, jobs_found: int, error_message: str | None = None,
):
    """Log a source run. Creates source if it doesn't exist."""
    # Ensure source exists
    db.execute(
        "INSERT OR IGNORE INTO sources (name, type, config) VALUES (?, ?, ?)",
        (name, "simple", "{}"),
    )
    source_id = db.execute(
        "SELECT id FROM sources WHERE name = ?", (name,)
    ).fetchone()["id"]

    # Update last_run
    if status == "success":
        db.execute(
            "UPDATE sources SET last_run = ? WHERE id = ?",
            (datetime.now().isoformat(), source_id),
        )

    # Log run
    db.execute(
        "INSERT INTO source_runs (source_id, started_at, finished_at, status, "
        "jobs_found, error_message) VALUES (?, ?, ?, ?, ?, ?)",
        (source_id, started_at, datetime.now().isoformat(), status,
         jobs_found, error_message),
    )
    db.commit()
