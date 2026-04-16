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


def _min_base_to_usd(config: Config) -> int:
    """Convert the user's min_base to USD using approximate rates."""
    min_base = config.filters.salary.min_base
    currency = config.filters.salary.currency.upper()
    if currency == "USD":
        return min_base

    # Map currency codes to the same rates used for job salary parsing
    _CODE_TO_RATE = {
        "USD": 1.0, "GBP": 1.25, "EUR": 1.10, "JPY": 0.0067,
        "INR": 0.012, "ILS": 0.28, "SEK": 0.095, "NOK": 0.095,
        "DKK": 0.095, "CHF": 1.15, "BRL": 0.18, "AUD": 0.65,
        "CAD": 0.73, "SGD": 0.75, "NZD": 0.60, "HKD": 0.13,
        "PLN": 0.25, "CZK": 0.044, "MXN": 0.058,
    }
    rate = _CODE_TO_RATE.get(currency, 1.0)
    return int(min_base * rate)


def _check_salary(job: RawJob, config: Config) -> FilterResult:
    """Reject only if salary is explicitly listed AND max < min_base."""
    if not job.salary_text:
        return FilterResult(passed=True)

    min_base = config.filters.salary.min_base
    if min_base <= 0:
        return FilterResult(passed=True)

    max_salary_usd = _parse_max_salary(job.salary_text)
    if max_salary_usd is None:
        # Couldn't parse — benefit of the doubt
        return FilterResult(passed=True)

    min_base_usd = _min_base_to_usd(config)

    if max_salary_usd < min_base_usd:
        return FilterResult(
            passed=False,
            reason=f"Salary: {job.salary_text} (≈${max_salary_usd:,} USD < ≈${min_base_usd:,} USD minimum)",
        )

    return FilterResult(passed=True)


# Currency symbols and their approximate USD conversion rates.
# Used only for the hard salary filter (reject/pass), not for display.
# Rates don't need to be exact — this is a "clearly below minimum" check.
_CURRENCY_TO_USD = {
    "$": 1.0,       # USD (also AUD, CAD, SGD — close enough for filtering)
    "£": 1.25,      # GBP
    "€": 1.10,      # EUR
    "¥": 0.0067,    # JPY (also CNY but salaries are usually monthly there)
    "₹": 0.012,     # INR
    "₪": 0.28,      # ILS
    "kr": 0.095,    # SEK/NOK/DKK (averaged)
    "CHF": 1.15,    # Swiss Franc
    "R$": 0.18,     # BRL
    "A$": 0.65,     # AUD (explicit)
    "C$": 0.73,     # CAD (explicit)
    # Currency codes (used when currency appears after the number)
    "USD": 1.0, "GBP": 1.25, "EUR": 1.10, "JPY": 0.0067,
    "INR": 0.012, "ILS": 0.28, "SEK": 0.095, "NOK": 0.095,
    "DKK": 0.095, "BRL": 0.18, "AUD": 0.65, "CAD": 0.73,
    "SGD": 0.75, "NZD": 0.60, "HKD": 0.13, "PLN": 0.25,
    "CZK": 0.044, "MXN": 0.058,
}

# Symbols that appear BEFORE the number
_PRE_SYMBOLS = r"[£€¥₹₪]|\$|A\$|C\$|R\$|CHF|kr"
# Currency codes/symbols that appear AFTER the number
_POST_CODES = r"USD|GBP|EUR|INR|ILS|SEK|NOK|DKK|CHF|BRL|AUD|CAD|JPY|SGD|NZD|HKD|PLN|CZK|MXN|kr|[£€¥₹₪]"

# Pattern 1: symbol before number — £220,000 / €250.000 / $280k / ₹40L / ₹1.5Cr
_PRE_PATTERN = re.compile(
    rf"(?P<currency>{_PRE_SYMBOLS})\s*(?P<amount>[\d][\d.,\s]*[\d]|[\d]+)"
    rf"(?:\s*(?P<suffix>k|L|LPA|Cr|lakh|lakhs|crore|crores))?\b",
    re.IGNORECASE,
)

# Pattern 2: number before currency code — 250,000 EUR / 280 000 GBP / 280.000 €
# Note: \b doesn't work after unicode symbols (€, £), so we use lookahead instead
_POST_PATTERN = re.compile(
    rf"(?P<amount>[\d][\d.,\s]*[\d]|[\d]+)\s*(?P<suffix>k|L|LPA|Cr|lakh|lakhs|crore|crores)?"
    rf"\s*(?P<currency>{_POST_CODES})(?:\b|$|\s)",
    re.IGNORECASE,
)


def _normalize_amount(amount_str: str) -> int | None:
    """Parse a number string handling US, EU, and space-separated formats.

    Handles: 280,000 / 280.000 / 280 000 / 250.000,00 / 1,50,00,000
    """
    # Strip spaces used as thousands separators (EU/Nordic: "250 000")
    clean = amount_str.replace(" ", "")

    # EU format with decimal: "250.000,00" → strip decimal part, dots are thousands
    if re.match(r"^\d{1,3}(\.\d{3})+,\d{2}$", clean):
        clean = clean.split(",")[0].replace(".", "")
    # EU format without decimal: "250.000" → dot is thousands separator
    elif re.match(r"^\d{1,3}(\.\d{3})+$", clean):
        clean = clean.replace(".", "")
    # US/Indian format: "280,000" or "1,50,00,000" → commas are thousands
    elif "," in clean:
        clean = clean.replace(",", "")
    # Dot as decimal point (e.g., "1.5" in "₹1.5Cr")
    elif "." in clean:
        try:
            return None  # will be handled by suffix (Cr, L) caller
        except ValueError:
            return None

    try:
        return int(clean)
    except ValueError:
        return None


def _parse_amount_with_suffix(amount_str: str, suffix: str) -> int | None:
    """Parse amount + suffix (k, L, Cr, etc.) into an integer."""
    suffix_lower = (suffix or "").lower()

    # Handle decimal amounts like "1.5" in "₹1.5Cr"
    if "." in amount_str.replace(" ", "") and suffix_lower:
        try:
            base = float(amount_str.replace(" ", "").replace(",", ""))
        except ValueError:
            return None
    else:
        base_int = _normalize_amount(amount_str)
        if base_int is None:
            return None
        base = float(base_int)

    multipliers = {
        "k": 1_000,
        "l": 100_000, "lpa": 100_000, "lakh": 100_000, "lakhs": 100_000,
        "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
    }
    multiplier = multipliers.get(suffix_lower, 1)
    return int(base * multiplier)


def _is_monthly(salary_text: str) -> bool:
    """Check if the salary text indicates a monthly rate."""
    return bool(re.search(r"/(month|mo|m)\b|per\s+month|monthly|p\.?m\.?\b", salary_text, re.I))


def _parse_max_salary(salary_text: str) -> int | None:
    """Extract the maximum salary from a salary string, converted to USD.

    Handles:
    - Symbols before number: $280k, £220,000, €250.000, ₹40L, ₹1.5Cr
    - Codes after number: 250,000 EUR, 280 000 GBP
    - Monthly rates: kr 85,000/month → annualized
    - EU number formats: 250.000 / 250 000 / 250.000,00

    Returns None if unparseable.
    """
    if not salary_text:
        return None

    monthly = _is_monthly(salary_text)
    parsed = []

    # Try symbol-before-number matches
    for m in _PRE_PATTERN.finditer(salary_text):
        currency = m.group("currency")
        amount_str = m.group("amount")
        suffix = m.group("suffix") or ""

        value = _parse_amount_with_suffix(amount_str, suffix)
        if value is None:
            continue
        if monthly:
            value *= 12

        rate = _CURRENCY_TO_USD.get(currency, _CURRENCY_TO_USD.get(currency.upper(), 1.0))
        parsed.append(int(value * rate))

    # Try number-before-code matches
    for m in _POST_PATTERN.finditer(salary_text):
        currency_raw = m.group("currency")
        amount_str = m.group("amount")
        suffix = m.group("suffix") or ""

        value = _parse_amount_with_suffix(amount_str, suffix)
        if value is None:
            continue
        if monthly:
            value *= 12

        # Try original case first (kr, €), then uppercase (EUR, GBP)
        rate = _CURRENCY_TO_USD.get(currency_raw, _CURRENCY_TO_USD.get(currency_raw.upper(), 1.0))
        parsed.append(int(value * rate))

    if not parsed:
        return None
    max_val = max(parsed)
    # Values below $30,000 USD are clearly not annual salaries
    # (probably funding amounts, hourly rates, or parser noise)
    if max_val < 30000:
        return None
    return max_val


_MIN_LISTED_SALARY_USD = 50_000


def is_listed_salary(salary_text: str | None) -> bool:
    """Return True iff salary_text is a parseable annual USD salary >= $50,000.

    Rejects None, monthly rates, and low values that are parser noise (e.g. "$13").
    """
    if not salary_text:
        return False
    if _is_monthly(salary_text):
        return False
    parsed = _parse_max_salary(salary_text)
    return parsed is not None and parsed >= _MIN_LISTED_SALARY_USD


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
