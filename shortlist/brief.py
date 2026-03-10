"""Daily markdown brief generator."""
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from shortlist.processors.enricher import is_job_board


TOP_MATCH_THRESHOLD = 80
WORTH_A_LOOK_THRESHOLD = 60
STALE_DAYS = 7


@dataclass
class BriefData:
    """Collected data for rendering a brief."""
    top_matches: list[dict] = field(default_factory=list)
    worth_a_look: list[dict] = field(default_factory=list)
    filtered_out: list[dict] = field(default_factory=list)
    tracker: list[dict] = field(default_factory=list)
    source_health: list[dict] = field(default_factory=list)
    total_collected: int = 0
    total_filtered: int = 0
    total_scored: int = 0

    @classmethod
    def from_db(cls, db: sqlite3.Connection) -> "BriefData":
        data = cls()

        # Counts
        data.total_collected = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        data.total_filtered = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'rejected'"
        ).fetchone()[0]
        data.total_scored = db.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('scored', 'low_score')"
        ).fetchone()[0]

        # Top matches: scored with high fit
        rows = db.execute(
            "SELECT * FROM jobs WHERE status IN ('scored', 'applied', 'interviewing') "
            "AND fit_score >= ? ORDER BY fit_score DESC",
            (TOP_MATCH_THRESHOLD,),
        ).fetchall()
        data.top_matches = _dedup_jobs([dict(r) for r in rows])

        # Worth a look: scored but lower fit
        rows = db.execute(
            "SELECT * FROM jobs WHERE status IN ('scored') "
            "AND fit_score >= ? AND fit_score < ? ORDER BY fit_score DESC",
            (WORTH_A_LOOK_THRESHOLD, TOP_MATCH_THRESHOLD),
        ).fetchall()
        data.worth_a_look = _dedup_jobs([dict(r) for r in rows])

        # Filtered out
        rows = db.execute(
            "SELECT * FROM jobs WHERE status = 'rejected' ORDER BY first_seen DESC"
        ).fetchall()
        data.filtered_out = [dict(r) for r in rows]

        # Tracker: scored, applied, interviewing only (not 'filtered' or 'low_score')
        rows = db.execute(
            "SELECT * FROM jobs WHERE status IN ('scored', 'applied', 'interviewing') "
            "ORDER BY fit_score DESC NULLS LAST"
        ).fetchall()
        data.tracker = [dict(r) for r in rows]

        # Source health
        rows = db.execute(
            "SELECT s.name, sr.status, sr.finished_at, sr.jobs_found "
            "FROM sources s LEFT JOIN source_runs sr ON s.id = sr.source_id "
            "ORDER BY sr.finished_at DESC"
        ).fetchall()
        data.source_health = [dict(r) for r in rows]

        return data


def _normalize_title(title: str) -> str:
    """Normalize a title for dedup comparison."""
    t = title.lower().strip()
    # Remove parenthetical location/team qualifiers
    t = re.sub(r'\s*\(.*?\)\s*', ' ', t)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _desc_overlap(desc1: str, desc2: str, min_word_len: int = 6) -> float:
    """Compute word overlap ratio between two descriptions."""
    words1 = set(w.lower() for w in (desc1 or "").split() if len(w) >= min_word_len)
    words2 = set(w.lower() for w in (desc2 or "").split() if len(w) >= min_word_len)
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / min(len(words1), len(words2))


def _dedup_jobs(jobs: list[dict]) -> list[dict]:
    """Deduplicate jobs by company + similar title, and recruiter vs direct.

    Pass 1: Merge same-company, same-title listings (LinkedIn vs Greenhouse).
    Pass 2: Merge recruiter listings that match a direct listing (>50% desc overlap).

    Keeps the highest-scored version. Stores alternate URLs on the winner.
    """
    seen: dict[str, dict] = {}  # key → best job dict

    # Pass 1: same company + title
    for job in jobs:
        company = (job.get("company") or "").lower()
        norm_title = _normalize_title(job.get("title") or "")
        key = f"{company}|{norm_title}"

        if key not in seen:
            job["alt_urls"] = []
            job["is_recruiter"] = is_job_board(job.get("company") or "")
            seen[key] = job
        else:
            existing = seen[key]
            alt_url = job.get("url", "")
            alt_source = job.get("sources_seen", "")

            if (job.get("fit_score") or 0) > (existing.get("fit_score") or 0):
                job["alt_urls"] = existing.get("alt_urls", [])
                job["is_recruiter"] = is_job_board(job.get("company") or "")
                if existing.get("url"):
                    job["alt_urls"].append((existing["url"], existing.get("sources_seen", "")))
                seen[key] = job
            else:
                if alt_url:
                    existing.setdefault("alt_urls", []).append((alt_url, alt_source))

    # Pass 2: merge recruiter listings into direct listings by description similarity
    result = list(seen.values())
    direct = [j for j in result if not j.get("is_recruiter")]
    recruiter = [j for j in result if j.get("is_recruiter")]
    merged_ids = set()

    for rj in recruiter:
        for dj in direct:
            overlap = _desc_overlap(rj.get("description", ""), dj.get("description", ""))
            if overlap > 0.50:
                # Same job — merge recruiter as alt on the direct listing
                dj.setdefault("alt_urls", []).append(
                    (rj.get("url", ""), rj.get("company", ""))
                )
                merged_ids.add(id(rj))
                break

    return [j for j in result if id(j) not in merged_ids]


def _job_marker(job: dict) -> str:
    """Return the appropriate marker emoji for a job."""
    brief_count = job.get("brief_count") or 0
    first_briefed = job.get("first_briefed")

    if brief_count == 0:
        return "🆕"

    if first_briefed:
        try:
            first_date = date.fromisoformat(str(first_briefed))
            if (date.today() - first_date).days >= STALE_DAYS:
                return "⏰"
        except (ValueError, TypeError):
            pass

    return "👁️"


def _render_top_match(job: dict, rank: int) -> str:
    """Render a single top match entry."""
    marker = _job_marker(job)
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    score = job.get("fit_score", "?")
    location = job.get("location") or "Unknown"
    track = job.get("matched_track") or ""
    salary = job.get("salary_estimate") or job.get("salary_text") or ""
    reasoning = job.get("score_reasoning") or ""
    url = job.get("url") or ""
    yellow_flags = job.get("yellow_flags") or ""

    recruiter_tag = " 🔍" if job.get("is_recruiter") else ""
    lines = [
        f"### {rank}. {marker} {title} — {company}{recruiter_tag}",
        f"**Score: {score}** | {location}" + (f" | {salary}" if salary else ""),
    ]
    if reasoning:
        lines.append(f"\n**Why it fits:** {reasoning}")
    if yellow_flags and yellow_flags != "[]":
        lines.append(f"\n**Yellow flags:** {yellow_flags}")
    if url:
        alt_urls = job.get("alt_urls") or []
        if alt_urls:
            links = [f"[Apply]({url})"]
            for alt_url, alt_src in alt_urls:
                src_label = ""
                if "linkedin" in alt_url:
                    src_label = "LinkedIn"
                elif "greenhouse" in alt_url:
                    src_label = "Greenhouse"
                elif "lever" in alt_url:
                    src_label = "Lever"
                elif "ashby" in alt_url:
                    src_label = "Ashby"
                else:
                    src_label = "Alt"
                links.append(f"[{src_label}]({alt_url})")
            lines.append(f"\n**Action:** {' · '.join(links)}")
        else:
            lines.append(f"\n**Action:** [Apply]({url})")

    enrichment = job.get("enrichment")
    if enrichment:
        try:
            from shortlist.processors.enricher import CompanyIntel
            intel = CompanyIntel.from_json(company, enrichment)
            lines.append(f"\n**Company intel:** {intel.summary()}")
            if intel.domain_description:
                lines.append(f"*{intel.domain_description}*")
        except Exception:
            pass

    resume_path = job.get("tailored_resume_path")
    if resume_path:
        lines.append(f"**Tailored resume:** [{resume_path}]({resume_path})")
        # Check for interest note alongside
        note_path = Path(resume_path).with_suffix(".note.md")
        if note_path.exists():
            note_text = note_path.read_text()
            # Extract just the interest note (first paragraph after header)
            import re
            interest = re.search(r"^# Why.*?\n\n(.*?)(?:\n\n|$)", note_text, re.DOTALL)
            if interest:
                lines.append(f"**Why I'm interested:** {interest.group(1).strip()}")

    return "\n".join(lines)


def _render_worth_a_look(job: dict) -> str:
    marker = _job_marker(job)
    return (
        f"- {marker} **{job.get('title', '?')}** — {job.get('company', '?')} "
        f"(Score: {job.get('fit_score', '?')} | {job.get('location') or '?'})"
    )


def generate_brief(db: sqlite3.Connection, output_dir: Path) -> Path:
    """Generate the daily markdown brief and return the file path."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today()
    data = BriefData.from_db(db)

    # Count new vs seen in top matches
    new_top = sum(1 for j in data.top_matches if (j.get("brief_count") or 0) == 0)
    seen_top = len(data.top_matches) - new_top

    lines = [
        f"# Shortlist — {today.strftime('%A, %B %d, %Y')}",
        "",
        f"> {data.total_collected} jobs collected | {data.total_filtered} filtered out | {data.total_scored} scored | {len(data.top_matches)} top matches",
        "",
    ]

    # Top matches
    if data.top_matches:
        header_parts = []
        if new_top:
            header_parts.append(f"{new_top} new")
        if seen_top:
            header_parts.append(f"{seen_top} seen before")
        lines.append(f"## 🟢 Top Matches ({', '.join(header_parts) if header_parts else '0'})")
        lines.append("")
        for i, job in enumerate(data.top_matches, 1):
            lines.append(_render_top_match(job, i))
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("## 🟢 Top Matches (0 today)")
        lines.append("")
        lines.append("No top matches today.")
        lines.append("")

    # Worth a look
    lines.append(f"## 🟡 Worth a Look ({len(data.worth_a_look)} today)")
    lines.append("")
    if data.worth_a_look:
        for job in data.worth_a_look:
            lines.append(_render_worth_a_look(job))
        lines.append("")
    else:
        lines.append("None today.")
        lines.append("")

    # Filtered out — summary with reason breakdown, not full list
    lines.append(f"## ⚫ Filtered Out ({len(data.filtered_out)} total)")
    lines.append("")
    if data.filtered_out:
        # Count by reason category
        reason_counts: dict[str, int] = {}
        for job in data.filtered_out:
            reason = job.get("reject_reason") or "Unknown"
            # Simplify reason to category
            if "location" in reason.lower():
                cat = "Location mismatch"
            elif "salary" in reason.lower():
                cat = "Below salary minimum"
            elif "ic role" in reason.lower() or "intern" in reason.lower():
                cat = "IC / intern role"
            else:
                cat = reason[:50]
            reason_counts[cat] = reason_counts.get(cat, 0) + 1

        for cat, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- **{cat}:** {count}")
        lines.append("")
    else:
        lines.append("None today.")
        lines.append("")

    # Tracker
    lines.append("## 📊 Tracker")
    lines.append("")
    if data.tracker:
        lines.append("| Company | Role | Score | Status | Notes |")
        lines.append("|---------|------|-------|--------|-------|")
        for job in data.tracker:
            marker = _job_marker(job)
            status = job.get("status", "?")
            notes = job.get("notes") or "—"
            lines.append(
                f"| {job.get('company', '?')} | {job.get('title', '?')} "
                f"| {job.get('fit_score') or '—'} | {marker} {status} | {notes} |"
            )
        lines.append("")
    else:
        lines.append("No tracked jobs yet.")
        lines.append("")

    # Source health
    lines.append("## 🔧 Source Health")
    lines.append("")
    if data.source_health:
        lines.append("| Source | Status | Last Success | Jobs Found |")
        lines.append("|--------|--------|-------------|------------|")
        for src in data.source_health:
            lines.append(
                f"| {src.get('name', '?')} | {src.get('status', '?')} "
                f"| {src.get('finished_at') or '—'} | {src.get('jobs_found', 0)} |"
            )
        lines.append("")
    else:
        lines.append("No source data yet.")
        lines.append("")

    # Write file
    content = "\n".join(lines)
    path = output_dir / f"{today.isoformat()}.md"
    path.write_text(content)

    # Update brief_count and first_briefed for jobs shown
    shown_jobs = data.top_matches + data.worth_a_look
    for job in shown_jobs:
        job_id = job.get("id")
        if job_id is None:
            continue
        first_briefed = job.get("first_briefed")
        if not first_briefed:
            db.execute(
                "UPDATE jobs SET brief_count = brief_count + 1, first_briefed = ? WHERE id = ?",
                (today.isoformat(), job_id),
            )
        else:
            db.execute(
                "UPDATE jobs SET brief_count = brief_count + 1 WHERE id = ?",
                (job_id,),
            )
    db.commit()

    return path
