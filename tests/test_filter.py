"""Tests for hard filters."""
import pytest

from shortlist.collectors.base import RawJob
from shortlist.processors.filter import apply_hard_filters, FilterResult
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter


@pytest.fixture
def config():
    return Config(
        filters=Filters(
            location=LocationFilter(
                remote=True, local_zip="75098", max_commute_minutes=30,
                local_cities=[
                    "dallas", "fort worth", "plano", "frisco", "mckinney",
                    "allen", "richardson", "arlington", "irving",
                ],
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
        description="Lead a team of 25 engineers. Management role.",
        source="hn",
        location="Remote",
        salary_text=None,
    )
    defaults.update(kwargs)
    return RawJob(**defaults)


class TestLocationFilter:
    def test_remote_passes(self, config):
        job = _make_job(location="Remote")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_remote_case_insensitive(self, config):
        job = _make_job(location="REMOTE")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_remote_in_description_passes(self, config):
        job = _make_job(location=None, description="This is a fully remote position. Lead 25 engineers.")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_local_area_passes(self, config):
        job = _make_job(location="Dallas, TX")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_local_metro_cities_pass(self, config):
        for city in ["McKinney, TX", "Plano, TX", "Frisco, TX", "Allen, TX", "Dallas, TX", "Fort Worth, TX"]:
            job = _make_job(location=city)
            result = apply_hard_filters(job, config)
            assert result.passed, f"{city} should pass location filter"

    def test_remote_in_title_with_city_location_passes(self, config):
        """Jobs with REMOTE in title pass even if location field has a city."""
        job = _make_job(title="Director of Engineering [REMOTE]", location="San Francisco, CA")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_remote_in_title_variants_pass(self, config):
        for title in [
            "Engineering Manager - Remote USA",
            "Remote - Director of Engineering",
            "VP Engineering (Home Based / Remote)",
        ]:
            job = _make_job(title=title, location="Irvine, CA")
            result = apply_hard_filters(job, config)
            assert result.passed, f"Title '{title}' should pass"

    def test_non_remote_title_with_city_still_fails(self, config):
        job = _make_job(title="Director of Engineering", location="San Francisco, CA")
        result = apply_hard_filters(job, config)
        assert not result.passed

    def test_non_local_non_remote_fails(self, config):
        job = _make_job(location="New York, NY")
        result = apply_hard_filters(job, config)
        assert not result.passed
        assert "location" in result.reason.lower()

    def test_onsite_non_local_fails(self, config):
        job = _make_job(location="San Francisco, CA (On-site)")
        result = apply_hard_filters(job, config)
        assert not result.passed

    def test_no_location_passes(self, config):
        """Jobs with no location info pass through (benefit of the doubt)."""
        job = _make_job(location=None, description="Great EM role. Lead 25 engineers.")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_hybrid_local_passes(self, config):
        job = _make_job(location="Hybrid - Dallas, TX")
        result = apply_hard_filters(job, config)
        assert result.passed


class TestSalaryFilter:
    def test_no_salary_passes(self, config):
        """No salary listed = pass through."""
        job = _make_job(salary_text=None)
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_salary_above_min_passes(self, config):
        job = _make_job(salary_text="$280,000 - $320,000")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_salary_range_max_above_min_passes(self, config):
        job = _make_job(salary_text="$200,000 - $280,000")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_salary_below_min_fails(self, config):
        job = _make_job(salary_text="$150,000 - $180,000")
        result = apply_hard_filters(job, config)
        assert not result.passed
        assert "salary" in result.reason.lower()

    def test_salary_k_format(self, config):
        job = _make_job(salary_text="$280k - $320k")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_salary_k_below_min_fails(self, config):
        job = _make_job(salary_text="$150k-$180k")
        result = apply_hard_filters(job, config)
        assert not result.passed

    def test_unparseable_salary_passes(self, config):
        """If we can't parse the salary, pass through."""
        job = _make_job(salary_text="competitive")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_tiny_dollar_amount_not_treated_as_salary(self, config):
        """$32, $70, etc. are clearly not annual salaries — ignore."""
        for amount in ["$32", "$70", "$135", "$13"]:
            job = _make_job(salary_text=amount)
            result = apply_hard_filters(job, config)
            assert result.passed, f"'{amount}' should not be treated as salary, got: {result.reason}"


class TestRoleTypeFilter:
    def test_management_title_passes(self, config):
        job = _make_job(title="Engineering Manager")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_vp_title_passes(self, config):
        job = _make_job(title="VP Engineering")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_director_title_passes(self, config):
        job = _make_job(title="Director of Engineering")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_explicit_ic_in_title_fails(self, config):
        job = _make_job(title="Senior Software Engineer", description="Individual contributor role. No direct reports.")
        result = apply_hard_filters(job, config)
        assert not result.passed
        assert "ic" in result.reason.lower() or "individual" in result.reason.lower()

    def test_explicit_ic_in_description_fails(self, config):
        job = _make_job(
            title="Staff Engineer",
            description="This is an individual contributor role. No management responsibilities.",
        )
        result = apply_hard_filters(job, config)
        assert not result.passed

    def test_ambiguous_title_passes(self, config):
        """Titles like 'Head of Engineering' should pass even without explicit 'manager'."""
        job = _make_job(title="Head of Engineering")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_lead_title_passes(self, config):
        job = _make_job(title="Engineering Lead")
        result = apply_hard_filters(job, config)
        assert result.passed

    def test_intern_fails(self, config):
        job = _make_job(title="Software Engineering Intern", description="Summer internship program.")
        result = apply_hard_filters(job, config)
        assert not result.passed

    def test_junior_fails(self, config):
        job = _make_job(title="Junior Software Engineer", description="Entry level position.")
        result = apply_hard_filters(job, config)
        assert not result.passed


class TestFilterResult:
    def test_passed_result(self):
        result = FilterResult(passed=True)
        assert result.passed
        assert result.reason == ""

    def test_failed_result_has_reason(self):
        result = FilterResult(passed=False, reason="Salary below $250k")
        assert not result.passed
        assert "Salary" in result.reason
