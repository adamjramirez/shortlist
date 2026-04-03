"""HN Who's Hiring collector."""
import re
from datetime import datetime, timezone
from html import unescape

from shortlist.collectors.base import BaseCollector, RawJob
from shortlist import http

# HN Algolia search API
ALGOLIA_SEARCH_URL = "https://hn.algolia.com/api/v1/search"




class HNCollector:
    """Collects jobs from HN 'Who's Hiring' monthly threads."""

    def fetch_new(self) -> list[RawJob]:
        """Fetch jobs from the most recent Who's Hiring thread."""
        thread_id = self._find_latest_thread()
        if thread_id is None:
            return []

        comments = self._fetch_comments(thread_id)
        return self._parse_comments(comments)

    def _find_latest_thread(self) -> int | None:
        """Find the most recent 'Ask HN: Who is hiring?' thread."""
        resp = http.get(
            ALGOLIA_SEARCH_URL,
            params={
                "query": "Ask HN: Who is hiring?",
                "tags": "story",
                "hitsPerPage": 1,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        hits = data.get("hits", [])
        if not hits:
            return None
        return int(hits[0]["objectID"])

    def _fetch_comments(self, thread_id: int) -> list[dict]:
        """Fetch all top-level comments from a thread."""
        all_comments = []
        page = 0
        while True:
            resp = http.get(
                ALGOLIA_SEARCH_URL,
                params={
                    "tags": f"comment,story_{thread_id}",
                    "hitsPerPage": 100,
                    "page": page,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", [])
            if not hits:
                break

            # Only top-level comments (parent_id == thread_id)
            top_level = [h for h in hits if h.get("parent_id") == thread_id]
            all_comments.extend(top_level)

            if page >= data.get("nbPages", 1) - 1:
                break
            page += 1

        return all_comments

    def _parse_comments(self, comments: list[dict]) -> list[RawJob]:
        """Parse HN comments into RawJob objects."""
        jobs = []
        for comment in comments:
            text = comment.get("comment_text", "")
            if not text:
                continue

            job = self._parse_single_comment(comment)
            if job is not None:
                jobs.append(job)

        return jobs

    def _parse_single_comment(self, comment: dict) -> RawJob | None:
        """Parse a single HN comment into a RawJob, or None if unparseable."""
        raw_html = comment.get("comment_text", "")
        if not raw_html:
            return None

        # Split on <p> tags to get lines
        lines = re.split(r"<p>", raw_html)
        first_line = _clean_html(lines[0])

        # Must have at least one | to be a structured job posting
        if "|" not in first_line:
            return None

        # Split on pipes — field order varies (Company|Role|Location or Company|Location|Role)
        # The LLM scorer will correct title/company/location from the full description
        raw_fields = [s.strip() for s in first_line.split("|")]
        company = raw_fields[0]
        title = raw_fields[1] if len(raw_fields) > 1 else company
        location = raw_fields[2] if len(raw_fields) > 2 else None

        # Extract salary if present anywhere in header
        salary_text = None
        salary_match = re.search(r"\$[\d,]+k?\s*[-–]\s*\$[\d,]+k?|\$[\d,]+k?", first_line)
        if salary_match:
            salary_text = salary_match.group(0)

        # Full description is all lines joined
        full_text = "\n".join(_clean_html(line) for line in lines)

        object_id = comment.get("objectID", "")
        url = f"https://news.ycombinator.com/item?id={object_id}"

        # Extract posting date from HN API
        posted_at = comment.get("created_at")  # ISO 8601 string from Algolia
        if not posted_at:
            ts = comment.get("created_at_i")
            if ts:
                posted_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        return RawJob(
            title=title,
            company=company,
            url=url,
            description=full_text,
            source="hn",
            location=location if location else None,
            salary_text=salary_text,
            posted_at=posted_at,
        )


def _clean_html(text: str) -> str:
    """Strip HTML tags and unescape entities."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
