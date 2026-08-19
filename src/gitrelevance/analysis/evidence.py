"""Evidence collection rules and weights for issue analysis."""

from __future__ import annotations

from typing import Callable

from gitrelevance.analysis.current_state import CurrentStateFacts
from gitrelevance.analysis.matcher import MatchSet
from gitrelevance.models import EvidenceItem

# Weight constants for scoring
WEIGHT_ISSUE_REFERENCED_BY_FIX_COMMIT = 3
WEIGHT_FIX_COMMIT_IN_HEAD = 3
WEIGHT_FIXING_PR_MERGED = 2
WEIGHT_FILES_STILL_EXIST = 2
WEIGHT_NO_REVERT_DETECTED = 1
WEIGHT_ISSUE_NUM_IN_COMMIT_MSG = 1
WEIGHT_FILES_SUBSTANTIALLY_MODIFIED = 1
WEIGHT_FILES_DELETED_NO_REPLACEMENT = -3
WEIGHT_FEATURE_NO_LONGER_PRESENT = -2
WEIGHT_FIX_LATER_REVERTED = -3


def check_fix_in_head(match_set: MatchSet, facts: CurrentStateFacts) -> EvidenceItem | None:
    """Check if the fix commit is present in HEAD ancestry."""
    if facts.fix_commit_in_head is not None:
        return EvidenceItem(
            description="Fix commit is present in HEAD history",
            weight=WEIGHT_FIX_COMMIT_IN_HEAD,
            category="strong",
            source_ref=facts.fix_commit_in_head.short_sha,
        )
    return None


def check_pr_merged(match_set: MatchSet, facts: CurrentStateFacts) -> EvidenceItem | None:
    """Check if any linked pull request was merged."""
    for pr in match_set.linked_prs:
        if pr.merged:
            return EvidenceItem(
                description=f"Fixing PR #{pr.number} merged",
                weight=WEIGHT_FIXING_PR_MERGED,
                category="strong",
                source_ref=f"PR #{pr.number}",
            )
    return None


def check_issue_referenced_by_fix_commit(
    match_set: MatchSet, facts: CurrentStateFacts
) -> EvidenceItem | None:
    """Check if commits directly reference the issue."""
    if match_set.referencing_commits:
        commit = match_set.referencing_commits[0]
        return EvidenceItem(
            description="Issue referenced in commit message",
            weight=WEIGHT_ISSUE_REFERENCED_BY_FIX_COMMIT,
            category="strong",
            source_ref=commit.short_sha,
        )
    return None


def check_files_exist(match_set: MatchSet, facts: CurrentStateFacts) -> EvidenceItem | None:
    """Check if all related files exist at HEAD."""
    if facts.all_related_files_exist and match_set.related_files:
        return EvidenceItem(
            description="All related files exist at HEAD",
            weight=WEIGHT_FILES_STILL_EXIST,
            category="medium",
            source_ref=None,
        )
    return None


def check_no_revert(match_set: MatchSet, facts: CurrentStateFacts) -> EvidenceItem | None:
    """Check if no revert commit was detected for the fix commit."""
    if facts.fix_commit_in_head is not None and not facts.reverts_of_fix:
        return EvidenceItem(
            description="No revert of fix commit detected",
            weight=WEIGHT_NO_REVERT_DETECTED,
            category="medium",
            source_ref=facts.fix_commit_in_head.short_sha,
        )
    return None


def check_issue_num_in_commit_msg(
    match_set: MatchSet, facts: CurrentStateFacts
) -> EvidenceItem | None:
    """Check if issue number is mentioned in commit message."""
    if match_set.referencing_commits:
        commit = match_set.referencing_commits[0]
        return EvidenceItem(
            description="Issue number mentioned in commit message",
            weight=WEIGHT_ISSUE_NUM_IN_COMMIT_MSG,
            category="medium",
            source_ref=commit.short_sha,
        )
    return None


def check_files_substantially_modified(
    match_set: MatchSet, facts: CurrentStateFacts
) -> EvidenceItem | None:
    """Check if related files were renamed or substantially modified."""
    if facts.renamed_files:
        return EvidenceItem(
            description=f"Files modified or renamed ({len(facts.renamed_files)} renamed)",
            weight=WEIGHT_FILES_SUBSTANTIALLY_MODIFIED,
            category="medium",
            source_ref=None,
        )
    return None


def check_files_deleted(match_set: MatchSet, facts: CurrentStateFacts) -> EvidenceItem | None:
    """Check if related files were deleted without replacement."""
    if facts.deleted_files:
        files_str = ", ".join(facts.deleted_files)
        return EvidenceItem(
            description=f"Related files deleted without replacement: {files_str}",
            weight=WEIGHT_FILES_DELETED_NO_REPLACEMENT,
            category="obsolescence",
            source_ref=None,
        )
    return None


def check_feature_no_longer_present(
    match_set: MatchSet, facts: CurrentStateFacts
) -> EvidenceItem | None:
    """Check if feature code was deleted and issue closed without a fix commit."""
    if match_set.issue.state == "closed" and facts.fix_commit_in_head is None and facts.deleted_files:
        return EvidenceItem(
            description="Feature files deleted and issue closed without fix commit",
            weight=WEIGHT_FEATURE_NO_LONGER_PRESENT,
            category="obsolescence",
            source_ref=None,
        )
    return None


def check_revert_of_fix(match_set: MatchSet, facts: CurrentStateFacts) -> EvidenceItem | None:
    """Check if the fix commit was later reverted."""
    if facts.reverts_of_fix:
        revert_commit = facts.reverts_of_fix[0]
        return EvidenceItem(
            description=f"Fix commit was reverted by {revert_commit.short_sha}",
            weight=WEIGHT_FIX_LATER_REVERTED,
            category="obsolescence",
            source_ref=revert_commit.short_sha,
        )
    return None


# Registered list of evidence rules
ALL_RULES: list[Callable[[MatchSet, CurrentStateFacts], EvidenceItem | None]] = [
    check_fix_in_head,
    check_pr_merged,
    check_issue_referenced_by_fix_commit,
    check_files_exist,
    check_no_revert,
    check_issue_num_in_commit_msg,
    check_files_substantially_modified,
    check_files_deleted,
    check_feature_no_longer_present,
    check_revert_of_fix,
]


def collect_evidence(match_set: MatchSet, facts: CurrentStateFacts) -> tuple[EvidenceItem, ...]:
    """Collect all applicable evidence items for a given MatchSet and CurrentStateFacts.

    Args:
        match_set: The MatchSet containing issue correlation data.
        facts: CurrentStateFacts describing repository state.

    Returns:
        Tuple of collected EvidenceItem instances.
    """
    items: list[EvidenceItem] = []
    for rule in ALL_RULES:
        item = rule(match_set, facts)
        if item is not None:
            items.append(item)
    return tuple(items)
