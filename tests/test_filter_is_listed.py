"""Tests for is_listed_salary helper."""
import pytest

from shortlist.processors.filter import is_listed_salary


@pytest.mark.parametrize("salary_text, expected", [
    (None, False),
    ("$200k", True),
    ("$200,000", True),
    ("$13", False),      # HN noise — below $30k internal filter
    ("$40k", False),     # Below $50k threshold
    ("$5k/month", False),  # Monthly rate
])
def test_is_listed_salary(salary_text, expected):
    assert is_listed_salary(salary_text) == expected
