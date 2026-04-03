"""Verify frontend COUNTRIES descriptions stay in sync with backend REGION_COUNTRIES.

If someone adds a country to a region in linkedin.py but forgets the frontend,
this test will catch the drift.
"""
import re
from pathlib import Path

from shortlist.collectors.linkedin import REGION_COUNTRIES


def _parse_frontend_regions() -> dict[str, list[str]]:
    """Extract region descriptions from constants.ts."""
    constants_path = Path(__file__).parent.parent / "web" / "src" / "lib" / "constants.ts"
    content = constants_path.read_text()

    regions: dict[str, list[str]] = {}
    # Match patterns like: { value: "DACH", label: "...", description: "Germany, Austria, Switzerland" }
    # Multiline: value on one line, description on next
    entries = re.findall(
        r'\{\s*value:\s*"([^"]+)"[^}]*description:\s*"([^"]+)"',
        content,
    )
    for value, description in entries:
        countries = [c.strip() for c in description.split(",")]
        regions[value] = countries
    return regions


class TestRegionSync:
    """Frontend region descriptions must match backend REGION_COUNTRIES."""

    def test_all_backend_regions_have_frontend_entry(self):
        frontend = _parse_frontend_regions()
        for region in REGION_COUNTRIES:
            assert region in frontend, (
                f"Region '{region}' exists in backend REGION_COUNTRIES but "
                f"has no description in web/src/lib/constants.ts"
            )

    def test_all_frontend_regions_have_backend_entry(self):
        frontend = _parse_frontend_regions()
        for region in frontend:
            assert region in REGION_COUNTRIES, (
                f"Region '{region}' has a description in constants.ts but "
                f"no entry in REGION_COUNTRIES (linkedin.py)"
            )

    def test_region_countries_match(self):
        frontend = _parse_frontend_regions()
        for region, backend_countries in REGION_COUNTRIES.items():
            if region not in frontend:
                continue  # caught by other test
            fe_countries = frontend[region]
            assert set(fe_countries) == set(backend_countries), (
                f"Region '{region}' mismatch:\n"
                f"  Backend:  {sorted(backend_countries)}\n"
                f"  Frontend: {sorted(fe_countries)}"
            )
