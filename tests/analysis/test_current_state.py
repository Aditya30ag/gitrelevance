"""Tests for analysis current_state module."""

from __future__ import annotations

from datetime import datetime, timezone
import git
import pytest

from gitrelevance.analysis.current_state import CurrentStateFacts, analyze_current_state
from gitrelevance.analysis.matcher import MatchSet, build_match_set
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import Issue, PullRequest
from tests.fixtures.repo_builder import RepoBuilder


def make_issue(number: int = 1, title: str = "Test Issue") -> Issue:
    return Issue(
        number=number,
        title=title,
        body="Body",
        state="closed",
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        labels=(),
        linked_pr_numbers=(),
    )


def make_pr(
    number: int = 10,
    merged: bool = True,
    merge_commit_sha: str | None = None,
    closes_issue_numbers: tuple[int, ...] = (1,),
    files_changed: tuple[str, ...] = (),
) -> PullRequest:
    return PullRequest(
        number=number,
        title="Test PR",
        merged=merged,
        merge_commit_sha=merge_commit_sha,
        closes_issue_numbers=closes_issue_numbers,
        files_changed=files_changed,
    )


class TestCurrentStateAnalysis:
    """Test cases for analyze_current_state."""

    def test_fix_commit_in_head(self) -> None:
        """A MatchSet whose fix commit is an ancestor of HEAD -> fix_commit_in_head set correctly."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"main.py": "print('hello')"})
            .commit("Fix #1: login bug", files={"auth.py": "def login(): pass"})
            .commit("Subsequent commit", files={"main.py": "print('updated')"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=1)
            match_set = build_match_set(issue, repo, provider_prs=[])

            facts = analyze_current_state(match_set, repo)

            assert isinstance(facts, CurrentStateFacts)
            assert facts.fix_commit_in_head is not None
            assert "Fix #1" in facts.fix_commit_in_head.message
            assert facts.all_related_files_exist is True
            assert facts.deleted_files == ()
            assert facts.renamed_files == ()
            assert facts.reverts_of_fix == ()
        finally:
            builder.cleanup()

    def test_deleted_files(self) -> None:
        """A MatchSet whose related file was deleted after the fix -> deleted_files populated, all_related_files_exist False."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: add old_module.py", files={"old_module.py": "# old code"})
        )
        path = builder.build()
        try:
            g = git.Repo(path)
            g.index.remove(["old_module.py"], working_tree=True)
            g.index.commit("Delete old_module.py")

            repo = GitRepository(path)
            issue = make_issue(number=1)
            match_set = build_match_set(issue, repo, provider_prs=[])

            facts = analyze_current_state(match_set, repo)

            assert facts.fix_commit_in_head is not None
            assert facts.all_related_files_exist is False
            assert "old_module.py" in facts.deleted_files
            assert facts.renamed_files == ()
        finally:
            builder.cleanup()

    def test_renamed_files(self) -> None:
        """A MatchSet whose related file was renamed (not deleted) -> renamed_files populated, and file not in deleted_files."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: add legacy.py", files={"legacy.py": "class Legacy: pass"})
        )
        path = builder.build()
        try:
            g = git.Repo(path)
            g.git.mv("legacy.py", "modern.py")
            g.index.commit("Rename legacy.py to modern.py")

            repo = GitRepository(path)
            issue = make_issue(number=1)
            match_set = build_match_set(issue, repo, provider_prs=[])

            facts = analyze_current_state(match_set, repo)

            assert ("legacy.py", "modern.py") in facts.renamed_files
            assert "legacy.py" not in facts.deleted_files
        finally:
            builder.cleanup()

    def test_reverts_of_fix(self) -> None:
        """A MatchSet whose fix commit was later reverted via a real git revert -> reverts_of_fix populated."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
            .commit("Fix #1: introduce feature", files={"feature.py": "def feature(): pass"})
        )
        path = builder.build()
        try:
            g = git.Repo(path)
            fix_sha = list(g.iter_commits(reverse=True))[1].hexsha

            builder.revert(fix_sha)

            repo = GitRepository(path)
            issue = make_issue(number=1)
            match_set = build_match_set(issue, repo, provider_prs=[])

            facts = analyze_current_state(match_set, repo)

            assert facts.fix_commit_in_head is not None
            assert len(facts.reverts_of_fix) == 1
            assert "Revert" in facts.reverts_of_fix[0].message
        finally:
            builder.cleanup()

    def test_empty_match_set(self) -> None:
        """An empty MatchSet (no commits at all) -> all fields sensibly empty/False, no exception."""
        builder = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "readme"})
        )
        path = builder.build()
        try:
            repo = GitRepository(path)
            issue = make_issue(number=999, title="Unrelated issue")
            match_set = build_match_set(issue, repo, provider_prs=[])

            facts = analyze_current_state(match_set, repo)

            assert isinstance(facts, CurrentStateFacts)
            assert facts.fix_commit_in_head is None
            assert facts.all_related_files_exist is False
            assert facts.deleted_files == ()
            assert facts.renamed_files == ()
            assert facts.reverts_of_fix == ()
        finally:
            builder.cleanup()
