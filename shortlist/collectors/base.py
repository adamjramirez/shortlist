"""Base collector protocol and shared types."""
import hashlib
import re
from dataclasses import dataclass, field
from typing import Protocol


def normalize_description(text: str) -> str:
    """Normalize description text for consistent hashing."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def description_hash(text: str) -> str:
    """SHA-256 hash of normalized description."""
    normalized = normalize_description(text)
    return hashlib.sha256(normalized.encode()).hexdigest()


@dataclass
class RawJob:
    """A job listing as collected from a source, before processing."""
    title: str
    company: str
    url: str
    description: str
    source: str
    location: str | None = None
    salary_text: str | None = None
    posted_at: str | None = None
    description_hash: str = ""

    def __post_init__(self):
        if not self.description_hash:
            self.description_hash = description_hash(self.description)


class BaseCollector(Protocol):
    """Protocol that all collectors must implement."""

    def fetch_new(self) -> list[RawJob]:
        """Fetch new job listings from this source."""
        ...
