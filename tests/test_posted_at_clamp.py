"""Unit tests for the posted_at <= first_seen clamp.

LinkedIn reposts carry a repost date, and f_TPR surfaces reposts as fresh, so
a job first seen months ago can acquire a posted_at of "yesterday". A posting
date later than when we first saw the job is a repost artifact — the effective
age should fall back to first_seen. Pure function, no DB/async.
"""
from datetime import datetime, timezone

from shortlist.api.routes.jobs import _effective_posted_at


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_posted_after_first_seen_clamps_to_first_seen():
    # Real incident: Oracle job first_seen 2026-03-12, posted_at 2026-07-02.
    posted = _dt(2026, 7, 2)
    first = _dt(2026, 3, 12)
    assert _effective_posted_at(posted, first) == first


def test_posted_before_first_seen_is_kept():
    posted = _dt(2026, 3, 1)
    first = _dt(2026, 3, 12)
    assert _effective_posted_at(posted, first) == posted


def test_posted_equal_first_seen_is_kept():
    d = _dt(2026, 3, 12)
    assert _effective_posted_at(d, d) == d


def test_none_posted_stays_none():
    assert _effective_posted_at(None, _dt(2026, 3, 12)) is None


def test_none_first_seen_keeps_posted():
    posted = _dt(2026, 3, 1)
    assert _effective_posted_at(posted, None) == posted
