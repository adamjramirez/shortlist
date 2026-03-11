"""Hard filters — cheap checks, no API calls."""
import re
from dataclasses import dataclass

from shortlist.collectors.base import RawJob
from shortlist.config import Config


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""


# Default empty — users configure local cities in profile.yaml
_LOCAL_CITIES: set[str] = set()

# Strings that look like locations (state/country abbreviations, country names, city patterns)
_STATE_ABBREVS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy", "dc",
}

_COUNTRY_NAMES = {
    "usa", "uk", "canada", "germany", "france", "india", "australia",
    "ireland", "netherlands", "spain", "italy", "brazil", "japan",
    "china", "singapore", "israel", "sweden", "norway", "denmark",
    "finland", "switzerland", "austria", "belgium", "poland", "portugal",
    "romania", "turkey", "mexico", "chile", "argentina", "colombia",
    "philippines", "thailand", "vietnam", "indonesia", "taiwan",
}

# Words that indicate this is NOT a location
_NON_LOCATION_SIGNALS = [
    "engineer", "developer", "designer", "scientist", "analyst", "manager",
    "director", "architect", "lead", "intern", "roles", "position",
    "full-time", "full time", "fulltime", "part-time", "part time",
    "contract", "freelance", "http://", "https://", "www.",
    "visa", "frontend", "backend", "full-stack", "full stack",
    "devops", "sre", "qa", "quality", "python", "java", "rust",
    "scala", "rails", "react", "mobile", "embedded", "data",
    "multiple", "various", "several", "openings",
]


def _looks_like_location(text: str) -> bool:
    """Determine if a string looks like an actual geographic location.

    Returns True for real locations, False for job titles, employment types,
    URLs, and other non-location strings that end up in the location field
    from messy HN parsing.
    """
    if not text or not text.strip():
        return False

    text_lower = text.lower().strip()

    # "Remote" is a valid location signal
    if "remote" in text_lower:
        return True

    # Check for non-location signals first
    for signal in _NON_LOCATION_SIGNALS:
        if signal in text_lower:
            # Exception: "onsite" with a city name is still a location
            if signal == "full-time" or signal == "full time" or signal == "fulltime":
                return False
            # For other signals, check if there's also a real location indicator
            # e.g. "Onsite SF" has "onsite" but also a city
            if _has_geo_indicator(text_lower):
                return True
            return False

    # "Onsite" / "ONSITE" — check if there's a city attached
    if re.match(r"^(onsite|on-site|on site)\b", text_lower):
        # "Onsite" alone = not a location
        stripped = re.sub(r"^(onsite|on-site|on site)\s*", "", text_lower).strip()
        if not stripped:
            return False
        # "Onsite SF" or "Onsite in San Francisco" = location
        return _has_geo_indicator(stripped)

    # Check for geographic indicators
    return _has_geo_indicator(text_lower)


def _has_geo_indicator(text: str) -> bool:
    """Check if text contains geographic indicators (state abbrevs, countries, etc.)."""
    # Check for "City, ST" pattern (e.g. "Dallas, TX", "London, UK")
    if re.search(r",\s*[A-Za-z]{2,3}\b", text):
        return True

    # Check for state abbreviations
    words = set(re.findall(r"\b[a-z]{2}\b", text))
    if words & _STATE_ABBREVS:
        return True

    # Check for country names
    for country in _COUNTRY_NAMES:
        if country in text:
            return True

    # Check for well-known city names (partial list for common ones)
    known_cities = {
        "san francisco", "new york", "los angeles",
        "chicago", "seattle", "boston", "austin", "denver", "portland",
        "atlanta", "london", "berlin", "paris", "tokyo", "toronto",
        "vancouver", "amsterdam", "dublin", "bangalore", "mumbai",
        "sydney", "melbourne", "tel aviv", "stockholm", "copenhagen",
        "munich", "zurich", "geneva", "barcelona", "madrid", "lisbon",
        "warsaw", "prague", "budapest", "bucharest", "helsinki", "oslo",
        "pittsburgh", "detroit", "miami", "minneapolis", "phoenix",
        "san diego", "san jose", "oakland", "sacramento", "raleigh",
        "charlotte", "nashville", "salt lake", "indianapolis",
    }
    # Short abbreviations that need word-boundary matching to avoid
    # false positives (e.g. "scala" matching "la", "sfo" matching "sf")
    short_city_abbrevs = {"sf", "nyc", "la", "dc"}

    for city in known_cities:
        if city in text:
            return True
    for abbrev in short_city_abbrevs:
        if re.search(rf"\b{abbrev}\b", text):
            return True

    return False

# Titles that are obviously IC / non-management
IC_TITLE_PATTERNS = [
    r"\bintern\b",
    r"\bjunior\b",
    r"\bjr\.?\b",
    r"\bentry[\s-]level\b",
]

# Explicit IC signals in description
IC_DESCRIPTION_SIGNALS = [
    "individual contributor role",
    "individual contributor position",
    "this is an ic role",
    "this is an ic position",
    "no direct reports",
    "no management responsibilities",
    "not a management role",
    "not a people management",
]


def apply_hard_filters(job: RawJob, config: Config) -> FilterResult:
    """Apply all hard filters to a job. Returns FilterResult."""
    # 1. Location filter
    result = _check_location(job, config)
    if not result.passed:
        return result

    # 2. Salary filter
    result = _check_salary(job, config)
    if not result.passed:
        return result

    # 3. Role type filter
    result = _check_role_type(job, config)
    if not result.passed:
        return result

    return FilterResult(passed=True)


def _check_location(job: RawJob, config: Config) -> FilterResult:
    """Reject if not remote AND not in local area."""
    location = (job.location or "").strip()
    location_lower = location.lower()
    description = (job.description or "").lower()

    # No location info — benefit of the doubt
    if not location and "remote" not in description:
        return FilterResult(passed=True)

    # If the "location" field doesn't look like a real location
    # (e.g. "Full-Time", "Software Engineers", URLs), treat as no location
    if location and not _looks_like_location(location):
        # Still check description for remote signal
        if "remote" in description:
            return FilterResult(passed=True)
        # Not a real location, benefit of the doubt
        return FilterResult(passed=True)

    # Check for remote (title, location, or description)
    title_lower = (job.title or "").lower()
    combined = f"{title_lower} {location_lower} {description}"
    if "remote" in combined:
        return FilterResult(passed=True)

    # Check for local area
    local_cities = set(c.lower() for c in config.filters.location.local_cities)
    if local_cities and _is_local_area(location_lower, local_cities):
        return FilterResult(passed=True)

    # Has a real location, not remote, not local
    if location:
        return FilterResult(passed=False, reason=f"Location: {job.location} (not remote or local)")

    return FilterResult(passed=True)


def _is_local_area(location: str, local_cities: set[str]) -> bool:
    """Check if a location string refers to one of the user's local cities."""
    location_lower = location.lower()
    for city in local_cities:
        if city in location_lower:
            return True
    return False


def _check_salary(job: RawJob, config: Config) -> FilterResult:
    """Reject only if salary is explicitly listed AND max < min_base."""
    if not job.salary_text:
        return FilterResult(passed=True)

    min_base = config.filters.salary.min_base
    if min_base <= 0:
        return FilterResult(passed=True)

    max_salary = _parse_max_salary(job.salary_text)
    if max_salary is None:
        # Couldn't parse — benefit of the doubt
        return FilterResult(passed=True)

    if max_salary < min_base:
        return FilterResult(
            passed=False,
            reason=f"Salary: {job.salary_text} (max ${max_salary:,} < ${min_base:,} minimum)",
        )

    return FilterResult(passed=True)


def _parse_max_salary(salary_text: str) -> int | None:
    """Extract the maximum salary from a salary string. Returns None if unparseable."""
    # Find all dollar amounts
    # Matches: $280,000  $280000  $280k  $280K
    amounts = re.findall(r"\$\s*([\d,]+)\s*k?\b", salary_text, re.IGNORECASE)
    if not amounts:
        return None

    parsed = []
    for amount_str in amounts:
        clean = amount_str.replace(",", "")
        try:
            value = int(clean)
        except ValueError:
            continue

        # Check if this was a "k" format
        k_match = re.search(rf"\${re.escape(amount_str)}\s*k", salary_text, re.IGNORECASE)
        if k_match:
            value *= 1000

        parsed.append(value)

    if not parsed:
        return None
    max_val = max(parsed)
    # Values below $30,000 are clearly not annual salaries
    # (probably funding amounts, hourly rates, or parser noise)
    if max_val < 30000:
        return None
    return max_val


def _check_role_type(job: RawJob, config: Config) -> FilterResult:
    """Reject only if explicitly IC."""
    if not config.filters.role_type.reject_explicit_ic:
        return FilterResult(passed=True)

    title_lower = (job.title or "").lower()
    desc_lower = (job.description or "").lower()

    # Check IC title patterns
    for pattern in IC_TITLE_PATTERNS:
        if re.search(pattern, title_lower):
            return FilterResult(
                passed=False,
                reason=f"IC role: title matches '{pattern}' ({job.title})",
            )

    # Check explicit IC signals in description
    for signal in IC_DESCRIPTION_SIGNALS:
        if signal in desc_lower:
            return FilterResult(
                passed=False,
                reason=f"IC role: description contains '{signal}'",
            )

    return FilterResult(passed=True)
