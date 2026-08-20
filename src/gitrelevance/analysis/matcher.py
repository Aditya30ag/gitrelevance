"""Matcher for correlating Git history data with issue tracker data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from gitrelevance.git.commits import Commit
from gitrelevance.git.history import commits_referencing
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import Issue, PullRequest

if TYPE_CHECKING:
    from gitrelevance.providers.base import Provider

logger = logging.getLogger(__name__)

# Temporary debug: issue numbers to trace in detail
_TRACE_ISSUES: set[int] = {34}


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
    _trace = issue.number in _TRACE_ISSUES

    # 1. Referencing commits using the cached single-pass commit index
    ref_commits = commits_referencing(repo, issue.number)

    if _trace:
        logger.warning(
            "[TRACE] === build_match_set for issue #%d (title=%r) ===",
            issue.number, issue.title,
        )
        logger.warning("[TRACE]   issue.state=%s, issue.linked_pr_numbers=%s",
                        issue.state, issue.linked_pr_numbers)
        if ref_commits:
            logger.warning("[TRACE]   (a) commits_referencing(%d) found %d commit(s):",
                           issue.number, len(ref_commits))
            for c in ref_commits:
                logger.warning("[TRACE]       sha=%s  message=%r  files_changed=%s",
                               c.short_sha, c.message, c.files_changed)
        else:
            logger.warning("[TRACE]   (a) commits_referencing(%d) found 0 commits.", issue.number)

    # 2. Linked PRs: union of PRs closing this issue or linked in the issue model
    matched_prs: list[PullRequest] = []
    seen_pr_numbers: set[int] = set()
    for pr in provider_prs:
        closes_match = issue.number in pr.closes_issue_numbers
        linked_match = pr.number in issue.linked_pr_numbers
        if closes_match or linked_match:
            if pr.number not in seen_pr_numbers:
                seen_pr_numbers.add(pr.number)
                matched_prs.append(pr)
                if _trace:
                    reason = []
                    if closes_match:
                        reason.append(f"closes_issue_numbers={pr.closes_issue_numbers}")
                    if linked_match:
                        reason.append(f"linked_pr_numbers match (PR#{pr.number} in issue.linked_pr_numbers)")
                    logger.warning(
                        "[TRACE]   (b) matched PR #%d (title=%r, merged=%s, files_changed=%d items):",
                        pr.number, pr.title, pr.merged, len(pr.files_changed),
                    )
                    logger.warning("[TRACE]       reason: %s", " + ".join(reason))
                    logger.warning("[TRACE]       files_changed=%s", pr.files_changed)

    if _trace and not matched_prs:
        logger.warning("[TRACE]   (b) No PRs matched for issue #%d.", issue.number)

    # 3. Resolve merge commits for linked PRs in local git history (skip if not found)
    resolved_pr_commits: list[Commit] = []
    seen_commit_shas: set[str] = set()
    # Track which PRs had their merge commit resolved locally, so we can
    # skip their pr.files_changed in step 4.  When the merge commit IS
    # in the local repo, its files_changed (from the actual git diff) is
    # already included via resolved_pr_commits and is more accurate than
    # the GitHub API file list, which may reflect a huge bundled changeset
    # unrelated to the specific issue.
    prs_with_resolved_commits: set[int] = set()
    for pr in matched_prs:
        if pr.merge_commit_sha:
            commit = repo.get_commit(pr.merge_commit_sha)
            if commit is not None and commit.sha not in seen_commit_shas:
                seen_commit_shas.add(commit.sha)
                resolved_pr_commits.append(commit)
                prs_with_resolved_commits.add(pr.number)
                if _trace:
                    logger.warning(
                        "[TRACE]   (c) resolved merge commit for PR #%d: sha=%s  files_changed=%s",
                        pr.number, commit.short_sha, commit.files_changed,
                    )
            elif _trace:
                logger.warning(
                    "[TRACE]   (c) PR #%d merge_commit_sha=%s NOT found in local repo",
                    pr.number, pr.merge_commit_sha,
                )

    # 4. Related files: union across referencing_commits, pr_commits, and linked_prs
    files: set[str] = set()
    for c in ref_commits:
        files.update(c.files_changed)
    for c in resolved_pr_commits:
        files.update(c.files_changed)
    # Add pr.files_changed only for PRs where it's safe:
    #
    #  - Unmerged PRs (WIP / review): always include — pr.files_changed
    #    is the only source of file info and drives the STILL_RELEVANT signal.
    #
    #  - Merged PRs whose merge commit IS in the local repo: skip — the
    #    merge commit's actual git diff (already added above) is more
    #    accurate than the GitHub API file list.
    #
    #  - Merged PRs whose merge commit is NOT in the local repo (shallow
    #    clone): skip — pr.files_changed may reflect a huge bundled
    #    squashed changeset (e.g. 27 files for a CODE_OF_CONDUCT PR)
    #    that injects unrelated server/ files into related_files,
    #    causing false OBSOLETE evidence when those files are deleted.
    for pr in matched_prs:
        if pr.number in prs_with_resolved_commits:
            # Merge commit found locally — its files are already included above
            continue
        if pr.merged:
            # Merged but merge commit missing (shallow clone) — skip
            # pr.files_changed to avoid cross-contamination from broad
            # bundled changesets that are unrelated to the specific issue.
            continue
        # Unmerged PR — include files_changed for STILL_RELEVANT detection
        files.update(pr.files_changed)

    if _trace:
        server_files = [f for f in files if f.startswith("server/")]
        logger.warning(
            "[TRACE]   (d) final related_files: %d total files, %d server/* files",
            len(files), len(server_files),
        )
        if server_files:
            logger.warning("[TRACE]       server files: %s", server_files)

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
