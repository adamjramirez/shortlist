"""End-to-end currency filter tests.

Verifies that users in different countries with min_base in their local
currency correctly filter jobs listed in various international currencies.
All jobs are Remote to isolate salary filtering from location filtering.
"""
import pytest

from shortlist.collectors.base import RawJob
from shortlist.config import Config, Filters, LocationFilter, SalaryFilter, RoleTypeFilter
from shortlist.processors.filter import apply_hard_filters, _parse_max_salary, _min_base_to_usd


# ---------------------------------------------------------------------------
# Jobs: real-world salary formats from international listings, all Remote
# ---------------------------------------------------------------------------

JOBS = [
    RawJob(title="Engineering Manager", company="Stripe (US)", url="https://stripe.com/jobs/1",
           description="Lead payments platform team. Remote.", source="hn",
           location="Remote", salary_text="$280,000 - $350,000"),
    RawJob(title="VP Engineering", company="Deliveroo (UK)", url="https://deliveroo.co.uk/jobs/1",
           description="Lead 60-person eng org. Remote.", source="hn",
           location="Remote", salary_text="£180,000 - £220,000"),
    RawJob(title="Head of Engineering", company="Klarna (SE)", url="https://klarna.com/jobs/1",
           description="Lead fintech platform. Remote.", source="hn",
           location="Remote", salary_text="kr 850,000"),
    RawJob(title="Engineering Director", company="Zalando (DE)", url="https://zalando.de/jobs/1",
           description="Lead e-commerce platform. Remote.", source="hn",
           location="Remote", salary_text="€150,000 - €190,000"),
    RawJob(title="CTO", company="Razorpay (IN)", url="https://razorpay.com/jobs/1",
           description="Lead all engineering. Remote.", source="hn",
           location="Remote", salary_text="₹1,20,00,000 - ₹1,50,00,000"),
    RawJob(title="VP Engineering", company="UBS (CH)", url="https://ubs.com/jobs/1",
           description="Lead digital banking eng. Remote.", source="hn",
           location="Remote", salary_text="CHF 250,000 - CHF 300,000"),
    RawJob(title="Engineering Manager", company="Nubank (BR)", url="https://nubank.com.br/jobs/1",
           description="Lead backend team. Remote.", source="hn",
           location="Remote", salary_text="R$540,000"),
    RawJob(title="Director Engineering", company="Atlassian (AU)", url="https://atlassian.com/jobs/1",
           description="Lead platform team. Remote.", source="hn",
           location="Remote", salary_text="A$320,000 - A$380,000"),
    RawJob(title="Head of Platform", company="Shopify (CA)", url="https://shopify.com/jobs/1",
           description="Lead platform org. Remote.", source="hn",
           location="Remote", salary_text="C$300,000 - C$350,000"),
    RawJob(title="VP Engineering", company="Wix (IL)", url="https://wix.com/jobs/1",
           description="Lead product eng. Remote.", source="hn",
           location="Remote", salary_text="₪780,000"),
    RawJob(title="Senior EM", company="Mystery Co", url="https://mystery.com/jobs/1",
           description="Lead team. Competitive salary.", source="hn",
           location="Remote", salary_text="competitive"),
    RawJob(title="Engineering Lead", company="Stealth Startup", url="https://stealth.com/jobs/1",
           description="First eng hire. Remote.", source="hn",
           location="Remote", salary_text=None),
]


def _make_config(min_base: int, currency: str = "USD") -> Config:
    return Config(
        filters=Filters(
            location=LocationFilter(remote=True),
            salary=SalaryFilter(min_base=min_base, currency=currency),
            role_type=RoleTypeFilter(reject_explicit_ic=False),
        ),
    )


def _filter_jobs(config: Config) -> tuple[list[str], list[str], list[str]]:
    """Run all jobs through filters. Returns (passed, rejected_salary, passed_unparsed)."""
    passed = []
    rejected_salary = []
    passed_unparsed = []
    for job in JOBS:
        result = apply_hard_filters(job, config)
        if result.passed:
            parsed = _parse_max_salary(job.salary_text) if job.salary_text else None
            if parsed is None:
                passed_unparsed.append(job.company)
            else:
                passed.append(job.company)
        elif "salary" in (result.reason or "").lower():
            rejected_salary.append(job.company)
    return passed, rejected_salary, passed_unparsed


# ---------------------------------------------------------------------------
# Salary parsing: verify each currency parses to a reasonable USD value
# ---------------------------------------------------------------------------

class TestInternationalSalaryParsing:
    """Verify each currency format parses to the correct approximate USD value."""

    def test_usd(self):
        assert _parse_max_salary("$280,000 - $350,000") == 350_000

    def test_gbp(self):
        usd = _parse_max_salary("£180,000 - £220,000")
        assert 270_000 <= usd <= 280_000  # £220k * 1.25

    def test_sek(self):
        usd = _parse_max_salary("kr 850,000")
        assert 75_000 <= usd <= 85_000  # 850k * 0.095

    def test_eur(self):
        usd = _parse_max_salary("€150,000 - €190,000")
        assert 200_000 <= usd <= 215_000  # €190k * 1.10

    def test_inr(self):
        usd = _parse_max_salary("₹1,20,00,000 - ₹1,50,00,000")
        assert 170_000 <= usd <= 185_000  # ₹1.5Cr * 0.012

    def test_chf(self):
        usd = _parse_max_salary("CHF 250,000 - CHF 300,000")
        assert 340_000 <= usd <= 350_000  # 300k * 1.15

    def test_brl(self):
        usd = _parse_max_salary("R$540,000")
        assert 95_000 <= usd <= 100_000  # 540k * 0.18

    def test_aud(self):
        usd = _parse_max_salary("A$320,000 - A$380,000")
        assert 245_000 <= usd <= 250_000  # 380k * 0.65

    def test_cad(self):
        usd = _parse_max_salary("C$300,000 - C$350,000")
        assert 250_000 <= usd <= 260_000  # 350k * 0.73

    def test_ils(self):
        usd = _parse_max_salary("₪780,000")
        assert 215_000 <= usd <= 220_000  # 780k * 0.28

    def test_unparseable_returns_none(self):
        assert _parse_max_salary("competitive") is None

    def test_no_salary_returns_none(self):
        assert _parse_max_salary("") is None


# ---------------------------------------------------------------------------
# User scenarios: different countries, different min_base currencies
# ---------------------------------------------------------------------------

class TestIndianUser:
    """Indian user: min_base = ₹40 lakh (≈$48k USD). Low bar — most jobs pass."""

    @pytest.fixture()
    def config(self):
        return _make_config(4_000_000, "INR")

    def test_min_base_converts_correctly(self, config):
        usd = _min_base_to_usd(config)
        assert 47_000 <= usd <= 49_000

    def test_all_parseable_salaries_pass(self, config):
        """At ≈$48k min, every real salary in our set should pass."""
        passed, rejected, _ = _filter_jobs(config)
        assert len(rejected) == 0
        assert len(passed) >= 8  # all parseable currencies

    def test_usd_job_passes(self, config):
        job = JOBS[0]  # Stripe $280-350k
        assert apply_hard_filters(job, config).passed

    def test_inr_job_passes(self, config):
        job = JOBS[4]  # Razorpay ₹1.2-1.5 Cr
        assert apply_hard_filters(job, config).passed


class TestUKUser:
    """UK user: min_base = £150k (≈$187k USD). Mid-range bar."""

    @pytest.fixture()
    def config(self):
        return _make_config(150_000, "GBP")

    def test_min_base_converts_correctly(self, config):
        assert _min_base_to_usd(config) == 187_500

    def test_high_usd_passes(self, config):
        job = JOBS[0]  # Stripe $280-350k
        assert apply_hard_filters(job, config).passed

    def test_gbp_at_threshold_passes(self, config):
        job = JOBS[1]  # Deliveroo £180-220k → ≈$275k
        assert apply_hard_filters(job, config).passed

    def test_low_sek_rejected(self, config):
        job = JOBS[2]  # Klarna kr 850k → ≈$80k
        assert not apply_hard_filters(job, config).passed

    def test_low_brl_rejected(self, config):
        job = JOBS[6]  # Nubank R$540k → ≈$97k
        assert not apply_hard_filters(job, config).passed

    def test_rejects_below_threshold(self, config):
        _, rejected, _ = _filter_jobs(config)
        assert len(rejected) >= 2  # at least SEK and BRL


class TestUSUser:
    """US user: min_base = $250k USD. High bar — pickiest filter."""

    @pytest.fixture()
    def config(self):
        return _make_config(250_000, "USD")

    def test_min_base_unchanged(self, config):
        assert _min_base_to_usd(config) == 250_000

    def test_high_usd_passes(self, config):
        job = JOBS[0]  # Stripe $350k
        assert apply_hard_filters(job, config).passed

    def test_chf_passes(self, config):
        job = JOBS[5]  # UBS CHF 300k → ≈$345k
        assert apply_hard_filters(job, config).passed

    def test_cad_passes(self, config):
        job = JOBS[8]  # Shopify C$350k → ≈$255k
        assert apply_hard_filters(job, config).passed

    def test_eur_below_rejected(self, config):
        job = JOBS[3]  # Zalando €190k → ≈$209k
        assert not apply_hard_filters(job, config).passed

    def test_sek_rejected(self, config):
        job = JOBS[2]  # Klarna kr 850k → ≈$80k
        assert not apply_hard_filters(job, config).passed

    def test_is_pickiest(self, config):
        """US $250k user should reject more than UK £150k user."""
        _, us_rejected, _ = _filter_jobs(config)
        _, uk_rejected, _ = _filter_jobs(_make_config(150_000, "GBP"))
        assert len(us_rejected) >= len(uk_rejected)

    def test_unparseable_and_missing_pass(self, config):
        """Jobs with no salary or 'competitive' always pass (benefit of the doubt)."""
        _, _, passed_unparsed = _filter_jobs(config)
        assert "Mystery Co" in passed_unparsed
        assert "Stealth Startup" in passed_unparsed


class TestEUUser:
    """EU user: min_base = €200k (≈$220k USD)."""

    @pytest.fixture()
    def config(self):
        return _make_config(200_000, "EUR")

    def test_min_base_converts_correctly(self, config):
        assert _min_base_to_usd(config) == 220_000

    def test_high_usd_passes(self, config):
        job = JOBS[0]  # Stripe $350k
        assert apply_hard_filters(job, config).passed

    def test_eur_below_own_threshold_rejected(self, config):
        job = JOBS[3]  # Zalando €190k → ≈$209k < $220k min
        assert not apply_hard_filters(job, config).passed

    def test_gbp_above_passes(self, config):
        job = JOBS[1]  # Deliveroo £220k → ≈$275k
        assert apply_hard_filters(job, config).passed
