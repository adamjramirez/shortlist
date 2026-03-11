"""Sanity tests for location filter — catch false rejections from HN's messy format."""
import pytest

from shortlist.collectors.base import RawJob
from shortlist.processors.filter import apply_hard_filters, _looks_like_location
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter


@pytest.fixture
def config():
    return Config(
        filters=Filters(
            location=LocationFilter(
                remote=True, local_zip="75098", max_commute_minutes=30,
                local_cities=["dallas", "fort worth", "plano", "frisco", "mckinney"],
            ),
            salary=SalaryFilter(min_base=250000),
            role_type=RoleTypeFilter(reject_explicit_ic=True),
        ),
    )


def _make_job(**kwargs) -> RawJob:
    defaults = dict(
        title="Engineering Manager",
        company="Acme",
        url="https://acme.com/jobs/1",
        description="Lead a team of 25 engineers.",
        source="hn",
        location=None,
        salary_text=None,
    )
    defaults.update(kwargs)
    return RawJob(**defaults)


class TestLooksLikeLocation:
    """The filter should distinguish real locations from HN parser garbage."""

    def test_real_cities(self):
        assert _looks_like_location("San Francisco, CA")
        assert _looks_like_location("New York, NY")
        assert _looks_like_location("London, UK")
        assert _looks_like_location("Berlin, Germany")
        assert _looks_like_location("Dallas, TX")
        assert _looks_like_location("Austin, TX")

    def test_remote_variants(self):
        assert _looks_like_location("Remote")
        assert _looks_like_location("REMOTE")
        assert _looks_like_location("Remote (US only)")
        assert _looks_like_location("US, REMOTE")

    def test_full_time_is_not_location(self):
        assert not _looks_like_location("Full-Time")
        assert not _looks_like_location("Full-time")
        assert not _looks_like_location("Full Time")
        assert not _looks_like_location("Fulltime")
        assert not _looks_like_location("Full-Time, Onsite")

    def test_job_titles_are_not_locations(self):
        assert not _looks_like_location("Software Engineer")
        assert not _looks_like_location("Software Engineers")
        assert not _looks_like_location("Senior Backend Developer")
        assert not _looks_like_location("Director of Engineering")
        assert not _looks_like_location("Engineering")
        assert not _looks_like_location("Data Scientist (Commercial)")
        assert not _looks_like_location("Multiple Engineering Roles")
        assert not _looks_like_location("Frontend, Backend, Full-Stack")

    def test_urls_are_not_locations(self):
        assert not _looks_like_location("https://www.barracuda.com")
        assert not _looks_like_location("https://strateos.com")
        assert not _looks_like_location("https://level.com/")

    def test_visa_is_not_location(self):
        assert not _looks_like_location("VISA")

    def test_onsite_alone_is_not_location(self):
        """'Onsite' without a city is ambiguous — should pass through."""
        assert not _looks_like_location("Onsite")
        assert not _looks_like_location("ONSITE")

    def test_onsite_with_city_is_location(self):
        assert _looks_like_location("Onsite SF")
        assert _looks_like_location("Onsite in San Francisco")
        assert _looks_like_location("ONSITE Seattle")

    def test_hybrid_with_city(self):
        assert _looks_like_location("Hybrid - Dallas, TX")
        assert _looks_like_location("San Francisco (On-site)")


class TestLocationFilterWithGarbageLocations:
    """Jobs with non-location strings in the location field should NOT be rejected."""

    def test_full_time_location_passes(self, config):
        job = _make_job(location="Full-Time")
        result = apply_hard_filters(job, config)
        assert result.passed, f"'Full-Time' location should pass, got: {result.reason}"

    def test_job_title_as_location_passes(self, config):
        job = _make_job(location="Software Engineers")
        result = apply_hard_filters(job, config)
        assert result.passed, f"'Software Engineers' location should pass, got: {result.reason}"

    def test_engineering_as_location_passes(self, config):
        job = _make_job(location="Engineering")
        result = apply_hard_filters(job, config)
        assert result.passed, f"'Engineering' location should pass, got: {result.reason}"

    def test_url_as_location_passes(self, config):
        job = _make_job(location="https://www.example.com")
        result = apply_hard_filters(job, config)
        assert result.passed, f"URL as location should pass, got: {result.reason}"

    def test_visa_as_location_passes(self, config):
        job = _make_job(location="VISA")
        result = apply_hard_filters(job, config)
        assert result.passed, f"'VISA' as location should pass, got: {result.reason}"

    def test_onsite_without_city_passes(self, config):
        job = _make_job(location="Onsite")
        result = apply_hard_filters(job, config)
        assert result.passed, f"'Onsite' without city should pass, got: {result.reason}"

    def test_real_non_local_location_still_rejected(self, config):
        """Real locations that aren't remote or local should still be rejected."""
        job = _make_job(location="San Francisco, CA")
        result = apply_hard_filters(job, config)
        assert not result.passed

    def test_remote_still_passes(self, config):
        job = _make_job(location="Remote")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_local_still_passes(self, config):
        job = _make_job(location="Dallas, TX")
        result = apply_hard_filters(job, config)
        assert result.passed
