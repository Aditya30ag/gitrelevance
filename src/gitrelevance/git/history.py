"""Commit reference index and revert detection for issue tracking."""

from __future__ import annotations

import re
from typing import Protocol

from gitrelevance.git.commits import Commit
from gitrelevance.git.repository import GitRepository


# Cache key for the commit reference index on GitRepository instances
_INDEX_CACHE_KEY = "_gitrelevance_commit_reference_index"
_REVERT_INDEX_CACHE_KEY = "_gitrelevance_revert_index"

# ---------------------------------------------------------------------------
# Issue-number extraction helpers (private)
# ---------------------------------------------------------------------------

# Matches any #123-style number in a message body
_HASH_ISSUE_RE = re.compile(r"#(\d+)")

# Matches GH-123-style references (unambiguous, never a PR number)
_GH_ISSUE_RE = re.compile(r"GH-(\d+)", re.IGNORECASE)

# Matches standard git revert trailer: "This reverts commit <sha>."
_REVERT_TRAILER_RE = re.compile(r"This reverts commit ([0-9a-fA-F]{40})\.")

# Detects PR-number contexts like "pull request #42" or "PR #42".
# We check whether the 30 characters *before* the # match this pattern.
_PR_CONTEXT_RE = re.compile(r"(?:pull\s+request|PR)\s+$", re.IGNORECASE)


def _extract_issue_numbers(message: str) -> list[int]:
    """Extract genuine issue numbers from a commit message.

    Matches ``#123`` and ``GH-123`` patterns, but **excludes** numbers that
    appear in PR-number contexts (e.g. ``pull request #42``, ``PR #42``).
    Those are GitHub pull-request identifiers, *not* issue references, and
    attributing a commit's file changes to a PR number causes evidence
    cross-contamination across unrelated issues.

    Returns a de-duplicated list of issue numbers in first-seen order.
    """
    numbers: list[int] = []
    seen: set[int] = set()

    # --- #NNN references ---
    for match in _HASH_ISSUE_RE.finditer(message):
        num = int(match.group(1))
        if num in seen:
            continue

        start = match.start()

        # Require a word boundary before '#': whitespace or start-of-string.
        # This prevents matching inside URLs, file paths, or parenthetical
        # PR-title patterns like "Feature (#42)".
        if start > 0 and not message[start - 1].isspace():
            continue

        # Filter PR-number false positives.
        # In squash-merge / merge-commit messages the subject line often
        # reads "Merge pull request #42 from …".  The #42 there is a PR
        # number, not an issue number.  We check the ~30 characters of
        # context preceding the # to decide.
        prefix = message[max(0, start - 30) : start]
        if _PR_CONTEXT_RE.search(prefix):
            continue

        seen.add(num)
        numbers.append(num)

    # --- GH-NNN references (always unambiguous) ---
    for match in _GH_ISSUE_RE.finditer(message):
        num = int(match.group(1))
        if num not in seen:
            seen.add(num)
            numbers.append(num)

    return numbers


def build_commit_reference_index(repo: GitRepository) -> dict[int, list[Commit]]:
    """Build an index mapping issue numbers to commits that reference them.

    This function walks the commit log exactly once and caches the result
    on the repository instance for reuse. This is critical for performance
    with large repositories (10,000+ commits).

    Issue references are detected by patterns like #123 or GH-123 in commit
    messages, where N is an issue number.  PR-number references (e.g.
    ``pull request #42``, ``PR #42``) are explicitly excluded to prevent
    evidence cross-contamination.

    Also populates the revert index mapping reverted SHAs to revert commits.

    Args:
        repo: The GitRepository to build the index for

    Returns:
        Dictionary mapping issue numbers to lists of commits referencing them
    """
    # Check if index already cached on repo instance
    if hasattr(repo, _INDEX_CACHE_KEY):
        return getattr(repo, _INDEX_CACHE_KEY)

    # Build the indices by walking commits once
    index: dict[int, list[Commit]] = {}
    revert_index: dict[str, list[Commit]] = {}

    for commit in repo.commits_since(None):
        issue_nums = _extract_issue_numbers(commit.message)
        for num in issue_nums:
            if num not in index:
                index[num] = []
            index[num].append(commit)

        for match in _REVERT_TRAILER_RE.finditer(commit.message):
            reverted_sha = match.group(1)
            if reverted_sha not in revert_index:
                revert_index[reverted_sha] = []
            revert_index[reverted_sha].append(commit)

    # Cache the indices on the repo instance
    setattr(repo, _INDEX_CACHE_KEY, index)
    setattr(repo, _REVERT_INDEX_CACHE_KEY, revert_index)

    return index


def commits_referencing(repo: GitRepository, issue_number: int) -> list[Commit]:
    """Get all commits that reference a specific issue.

    Uses the cached index instead of scanning history itself.

    Args:
        repo: The GitRepository to search
        issue_number: The issue number to find commits for

    Returns:
        List of commits referencing the issue, newest first
    """
    index = build_commit_reference_index(repo)
    return index.get(issue_number, [])


class RevertDetector(Protocol):
    """Protocol for detecting reverts of commits.

    Future implementations could use inverse-diff comparison,
    message heuristics, patch similarity, or semantic analysis.
    """

    def find_reverts_of(self, repo: GitRepository, commit_sha: str) -> list[Commit]:
        """Find commits that revert the specified commit.

        Args:
            repo: The GitRepository to search
            commit_sha: SHA of the commit to find reverts of

        Returns:
            List of commits that revert the specified commit
        """
        ...


class GitNativeRevertDetector:
    """MVP implementation: detects only commits Git's own revert machinery produced.

    This detector uses Git's native revert detection, which relies on
    the parent/trailer relationship that 'git revert' creates. It does
    NOT use free-text commit-message pattern matching or inverse-diff
    comparison.
    """

    def find_reverts_of(self, repo: GitRepository, commit_sha: str) -> list[Commit]:
        """Find commits that revert the specified commit using Git's native detection.

        ``git revert`` always inserts exactly this sentence into the commit
        message::

            This reverts commit <full-sha>.

        That line is generated by Git's own revert machinery and is the
        authoritative signal we use.  We deliberately do NOT match commits
        that merely mention "revert" in their message (the fake-revert test
        exercises this).

        Args:
            repo: The GitRepository to search
            commit_sha: SHA of the commit to find reverts of

        Returns:
            List of commits that revert the specified commit, or empty list
        """
        # Resolve the full SHA so partial SHAs compare correctly
        target_commit = repo.get_commit(commit_sha)
        if target_commit is None:
            return []
        full_sha = target_commit.sha

        revert_index = getattr(repo, _REVERT_INDEX_CACHE_KEY, None)
        if revert_index is None:
            build_commit_reference_index(repo)
            revert_index = getattr(repo, _REVERT_INDEX_CACHE_KEY, {})

        return list(revert_index.get(full_sha, []))


# Default detector instance (module-level singleton)
_default_detector: GitNativeRevertDetector | None = None


def default_revert_detector() -> RevertDetector:
    """Get the default revert detector.

    Returns the singleton instance of GitNativeRevertDetector.
    This can be swapped out later by reassigning the module-level variable
    or by providing an alternative factory.

    Returns:
        The default RevertDetector implementation
    """
    global _default_detector
    if _default_detector is None:
        _default_detector = GitNativeRevertDetector()
    return _default_detector
