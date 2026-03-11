"""Pipeline orchestrator — collect → filter → score → brief."""
import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from shortlist.collectors.base import RawJob
from shortlist.collectors.hn import HNCollector
from shortlist.collectors.linkedin import LinkedInCollector
from shortlist.collectors.nextplay import NextPlayCollector
from shortlist.config import Config
from shortlist import llm
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


def _progress(msg: str):
    """Print progress to stderr so user sees it. Also log."""
    import sys
    print(msg, file=sys.stderr, flush=True)
    logger.info(msg)


def _emit(on_progress, msg: str, **kwargs):
    """Print progress AND call the structured callback if provided."""
    _progress(msg)
    if on_progress:
        kwargs.setdefault("detail", msg)
        on_progress(kwargs)


def _ensure_llm(config: Config) -> None:
    """Configure the LLM if not already configured."""
    if llm._provider is None:
        llm.configure(config.llm.model)


class CancelledError(Exception):
    """Raised when a pipeline run is cancelled."""
    pass


def run_pipeline(
    config: Config,
    project_root: Path,
    skip_collect: bool = False,
    on_progress: callable = None,
    on_jobs_ready: callable = None,
    cancel_event: "threading.Event | None" = None,
) -> Path:
    """Run the full pipeline and return the brief path."""
    _ensure_llm(config)
    db_path = project_root / "jobs.db"
    db = init_db(db_path)
    db.row_factory = sqlite3.Row

    from shortlist.collectors.linkedin import fetch_description_for_url
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _check_cancel():
        if cancel_event and cancel_event.is_set():
            raise CancelledError("Run cancelled by user")

    run_start = datetime.now().isoformat()
    errors = []
    jobs_collected = 0
    jobs_filtered = 0
    llm_calls = 0
    total_scored = 0
    total_matches = 0
    max_jobs = config.llm.max_jobs_per_run
    jobs_scored_so_far = 0

    def _filter_new_jobs():
        """Filter all jobs with status='new'. Returns (passed, rejected) counts."""
        nonlocal jobs_filtered
        new_jobs = db.execute("SELECT * FROM jobs WHERE status = 'new'").fetchall()
        rejected = 0
        for row in new_jobs:
            job = _row_to_raw_job(row)
            result = apply_hard_filters(job, config)
            if result.passed:
                db.execute("UPDATE jobs SET status = 'filtered' WHERE id = ?", (row["id"],))
            else:
                db.execute(
                    "UPDATE jobs SET status = 'rejected', reject_reason = ? WHERE id = ?",
                    (result.reason, row["id"]),
                )
                rejected += 1
        db.commit()
        jobs_filtered += rejected
        return len(new_jobs) - rejected, rejected

    def _fetch_descriptions():
        """Fetch full descriptions for filtered LinkedIn jobs missing them."""
        needs_desc = db.execute(
            "SELECT id, url, description FROM jobs WHERE status = 'filtered' "
            "AND sources_seen LIKE '%linkedin%' "
            "AND length(description) < 200 "
            "AND first_seen = last_seen"
        ).fetchall()
        if not needs_desc:
            return 0

        _emit(on_progress, f"Fetching details for {len(needs_desc)} jobs…",
              phase="fetching", detail=f"Fetching details for {len(needs_desc)} jobs…")

        def _fetch_one(row):
            desc = fetch_description_for_url(row["url"])
            return row["id"], desc

        fetched = 0
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(_fetch_one, row): row for row in needs_desc}
            for future in as_completed(futures):
                try:
                    row_id, desc = future.result()
                    if desc:
                        db.execute("UPDATE jobs SET description = ? WHERE id = ?", (desc, row_id))
                        fetched += 1
                except Exception as e:
                    logger.warning(f"Failed to fetch description: {e}")
        db.commit()
        return fetched

    def _score_filtered():
        """Score all filtered jobs up to max_jobs limit. Returns (scored, matches)."""
        _check_cancel()
        nonlocal llm_calls, jobs_scored_so_far
        remaining = max_jobs - jobs_scored_so_far
        if remaining <= 0:
            return 0, 0

        filtered_jobs = db.execute(
            "SELECT * FROM jobs WHERE status = 'filtered' ORDER BY first_seen DESC LIMIT ?",
            (remaining,),
        ).fetchall()

        score_inputs = [(row["id"], _row_to_raw_job(row)) for row in filtered_jobs]
        if not score_inputs:
            return 0, 0

        _emit(on_progress, f"Scoring {len(score_inputs)} jobs…",
              phase="scoring", detail=f"Scoring {len(score_inputs)} jobs…",
              scored=jobs_scored_so_far, total=jobs_scored_so_far + len(score_inputs))

        def _on_scored(done, total):
            _emit(on_progress, f"  Scored {done}/{total}", phase="scoring",
                  detail=f"Scoring jobs…",
                  scored=jobs_scored_so_far + done,
                  total=jobs_scored_so_far + total)

        score_results = score_jobs_parallel(score_inputs, config, max_workers=10, on_scored=_on_scored, cancel_event=cancel_event)
        _check_cancel()

        matches = 0
        for row_id, score_result in score_results:
            if score_result:
                llm_calls += 1
                status = "scored" if score_result.fit_score >= 60 else "low_score"
                if score_result.fit_score >= 60:
                    matches += 1
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

        jobs_scored_so_far += len(score_inputs)
        return len(score_inputs), matches

    def _notify_jobs_ready():
        """Tell the worker to copy newly scored jobs to PostgreSQL now."""
        if on_jobs_ready:
            on_jobs_ready(db)

    # === Main pipeline: process sources with LinkedIn in background ===

    if not skip_collect:
        collectors = _get_collectors(config=config, db=db)

        # Separate LinkedIn from fast sources
        linkedin_collector = collectors.pop("linkedin", None)
        fast_collectors = collectors  # hn, nextplay, etc.

        # Start LinkedIn collection in background — spreads requests across
        # the entire run instead of one burst. By the time we need LinkedIn
        # results, most search pages are already fetched.
        import threading
        linkedin_result = {"jobs": [], "error": None}
        linkedin_done = threading.Event()

        def _collect_linkedin():
            if not linkedin_collector:
                linkedin_done.set()
                return
            try:
                logger.info("Collecting from linkedin (background)…")
                jobs = linkedin_collector.fetch_new()
                linkedin_result["jobs"] = jobs
            except Exception as e:
                linkedin_result["error"] = str(e)
            finally:
                linkedin_done.set()

        # Emit initial status BEFORE starting LinkedIn thread
        fast_names = list(fast_collectors.keys())
        _emit(on_progress, f"Starting search…",
              phase="collecting", detail=f"Searching {', '.join(fast_names)}…")

        linkedin_thread = threading.Thread(target=_collect_linkedin, daemon=True)
        linkedin_thread.start()

        # Process fast sources immediately (HN, NextPlay)
        for name, collector in fast_collectors.items():
            _check_cancel()
            _emit(on_progress, f"Collecting from {name}...",
                  phase="collecting", detail=f"Searching {name}…")
            source_start = datetime.now().isoformat()
            try:
                jobs = collector.fetch_new()
                for job in jobs:
                    upsert_job(db, job)
                jobs_collected += len(jobs)
                _emit(on_progress, f"  → {name}: {len(jobs)} jobs",
                      phase="collecting", detail=f"{name}: {len(jobs)} jobs",
                      collected=jobs_collected)
                _log_source_run(db, name, source_start, "success", len(jobs))
            except Exception as e:
                errors.append(f"{name}: {str(e)}")
                _emit(on_progress, f"  → {name}: failed ({e})",
                      phase="collecting", detail=f"{name}: failed")
                _log_source_run(db, name, source_start, "failure", 0, str(e))
                continue

            if not jobs:
                continue

            # Filter → Score → Save immediately
            passed, rejected = _filter_new_jobs()
            _emit(on_progress, f"  → {passed} passed, {rejected} rejected",
                  phase="filtering", detail=f"{passed} passed, {rejected} rejected")

            if passed > 0:
                scored, matches = _score_filtered()
                total_scored += scored
                total_matches += matches
                if scored:
                    _emit(on_progress, f"  → {total_matches} matches so far",
                          phase="scoring", detail=f"{total_matches} matches so far",
                          matches=total_matches)
                _notify_jobs_ready()

        # Wait for LinkedIn background collection to finish
        if linkedin_collector:
            _check_cancel()
            _emit(on_progress, "Waiting for LinkedIn results…",
                  phase="collecting", detail=f"Waiting for LinkedIn… ({total_matches} matches so far)",
                  matches=total_matches)
            # Poll with timeout so we can check for cancellation
            while not linkedin_done.wait(timeout=2.0):
                _check_cancel()

            source_start = datetime.now().isoformat()
            if linkedin_result["error"]:
                errors.append(f"linkedin: {linkedin_result['error']}")
                _emit(on_progress, f"  → linkedin: failed ({linkedin_result['error']})",
                      phase="collecting", detail="LinkedIn: failed")
                _log_source_run(db, "linkedin", source_start, "failure", 0, linkedin_result["error"])
            else:
                li_jobs = linkedin_result["jobs"]
                for job in li_jobs:
                    upsert_job(db, job)
                jobs_collected += len(li_jobs)
                _emit(on_progress, f"  → linkedin: {len(li_jobs)} jobs",
                      phase="collecting", detail=f"LinkedIn: {len(li_jobs)} jobs",
                      collected=jobs_collected)
                _log_source_run(db, "linkedin", source_start, "success", len(li_jobs))

                if li_jobs:
                    # Filter → Fetch descriptions → Score → Save
                    passed, rejected = _filter_new_jobs()
                    _emit(on_progress, f"  → {passed} passed, {rejected} rejected",
                          phase="filtering", detail=f"{passed} passed, {rejected} rejected")

                    if passed > 0:
                        fetched = _fetch_descriptions()
                        if fetched:
                            _emit(on_progress, f"  → {fetched} descriptions fetched",
                                  phase="fetching", detail=f"{fetched} descriptions fetched")

                        scored, matches = _score_filtered()
                        total_scored += scored
                        total_matches += matches
                        if scored:
                            _emit(on_progress, f"  → {total_matches} matches total",
                                  phase="scoring", detail=f"{total_matches} matches total",
                                  matches=total_matches)
                        _notify_jobs_ready()

        _emit(on_progress, f"Collection done: {jobs_collected} jobs, {total_matches} matches",
              phase="collecting", detail=f"Found {total_matches} matches from {jobs_collected} jobs",
              collected=jobs_collected, matches=total_matches)
    else:
        _emit(on_progress, "Skipping collection (--no-collect)",
              phase="collecting", detail="Skipping collection")

    scored_count = db.execute("SELECT COUNT(*) FROM jobs WHERE status = 'scored'").fetchone()[0]

    # Step 4: Enrich companies + re-score
    _check_cancel()
    scored_jobs = db.execute(
        "SELECT * FROM jobs WHERE status = 'scored' AND enrichment IS NULL "
        "ORDER BY fit_score DESC LIMIT ?",
        (config.brief.top_n,),
    ).fetchall()

    if scored_jobs:
        _emit(on_progress, f"Enriching {len(scored_jobs)} companies...", phase="enriching", detail=f"Researching {len(scored_jobs)} companies…")

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
    companies_to_probe = db.execute(
        "SELECT id, name, domain FROM companies "
        "WHERE domain IS NOT NULL AND ats_platform IS NULL AND domain != ''"
    ).fetchall()

    if companies_to_probe:
        _emit(on_progress, f"Discovering career pages for {len(companies_to_probe)} companies...", phase="enriching", detail=f"Discovering career pages…")

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
    _check_cancel()
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
        _emit(on_progress, f"Tailoring resumes for {len(tailor_inputs)} top matches (parallel, 10 workers)...", phase="tailoring", detail=f"Tailoring {len(tailor_inputs)} resumes…")
        results = tailor_jobs_parallel(
            tailor_inputs, config, project_root, drafts_dir, today,
            max_workers=10,
        )
        tailored_count = 0
        for job_id, tailored, output_path in results:
            if tailored and output_path:
                db.execute(
                    "UPDATE jobs SET tailored_resume_path = ? WHERE id = ?",
                    (str(output_path), job_id),
                )
                llm_calls += 2  # select + tailor
                tailored_count += 1
        _emit(on_progress, f"  → {tailored_count} resumes tailored", phase="tailoring", detail=f"{tailored_count} resumes tailored")

    db.commit()

    # Step 6: Generate brief
    _emit(on_progress, "Generating brief...", phase="finishing", detail="Generating brief…")
    briefs_dir = project_root / config.brief.output_dir
    brief_path = generate_brief(db, briefs_dir)
    _emit(on_progress, f"  → {brief_path}", phase="finishing", detail="Brief generated")

    # Log run
    db.execute(
        "INSERT INTO run_logs (started_at, finished_at, jobs_collected, jobs_filtered, "
        "jobs_scored, llm_calls, brief_path, errors) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_start, datetime.now().isoformat(), jobs_collected, jobs_filtered,
            total_scored, llm_calls, str(brief_path),
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
    collectors = _get_collectors(config=config, db=db)
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


def _get_collectors(config: Config | None = None, db: sqlite3.Connection | None = None) -> dict:
    """Get all enabled collectors."""
    collectors = {
        "hn": HNCollector(),
    }

    # LinkedIn: build searches from config track queries
    if config and config.tracks:
        from shortlist.collectors.linkedin import searches_from_config
        searches = searches_from_config(config)
        collectors["linkedin"] = LinkedInCollector(searches=searches, time_filter="r604800")
    else:
        collectors["linkedin"] = LinkedInCollector(time_filter="r604800")

    collectors["nextplay"] = NextPlayCollector(db=db)

    return collectors


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
