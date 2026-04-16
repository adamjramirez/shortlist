"""Pipeline orchestrator — collect → filter → score → brief."""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from shortlist.collectors.base import RawJob
from shortlist.collectors.hn import HNCollector
from shortlist.collectors.linkedin import LinkedInCollector
from shortlist.collectors.nextplay import NextPlayCollector
from shortlist.config import Config, SCORE_SAVED, SCORE_VISIBLE
from shortlist import llm
from shortlist.db import init_db, get_db, upsert_job
from shortlist.processors.filter import apply_hard_filters
from shortlist.processors.scorer import score_job, score_jobs_parallel, ScoreResult
from shortlist.processors.title_gate import gate_titles
from shortlist.processors.enricher import (
    get_cached_enrichment, enrich_company, cache_enrichment,
    rescore_with_enrichment, CompanyIntel, generate_interest_note,
)
from shortlist.collectors.career_page import discover_ats_from_domain, FETCHERS
from shortlist.processors.resume import tailor_jobs_parallel
from shortlist.brief import generate_brief

logger = logging.getLogger(__name__)

# Max companies to probe for ATS career pages per pipeline run.
# Probed companies are marked ats_platform='none' so they're never re-probed.
# Capped to prevent a large first-run from spiking RAM.
PROBE_LIMIT_PER_RUN = 20


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
    total_matches = 0       # >= SCORE_SAVED (stored as "scored" in DB)
    visible_matches = 0     # >= SCORE_VISIBLE (shown to user)
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
        """Score all filtered jobs up to max_jobs limit. Returns (scored, matches, visible)."""
        _check_cancel()
        nonlocal llm_calls, jobs_scored_so_far
        remaining = max_jobs - jobs_scored_so_far
        if remaining <= 0:
            return 0, 0, 0

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

        score_results = score_jobs_parallel(score_inputs, config, max_workers=2, on_scored=_on_scored, cancel_event=cancel_event)
        _check_cancel()

        matches = 0
        visible = 0
        for row_id, score_result in score_results:
            if score_result:
                llm_calls += 1
                status = "scored" if score_result.fit_score >= SCORE_SAVED else "low_score"
                if score_result.fit_score >= SCORE_SAVED:
                    matches += 1
                if score_result.fit_score >= SCORE_VISIBLE:
                    visible += 1
                # Apply LLM-corrected title/company/location if provided
                updates = {
                    "status": status,
                    "fit_score": score_result.fit_score,
                    "matched_track": score_result.matched_track,
                    "score_reasoning": score_result.reasoning,
                    "yellow_flags": json.dumps(score_result.yellow_flags),
                    "salary_estimate": score_result.salary_estimate,
                    "salary_confidence": score_result.salary_confidence,
                    "salary_basis": score_result.salary_basis,
                }
                if score_result.corrected_title:
                    updates["title"] = score_result.corrected_title
                if score_result.corrected_company:
                    updates["company"] = score_result.corrected_company
                if score_result.corrected_location:
                    updates["location"] = score_result.corrected_location

                set_clause = ", ".join(f"{k} = ?" for k in updates)
                db.execute(
                    f"UPDATE jobs SET {set_clause} WHERE id = ?",
                    (*updates.values(), row_id),
                )
            else:
                logger.warning(f"Failed to score job {row_id}")
        db.commit()

        jobs_scored_so_far += len(score_inputs)
        return len(score_inputs), matches, visible

    def _notify_jobs_ready():
        """Tell the worker to copy newly scored jobs to PostgreSQL now."""
        if on_jobs_ready:
            on_jobs_ready(db)

    # === Main pipeline: process sources with LinkedIn in background ===

    if not skip_collect:
        collectors = _get_collectors(config=config, db=db)
        import threading
        import queue

        # Per-source progress tracking
        source_progress = {name: {"status": "searching"} for name in collectors}

        def _emit_sources(**extra):
            """Emit progress with per-source state."""
            _emit(on_progress, "", phase="pipeline",
                  sources=dict(source_progress), matches=visible_matches, **extra)

        # Queue for completed collections: (name, jobs_list, source_start, needs_descriptions)
        results_queue: queue.Queue = queue.Queue()

        def _collect_source(name, collector):
            """Collect jobs in a background thread, put results on queue."""
            source_start = datetime.now().isoformat()
            try:
                logger.info(f"Collecting from {name}...")
                jobs = collector.fetch_new()
                results_queue.put((name, jobs, source_start, name == "linkedin"))
            except Exception as e:
                results_queue.put((name, e, source_start, False))

        # Launch ALL sources in parallel threads
        threads = []
        for name, collector in collectors.items():
            t = threading.Thread(target=_collect_source, args=(name, collector), daemon=True)
            t.start()
            threads.append(t)
        _emit_sources(detail="Searching all sources…")

        def _process_collected(name, jobs_list, source_start, needs_descriptions):
            """Filter → (fetch descriptions) → Score → Save. Runs on main thread (SQLite safe)."""
            nonlocal jobs_collected, total_scored, total_matches, visible_matches

            for job in jobs_list:
                upsert_job(db, job)
            jobs_collected += len(jobs_list)
            _log_source_run(db, name, source_start, "success", len(jobs_list))

            if not jobs_list:
                source_progress[name]["status"] = "done"
                source_progress[name].update({"collected": 0, "matches": 0})
                _emit_sources(detail=f"{name}: no jobs found")
                return

            source_progress[name]["status"] = "filtering"
            source_progress[name]["collected"] = len(jobs_list)
            _emit_sources(detail=f"Filtering {name} jobs…")

            passed, rejected = _filter_new_jobs()
            source_progress[name]["filtered"] = passed
            source_progress[name]["rejected"] = rejected

            if passed > 0:
                if needs_descriptions:
                    source_progress[name]["status"] = "fetching"
                    _emit_sources(detail=f"Fetching {passed} job descriptions…")
                    _fetch_descriptions()

                source_progress[name]["status"] = "scoring"
                _emit_sources(detail=f"Scoring {name} jobs…")

                scored, matches, vis = _score_filtered()
                total_scored += scored
                total_matches += matches
                visible_matches += vis
                source_progress[name]["matches"] = vis
                source_progress[name]["scored"] = scored
            else:
                source_progress[name]["matches"] = 0

            source_progress[name]["status"] = "done"
            _emit_sources(detail=f"{name} complete — {source_progress[name]['matches']} matches")
            _notify_jobs_ready()

        # Process results as they arrive (main thread — SQLite is single-threaded)
        sources_remaining = len(collectors)
        while sources_remaining > 0:
            _check_cancel()
            try:
                name, result, source_start, needs_desc = results_queue.get(timeout=2.0)
            except queue.Empty:
                continue

            sources_remaining -= 1

            if isinstance(result, Exception):
                errors.append(f"{name}: {str(result)}")
                source_progress[name]["status"] = "failed"
                source_progress[name]["error"] = str(result)[:100]
                _emit_sources(detail=f"{name} failed")
                _log_source_run(db, name, source_start, "failure", 0, str(result))
            else:
                _process_collected(name, result, source_start, needs_desc)
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
                new_status = "scored" if new_score >= SCORE_SAVED else "low_score"
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
        "WHERE domain IS NOT NULL AND ats_platform IS NULL AND domain != '' "
        f"LIMIT {PROBE_LIMIT_PER_RUN}"
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
            max_workers=3,
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


# Sources that get a known-URL pre-filter before upserting.
# LinkedIn uses f_TPR to limit fetch volume; HN is low-traffic — both bypass.
_PREFILTER_SOURCES = {"nextplay"}


def _split_known_new(conn, user_id: int, name: str, jobs: list) -> tuple[list, list]:
    """Split a job list into (known_urls, new_jobs) for sources that benefit from pre-filtering.

    Returns:
        known_urls: list of URL strings already in the DB (need last_seen bump only)
        new_jobs:   list of RawJob objects not yet in DB (go through full pipeline)
    """
    from shortlist import pgdb
    if name not in _PREFILTER_SOURCES:
        return [], list(jobs)

    checkable = [j.url for j in jobs if j.url]
    existing = pgdb.get_existing_urls(conn, user_id, checkable)
    known_urls = [j.url for j in jobs if j.url and j.url in existing]
    new_jobs = [j for j in jobs if not j.url or j.url not in existing]
    return known_urls, new_jobs


def run_pipeline_pg(
    config: Config,
    db_url: str,
    user_id: int,
    on_progress: callable = None,
    cancel_event: "threading.Event | None" = None,
    run_id: int | None = None,
) -> dict:
    """Run the full pipeline writing directly to PostgreSQL.

    Returns dict with run stats: {jobs_collected, total_scored, visible_matches, errors}.
    """
    from shortlist import pgdb
    from shortlist.collectors.linkedin import fetch_description_for_url
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import queue

    _ensure_llm(config)
    run_started_at = datetime.now(timezone.utc)
    conn = pgdb.get_pg_connection(db_url)
    pgdb.ensure_nextplay_cache_table(conn)
    pgdb.ensure_career_page_sources_table(conn)

    # Drain any jobs stuck in 'new' from previous failed/cancelled runs
    _orphan_new = pgdb.fetch_jobs(conn, user_id, "new")
    if _orphan_new:
        logger.info(f"Draining {len(_orphan_new)} orphaned 'new' jobs from prior runs")
        _orphan_passed = 0
        _orphan_rejected = 0
        for _row in _orphan_new:
            _result = apply_hard_filters(_row_to_raw_job(_row), config)
            if _result.passed:
                pgdb.update_job(conn, _row["id"], status="filtered")
                _orphan_passed += 1
            else:
                pgdb.update_job(conn, _row["id"], status="rejected", reject_reason=_result.reason)
                _orphan_rejected += 1
        conn.commit()
        logger.info(f"Orphan drain: {_orphan_passed} filtered, {_orphan_rejected} rejected")

    # Surface HTTP 429s / backoff to the UI via on_progress
    from shortlist import http as _http
    def _http_status(msg):
        _emit(on_progress, msg, phase="pipeline", http_status=msg)
    _http.set_status_callback(_http_status)

    def _check_cancel():
        if cancel_event and cancel_event.is_set():
            raise CancelledError("Run cancelled by user")

    errors = []
    jobs_collected = 0
    llm_calls = 0
    total_scored = 0
    total_matches = 0
    visible_matches = 0
    max_jobs = config.llm.max_jobs_per_run
    jobs_scored_so_far = 0

    def _filter_new_jobs():
        nonlocal jobs_collected
        new_jobs = pgdb.fetch_jobs(conn, user_id, "new")
        rejected = 0
        for row in new_jobs:
            job = _row_to_raw_job(row)
            result = apply_hard_filters(job, config)
            if result.passed:
                pgdb.update_job(conn, row["id"], status="filtered")
            else:
                pgdb.update_job(conn, row["id"], status="rejected", reject_reason=result.reason)
                rejected += 1
        conn.commit()
        return len(new_jobs) - rejected, rejected

    def _fetch_descriptions(on_fetch_progress=None):
        needs_desc = pgdb.fetch_jobs(
            conn, user_id, "filtered",
            extra_where="AND sources_seen::text LIKE '%%linkedin%%' AND length(description) < 200",
        )
        if not needs_desc:
            return 0

        total = len(needs_desc)

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
                        pgdb.update_job(conn, row_id, description=desc)
                        fetched += 1
                except Exception as e:
                    logger.warning(f"Failed to fetch description: {e}")
                if on_fetch_progress:
                    on_fetch_progress(fetched, total)
        conn.commit()
        return fetched

    _sources_scored = 0

    def _score_filtered(budget_override: int | None = None):
        """Score filtered jobs. Returns (scored, matches, visible).

        When called from a source: reserves budget across remaining sources.
        When called with budget_override (backlog pass): uses that budget directly.
        """
        _check_cancel()
        nonlocal llm_calls, jobs_scored_so_far, _sources_scored
        remaining = max_jobs - jobs_scored_so_far
        if remaining <= 0:
            return 0, 0, 0

        if budget_override is not None:
            per_source_budget = min(budget_override, remaining)
        else:
            # Reserve budget for sources that haven't scored yet
            sources_left = max(len(collectors) - _sources_scored, 1)
            per_source_budget = max(remaining // sources_left, 20)
            _sources_scored += 1

        filtered_jobs = pgdb.fetch_jobs(
            conn, user_id, "filtered",
            order="first_seen DESC", limit=per_source_budget,
        )

        # Pre-score title gate — cheap batch LLM prune before expensive per-job scoring
        if config.llm.title_gate_enabled and filtered_jobs:
            pre_gate = [(row["id"], _row_to_raw_job(row)) for row in filtered_jobs]
            decisions, gate_batch_count = gate_titles(pre_gate, config)
            llm_calls += gate_batch_count
            kept_rows = []
            title_rejected = 0
            for row in filtered_jobs:
                passed, reason = decisions.get(row["id"], (True, ""))
                if passed:
                    kept_rows.append(row)
                else:
                    pgdb.update_job(conn, row["id"], status="title_rejected",
                                    reject_reason=(reason or "title_gate")[:200])
                    title_rejected += 1
            if title_rejected:
                conn.commit()
            logger.info(f"Title gate: {len(kept_rows)}/{len(filtered_jobs)} passed, {title_rejected} rejected ({gate_batch_count} batch calls)")
            filtered_jobs = kept_rows

        score_inputs = [(row["id"], _row_to_raw_job(row)) for row in filtered_jobs]
        if not score_inputs:
            return 0, 0, 0

        _emit(on_progress, f"Scoring {len(score_inputs)} jobs…",
              phase="scoring", detail=f"Scoring {len(score_inputs)} jobs…",
              scored=jobs_scored_so_far, total=jobs_scored_so_far + len(score_inputs))

        def _on_scored(done, total):
            _emit(on_progress, f"  Scored {done}/{total}", phase="scoring",
                  detail=f"Scoring jobs…",
                  scored=jobs_scored_so_far + done,
                  total=jobs_scored_so_far + total)

        score_results = score_jobs_parallel(
            score_inputs, config, max_workers=4,
            on_scored=_on_scored, cancel_event=cancel_event,
        )
        _check_cancel()

        matches = 0
        visible = 0
        # Batch updates
        for row_id, score_result in score_results:
            if score_result:
                llm_calls += 1
                status = "scored" if score_result.fit_score >= SCORE_SAVED else "low_score"
                if score_result.fit_score >= SCORE_SAVED:
                    matches += 1
                if score_result.fit_score >= SCORE_VISIBLE:
                    visible += 1

                updates = {
                    "status": status,
                    "fit_score": score_result.fit_score,
                    "matched_track": score_result.matched_track,
                    "score_reasoning": score_result.reasoning,
                    "yellow_flags": json.dumps(score_result.yellow_flags),
                    "salary_estimate": score_result.salary_estimate,
                    "salary_confidence": score_result.salary_confidence,
                    "salary_basis": score_result.salary_basis,
                }
                if run_id is not None:
                    updates["run_id"] = run_id
                    updates["viewed_at"] = None  # re-scored = unread
                if score_result.corrected_title:
                    updates["title"] = score_result.corrected_title
                if score_result.corrected_company:
                    updates["company"] = score_result.corrected_company
                if score_result.corrected_location:
                    updates["location"] = score_result.corrected_location
                if score_result.prestige_tier:
                    updates["prestige_tier"] = score_result.prestige_tier

                pgdb.update_job(conn, row_id, **updates)
            else:
                logger.warning(f"Failed to score job {row_id}")
        conn.commit()

        jobs_scored_so_far += len(score_inputs)
        return len(score_inputs), matches, visible

    def _enrich_scored_jobs():
        """Enrich all scored jobs that don't have enrichment yet."""
        nonlocal llm_calls
        unenriched = pgdb.fetch_jobs(
            conn, user_id, "scored",
            extra_where="AND enrichment IS NULL",
            order="fit_score DESC", limit=config.brief.top_n,
        )
        for i, row in enumerate(unenriched, 1):
            _check_cancel()
            company = row["company"]
            _emit(on_progress, f"Researching {company}…",
                  phase="enriching",
                  detail=f"Researching {company} ({i}/{len(unenriched)})…")
            try:
                intel = pgdb.get_cached_enrichment(conn, user_id, company)
                if not intel:
                    intel = enrich_company(company, row["description"] or "")
                    if intel:
                        pgdb.cache_enrichment(conn, user_id, company, intel)
                        llm_calls += 1

                if intel:
                    updates = {
                        "enrichment": intel.to_json(),
                        "enriched_at": datetime.now().isoformat(),
                    }
                    # Look up direct ATS careers page from NextPlay cache
                    if intel.website_domain and not row.get("career_page_url"):
                        ats_url = pgdb.get_career_url_for_domain(conn, intel.website_domain)
                        if ats_url:
                            updates["career_page_url"] = ats_url
                    pgdb.update_job(conn, row["id"], **updates)

                    rescore = rescore_with_enrichment(
                        row["fit_score"], row["score_reasoning"] or "",
                        row["yellow_flags"] or "[]", intel, config,
                    )
                    if rescore:
                        new_score, delta, reason = rescore
                        llm_calls += 1
                        new_status = "scored" if new_score >= SCORE_SAVED else "low_score"
                        pgdb.update_job(conn, row["id"],
                                        fit_score=new_score, status=new_status,
                                        score_reasoning=f"{row['score_reasoning']} [Re-scored: {reason}]")
                        logger.info(f"Re-scored {company}/{row['title']}: {row['fit_score']} → {new_score} ({delta:+d})")
            except Exception as e:
                logger.error("Enrichment failed for job %s (%s): %s", row["id"], company, e)
        conn.commit()

        # Generate interest notes for scored jobs that don't have one yet
        needs_notes = pgdb.fetch_jobs(
            conn, user_id, "scored",
            extra_where="AND interest_note IS NULL AND fit_score >= %s",
            extra_params=[SCORE_VISIBLE],
            order="fit_score DESC", limit=config.brief.top_n,
        )
        for i, row in enumerate(needs_notes, 1):
            _check_cancel()
            _emit(on_progress, f"Writing pitch for {row['company']}…",
                  phase="enriching",
                  detail=f"Writing pitch ({i}/{len(needs_notes)})…")
            try:
                intel_json = row.get("enrichment")
                intel = CompanyIntel.from_json(row["company"], intel_json) if intel_json else None
                note = generate_interest_note(
                    row["company"], row["title"], row["description"] or "",
                    config.fit_context, intel,
                )
                if note:
                    pgdb.update_job(conn, row["id"], interest_note=note)
                    llm_calls += 1
            except Exception as e:
                logger.error("Interest note failed for job %s (%s): %s", row["id"], row["company"], e)
        conn.commit()

    # === Collect from all sources in parallel ===
    # Use 24h filter for recurring runs; week filter for first run to populate inbox.
    try:
        with conn.cursor() as _cur:
            _cur.execute(
                "SELECT COUNT(*) as n FROM jobs "
                "WHERE user_id = %s AND status IN ('scored', 'low_score')",
                (user_id,),
            )
            _row = _cur.fetchone()
            _has_prior_jobs = int(_row["n"]) > 0 if _row else False
    except Exception:
        _has_prior_jobs = False  # Safe default: use first-run (week) filter
    li_time_filter = "r86400" if _has_prior_jobs else "r604800"
    run_type = "recurring" if _has_prior_jobs else "first run"
    logger.info(f"LinkedIn time filter: {li_time_filter} ({run_type})")

    collectors = _get_collectors(config=config, db=None, pg_db_url=db_url,
                                 li_time_filter=li_time_filter)
    source_timers: dict[str, float] = {}  # name → start time (monotonic)
    source_final_elapsed: dict[str, int] = {}  # name → frozen elapsed when done
    source_progress = {name: {"status": "searching"} for name in collectors}

    def _source_start_timer(name):
        import time as _time
        source_timers[name] = _time.monotonic()

    def _source_elapsed(name) -> int:
        if name in source_final_elapsed:
            return source_final_elapsed[name]
        import time as _time
        start = source_timers.get(name)
        if start is None:
            return 0
        return int(_time.monotonic() - start)

    def _source_freeze_timer(name):
        source_final_elapsed[name] = _source_elapsed(name)

    def _emit_sources(**extra):
        # Attach per-source elapsed times
        for name in source_progress:
            source_progress[name]["elapsed"] = _source_elapsed(name)
        _emit(on_progress, "", phase="pipeline",
              sources=dict(source_progress), matches=visible_matches, **extra)

    # Wire NextPlay progress to source_progress
    if "nextplay" in collectors:
        def _nextplay_progress(msg):
            source_progress["nextplay"]["substatus"] = msg
            _emit_sources(detail=msg)
        collectors["nextplay"].on_progress = _nextplay_progress

    results_queue: queue.Queue = queue.Queue()

    def _collect_source(name, collector):
        _source_start_timer(name)
        source_start = datetime.now().isoformat()
        try:
            logger.info(f"Collecting from {name}...")
            jobs = collector.fetch_new()
            results_queue.put((name, jobs, source_start, name == "linkedin"))
        except Exception as e:
            results_queue.put((name, e, source_start, False))

    threads = []
    for name, collector in collectors.items():
        t = threading.Thread(target=_collect_source, args=(name, collector), daemon=True)
        t.start()
        threads.append(t)
    _emit_sources(detail="Searching all sources…")

    def _process_collected(name, jobs_list, source_start, needs_descriptions):
        nonlocal jobs_collected, total_scored, total_matches, visible_matches

        known_urls, new_jobs = _split_known_new(conn, user_id, name, jobs_list)
        if known_urls:
            pgdb.bulk_update_last_seen(conn, user_id, known_urls)
        for job in new_jobs:
            pgdb.upsert_job(conn, user_id, job)
        jobs_collected += len(new_jobs)
        if known_urls:
            logger.info(
                f"{name}: {len(new_jobs)} new, {len(known_urls)} already known "
                f"(last_seen updated)"
            )
        pgdb.log_source_run(conn, user_id, name, source_start, "success", len(new_jobs))

        if not jobs_list:
            _source_freeze_timer(name)
            source_progress[name].update({"status": "done", "collected": 0, "matches": 0})
            _emit_sources(detail=f"{name}: no jobs found")
            return

        source_progress[name].update({"status": "filtering", "collected": len(jobs_list)})
        _emit_sources(detail=f"Filtering {name} jobs…")

        passed, rejected = _filter_new_jobs()
        source_progress[name].update({"filtered": passed, "rejected": rejected})

        if passed > 0:
            if needs_descriptions:
                source_progress[name]["status"] = "fetching"
                _emit_sources(detail=f"Fetching job descriptions…")

                def _on_fetch(done, total, _name=name):
                    source_progress[_name]["fetch_progress"] = f"{done}/{total}"
                    _emit_sources(detail=f"Fetching descriptions ({done}/{total})…")

                _fetch_descriptions(on_fetch_progress=_on_fetch)

            source_progress[name]["status"] = "scoring"
            _emit_sources(detail=f"Scoring {name} jobs…")

            scored, matches, vis = _score_filtered()
            total_scored += scored
            total_matches += matches
            visible_matches += vis
            source_progress[name].update({"matches": vis, "scored": scored})

            # Enrich immediately so cards show company intel
            if vis > 0:
                source_progress[name]["status"] = "enriching"
                _emit_sources(detail=f"Researching {name} companies…")
                _enrich_scored_jobs()
        else:
            source_progress[name]["matches"] = 0

        _source_freeze_timer(name)
        source_progress[name]["status"] = "done"
        _emit_sources(detail=f"{name} complete — {source_progress[name]['matches']} matches")

    # Process results as they arrive
    sources_remaining = len(collectors)
    while sources_remaining > 0:
        _check_cancel()
        try:
            name, result, source_start, needs_desc = results_queue.get(timeout=2.0)
        except queue.Empty:
            continue

        sources_remaining -= 1

        if isinstance(result, Exception):
            _source_freeze_timer(name)
            errors.append(f"{name}: {str(result)}")
            source_progress[name].update({"status": "failed", "error": str(result)[:100]})
            _emit_sources(detail=f"{name} failed")
            pgdb.log_source_run(conn, user_id, name, source_start, "failure", 0, str(result))
        else:
            _process_collected(name, result, source_start, needs_desc)

    # === Curated career page sources ===
    from shortlist.collectors.curated import CuratedSourcesCollector
    curated_sources = pgdb.get_active_career_page_sources(conn)
    if curated_sources:
        _emit(on_progress, f"Fetching {len(curated_sources)} curated sources…",
              phase="searching", detail=f"Fetching curated sources…")

        def _on_curated_fetched(career_url, jobs, error):
            pgdb.update_career_page_source_after_fetch(
                conn, career_url=career_url, jobs_found=len(jobs), fetch_error=error
            )
            for job in jobs:
                pgdb.upsert_job(conn, user_id, job)

        curated_collector = CuratedSourcesCollector(
            curated_sources, on_fetched=_on_curated_fetched
        )
        curated_jobs = curated_collector.fetch_new()
        if curated_jobs:
            jobs_collected += len(curated_jobs)
            logger.info(f"Curated sources: {len(curated_jobs)} jobs collected")
            passed, rejected = _filter_new_jobs()
            logger.info(f"Curated sources: {passed} passed filters, {rejected} rejected")
        conn.commit()

    # === Score remaining filtered backlog ===
    # Sources only score when they produce new filtered jobs (passed > 0).
    # Jobs filtered by the orphan drain or prior runs stay in 'filtered' forever
    # unless we explicitly score them here.
    _backlog = pgdb.fetch_jobs(conn, user_id, "filtered", limit=1)
    if _backlog and jobs_scored_so_far < max_jobs:
        _remaining = max_jobs - jobs_scored_so_far
        logger.info(f"Scoring backlog: {_remaining} budget remaining, fetching filtered jobs")
        _emit(on_progress, f"Scoring backlog…", phase="scoring", detail=f"Scoring backlog…")
        scored, matches, vis = _score_filtered(budget_override=_remaining)
        total_scored += scored
        total_matches += matches
        visible_matches += vis
        if vis > 0:
            _emit(on_progress, f"Backlog: {vis} new matches",
                  phase="scoring", detail=f"Backlog: {vis} new matches")
        logger.info(f"Backlog scoring: {scored} scored, {vis} new matches")

    # === Discover career pages ===
    companies_to_probe = pgdb.fetch_companies(
        conn, user_id,
        extra_where=f"AND domain IS NOT NULL AND (ats_platform IS NULL) AND domain != '' LIMIT {PROBE_LIMIT_PER_RUN}",
    )

    if companies_to_probe:
        _emit(on_progress, f"Discovering career pages...",
              phase="enriching", detail=f"Discovering career pages…")

    for company_row in companies_to_probe:
        domain = company_row["domain"]
        try:
            ats, slug = discover_ats_from_domain(domain)
            if ats and slug:
                pgdb.update_company(conn, company_row["id"],
                                    ats_platform=ats,
                                    career_page_url=f"https://jobs.{'ashbyhq.com' if ats == 'ashby' else 'boards-api.greenhouse.io' if ats == 'greenhouse' else 'api.lever.co'}/{slug}")
                fetcher = FETCHERS.get(ats)
                if fetcher:
                    new_jobs = fetcher(slug, company_name=company_row["name"])
                    for job in new_jobs:
                        pgdb.upsert_job(conn, user_id, job)
                    if new_jobs:
                        jobs_collected += len(new_jobs)
                        logger.info(f"Company discovery: {company_row['name']} → {ats}/{slug} → {len(new_jobs)} jobs")
            else:
                pgdb.update_company(conn, company_row["id"], ats_platform="none")
        except Exception as e:
            logger.warning(f"Career page discovery failed for {company_row['name']}: {e}")
    conn.commit()

    # === Mark stale/expired jobs ===
    closed_count = pgdb.mark_stale_jobs(conn, user_id, run_started_at)
    if closed_count:
        logger.info(f"Marked {closed_count} stale jobs as closed")
        _emit(on_progress, f"Closed {closed_count} expired listings",
              phase="done", detail=f"Closed {closed_count} expired listings")
    conn.commit()

    _emit(on_progress, "Done", phase="done",
          detail=f"Complete — {visible_matches} matches",
          matches=visible_matches)

    conn.close()

    return {
        "jobs_collected": jobs_collected,
        "total_scored": total_scored,
        "visible_matches": visible_matches,
        "closed_count": closed_count,
        "errors": errors,
    }


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


def _get_collectors(config: Config | None = None, db: sqlite3.Connection | None = None,
                    pg_db_url: str | None = None,
                    li_time_filter: str = "r86400") -> dict:
    """Get all enabled collectors.

    li_time_filter: LinkedIn f_TPR value. Use 'r86400' (24h) for recurring runs
    and 'r604800' (1 week) for a user's first run to populate their initial inbox.
    """
    collectors = {
        "hn": HNCollector(),
    }

    # LinkedIn: build searches from config track queries, use user's country
    linkedin_location = "United States"
    if config and config.filters.location.country:
        linkedin_location = config.filters.location.country

    if config and config.tracks:
        from shortlist.collectors.linkedin import searches_from_config
        searches = searches_from_config(config)
        collectors["linkedin"] = LinkedInCollector(
            searches=searches, time_filter=li_time_filter, location=linkedin_location,
        )
    else:
        collectors["linkedin"] = LinkedInCollector(
            time_filter=li_time_filter, location=linkedin_location,
        )

    from shortlist.collectors.nextplay import _is_leadership_role
    collectors["nextplay"] = NextPlayCollector(
        db=db, pg_db_url=pg_db_url,
        title_filter=_is_leadership_role,
    )

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
