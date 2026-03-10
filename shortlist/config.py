"""Configuration loading and models."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Track:
    title: str
    resume: str = ""  # single resume path
    resumes: list[str] = field(default_factory=list)  # multiple resume variants
    target_orgs: str = "any"
    min_reports: int = 0
    search_queries: list[str] = field(default_factory=list)

    def get_resume_paths(self) -> list[str]:
        """Return all resume paths for this track."""
        if self.resumes:
            return self.resumes
        if self.resume:
            return [self.resume]
        return []


@dataclass
class LocationFilter:
    remote: bool = True
    local_zip: str = ""
    max_commute_minutes: int = 30


@dataclass
class SalaryFilter:
    min_base: int = 0


@dataclass
class RoleTypeFilter:
    reject_explicit_ic: bool = True


@dataclass
class Filters:
    location: LocationFilter = field(default_factory=LocationFilter)
    salary: SalaryFilter = field(default_factory=SalaryFilter)
    role_type: RoleTypeFilter = field(default_factory=RoleTypeFilter)


@dataclass
class LLMConfig:
    model: str = "claude-sonnet-4-20250514"
    max_jobs_per_run: int = 50
    cost_budget_daily: float = 2.00


@dataclass
class BriefConfig:
    output_dir: str = "briefs/"
    top_n: int = 10
    show_filtered: bool = True
    stale_threshold_days: int = 7


@dataclass
class Config:
    name: str = ""
    fit_context: str = ""  # freeform text about what roles fit this person
    tracks: dict[str, Track] = field(default_factory=dict)
    filters: Filters = field(default_factory=Filters)
    preferences: dict[str, str] = field(default_factory=dict)
    llm: LLMConfig = field(default_factory=LLMConfig)
    brief: BriefConfig = field(default_factory=BriefConfig)


def _build_dataclass(cls, data: dict[str, Any] | None):
    """Build a dataclass from a dict, ignoring unknown keys."""
    if data is None:
        return cls()
    valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
    return cls(**{k: v for k, v in data.items() if k in valid_fields})


def load_config(path: Path) -> Config:
    """Load configuration from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    # Build tracks
    tracks = {}
    for key, track_data in raw.get("tracks", {}).items():
        tracks[key] = _build_dataclass(Track, track_data)

    # Build filters
    filters_raw = raw.get("filters", {})
    filters = Filters(
        location=_build_dataclass(LocationFilter, filters_raw.get("location")),
        salary=_build_dataclass(SalaryFilter, filters_raw.get("salary")),
        role_type=_build_dataclass(RoleTypeFilter, filters_raw.get("role_type")),
    )

    return Config(
        name=raw.get("name", ""),
        fit_context=raw.get("fit_context", ""),
        tracks=tracks,
        filters=filters,
        preferences=raw.get("preferences", {}),
        llm=_build_dataclass(LLMConfig, raw.get("llm")),
        brief=_build_dataclass(BriefConfig, raw.get("brief")),
    )
