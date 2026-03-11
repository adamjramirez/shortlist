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
    local_cities: list[str] = field(default_factory=list)  # cities near you


@dataclass
class SalaryFilter:
    min_base: int = 0
    currency: str = "USD"  # currency of min_base (USD, GBP, EUR, INR, etc.)


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


class ConfigError(Exception):
    """Raised when config validation fails. Message is user-friendly."""
    pass


def validate_config(config: Config, project_root: Path) -> list[str]:
    """Validate config and return list of error messages. Empty = valid."""
    errors = []

    if not config.name or config.name == "Your Name":
        errors.append("Set your name in config/profile.yaml (currently 'Your Name')")

    if not config.fit_context or "Describe what" in config.fit_context:
        errors.append(
            "Write a fit_context in config/profile.yaml — describe what roles you're "
            "looking for, your background, and what should score high vs. low"
        )

    if not config.tracks:
        errors.append(
            "Add at least one track to config/profile.yaml (e.g., 'em' with title, "
            "resume path, and search_queries)"
        )

    for key, track in config.tracks.items():
        if not track.title:
            errors.append(f"Track '{key}': missing title")

        paths = track.get_resume_paths()
        if not paths:
            errors.append(
                f"Track '{key}': no resume configured. Add 'resume: resumes/your_resume.tex' "
                f"to the track in config/profile.yaml"
            )
        for p in paths:
            full = project_root / p
            if not full.exists():
                errors.append(
                    f"Track '{key}': resume not found at {p} — "
                    f"put your LaTeX resume at {full}"
                )

        if not track.search_queries:
            errors.append(
                f"Track '{key}': no search_queries. Add keywords like "
                f"'Engineering Manager' for LinkedIn searches"
            )

    return errors


def validate_env(project_root: Path, config: "Config | None" = None) -> list[str]:
    """Validate .env file and return list of error messages."""
    import os
    from dotenv import dotenv_values, load_dotenv
    from shortlist.llm import detect_provider, _ENV_KEYS

    env_path = project_root / ".env"
    errors = []

    if not env_path.exists():
        errors.append(
            "Missing .env file. Create one with your LLM API key.\n"
            "  Run 'shortlist init' to generate a template."
        )
        return errors

    # override=True ensures .env values win over stale environment
    load_dotenv(env_path, override=True)
    env_vals = dotenv_values(env_path)

    # Determine which provider/key we need
    model = config.llm.model if config else "gemini-2.5-flash"
    provider = detect_provider(model)
    env_key = _ENV_KEYS[provider]
    key = env_vals.get(env_key, "") or os.environ.get(env_key, "")

    _KEY_HELP = {
        "gemini": (
            f"{env_key} not set in .env. Get a key at:\n"
            "  https://aistudio.google.com/ → Get API key → Create API key\n"
            f"Then add to .env: {env_key}=AIzaSy...your-key"
        ),
        "openai": (
            f"{env_key} not set in .env. Get a key at:\n"
            "  https://platform.openai.com/api-keys\n"
            f"Then add to .env: {env_key}=sk-...your-key"
        ),
        "anthropic": (
            f"{env_key} not set in .env. Get a key at:\n"
            "  https://console.anthropic.com/settings/keys\n"
            f"Then add to .env: {env_key}=sk-ant-...your-key"
        ),
    }

    if not key or key == "your-key-here":
        errors.append(_KEY_HELP.get(provider, f"{env_key} not set in .env."))
    else:
        # Basic format check
        _PREFIX_CHECK = {
            "gemini": ("AIza", "Google API keys usually start with 'AIza'"),
            "openai": ("sk-", "OpenAI API keys usually start with 'sk-'"),
            "anthropic": ("sk-ant-", "Anthropic API keys usually start with 'sk-ant-'"),
        }
        expected_prefix, hint = _PREFIX_CHECK.get(provider, ("", ""))
        if expected_prefix and not key.startswith(expected_prefix):
            errors.append(
                f"{env_key} looks wrong (starts with '{key[:6]}...'). "
                f"{hint} Check your .env file."
            )

    return errors


def test_llm_key(project_root: Path | None = None, config: "Config | None" = None) -> str | None:
    """Make a tiny LLM API call to verify the key works.

    Returns None on success, or an error message string.
    """
    from shortlist.llm import detect_provider, _make_provider

    model = config.llm.model if config else "gemini-2.5-flash"
    provider_name = detect_provider(model)

    try:
        provider = _make_provider(provider_name)
    except ValueError as e:
        return None  # Already caught by validate_env

    try:
        result = provider.call("Reply with just the word 'ok'.", model)
        if result:
            return None  # Success
        return f"{provider_name} API returned empty response. Key may be invalid."
    except Exception as e:
        err = str(e).lower()
        if any(s in err for s in ("api_key", "invalid", "permission", "403", "401", "authentication")):
            return (
                f"{provider_name} API key is invalid.\n"
                f"  Double-check the key in your .env file."
            )
        if "quota" in err or "429" in err or "rate" in err:
            return (
                f"{provider_name} API rate limit or quota exceeded.\n"
                f"  Check your usage and billing."
            )
        return f"{provider_name} API test failed: {e}"
