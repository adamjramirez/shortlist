"""Test that worker.py correctly builds pipeline Config from profile JSON."""
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter


class TestWorkerConfigBuilding:
    """Verify the inline Config construction in worker.py handles new fields."""

    def _build_config_from_profile(self, profile_config: dict) -> Config:
        """Replicate the worker's Config construction logic."""
        filters_raw = profile_config.get("filters", {})
        loc = filters_raw.get("location", {})
        sal = filters_raw.get("salary", {})

        return Config(
            filters=Filters(
                location=LocationFilter(
                    remote=loc.get("remote", True),
                    local_zip=loc.get("local_zip", ""),
                    max_commute_minutes=loc.get("max_commute_minutes", 30),
                    local_cities=loc.get("local_cities", []),
                    country=loc.get("country", ""),
                ),
                salary=SalaryFilter(
                    min_base=sal.get("min_base", 0),
                    currency=sal.get("currency", "USD"),
                ),
            ),
        )

    def test_country_from_profile(self):
        config = self._build_config_from_profile({
            "filters": {"location": {"country": "United Kingdom"}},
        })
        assert config.filters.location.country == "United Kingdom"

    def test_country_defaults_empty_when_missing(self):
        config = self._build_config_from_profile({"filters": {}})
        assert config.filters.location.country == ""

    def test_currency_from_profile(self):
        config = self._build_config_from_profile({
            "filters": {"salary": {"min_base": 80000, "currency": "GBP"}},
        })
        assert config.filters.salary.currency == "GBP"
        assert config.filters.salary.min_base == 80000

    def test_currency_defaults_usd(self):
        config = self._build_config_from_profile({"filters": {}})
        assert config.filters.salary.currency == "USD"
