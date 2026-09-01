"""Unit and integration tests for CLI commands."""

from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest
from typer.testing import CliRunner

from gitrelevance.cli.commands import app, set_provider_override
from gitrelevance.issues.models import Issue, PullRequest
from tests.fixtures.repo_builder import RepoBuilder


runner = CliRunner()


class FakeCLIProvider:
    """In-memory provider for CLI tests."""

    def __init__(self, issues: list[Issue] | None = None, prs: list[PullRequest] | None = None) -> None:
        self._issues = issues or []
        self._prs = prs or []

    def parse_remote(self, remote_url: str) -> tuple[str, str] | None:
        return ("testowner", "testrepo")

    def get_issues(self, state: str = "all") -> list[Issue]:
        if state == "all":
            return self._issues
        return [i for i in self._issues if i.state == state]

    def get_pull_requests(self, state: str = "all") -> list[PullRequest]:
        return self._prs

    def get_issue_comments(self, issue_number: int) -> list[str]:
        return []


def make_issue(number: int = 1, title: str = "Bug in login", state: str = "closed", created_at: datetime | None = None) -> Issue:
    return Issue(
        number=number,
        title=title,
        body="Body",
        state="closed" if state == "closed" else "open",
        created_at=created_at or datetime(2024, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc) if state == "closed" else None,
        labels=(),
        linked_pr_numbers=(),
    )


@pytest.fixture(autouse=True)
def cleanup_provider_override():
    """Ensure provider override is reset after each test."""
    yield
    set_provider_override(None)


def test_cli_outside_git_repo(tmp_path) -> None:
    """Running gitrelevance analyze outside a git repo fails gracefully with exit code 1."""
    result = runner.invoke(app, ["analyze", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "not a Git repository" in result.output


def test_cli_repo_without_remote() -> None:
    """Running gitrelevance in a repo without an origin remote fails with clear error."""
    builder = RepoBuilder().commit("Initial commit", files={"README.md": "readme"})
    path = builder.build()
    try:
        result = runner.invoke(app, ["analyze", "--path", path])
        assert result.exit_code == 1
        assert "No 'origin' remote found" in result.output
    finally:
        builder.cleanup()


def test_cli_repo_with_non_github_remote() -> None:
    """Running in a repo with a non-GitHub remote fails with clear error."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "readme"})
        .add_remote("origin", "https://gitlab.com/owner/repo.git")
    )
    path = builder.build()
    try:
        result = runner.invoke(app, ["analyze", "--path", path])
        assert result.exit_code == 1
        assert "not a recognized" in result.output
        assert "GitHub" in result.output
    finally:
        builder.cleanup()


def test_cli_analyze_normal_flow() -> None:
    """Normal execution with GitHub remote and provider override prints terminal report."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "readme"})
        .commit("Fix #1: login bug", files={"auth.py": "def login(): pass"})
        .add_remote("origin", "https://github.com/testowner/testrepo.git")
    )
    path = builder.build()
    try:
        issue = make_issue(number=1, title="Login bug", state="closed")
        fake_provider = FakeCLIProvider(issues=[issue])
        set_provider_override(fake_provider)

        result = runner.invoke(app, ["analyze", "--path", path])
        assert result.exit_code == 0
        assert "GitRelevance" in result.output
        assert "Repository: github.com/testowner/testrepo" in result.output
        assert "RESOLVED" in result.output
        assert "#1 Login bug" in result.output
    finally:
        builder.cleanup()


def test_cli_analyze_json_flow() -> None:
    """Running with --json outputs valid parseable JSON with full results."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "readme"})
        .commit("Fix #1: login bug", files={"auth.py": "def login(): pass"})
        .add_remote("origin", "git@github.com:testowner/testrepo.git")
    )
    path = builder.build()
    try:
        issue = make_issue(number=1, title="Login bug", state="closed")
        fake_provider = FakeCLIProvider(issues=[issue])
        set_provider_override(fake_provider)

        result = runner.invoke(app, ["analyze", "--path", path, "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_issues"] == 1
        assert data["results"][0]["classification"] == "RESOLVED"
        assert data["results"][0]["issue"]["number"] == 1
    finally:
        builder.cleanup()


def test_cli_since_filter() -> None:
    """--since filters out issues created before the specified date."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "readme"})
        .add_remote("origin", "https://github.com/testowner/testrepo.git")
    )
    path = builder.build()
    try:
        i_old = make_issue(number=1, title="Old issue", created_at=datetime(2023, 1, 1, tzinfo=timezone.utc))
        i_new = make_issue(number=2, title="New issue", created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
        fake_provider = FakeCLIProvider(issues=[i_old, i_new])
        set_provider_override(fake_provider)

        result = runner.invoke(app, ["analyze", "--path", path, "--since", "2024-01-01", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_issues"] == 1
        assert data["results"][0]["issue"]["number"] == 2
    finally:
        builder.cleanup()


def test_cli_token_option_and_auth_command(tmp_path, monkeypatch) -> None:
    """--token flag and auth command work properly."""
    # Test auth command
    custom_token_file = tmp_path / "token"
    monkeypatch.setattr("gitrelevance.config.TOKEN_FILE", custom_token_file)
    monkeypatch.setattr("gitrelevance.config.CONFIG_DIR", tmp_path)

    result = runner.invoke(app, ["auth", "--token", "ghp_mock_token_12345"])
    assert result.exit_code == 0
    assert "Token saved successfully" in result.output
    assert custom_token_file.read_text(encoding="utf-8").strip() == "ghp_mock_token_12345"

    # Test analyze with --token
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "readme"})
        .add_remote("origin", "https://github.com/testowner/testrepo.git")
    )
    path = builder.build()
    try:
        issue = make_issue(number=1, title="Test", state="closed")
        fake_provider = FakeCLIProvider(issues=[issue])
        set_provider_override(fake_provider)

        res = runner.invoke(app, ["analyze", "--path", path, "--token", "ghp_custom_token", "--json"])
        assert res.exit_code == 0
    finally:
        builder.cleanup()
