"""Unit tests for the displayed posted_at date.

We show the source's posted/updated date (posted_at), falling back to
first_seen only when the source gave no date. No clamp to first_seen — users
want the source's posting date, not our crawl time. Pure function, no DB/async.
"""
from datetime import datetime, timezone

from shortlist.api.routes.jobs import _effective_posted_at


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_source_date_shown_even_when_after_first_seen():
    # A repost date later than first_seen is now shown (not clamped away) —
    # it's the source's "last posted/updated" signal.
    posted = _dt(2026, 7, 2)
    first = _dt(2026, 3, 12)
    assert _effective_posted_at(posted, first) == posted


def test_source_date_shown_when_before_first_seen():
    posted = _dt(2026, 3, 1)
    first = _dt(2026, 3, 12)
    assert _effective_posted_at(posted, first) == posted


def test_falls_back_to_first_seen_when_no_source_date():
    first = _dt(2026, 3, 12)
    assert _effective_posted_at(None, first) == first


def test_source_date_kept_when_no_first_seen():
    posted = _dt(2026, 3, 1)
    assert _effective_posted_at(posted, None) == posted


def test_none_when_both_absent():
    assert _effective_posted_at(None, None) is None
