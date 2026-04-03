"""Test JobStatusUpdate schema accepts clear and rejects invalid statuses."""
import pytest
from pydantic import ValidationError
from shortlist.api.schemas import JobStatusUpdate


def test_status_clear_accepted():
    update = JobStatusUpdate(status="clear")
    assert update.status == "clear"


def test_status_saved_accepted():
    update = JobStatusUpdate(status="saved")
    assert update.status == "saved"


def test_status_applied_accepted():
    update = JobStatusUpdate(status="applied")
    assert update.status == "applied"


def test_status_skipped_accepted():
    update = JobStatusUpdate(status="skipped")
    assert update.status == "skipped"


def test_status_invalid_rejected():
    with pytest.raises(ValidationError):
        JobStatusUpdate(status="invalid")


def test_status_empty_rejected():
    with pytest.raises(ValidationError):
        JobStatusUpdate(status="")
