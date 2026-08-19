"""Issue and Pull Request data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class Issue:
    """Represents a GitHub issue.

    Attributes:
        number: Issue number
        title: Issue title
        body: Issue body text
        state: State of issue ("open" or "closed")
        created_at: Datetime issue was created
        closed_at: Datetime issue was closed, or None if open
        labels: Tuple of label names attached to the issue
        linked_pr_numbers: Tuple of PR numbers linked to this issue
    """

    number: int
    title: str
    body: str
    state: Literal["open", "closed"]
    created_at: datetime
    closed_at: datetime | None
    labels: tuple[str, ...]
    linked_pr_numbers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PullRequest:
    """Represents a GitHub pull request.

    Attributes:
        number: Pull request number
        title: Pull request title
        merged: Whether the pull request was merged
        merge_commit_sha: SHA of the merge commit, if merged
        closes_issue_numbers: Tuple of issue numbers closed by this PR
        files_changed: Tuple of file paths changed in this PR
    """

    number: int
    title: str
    merged: bool
    merge_commit_sha: str | None
    closes_issue_numbers: tuple[int, ...]
    files_changed: tuple[str, ...]
