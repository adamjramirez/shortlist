"""Career page parsers for Greenhouse, Lever, and Ashby ATS platforms."""
import logging
import re
from html import unescape
from urllib.parse import urlparse

from shortlist.collectors.base import RawJob
from shortlist import http

logger = logging.getLogger(__name__)


def detect_ats(url: str) -> str | None:
    """Detect which ATS platform a career page URL belongs to.

    Returns: 'greenhouse', 'lever', 'ashby', or None.
    """
    if "greenhouse.io" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    if "ashbyhq.com" in url:
        return "ashby"
    return None


def extract_org_slug(url: str, ats: str) -> str | None:
    """Extract the organization slug from an ATS URL.

    Examples:
        https://boards.greenhouse.io/nabis -> 'nabis'
        https://job-boards.greenhouse.io/nabis/jobs/123 -> 'nabis'
        https://jobs.lever.co/soraschools -> 'soraschools'
        https://jobs.ashbyhq.com/suno -> 'suno'
    """
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    return parts[0] if parts else None


# --- ATS discovery from company websites ---

# Patterns to find ATS URLs in page content (href, JSON-LD, inline text)
ATS_URL_PATTERNS = [
    (re.compile(r'https?://(?:boards-api\.greenhouse\.io|job-boards\.greenhouse\.io|boards\.greenhouse\.io)/([a-z0-9_-]+)', re.I), "greenhouse"),
    (re.compile(r'https?://jobs\.ashbyhq\.com/([a-z0-9_-]+)', re.I), "ashby"),
    (re.compile(r'https?://(?:api\.)?(?:jobs\.)?lever\.co/(?:v0/postings/)?([a-z0-9_-]+)', re.I), "lever"),
]


def discover_ats_from_url(url: str) -> tuple[str | None, str | None]:
    """Visit a URL and discover which ATS the company uses.

    Checks homepage links, /careers page content, redirects, JSON-LD, and
    embedded iframes/scripts for ATS platform references.

    Returns: (ats_platform, org_slug) or (None, None) if not found.
    """
    try:
        resp = http.get(url, timeout=10, follow_redirects=True)
    except Exception as e:
        logger.debug(f"Failed to fetch {url}: {e}")
        return None, None

    # Check the page content for ATS URLs
    ats, slug = _find_ats_in_content(resp.text)
    if ats:
        return ats, slug

    # Follow /careers or /jobs links
    domain = urlparse(url).netloc
    links = re.findall(r'href=["\']([^"\']*)["\']', resp.text, re.I)
    career_links = [l for l in links if re.search(r'/careers|/jobs(?!\w)', l, re.I)]

    for cl in career_links[:2]:
        # Check if the career link itself is an ATS URL
        for pattern, ats_name in ATS_URL_PATTERNS:
            m = pattern.search(cl)
            if m:
                return ats_name, m.group(1)

        # Follow the link
        if cl.startswith('/'):
            cl = f"https://{domain}{cl}"
        try:
            resp2 = http.get(cl, timeout=10, follow_redirects=True)

            # Check for ATS redirect
            final_url = str(resp2.url)
            for pattern, ats_name in ATS_URL_PATTERNS:
                m = pattern.search(final_url)
                if m:
                    return ats_name, m.group(1)

            # Check careers page content
            ats, slug = _find_ats_in_content(resp2.text)
            if ats:
                return ats, slug
        except Exception:
            continue

    return None, None


def discover_ats_from_domain(domain: str) -> tuple[str | None, str | None]:
    """Discover ATS from a company domain.

    Strategy:
    1. Visit homepage + /careers page, look for ATS links/redirects
    2. If not found, try the domain slug directly on Greenhouse/Lever
       (many companies use Greenhouse with their domain as the slug)
    """
    clean = domain.lower().removeprefix("www.")

    # Strategy 1: Visit the website
    ats, slug = discover_ats_from_url(f"https://{clean}")
    if ats:
        return ats, slug

    if not domain.startswith("www."):
        ats, slug = discover_ats_from_url(f"https://www.{clean}")
        if ats:
            return ats, slug

    # Strategy 2: Try domain slug directly on Greenhouse/Lever
    # (e.g., affirm.com → boards-api.greenhouse.io/v1/boards/affirm/jobs)
    domain_slug = clean.split(".")[0]
    if domain_slug and len(domain_slug) > 2:
        for ats_name, probe_fn in [
            ("greenhouse", _probe_greenhouse),
            ("lever", _probe_lever),
        ]:
            if probe_fn(domain_slug):
                return ats_name, domain_slug

    return None, None


def _probe_greenhouse(slug: str) -> bool:
    """Quick check if a Greenhouse board exists (no job fetching)."""
    try:
        resp = http.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            return len(data.get("jobs", [])) > 0
    except Exception:
        pass
    return False


def _probe_lever(slug: str) -> bool:
    """Quick check if a Lever board exists (no job fetching)."""
    try:
        resp = http.get(
            f"https://api.lever.co/v0/postings/{slug}",
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            return isinstance(data, list) and len(data) > 0
    except Exception:
        pass
    return False


def _find_ats_in_content(html: str) -> tuple[str | None, str | None]:
    """Search page HTML for ATS platform URLs."""
    for pattern, ats_name in ATS_URL_PATTERNS:
        m = pattern.search(html)
        if m:
            slug = m.group(1)
            # Filter out generic/false-positive slugs
            if slug in ("api", "v0", "v1", "postings", "jobs", "boards",
                         "embed", "widget", "iframe", "static", "assets"):
                continue
            return ats_name, slug
    return None, None


# --- ATS API fetchers ---

def fetch_greenhouse_jobs(org_slug: str, company_name: str | None = None) -> list[RawJob]:
    """Fetch jobs from Greenhouse's public JSON API."""
    try:
        resp = http.get(
            f"https://boards-api.greenhouse.io/v1/boards/{org_slug}/jobs",
            params={"content": "true"},
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Greenhouse API failed for {org_slug}: {e}")
        return []

    # Get proper company name from board metadata if not provided
    if not company_name:
        try:
            board_resp = http.get(
                f"https://boards-api.greenhouse.io/v1/boards/{org_slug}"
            )
            company_name = board_resp.json().get("name", org_slug)
        except Exception:
            company_name = org_slug

    jobs = []
    for item in resp.json().get("jobs", []):
        jobs.append(RawJob(
            title=item.get("title", ""),
            company=company_name,
            url=item.get("absolute_url", ""),
            description=_clean_html(item.get("content", "")),
            source="greenhouse",
            location=item.get("location", {}).get("name", ""),
        ))

    logger.info(f"Greenhouse/{org_slug}: {len(jobs)} jobs")
    return jobs


def fetch_lever_jobs(org_slug: str, company_name: str | None = None) -> list[RawJob]:
    """Fetch jobs from Lever's public JSON API."""
    try:
        resp = http.get(f"https://api.lever.co/v0/postings/{org_slug}")
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Lever API failed for {org_slug}: {e}")
        return []

    try:
        data = resp.json()
    except Exception:
        logger.debug(f"Lever/{org_slug}: response was not JSON (likely invalid slug)")
        return []

    name = company_name or org_slug

    jobs = []
    for item in data:
        description = item.get("descriptionPlain", "")
        for lst in item.get("lists", []):
            description += f"\n{lst.get('text', '')}:\n"
            description += "\n".join(f"- {c}" for c in lst.get("content", ""))

        jobs.append(RawJob(
            title=item.get("text", ""),
            company=name,
            url=item.get("hostedUrl", ""),
            description=description,
            source="lever",
            location=item.get("categories", {}).get("location", ""),
        ))

    logger.info(f"Lever/{org_slug}: {len(jobs)} jobs")
    return jobs


def fetch_ashby_jobs(org_slug: str, company_name: str | None = None) -> list[RawJob]:
    """Fetch jobs from Ashby's GraphQL API."""
    try:
        resp = http.post(
            "https://jobs.ashbyhq.com/api/non-user-graphql?operationName=ApiJobBoardWithTeams",
            json={
                "operationName": "ApiJobBoardWithTeams",
                "variables": {"organizationHostedJobsPageName": org_slug},
                "query": (
                    "query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {"
                    "  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {"
                    "    jobPostings { id title locationName compensationTierSummary employmentType }"
                    "  }"
                    "}"
                ),
            },
        )
        resp.raise_for_status()
    except Exception as e:
        # 406 = org doesn't exist on Ashby — not a real error
        if "406" in str(e):
            logger.debug(f"Ashby: no board for {org_slug}")
        else:
            logger.warning(f"Ashby API failed for {org_slug}: {e}")
        return []

    board = resp.json().get("data", {}).get("jobBoard")
    if not board:
        logger.debug(f"Ashby/{org_slug}: no job board found")
        return []

    jobs = []
    for item in board.get("jobPostings", []):
        job_id = item.get("id", "")
        compensation = item.get("compensationTierSummary", "")

        description = _fetch_ashby_description(org_slug, job_id)
        if compensation and compensation not in description:
            description = f"Compensation: {compensation}\n{description}"

        jobs.append(RawJob(
            title=item.get("title", ""),
            company=company_name or org_slug,
            url=f"https://jobs.ashbyhq.com/{org_slug}/{job_id}",
            description=description,
            source="ashby",
            location=item.get("locationName", ""),
        ))

    logger.info(f"Ashby/{org_slug}: {len(jobs)} jobs")
    return jobs


def _fetch_ashby_description(org_slug: str, job_id: str) -> str:
    """Fetch a single Ashby job's description via GraphQL."""
    try:
        resp = http.post(
            "https://jobs.ashbyhq.com/api/non-user-graphql?operationName=ApiJobPosting",
            json={
                "operationName": "ApiJobPosting",
                "variables": {
                    "organizationHostedJobsPageName": org_slug,
                    "jobPostingId": job_id,
                },
                "query": (
                    "query ApiJobPosting("
                    "  $organizationHostedJobsPageName: String!,"
                    "  $jobPostingId: String!"
                    ") {"
                    "  jobPosting("
                    "    organizationHostedJobsPageName: $organizationHostedJobsPageName,"
                    "    jobPostingId: $jobPostingId"
                    "  ) { descriptionHtml }"
                    "}"
                ),
            },
        )
        resp.raise_for_status()
        posting = resp.json().get("data", {}).get("jobPosting", {})
        if posting and posting.get("descriptionHtml"):
            return _clean_html(posting["descriptionHtml"])
    except Exception as e:
        logger.debug(f"Ashby description fetch failed for {org_slug}/{job_id}: {e}")

    return ""


FETCHERS = {
    "greenhouse": fetch_greenhouse_jobs,
    "lever": fetch_lever_jobs,
    "ashby": fetch_ashby_jobs,
}


def fetch_career_page(url: str) -> list[RawJob]:
    """Detect ATS and fetch jobs from a career page URL.

    Returns empty list if ATS is unrecognized or fetch fails.
    """
    ats = detect_ats(url)
    if not ats:
        logger.debug(f"Unrecognized ATS for {url}")
        return []

    slug = extract_org_slug(url, ats)
    if not slug:
        logger.debug(f"Could not extract org slug from {url}")
        return []

    fetcher = FETCHERS.get(ats)
    if not fetcher:
        return []

    return fetcher(slug)


def _clean_html(text: str) -> str:
    """Strip HTML tags, unescape entities, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
