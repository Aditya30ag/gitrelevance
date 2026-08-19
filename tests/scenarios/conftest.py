"""Shared fixtures and helpers for the GitRelevance scenario test suite.

Each scenario test file imports from here to avoid duplicating RepoBuilder
boilerplate across files.

How to add a new scenario test
-------------------------------
1. Create a new file:  tests/scenarios/test_scenario_<name>.py
2. Import FakeProvider, make_issue, and make_pr from this module.
3. Use RepoBuilder to build a real temporary Git repo.
4. Wire up FakeProvider, call AnalysisEngine(repo, provider).analyze(), and
   assert on the AnalysisResult fields (classification, confidence, evidence).
5. Always call builder.cleanup() in a try/finally block (or use the
   RepoBuilder context manager: with RepoBuilder() as builder: ...).

Tip: the assert_has_evidence() helper in this module reduces repetitive
evidence-searching boilerplate.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gitrelevance.issues.models import Issue, PullRequest


class FakeProvider:
    """In-memory fake provider for scenario testing.

    Implements the Provider protocol without any network calls.
    """

    def __init__(
        self,
        issues: list[Issue] | None = None,
        pull_requests: list[PullRequest] | None = None,
    ) -> None:
        self.issues = issues or []
        self.pull_requests = pull_requests or []

    def parse_remote(self, remote_url: str) -> tuple[str, str] | None:
        return ("fake_owner", "fake_repo")

    def get_issues(self, state: str = "all") -> list[Issue]:
        return self.issues

    def get_pull_requests(self, state: str = "all") -> list[PullRequest]:
        return self.pull_requests

    def get_issue_comments(self, issue_number: int) -> list[str]:
        return []


def make_issue(
    number: int,
    title: str = "Test Issue",
    state: str = "open",
    body: str = "Issue description",
    linked_pr_numbers: tuple[int, ...] = (),
) -> Issue:
    """Build a minimal Issue dataclass for test fixtures."""
    return Issue(
        number=number,
        title=title,
        body=body,
        state="closed" if state == "closed" else "open",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc) if state == "closed" else None,
        labels=(),
        linked_pr_numbers=linked_pr_numbers,
    )


def make_pr(
    number: int,
    merged: bool = True,
    merge_commit_sha: str | None = None,
    closes_issue_numbers: tuple[int, ...] = (),
    files_changed: tuple[str, ...] = (),
    title: str = "Test PR",
) -> PullRequest:
    """Build a minimal PullRequest dataclass for test fixtures."""
    return PullRequest(
        number=number,
        title=title,
        merged=merged,
        merge_commit_sha=merge_commit_sha,
        closes_issue_numbers=closes_issue_numbers,
        files_changed=files_changed,
    )


def assert_has_evidence(evidence: tuple, keyword: str) -> None:
    """Assert that at least one evidence item's description contains keyword."""
    matches = [e for e in evidence if keyword.lower() in e.description.lower()]
    assert matches, (
        f"No evidence item with '{keyword}' in description. "
        f"Got: {[e.description for e in evidence]}"
    )


def assert_no_evidence(evidence: tuple, keyword: str) -> None:
    """Assert that no evidence item's description contains keyword."""
    matches = [e for e in evidence if keyword.lower() in e.description.lower()]
    assert not matches, (
        f"Unexpected evidence item with '{keyword}' in description: "
        f"{[e.description for e in matches]}"
    )
