"""Matcher for correlating Git history data with issue tracker data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from gitrelevance.git.commits import Commit
from gitrelevance.git.history import commits_referencing
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import Issue, PullRequest

if TYPE_CHECKING:
    from gitrelevance.providers.base import Provider


@dataclass(frozen=True, slots=True)
class MatchSet:
    """Encapsulates all Git and PR evidence related to a specific Issue.

    Attributes:
        issue: The issue being analyzed.
        referencing_commits: Commits directly referencing the issue (e.g., #123, GH-123).
        linked_prs: Pull requests connected or closing the issue.
        pr_commits: Resolved merge commits from linked PRs present in local Git history.
        related_files: Deterministic sorted tuple of all files touched by referencing commits,
                       PR merge commits, or linked PR file changes.
    """

    issue: Issue
    referencing_commits: tuple[Commit, ...]
    linked_prs: tuple[PullRequest, ...]
    pr_commits: tuple[Commit, ...]
    related_files: tuple[str, ...]


def build_match_set(
    issue: Issue,
    repo: GitRepository,
    provider_prs: list[PullRequest],
) -> MatchSet:
    """Build a MatchSet describing everything in Git history related to an issue.

    Args:
        issue: The issue to build the match set for.
        repo: The local Git repository wrapper.
        provider_prs: List of pull requests fetched from the provider.

    Returns:
        A MatchSet containing referencing commits, linked PRs, PR merge commits,
        and affected file paths.
    """
    # 1. Referencing commits using the cached single-pass commit index
    ref_commits = commits_referencing(repo, issue.number)

    # 2. Linked PRs: union of PRs closing this issue or linked in the issue model
    matched_prs: list[PullRequest] = []
    seen_pr_numbers: set[int] = set()
    for pr in provider_prs:
        if (issue.number in pr.closes_issue_numbers) or (pr.number in issue.linked_pr_numbers):
            if pr.number not in seen_pr_numbers:
                seen_pr_numbers.add(pr.number)
                matched_prs.append(pr)

    # 3. Resolve merge commits for linked PRs in local git history (skip if not found)
    resolved_pr_commits: list[Commit] = []
    seen_commit_shas: set[str] = set()
    for pr in matched_prs:
        if pr.merge_commit_sha:
            commit = repo.get_commit(pr.merge_commit_sha)
            if commit is not None and commit.sha not in seen_commit_shas:
                seen_commit_shas.add(commit.sha)
                resolved_pr_commits.append(commit)

    # 4. Related files: union across referencing_commits, pr_commits, and linked_prs
    files: set[str] = set()
    for c in ref_commits:
        files.update(c.files_changed)
    for c in resolved_pr_commits:
        files.update(c.files_changed)
    for pr in matched_prs:
        files.update(pr.files_changed)

    return MatchSet(
        issue=issue,
        referencing_commits=tuple(ref_commits),
        linked_prs=tuple(matched_prs),
        pr_commits=tuple(resolved_pr_commits),
        related_files=tuple(sorted(files)),
    )


def build_all_match_sets(
    issues: list[Issue],
    repo: GitRepository,
    provider: Provider,
) -> dict[int, MatchSet]:
    """Build match sets for all given issues, fetching pull requests only once.

    Args:
        issues: List of issues to correlate.
        repo: The local Git repository wrapper.
        provider: Issue tracker provider implementing Provider protocol.

    Returns:
        Dictionary mapping issue number to its corresponding MatchSet.
    """
    prs = provider.get_pull_requests(state="all")
    return {issue.number: build_match_set(issue, repo, prs) for issue in issues}
