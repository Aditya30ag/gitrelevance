"""Base provider protocol and provider-related exceptions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from gitrelevance.issues.models import Issue, PullRequest


class GitRelevanceError(Exception):
    """Base exception for all GitRelevance errors."""


class RateLimitExceededError(GitRelevanceError):
    """Raised when provider API rate limit is exceeded."""

    def __init__(self, reset_at: datetime | int | float | str | None = None, message: str | None = None) -> None:
        self.reset_at = reset_at
        if message:
            msg = message
        elif reset_at is not None:
            msg = f"API rate limit exceeded. Reset time: {reset_at}"
        else:
            msg = "API rate limit exceeded."
        super().__init__(msg)


@runtime_checkable
class Provider(Protocol):
    """Protocol defining the interface for issue tracker providers."""

    def parse_remote(self, remote_url: str) -> tuple[str, str] | None:
        """Parse a remote URL into (owner, repo) pair.

        Args:
            remote_url: Remote URL string (git@..., https://..., etc.)

        Returns:
            Tuple of (owner, repo) if valid for this provider, None otherwise.
        """
        ...

    def get_issues(self, state: Literal["open", "closed", "all"] = "all") -> list[Issue]:
        """Fetch repository issues.

        Args:
            state: Issue state filter ("open", "closed", or "all")

        Returns:
            List of Issue dataclasses.
        """
        ...

    def get_pull_requests(self, state: Literal["open", "closed", "all"] = "all") -> list[PullRequest]:
        """Fetch repository pull requests.

        Args:
            state: Pull request state filter ("open", "closed", or "all")

        Returns:
            List of PullRequest dataclasses.
        """
        ...

    def get_issue_comments(self, issue_number: int) -> list[str]:
        """Fetch comment bodies for a given issue.

        Args:
            issue_number: Issue number

        Returns:
            List of comment body strings.
        """
        ...
