"""GitHub provider implementation using PyGithub."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from typing import Literal

from diskcache import Cache
from github import Auth, Github, GithubException, RateLimitExceededException

from gitrelevance.config import load_github_token
from gitrelevance.issues.models import Issue, PullRequest
from gitrelevance.providers.base import Provider, RateLimitExceededError


class GitHubProvider:
    """GitHub provider implementing the Provider protocol.

    Provides access to GitHub issues, pull requests, and comments with disk caching
    and rate limit error handling.
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        cache_dir: str | None = None,
        ttl: int = 900,
    ) -> None:
        """Initialize the GitHub provider.

        Args:
            owner: Repository owner or organization name
            repo: Repository name
            token: Optional GitHub Personal Access Token. If None, loaded from GITHUB_TOKEN env var.
            cache_dir: Directory for diskcache storage. If None, uses a temporary directory.
            ttl: Cache TTL in seconds (default: 900 / 15 minutes).
        """
        self.owner = owner
        self.repo_name = repo
        self._token = token or load_github_token()
        self.ttl = ttl

        if cache_dir is None:
            cache_dir = os.path.join(tempfile.gettempdir(), "gitrelevance_cache")
        self._cache = Cache(cache_dir)

        if self._token:
            auth = Auth.Token(self._token)
            self._client = Github(auth=auth)
        else:
            self._client = Github()

    @staticmethod
    def parse_remote(remote_url: str) -> tuple[str, str] | None:
        """Parse a remote URL into (owner, repo) pair for GitHub repositories.

        Supported URL formats:
        - git@github.com:owner/repo.git
        - https://github.com/owner/repo.git
        - https://github.com/owner/repo
        - github.com/owner/repo

        Args:
            remote_url: Remote URL string

        Returns:
            Tuple of (owner, repo) if valid GitHub URL, None otherwise.
        """
        if not remote_url:
            return None

        url = remote_url.strip()

        patterns = [
            r"^git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$",
            r"^https?://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$",
            r"^github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$",
        ]

        for pattern in patterns:
            match = re.match(pattern, url)
            if match:
                owner, repo = match.group(1), match.group(2)
                return owner, repo

        return None

    def _get_github_repo(self) -> object:
        """Get PyGithub Repository instance."""
        return self._client.get_repo(f"{self.owner}/{self.repo_name}")

    def get_issues(
        self,
        state: Literal["open", "closed", "all"] = "all",
        force_refresh: bool = False,
    ) -> list[Issue]:
        """Fetch repository issues.

        Args:
            state: Issue state filter ("open", "closed", or "all")
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of Issue dataclasses.

        Raises:
            RateLimitExceededError: If GitHub API rate limit is exceeded.
        """
        cache_key = (self.owner, self.repo_name, "issues", state)
        if not force_refresh and self.ttl > 0:
            cached_data = self._cache.get(cache_key)
            if cached_data is not None:
                return cached_data

        try:
            gh_repo = self._get_github_repo()
            gh_issues = gh_repo.get_issues(state=state)

            issues: list[Issue] = []
            for gh_issue in gh_issues:
                # Filter out PRs (PyGithub get_issues returns issues + PRs unless filtered)
                is_pr = False
                raw_data = getattr(gh_issue, "_rawData", None)
                if isinstance(raw_data, dict):
                    is_pr = bool(raw_data.get("pull_request"))
                else:
                    try:
                        is_pr = getattr(gh_issue, "pull_request", None) is not None
                    except Exception:
                        is_pr = False

                if is_pr:
                    continue

                linked_prs: list[int] = []
                try:
                    timeline = gh_issue.get_timeline()
                    for event in timeline:
                        event_name = getattr(event, "event", None)
                        if event_name in ("cross-referenced", "connected", "referenced"):
                            source = getattr(event, "source", None)
                            if source and isinstance(source, dict):
                                issue_info = source.get("issue")
                                if issue_info and isinstance(issue_info, dict):
                                    if "pull_request" in issue_info or issue_info.get("pull_request") is not None:
                                        pr_num = issue_info.get("number")
                                        if pr_num is not None and int(pr_num) not in linked_prs:
                                            linked_prs.append(int(pr_num))
                            elif source:
                                issue_info = getattr(source, "issue", None)
                                if issue_info:
                                    if getattr(issue_info, "pull_request", None) is not None:
                                        pr_num = getattr(issue_info, "number", None)
                                        if pr_num is not None and int(pr_num) not in linked_prs:
                                            linked_prs.append(int(pr_num))
                except Exception:
                    pass

                issue = Issue(
                    number=gh_issue.number,
                    title=gh_issue.title,
                    body=gh_issue.body or "",
                    state="closed" if gh_issue.state == "closed" else "open",
                    created_at=gh_issue.created_at,
                    closed_at=gh_issue.closed_at,
                    labels=tuple(label.name for label in gh_issue.labels),
                    linked_pr_numbers=tuple(linked_prs),
                )
                issues.append(issue)

            if self.ttl > 0:
                self._cache.set(cache_key, issues, expire=self.ttl)
            return issues

        except RateLimitExceededException as e:
            reset = getattr(e, "reset", None)
            raise RateLimitExceededError(reset_at=reset) from e
        except GithubException as e:
            if e.status in (403, 429) and "rate limit" in str(e).lower():
                reset = getattr(e, "reset", None)
                raise RateLimitExceededError(reset_at=reset) from e
            raise

    def get_pull_requests(
        self,
        state: Literal["open", "closed", "all"] = "all",
        force_refresh: bool = False,
    ) -> list[PullRequest]:
        """Fetch repository pull requests.

        Args:
            state: Pull request state filter ("open", "closed", or "all")
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of PullRequest dataclasses.

        Raises:
            RateLimitExceededError: If GitHub API rate limit is exceeded.
        """
        cache_key = (self.owner, self.repo_name, "pull_requests", state)
        if not force_refresh and self.ttl > 0:
            cached_data = self._cache.get(cache_key)
            if cached_data is not None:
                return cached_data

        try:
            gh_repo = self._get_github_repo()
            gh_prs = gh_repo.get_pulls(state=state)

            prs: list[PullRequest] = []
            for gh_pr in gh_prs:
                closes_issues: list[int] = []

                try:
                    files_changed = tuple(f.filename for f in gh_pr.get_files())
                except Exception:
                    files_changed = ()

                pr = PullRequest(
                    number=gh_pr.number,
                    title=gh_pr.title,
                    merged=bool(getattr(gh_pr, "merged", False)),
                    merge_commit_sha=getattr(gh_pr, "merge_commit_sha", None),
                    closes_issue_numbers=tuple(closes_issues),
                    files_changed=files_changed,
                )
                prs.append(pr)

            if self.ttl > 0:
                self._cache.set(cache_key, prs, expire=self.ttl)
            return prs

        except RateLimitExceededException as e:
            reset = getattr(e, "reset", None)
            raise RateLimitExceededError(reset_at=reset) from e
        except GithubException as e:
            if e.status in (403, 429) and "rate limit" in str(e).lower():
                reset = getattr(e, "reset", None)
                raise RateLimitExceededError(reset_at=reset) from e
            raise

    def get_issue_comments(
        self,
        issue_number: int,
        force_refresh: bool = False,
    ) -> list[str]:
        """Fetch comment bodies for a given issue.

        Args:
            issue_number: Issue number
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of comment body strings.

        Raises:
            RateLimitExceededError: If GitHub API rate limit is exceeded.
        """
        cache_key = (self.owner, self.repo_name, "comments", issue_number)
        if not force_refresh and self.ttl > 0:
            cached_data = self._cache.get(cache_key)
            if cached_data is not None:
                return cached_data

        try:
            gh_repo = self._get_github_repo()
            gh_issue = gh_repo.get_issue(issue_number)
            comments = [comment.body for comment in gh_issue.get_comments() if comment.body]

            if self.ttl > 0:
                self._cache.set(cache_key, comments, expire=self.ttl)
            return comments

        except RateLimitExceededException as e:
            reset = getattr(e, "reset", None)
            raise RateLimitExceededError(reset_at=reset) from e
        except GithubException as e:
            if e.status in (403, 429) and "rate limit" in str(e).lower():
                reset = getattr(e, "reset", None)
                raise RateLimitExceededError(reset_at=reset) from e
            raise
