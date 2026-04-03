"""Tests for config loading."""
import pytest

from shortlist.config import load_config, Config


@pytest.fixture
def config_dir(tmp_path):
    config_file = tmp_path / "profile.yaml"
    config_file.write_text("""
name: TestUser

tracks:
  em:
    title: Engineering Manager
    resume: resumes/em.md
    target_orgs: large
    min_reports: 20
    search_queries:
      - "Engineering Manager"
      - "Head of Engineering"
  vp:
    title: VP Engineering
    resume: resumes/vp.md
    target_orgs: series_b_plus
    min_reports: 20
    search_queries:
      - "VP Engineering"
      - "VP of Engineering"

filters:
  location:
    remote: true
    local_zip: "75098"
    max_commute_minutes: 30
  salary:
    min_base: 250000
  role_type:
    reject_explicit_ic: true

preferences:
  equity: nice_to_have
  travel: minimal
  series_a_fresh_funding: yellow_flag

llm:
  model: claude-sonnet-4-20250514
  max_jobs_per_run: 50
  cost_budget_daily: 2.00

brief:
  output_dir: briefs/
  top_n: 10
  show_filtered: true
  stale_threshold_days: 7
""")
    return tmp_path


class TestLoadConfig:
    def test_loads_yaml(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert isinstance(config, Config)

    def test_has_name(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert config.name == "TestUser"

    def test_has_tracks(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert "em" in config.tracks
        assert "vp" in config.tracks

    def test_track_has_search_queries(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert "Engineering Manager" in config.tracks["em"].search_queries
        assert "Head of Engineering" in config.tracks["em"].search_queries

    def test_track_has_resume_path(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert config.tracks["em"].resume == "resumes/em.md"

    def test_filters_location(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert config.filters.location.remote is True
        assert config.filters.location.local_zip == "75098"
        assert config.filters.location.max_commute_minutes == 30
        assert config.filters.location.country == ""  # default: empty

    def test_filters_location_with_country(self, config_dir):
        """Country field round-trips through YAML config."""
        yaml_path = config_dir / "profile.yaml"
        content = yaml_path.read_text()
        content = content.replace(
            "  location:\n    remote: true\n    local_zip: \"75098\"",
            "  location:\n    remote: true\n    local_zip: \"75098\"\n    country: \"United Kingdom\"",
        )
        yaml_path.write_text(content)
        config = load_config(yaml_path)
        assert config.filters.location.country == "United Kingdom"

    def test_filters_salary(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert config.filters.salary.min_base == 250000

    def test_llm_config(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert config.llm.model == "claude-sonnet-4-20250514"
        assert config.llm.max_jobs_per_run == 50
        assert config.llm.cost_budget_daily == 2.00

    def test_brief_config(self, config_dir):
        config = load_config(config_dir / "profile.yaml")
        assert config.brief.top_n == 10
        assert config.brief.stale_threshold_days == 7

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")
