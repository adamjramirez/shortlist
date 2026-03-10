"""Tests for CLI commands."""
import pytest
from click.testing import CliRunner

from shortlist.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestCli:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "shortlist" in result.output.lower() or "Usage" in result.output

    def test_run_command_exists(self, runner):
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0

    def test_collect_command_exists(self, runner):
        result = runner.invoke(cli, ["collect", "--help"])
        assert result.exit_code == 0

    def test_brief_command_exists(self, runner):
        result = runner.invoke(cli, ["brief", "--help"])
        assert result.exit_code == 0

    def test_today_command_exists(self, runner):
        result = runner.invoke(cli, ["today", "--help"])
        assert result.exit_code == 0

    def test_status_command_exists(self, runner):
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0

    def test_health_command_exists(self, runner):
        result = runner.invoke(cli, ["health", "--help"])
        assert result.exit_code == 0
