"""Current-state analysis helpers for evaluating Git repository status against MatchSets."""

from __future__ import annotations

from dataclasses import dataclass

from gitrelevance.analysis.matcher import MatchSet
from gitrelevance.git.commits import Commit
from gitrelevance.git.files import get_file_operations
from gitrelevance.git.history import default_revert_detector
from gitrelevance.git.repository import GitRepository


@dataclass(frozen=True, slots=True)
class CurrentStateFacts:
    """Summarizes current repository state facts for a MatchSet.

    Attributes:
        fix_commit_in_head: First referencing or PR commit present in HEAD history, or None.
        all_related_files_exist: True if all related files exist at HEAD (False if empty).
        deleted_files: Tuple of related file paths that were deleted and do not exist at HEAD.
        renamed_files: Tuple of (old_path, new_path) rename pairs found for related files.
        reverts_of_fix: Tuple of commits reverting fix_commit_in_head (empty if no fix commit).
    """

    fix_commit_in_head: Commit | None
    all_related_files_exist: bool
    deleted_files: tuple[str, ...]
    renamed_files: tuple[tuple[str, str], ...]
    reverts_of_fix: tuple[Commit, ...]


def analyze_current_state(match_set: MatchSet, repo: GitRepository) -> CurrentStateFacts:
    """Analyze current repository state relative to a MatchSet.

    Args:
        match_set: The MatchSet containing issue evidence.
        repo: The local Git repository wrapper.

    Returns:
        CurrentStateFacts summarizing current HEAD state.
    """
    ops = get_file_operations(repo)

    # 1. Determine fix_commit_in_head (ignoring revert commits)
    fix_commit_in_head: Commit | None = None
    try:
        head = repo.head_commit()
        head_sha = head.sha
        candidate_commits = list(match_set.referencing_commits) + list(match_set.pr_commits)
        for commit in candidate_commits:
            # Skip revert commits when looking for the fix commit
            if "This reverts commit " in commit.message:
                continue
            if repo.is_ancestor(commit.sha, head_sha):
                fix_commit_in_head = commit
                break
    except Exception:
        fix_commit_in_head = None

    # 2. Renamed files and deleted files
    renamed: list[tuple[str, str]] = []
    seen_renames: set[tuple[str, str]] = set()

    for path in match_set.related_files:
        renames_for_path = ops.find_renames(path)
        for pair in renames_for_path:
            if pair not in seen_renames:
                seen_renames.add(pair)
                renamed.append(pair)

    deleted: list[str] = []
    for path in match_set.related_files:
        if not ops.file_exists_at_head(path):
            # A file is considered deleted only if it does not exist at HEAD,
            # was marked as deleted/historical, and was NOT renamed.
            if ops.was_file_deleted(path) and not ops.find_renames(path):
                deleted.append(path)

    # 3. all_related_files_exist
    if not match_set.related_files:
        all_exist = False
    else:
        all_exist = all(ops.file_exists_at_head(path) for path in match_set.related_files)

    # 4. Reverts of fix commit
    reverts: list[Commit] = []
    if fix_commit_in_head is not None:
        detector = default_revert_detector()
        reverts = detector.find_reverts_of(repo, fix_commit_in_head.sha)

    return CurrentStateFacts(
        fix_commit_in_head=fix_commit_in_head,
        all_related_files_exist=all_exist,
        deleted_files=tuple(deleted),
        renamed_files=tuple(renamed),
        reverts_of_fix=tuple(reverts),
    )
