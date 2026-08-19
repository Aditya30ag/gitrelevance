"""Tests for GitHub provider layer."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import responses
from github import GithubException, RateLimitExceededException

from gitrelevance.config import load_github_token
from gitrelevance.issues.models import Issue, PullRequest
from gitrelevance.providers.base import RateLimitExceededError
from gitrelevance.providers.github import GitHubProvider


class TestRemoteUrlParsing:
    """Test remote URL parsing for various GitHub and non-GitHub URL formats."""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("git@github.com:octocat/Hello-World.git", ("octocat", "Hello-World")),
            ("https://github.com/octocat/Hello-World.git", ("octocat", "Hello-World")),
            ("https://github.com/octocat/Hello-World", ("octocat", "Hello-World")),
            ("github.com/octocat/Hello-World", ("octocat", "Hello-World")),
            ("http://github.com/owner/repo", ("owner", "repo")),
            ("git@github.com:owner/repo", ("owner", "repo")),
            ("https://github.com/owner/repo/", ("owner", "repo")),
        ],
    )
    def test_valid_github_urls(self, url: str, expected: tuple[str, str]) -> None:
        assert GitHubProvider.parse_remote(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "git@gitlab.com:octocat/Hello-World.git",
            "https://bitbucket.org/octocat/Hello-World",
            "https://example.com/repo.git",
            "invalid_url_format",
            "",
        ],
    )
    def test_non_github_urls_return_none(self, url: str) -> None:
        assert GitHubProvider.parse_remote(url) is None


class TestTokenHandling:
    """Test GITHUB_TOKEN environment loading and provider authentication mode."""

    def test_load_github_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token_123")
        assert load_github_token() == "ghp_test_token_123"

    def test_load_github_token_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert load_github_token() is None

    def test_provider_unauthenticated_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        provider = GitHubProvider(
            owner="octocat",
            repo="Hello-World",
            token=None,
            cache_dir=str(tmp_path),
        )
        assert provider._token is None

    def test_provider_authenticated_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: object
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_env_token")
        provider = GitHubProvider(
            owner="octocat",
            repo="Hello-World",
            cache_dir=str(tmp_path),
        )
        assert provider._token == "ghp_env_token"


class TestGitHubProviderMocked:
    """Test get_issues, get_pull_requests, get_issue_comments with mock responses/PyGithub."""

    @pytest.fixture
    def provider(self, tmp_path: object) -> GitHubProvider:
        return GitHubProvider(
            owner="octocat",
            repo="Hello-World",
            token="ghp_fake_token",
            cache_dir=str(tmp_path),
            ttl=900,
        )

    def test_get_issues_normalization_and_pr_filtering(
        self, provider: GitHubProvider
    ) -> None:
        mock_repo = MagicMock()
        mock_issue1 = MagicMock()
        mock_issue1.number = 1
        mock_issue1.title = "Bug report"
        mock_issue1.body = "Detailed bug info"
        mock_issue1.state = "open"
        mock_issue1.created_at = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        mock_issue1.closed_at = None
        mock_label1 = MagicMock()
        mock_label1.name = "bug"
        mock_issue1.labels = [mock_label1]
        mock_issue1.pull_request = None  # Genuine issue

        # Create event for linked PR
        mock_event = MagicMock()
        mock_event.event = "cross-referenced"
        mock_event.source = {"issue": {"pull_request": {}, "number": 10}}
        mock_issue1.get_timeline.return_value = [mock_event]

        # PR issue (should be filtered out)
        mock_pr_issue = MagicMock()
        mock_pr_issue.pull_request = MagicMock()

        mock_repo.get_issues.return_value = [mock_issue1, mock_pr_issue]

        with patch.object(provider, "_get_github_repo", return_value=mock_repo):
            issues = provider.get_issues(state="all", force_refresh=True)

        assert len(issues) == 1
        issue = issues[0]
        assert isinstance(issue, Issue)
        assert issue.number == 1
        assert issue.title == "Bug report"
        assert issue.state == "open"
        assert issue.labels == ("bug",)
        assert issue.linked_pr_numbers == (10,)

    def test_get_pull_requests_normalization(self, provider: GitHubProvider) -> None:
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 5
        mock_pr.title = "Add feature"
        mock_pr.merged = True
        mock_pr.merge_commit_sha = "1234567890abcdef"
        mock_file = MagicMock()
        mock_file.filename = "src/feature.py"
        mock_pr.get_files.return_value = [mock_file]

        mock_repo.get_pulls.return_value = [mock_pr]

        with patch.object(provider, "_get_github_repo", return_value=mock_repo):
            prs = provider.get_pull_requests(state="all", force_refresh=True)

        assert len(prs) == 1
        pr = prs[0]
        assert isinstance(pr, PullRequest)
        assert pr.number == 5
        assert pr.title == "Add feature"
        assert pr.merged is True
        assert pr.merge_commit_sha == "1234567890abcdef"
        assert pr.files_changed == ("src/feature.py",)

    def test_get_issue_comments(self, provider: GitHubProvider) -> None:
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_comment1 = MagicMock()
        mock_comment1.body = "First comment"
        mock_comment2 = MagicMock()
        mock_comment2.body = "Second comment"
        mock_issue.get_comments.return_value = [mock_comment1, mock_comment2]
        mock_repo.get_issue.return_value = mock_issue

        with patch.object(provider, "_get_github_repo", return_value=mock_repo):
            comments = provider.get_issue_comments(1, force_refresh=True)

        assert comments == ["First comment", "Second comment"]

    def test_rate_limit_exceeded_error_raising(self, provider: GitHubProvider) -> None:
        mock_repo = MagicMock()
        # Raise RateLimitExceededException
        exc = RateLimitExceededException(
            status=403,
            data={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-reset": "1700000000"},
        )
        setattr(exc, "reset", datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc))
        mock_repo.get_issues.side_effect = exc

        with patch.object(provider, "_get_github_repo", return_value=mock_repo):
            with pytest.raises(RateLimitExceededError) as exc_info:
                provider.get_issues(force_refresh=True)

            assert exc_info.value.reset_at == datetime(
                2024, 1, 1, 12, 0, tzinfo=timezone.utc
            )

    def test_caching_behavior(self, provider: GitHubProvider) -> None:
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.number = 1
        mock_issue.title = "Test Issue"
        mock_issue.body = "Body"
        mock_issue.state = "open"
        mock_issue.created_at = datetime.now(timezone.utc)
        mock_issue.closed_at = None
        mock_issue.labels = []
        mock_issue.pull_request = None
        mock_issue.get_timeline.return_value = []
        mock_repo.get_issues.return_value = [mock_issue]

        with patch.object(provider, "_get_github_repo", return_value=mock_repo):
            # First call — populates cache
            issues1 = provider.get_issues(state="all", force_refresh=False)
            assert mock_repo.get_issues.call_count == 1

            # Second call — served from cache (get_issues call count remains 1)
            issues2 = provider.get_issues(state="all", force_refresh=False)
            assert mock_repo.get_issues.call_count == 1
            assert issues1 == issues2

            # Third call with force_refresh=True — bypasses cache
            issues3 = provider.get_issues(state="all", force_refresh=True)
            assert mock_repo.get_issues.call_count == 2
            assert issues3 == issues1


class TestGitHubProviderHTTPResponses:
    """HTTP-level testing with `responses` library."""

    @responses.activate
    def test_http_endpoint_responses(self, tmp_path: object) -> None:
        import re

        # Mock repo endpoint
        responses.add(
            responses.GET,
            re.compile(r"https://api\.github\.com(?::443)?/repos/octocat/Hello-World$"),
            json={"name": "Hello-World", "owner": {"login": "octocat"}},
            status=200,
        )
        # Mock issues endpoint page 1
        responses.add(
            responses.GET,
            re.compile(r"https://api\.github\.com(?::443)?/repos/octocat/Hello-World/issues\?state=all"),
            json=[
                {
                    "url": "https://api.github.com/repos/octocat/Hello-World/issues/101",
                    "number": 101,
                    "title": "HTTP Issue",
                    "body": "Issue body",
                    "state": "open",
                    "created_at": "2024-01-01T00:00:00Z",
                    "closed_at": None,
                    "labels": [],
                    "pull_request": None,
                }
            ],
            status=200,
        )

        provider = GitHubProvider(
            owner="octocat",
            repo="Hello-World",
            token="ghp_test_token",
            cache_dir=str(tmp_path),
        )
        issues = provider.get_issues(state="all", force_refresh=True)

        assert len(issues) == 1
        assert issues[0].number == 101
        assert issues[0].title == "HTTP Issue"
