"""NextPlay Substack meta-source collector.

Scrapes NextPlay newsletter articles for career page URLs,
then routes them through ATS parsers (Greenhouse, Lever, Ashby)
to collect actual job listings.

Two extraction strategies:
1. Direct: find ATS links and /careers /jobs paths in articles
2. Probe: for company homepages, try known ATS slug patterns
"""
import logging
import os
import re
import sqlite3
from urllib.parse import urlparse

from dotenv import load_dotenv

from shortlist.collectors.base import RawJob
from shortlist.collectors.career_page import (
    detect_ats, extract_org_slug, fetch_career_page,
    discover_ats_from_domain, FETCHERS,
    fetch_ashby_jobs, fetch_greenhouse_jobs, fetch_lever_jobs,
)
from shortlist import http

load_dotenv()

logger = logging.getLogger(__name__)

FEED_URL = "https://nextplayso.substack.com/feed"

# Domains to skip entirely
SKIP_DOMAINS = {
    "linkedin.com",
    "substack.com",
    "substackcdn.com",
    "instagram.com",
    "fonts.gstatic.com",
}

# URL path patterns that indicate a career/jobs page (not just domain)
CAREER_PATH_PATTERN = re.compile(
    r"/(?:careers|jobs|hiring|positions|join.*team|open-roles|work-with-us)",
    re.I,
)


def _is_ats_url(url: str) -> bool:
    """Check if URL is a known ATS platform."""
    return detect_ats(url) is not None


def _is_career_url(url: str) -> bool:
    """Check if URL looks like a career page (ATS or path-based)."""
    if _is_ats_url(url):
        return True
    parsed = urlparse(url)
    return bool(CAREER_PATH_PATTERN.search(parsed.path))


def _domain_to_slugs(domain: str) -> list[str]:
    """Generate possible ATS slugs from a company domain.

    Example: 'www.activesite.bio' -> ['activesite', 'active-site']
    """
    # Strip www. and TLD
    name = domain.lower()
    if name.startswith("www."):
        name = name[4:]
    name = name.split(".")[0]

    slugs = [name]
    # Try hyphenated version for camelCase-ish names
    # e.g., 'corestory' -> 'core-story' (unlikely but cheap to try)
    return slugs


class NextPlayCollector:
    """Collects jobs by scraping NextPlay Substack for career page links."""

    def __init__(self, substack_sid: str | None = None, max_articles: int = 10,
                 probe_ats: bool = True, db: sqlite3.Connection | None = None):
        self.substack_sid = substack_sid or os.getenv("SUBSTACK_SID", "")
        self.max_articles = max_articles
        self.probe_ats = probe_ats
        self.db = db
        self._seen_slugs: set[str] = set()  # "ats:slug" keys

    # Re-crawl articles after this many days (catches updates/edits)
    ARTICLE_CACHE_DAYS = 7

    def _is_article_crawled(self, url: str) -> bool:
        """Check if we've recently crawled this article URL."""
        if not self.db:
            return False
        row = self.db.execute(
            "SELECT id FROM crawled_articles WHERE url = ? "
            "AND crawled_at > datetime('now', ?)",
            (url, f"-{self.ARTICLE_CACHE_DAYS} days"),
        ).fetchone()
        return row is not None

    def _mark_article_crawled(self, article: dict, career_count: int, job_count: int):
        """Record that we crawled this article. Updates timestamp on re-crawl."""
        if not self.db:
            return
        self.db.execute(
            "INSERT INTO crawled_articles "
            "(url, source, title, career_urls_found, jobs_found) "
            "VALUES (?, 'nextplay', ?, ?, ?) "
            "ON CONFLICT(url) DO UPDATE SET "
            "crawled_at = CURRENT_TIMESTAMP, "
            "career_urls_found = excluded.career_urls_found, "
            "jobs_found = excluded.jobs_found",
            (article["url"], article.get("title", ""), career_count, job_count),
        )
        self.db.commit()

    def fetch_new(self) -> list[RawJob]:
        """Fetch RSS feed, extract career URLs, scrape ATS pages."""
        articles = self._fetch_feed()

        # Filter out already-crawled articles
        new_articles = []
        for a in articles:
            if a.get("url") and self._is_article_crawled(a["url"]):
                logger.debug(f"NextPlay: skipping already-crawled article: {a.get('title', '?')}")
            else:
                new_articles.append(a)

        if len(articles) != len(new_articles):
            logger.info(
                f"NextPlay: {len(articles)} articles in feed, "
                f"{len(articles) - len(new_articles)} already crawled, "
                f"{len(new_articles)} new"
            )

        career_urls, homepage_domains = self._extract_urls(new_articles)
        logger.info(
            f"NextPlay: {len(new_articles)} new articles → "
            f"{len(career_urls)} career pages, {len(homepage_domains)} homepages to probe"
        )

        all_jobs = []

        # 1. Fetch from known ATS links (structured APIs)
        ats_urls = [u for u in career_urls if _is_ats_url(u)]
        direct_urls = [u for u in career_urls if not _is_ats_url(u)]
        seen_ats_domains = {urlparse(u).netloc.lower() for u in ats_urls}
        if direct_urls:
            logger.info(
                f"NextPlay: skipping {len(direct_urls)} direct career pages "
                f"(no ATS parser): {[u.split('//')[1][:30] for u in direct_urls[:5]]}"
            )

        for url in ats_urls:
            try:
                jobs = fetch_career_page(url)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.warning(f"NextPlay: failed to fetch {url}: {e}")

        # 2. Probe ATS platforms for direct career page domains
        #    (they might have an ATS board even if the link was to /careers)
        if self.probe_ats:
            direct_domains = set()
            for url in direct_urls:
                domain = urlparse(url).netloc.lower()
                if domain not in seen_ats_domains:
                    direct_domains.add(domain)
            if direct_domains:
                logger.info(
                    f"NextPlay: probing {len(direct_domains)} direct career page domains for ATS boards"
                )
                probed_direct = self._probe_homepages(list(direct_domains))
                all_jobs.extend(probed_direct)

        # 3. Probe ATS platforms for company homepages
        if self.probe_ats:
            probed = self._probe_homepages(homepage_domains)
            all_jobs.extend(probed)

        # Mark all new articles as crawled
        for article in new_articles:
            if article.get("url"):
                self._mark_article_crawled(
                    article, len(career_urls), len(all_jobs),
                )

        logger.info(f"NextPlay: collected {len(all_jobs)} jobs total")
        return all_jobs

    def _fetch_feed(self) -> list[dict]:
        """Fetch the NextPlay RSS feed and return article content."""
        cookies = {}
        if self.substack_sid:
            cookies["substack.sid"] = self.substack_sid

        try:
            resp = http.get(FEED_URL, cookies=cookies, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"NextPlay feed fetch failed: {e}")
            return []

        return self._parse_rss(resp.text)

    def _parse_rss(self, xml: str) -> list[dict]:
        """Parse RSS XML into article dicts with title and content."""
        items = re.findall(r"<item>(.*?)</item>", xml, re.DOTALL)
        articles = []

        for item in items[: self.max_articles]:
            title_m = re.search(r"<title><!\[CDATA\[(.*?)\]\]></title>", item)
            content_m = re.search(
                r"<content:encoded><!\[CDATA\[(.*?)\]\]></content:encoded>",
                item, re.DOTALL,
            )
            link_m = re.search(r"<link>(.*?)</link>", item)

            if content_m:
                articles.append({
                    "title": title_m.group(1).strip() if title_m else "",
                    "content": content_m.group(1),
                    "url": link_m.group(1).strip() if link_m else "",
                })

        return articles

    def _extract_urls(self, articles: list[dict]) -> tuple[list[str], list[str]]:
        """Extract career page URLs and company homepage domains from articles.

        Returns:
            (career_urls, homepage_domains) — career URLs to fetch directly,
            and homepage domains to probe for ATS boards.
        """
        career_urls: list[str] = []
        homepage_domains: list[str] = []
        seen_domains: set[str] = set()

        for article in articles:
            links = re.findall(r'href="(https?://[^"]+)"', article["content"])

            for raw_link in links:
                link = raw_link.split("?")[0].rstrip("/")
                link = link.replace("&amp;", "&")

                domain = urlparse(link).netloc.lower()
                if any(skip in domain for skip in SKIP_DOMAINS):
                    continue

                if _is_career_url(link):
                    # It's a career page or ATS link — dedupe by org slug
                    ats = detect_ats(link)
                    if ats:
                        slug = extract_org_slug(link, ats)
                        if slug:
                            key = f"{ats}:{slug}"
                            if key in self._seen_slugs:
                                continue
                            self._seen_slugs.add(key)

                    if link not in career_urls:
                        career_urls.append(link)
                    seen_domains.add(domain)

                elif domain not in seen_domains:
                    # Company homepage — candidate for ATS probing
                    seen_domains.add(domain)
                    homepage_domains.append(domain)

        return career_urls, homepage_domains

    def _probe_homepages(self, domains: list[str]) -> list[RawJob]:
        """Discover ATS from company homepages and fetch their jobs.

        Instead of blindly probing all 3 ATS APIs per domain, we visit the
        company's website, find their careers page, and detect which ATS
        they actually use — then make a single targeted API call.
        """
        all_jobs = []

        for domain in domains:
            # Skip if we already have jobs from this company
            slugs = _domain_to_slugs(domain)
            if any(f"{ats}:{slug}" in self._seen_slugs
                   for slug in slugs
                   for ats in ("greenhouse", "lever", "ashby")):
                continue

            # Visit the website and discover ATS
            ats, slug = discover_ats_from_domain(domain)
            if not ats or not slug:
                logger.debug(f"NextPlay: no ATS found for {domain}")
                continue

            key = f"{ats}:{slug}"
            if key in self._seen_slugs:
                continue
            self._seen_slugs.add(key)

            # Fetch jobs from the discovered ATS
            fetcher = FETCHERS.get(ats)
            if fetcher:
                try:
                    jobs = fetcher(slug)
                    if jobs:
                        logger.info(f"NextPlay discover: {domain} → {ats}/{slug} → {len(jobs)} jobs")
                        all_jobs.extend(jobs)
                except Exception as e:
                    logger.warning(f"NextPlay: failed to fetch {ats}/{slug} for {domain}: {e}")

        return all_jobs
