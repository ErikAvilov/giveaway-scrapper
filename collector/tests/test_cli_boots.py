"""Smoke tests: the package and CLI boot without credentials."""

from __future__ import annotations

from click.testing import CliRunner

from app import __version__
from app.cli import main


def test_version_constant() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_boots() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "db-init" in result.output
    assert "crawl" in result.output
    assert "analyze" in result.output
    assert "stats" in result.output


def test_cli_version() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
