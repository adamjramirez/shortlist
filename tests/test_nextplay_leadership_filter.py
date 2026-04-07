"""Tests for NextPlay leadership title filter."""
import pytest
from shortlist.collectors.nextplay import _is_leadership_role


@pytest.mark.parametrize("title,expected", [
    # Should match — leadership roles
    ("VP of Engineering", True),
    ("SVP Engineering", True),
    ("CTO", True),
    ("Chief Technology Officer", True),
    ("Chief AI Officer", True),
    ("Head of Engineering", True),
    ("Head of AI", True),
    ("Director of Engineering", True),
    ("Senior Director, Engineering", True),
    ("VP, AI Engineering", True),
    ("General Manager, Platform", True),
    ("President of Engineering", True),
    ("CPO", True),
    ("COO", True),
    # Should not match — IC / non-leadership roles
    ("Software Engineer", False),
    ("Staff Engineer", False),
    ("Engineering Manager", False),
    ("Senior Software Engineer", False),
    ("Product Manager", False),
    ("Data Scientist", False),
    ("Account Executive", False),
    ("Marketing Manager", False),
    ("Technical Recruiter", False),
    ("DevOps Engineer", False),
])
def test_is_leadership_role(title, expected):
    assert _is_leadership_role(title) == expected


def test_leadership_filter_case_insensitive():
    assert _is_leadership_role("vp of engineering")
    assert _is_leadership_role("HEAD OF AI")
    assert _is_leadership_role("cto")


def test_title_filter_applied_after_cache_in_probe_homepages():
    """Filter runs on in-memory objects after _probe_one returns — cache is unaffected."""
    from unittest.mock import patch
    from shortlist.collectors.nextplay import NextPlayCollector
    from shortlist.collectors.base import RawJob
    from shortlist.collectors import career_page

    jobs_on_board = [
        RawJob(title="VP of Engineering", company="acme", url="u1", description="d", source="ashby"),
        RawJob(title="Software Engineer", company="acme", url="u2", description="d", source="ashby"),
        RawJob(title="CTO", company="acme", url="u3", description="d", source="ashby"),
        RawJob(title="Account Executive", company="acme", url="u4", description="d", source="ashby"),
    ]
    original = career_page.FETCHERS.get("ashby")
    career_page.FETCHERS["ashby"] = lambda slug: jobs_on_board
    try:
        with patch("shortlist.collectors.nextplay.discover_ats_from_domain", return_value=("ashby", "acme")):
            collector = NextPlayCollector(probe_ats=True, title_filter=_is_leadership_role)
            results = collector._probe_homepages(["acme.io"])
    finally:
        if original is not None:
            career_page.FETCHERS["ashby"] = original

    # Only VP of Engineering and CTO pass the filter
    assert len(results) == 2
    assert {j.title for j in results} == {"VP of Engineering", "CTO"}


def test_no_title_filter_returns_all_jobs():
    """Without title_filter, all jobs are returned (default behaviour, preserves cache semantics)."""
    from unittest.mock import patch
    from shortlist.collectors.nextplay import NextPlayCollector
    from shortlist.collectors.base import RawJob
    from shortlist.collectors import career_page

    jobs_on_board = [
        RawJob(title="VP of Engineering", company="acme", url="u1", description="d", source="ashby"),
        RawJob(title="Software Engineer", company="acme", url="u2", description="d", source="ashby"),
    ]
    original = career_page.FETCHERS.get("ashby")
    career_page.FETCHERS["ashby"] = lambda slug: jobs_on_board
    try:
        with patch("shortlist.collectors.nextplay.discover_ats_from_domain", return_value=("ashby", "acme")):
            collector = NextPlayCollector(probe_ats=True)  # no title_filter
            results = collector._probe_homepages(["acme.io"])
    finally:
        if original is not None:
            career_page.FETCHERS["ashby"] = original

    assert len(results) == 2
