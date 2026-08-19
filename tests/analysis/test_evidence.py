"""Unit tests for evidence collection rules."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from gitrelevance.analysis.current_state import CurrentStateFacts
from gitrelevance.analysis.evidence import (
    WEIGHT_FEATURE_NO_LONGER_PRESENT,
    WEIGHT_FILES_DELETED_NO_REPLACEMENT,
    WEIGHT_FILES_STILL_EXIST,
    WEIGHT_FILES_SUBSTANTIALLY_MODIFIED,
    WEIGHT_FIX_COMMIT_IN_HEAD,
    WEIGHT_FIX_LATER_REVERTED,
    WEIGHT_FIXING_PR_MERGED,
    WEIGHT_ISSUE_NUM_IN_COMMIT_MSG,
    WEIGHT_ISSUE_REFERENCED_BY_FIX_COMMIT,
    WEIGHT_NO_REVERT_DETECTED,
    check_feature_no_longer_present,
    check_files_deleted,
    check_files_exist,
    check_files_substantially_modified,
    check_fix_in_head,
    check_revert_of_fix,
    check_issue_num_in_commit_msg,
    check_issue_referenced_by_fix_commit,
    check_no_revert,
    check_pr_merged,
    collect_evidence,
)
from gitrelevance.analysis.matcher import MatchSet
from gitrelevance.git.commits import Commit
from gitrelevance.issues.models import Issue, PullRequest


def make_dummy_commit(sha: str = "1234567890abcdef1234567890abcdef12345678", msg: str = "Fix #1") -> Commit:
    return Commit(
        sha=sha,
        short_sha=sha[:7],
        message=msg,
        author="Author",
        date=datetime.now(timezone.utc),
        files_changed=("file.py",),
    )


def make_dummy_issue(number: int = 1, state: str = "open") -> Issue:
    return Issue(
        number=number,
        title="Test Issue",
        body="Body",
        state="closed" if state == "closed" else "open",
        created_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc) if state == "closed" else None,
        labels=(),
        linked_pr_numbers=(),
    )


def make_dummy_pr(number: int = 10, merged: bool = True) -> PullRequest:
    return PullRequest(
        number=number,
        title="Test PR",
        merged=merged,
        merge_commit_sha="abcdef1234567890abcdef1234567890abcdef12",
        closes_issue_numbers=(1,),
        files_changed=("file.py",),
    )


def make_dummy_match_set(
    issue: Issue | None = None,
    referencing_commits: tuple[Commit, ...] = (),
    linked_prs: tuple[PullRequest, ...] = (),
    pr_commits: tuple[Commit, ...] = (),
    related_files: tuple[str, ...] = (),
) -> MatchSet:
    return MatchSet(
        issue=issue or make_dummy_issue(),
        referencing_commits=referencing_commits,
        linked_prs=linked_prs,
        pr_commits=pr_commits,
        related_files=related_files,
    )


def make_dummy_facts(
    fix_commit_in_head: Commit | None = None,
    all_related_files_exist: bool = False,
    deleted_files: tuple[str, ...] = (),
    renamed_files: tuple[tuple[str, str], ...] = (),
    reverts_of_fix: tuple[Commit, ...] = (),
) -> CurrentStateFacts:
    return CurrentStateFacts(
        fix_commit_in_head=fix_commit_in_head,
        all_related_files_exist=all_related_files_exist,
        deleted_files=deleted_files,
        renamed_files=renamed_files,
        reverts_of_fix=reverts_of_fix,
    )


class TestEvidenceRules:

    def test_check_fix_in_head(self) -> None:
        commit = make_dummy_commit()
        match_set = make_dummy_match_set()
        facts_hit = make_dummy_facts(fix_commit_in_head=commit)
        facts_miss = make_dummy_facts(fix_commit_in_head=None)

        item = check_fix_in_head(match_set, facts_hit)
        assert item is not None
        assert item.weight == WEIGHT_FIX_COMMIT_IN_HEAD
        assert item.category == "strong"
        assert item.source_ref == commit.short_sha

        assert check_fix_in_head(match_set, facts_miss) is None

    def test_check_pr_merged(self) -> None:
        pr_merged = make_dummy_pr(number=42, merged=True)
        pr_unmerged = make_dummy_pr(number=43, merged=False)

        match_set_hit = make_dummy_match_set(linked_prs=(pr_merged,))
        match_set_miss = make_dummy_match_set(linked_prs=(pr_unmerged,))
        facts = make_dummy_facts()

        item = check_pr_merged(match_set_hit, facts)
        assert item is not None
        assert item.weight == WEIGHT_FIXING_PR_MERGED
        assert item.category == "strong"
        assert item.source_ref == "PR #42"

        assert check_pr_merged(match_set_miss, facts) is None

    def test_check_issue_referenced_by_fix_commit(self) -> None:
        commit = make_dummy_commit()
        match_set_hit = make_dummy_match_set(referencing_commits=(commit,))
        match_set_miss = make_dummy_match_set(referencing_commits=())
        facts = make_dummy_facts()

        item = check_issue_referenced_by_fix_commit(match_set_hit, facts)
        assert item is not None
        assert item.weight == WEIGHT_ISSUE_REFERENCED_BY_FIX_COMMIT
        assert item.category == "strong"
        assert item.source_ref == commit.short_sha

        assert check_issue_referenced_by_fix_commit(match_set_miss, facts) is None

    def test_check_files_exist(self) -> None:
        match_set = make_dummy_match_set(related_files=("a.py",))
        facts_hit = make_dummy_facts(all_related_files_exist=True)
        facts_miss = make_dummy_facts(all_related_files_exist=False)

        item = check_files_exist(match_set, facts_hit)
        assert item is not None
        assert item.weight == WEIGHT_FILES_STILL_EXIST
        assert item.category == "medium"

        assert check_files_exist(match_set, facts_miss) is None

    def test_check_no_revert(self) -> None:
        commit = make_dummy_commit()
        match_set = make_dummy_match_set()
        facts_hit = make_dummy_facts(fix_commit_in_head=commit, reverts_of_fix=())
        facts_miss = make_dummy_facts(fix_commit_in_head=commit, reverts_of_fix=(make_dummy_commit(),))

        item = check_no_revert(match_set, facts_hit)
        assert item is not None
        assert item.weight == WEIGHT_NO_REVERT_DETECTED
        assert item.category == "medium"

        assert check_no_revert(match_set, facts_miss) is None

    def test_check_files_deleted(self) -> None:
        match_set = make_dummy_match_set()
        facts_hit = make_dummy_facts(deleted_files=("old.py",))
        facts_miss = make_dummy_facts(deleted_files=())

        item = check_files_deleted(match_set, facts_hit)
        assert item is not None
        assert item.weight == WEIGHT_FILES_DELETED_NO_REPLACEMENT
        assert item.category == "obsolescence"

        assert check_files_deleted(match_set, facts_miss) is None

    def test_check_revert_of_fix(self) -> None:
        revert_commit = make_dummy_commit(sha="9999999999999999999999999999999999999999", msg="Revert fix")
        match_set = make_dummy_match_set()
        facts_hit = make_dummy_facts(reverts_of_fix=(revert_commit,))
        facts_miss = make_dummy_facts(reverts_of_fix=())

        item = check_revert_of_fix(match_set, facts_hit)
        assert item is not None
        assert item.weight == WEIGHT_FIX_LATER_REVERTED
        assert item.category == "obsolescence"
        assert item.source_ref == revert_commit.short_sha

        assert check_revert_of_fix(match_set, facts_miss) is None

    def test_collect_evidence_integration(self) -> None:
        commit = make_dummy_commit()
        match_set = make_dummy_match_set(referencing_commits=(commit,), related_files=("a.py",))
        facts = make_dummy_facts(fix_commit_in_head=commit, all_related_files_exist=True)

        items = collect_evidence(match_set, facts)
        assert len(items) > 0
        descriptions = [i.description for i in items]
        assert "Fix commit is present in HEAD history" in descriptions
