"""Tests for analysis matcher layer."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

import pytest

from gitrelevance.analysis.matcher import MatchSet, build_all_match_sets, build_match_set
from gitrelevance.git.repository import GitRepository
from gitrelevance.issues.models import Issue, PullRequest
from gitrelevance.providers.base import Provider
from tests.fixtures.repo_builder import RepoBuilder


class FakeProvider:
    """In-memory fake provider conforming to the Provider protocol."""

    def __init__(
        self,
        issues: list[Issue] | None = None,
        pull_requests: list[PullRequest] | None = None,
        comments: dict[int, list[str]] | None = None,
    ) -> None:
        self.issues = issues or []
        self.pull_requests = pull_requests or []
        self.comments = comments or {}
        self.get_pull_requests_call_count = 0
        self.get_issues_call_count = 0

    def parse_remote(self, remote_url: str) -> tuple[str, str] | None:
        return ("fake_owner", "fake_repo")

    def get_issues(self, state: Literal["open", "closed", "all"] = "all") -> list[Issue]:
        self.get_issues_call_count += 1
        return self.issues

    def get_pull_requests(
        self, state: Literal["open", "closed", "all"] = "all"
    ) -> list[PullRequest]:
        self.get_pull_requests_call_count += 1
        return self.pull_requests

    def get_issue_comments(self, issue_number: int) -> list[str]:
        return self.comments.get(issue_number, [])


@pytest.fixture
def test_repo() -> tuple[str, RepoBuilder, dict[str, str]]:
    """Build a real git repo with specific commits and capture SHAs."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "readme"})
        .commit("Fix #1: authentication bug", files={"auth.py": "auth fix", "config.py": "cfg"})
        .commit("Add feature for GH-2", files={"feature.py": "feat"})
        .commit("Merge pull request #10 from dev/fix-bug", files={"bug.py": "fix"})
    )
    path = builder.build()
    repo = GitRepository(path)

    shas = {}
    for c in repo.commits_since(None):
        if "Initial commit" in c.message:
            shas["initial"] = c.sha
        elif "Fix #1" in c.message:
            shas["issue_1"] = c.sha
        elif "GH-2" in c.message:
            shas["issue_2"] = c.sha
        elif "Merge pull request #10" in c.message:
            shas["pr_10_merge"] = c.sha

    yield path, builder, shas
    builder.cleanup()


def make_issue(
    number: int,
    title: str = "Test Issue",
    state: Literal["open", "closed"] = "open",
    linked_pr_numbers: tuple[int, ...] = (),
) -> Issue:
    return Issue(
        number=number,
        title=title,
        body="Issue description",
        state=state,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        closed_at=None if state == "open" else datetime(2024, 1, 2, tzinfo=timezone.utc),
        labels=("bug",),
        linked_pr_numbers=linked_pr_numbers,
    )


def make_pr(
    number: int,
    title: str = "Test PR",
    merged: bool = True,
    merge_commit_sha: str | None = None,
    closes_issue_numbers: tuple[int, ...] = (),
    files_changed: tuple[str, ...] = (),
) -> PullRequest:
    return PullRequest(
        number=number,
        title=title,
        merged=merged,
        merge_commit_sha=merge_commit_sha,
        closes_issue_numbers=closes_issue_numbers,
        files_changed=files_changed,
    )


class TestMatcher:
    """Test suite for analysis/matcher.py."""

    def test_protocol_conformance(self) -> None:
        """Verify FakeProvider satisfies Provider protocol."""
        provider = FakeProvider()
        assert isinstance(provider, Provider)

    def test_issue_referenced_only_by_commit_message(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """Issue referenced only by raw commit message (no PR) -> referencing_commits populated, linked_prs empty."""
        path, _, shas = test_repo
        repo = GitRepository(path)

        issue1 = make_issue(number=1, title="Auth bug")
        match_set = build_match_set(issue1, repo, provider_prs=[])

        assert isinstance(match_set, MatchSet)
        assert match_set.issue == issue1
        assert len(match_set.referencing_commits) == 1
        assert match_set.referencing_commits[0].sha == shas["issue_1"]
        assert match_set.linked_prs == ()
        assert match_set.pr_commits == ()
        assert match_set.related_files == ("auth.py", "config.py")

    def test_issue_closed_by_merged_pr(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """Issue closed by a merged PR -> linked_prs populated, pr_commits resolved, files included."""
        path, _, shas = test_repo
        repo = GitRepository(path)

        issue = make_issue(number=100, title="Closed by PR")
        pr10 = make_pr(
            number=10,
            title="Fix bug PR",
            merged=True,
            merge_commit_sha=shas["pr_10_merge"],
            closes_issue_numbers=(100,),
            files_changed=("bug.py", "extra.py"),
        )

        match_set = build_match_set(issue, repo, provider_prs=[pr10])

        assert len(match_set.referencing_commits) == 0
        assert len(match_set.linked_prs) == 1
        assert match_set.linked_prs[0].number == 10
        assert len(match_set.pr_commits) == 1
        assert match_set.pr_commits[0].sha == shas["pr_10_merge"]
        # When merge commit IS resolved locally, pr.files_changed is skipped
        # in favor of the merge commit's actual git diff (more accurate).
        # The merge commit only touched bug.py, not extra.py.
        assert match_set.related_files == ("bug.py",)

    def test_issue_linked_via_issue_linked_prs(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """Issue connected to PR via issue.linked_pr_numbers (e.g. cross-referenced)."""
        path, _, shas = test_repo
        repo = GitRepository(path)

        issue = make_issue(number=200, title="Cross ref issue", linked_pr_numbers=(10,))
        pr10 = make_pr(
            number=10,
            title="Referencing PR",
            merged=True,
            merge_commit_sha=shas["pr_10_merge"],
            closes_issue_numbers=(),  # Not explicitly closing, but linked in issue
            files_changed=("bug.py",),
        )

        match_set = build_match_set(issue, repo, provider_prs=[pr10])

        assert len(match_set.linked_prs) == 1
        assert match_set.linked_prs[0].number == 10
        assert len(match_set.pr_commits) == 1
        assert match_set.pr_commits[0].sha == shas["pr_10_merge"]

    def test_issue_with_no_relationship(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """Issue with no relationship to any commit/PR -> MatchSet with all empty tuples."""
        path, _, _ = test_repo
        repo = GitRepository(path)

        issue = make_issue(number=999, title="Unrelated issue")
        pr = make_pr(number=50, closes_issue_numbers=(123,))

        match_set = build_match_set(issue, repo, provider_prs=[pr])

        assert match_set.issue == issue
        assert match_set.referencing_commits == ()
        assert match_set.linked_prs == ()
        assert match_set.pr_commits == ()
        assert match_set.related_files == ()

    def test_pr_merge_commit_not_in_local_repo(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """PR merge commit not present in local repo is gracefully skipped."""
        path, _, _ = test_repo
        repo = GitRepository(path)

        issue = make_issue(number=5)
        pr = make_pr(
            number=55,
            merged=True,
            merge_commit_sha="0000000000000000000000000000000000000000",
            closes_issue_numbers=(5,),
            files_changed=("remote_only.py",),
        )

        match_set = build_match_set(issue, repo, provider_prs=[pr])

        assert len(match_set.linked_prs) == 1
        assert match_set.pr_commits == ()  # Missing commit skipped gracefully
        # Merged PRs whose merge commit is missing (shallow clone) also skip
        # pr.files_changed to avoid cross-contamination from unrelated changesets.
        assert match_set.related_files == ()

    def test_pr_deduplication(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """If a PR is both in closes_issue_numbers and linked_pr_numbers, it is not duplicated."""
        path, _, shas = test_repo
        repo = GitRepository(path)

        issue = make_issue(number=100, linked_pr_numbers=(10,))
        pr10 = make_pr(
            number=10,
            merged=True,
            merge_commit_sha=shas["pr_10_merge"],
            closes_issue_numbers=(100,),
            files_changed=("bug.py",),
        )

        match_set = build_match_set(issue, repo, provider_prs=[pr10])
        assert len(match_set.linked_prs) == 1
        assert len(match_set.pr_commits) == 1

    def test_related_files_sorting_and_deduplication(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """related_files combines referencing commits, PR commits, and PR file lists."""
        path, _, shas = test_repo
        repo = GitRepository(path)

        # Issue 1 is referenced by commit with auth.py and config.py
        issue = make_issue(number=1)
        pr = make_pr(
            number=10,
            merged=True,
            merge_commit_sha=shas["pr_10_merge"],  # has bug.py
            closes_issue_numbers=(1,),
            files_changed=("zebra.py", "auth.py"),  # auth.py is duplicate
        )

        match_set = build_match_set(issue, repo, provider_prs=[pr])
        # Union from referencing commits (auth.py, config.py) + merge commit (bug.py).
        # PR files_changed (zebra.py) is skipped because the merge commit IS resolved
        # locally and its actual git diff is more accurate.
        assert match_set.related_files == ("auth.py", "bug.py", "config.py")

    def test_build_all_match_sets_single_pr_fetch(
        self, test_repo: tuple[str, RepoBuilder, dict[str, str]]
    ) -> None:
        """build_all_match_sets only calls provider.get_pull_requests once regardless of issue count."""
        path, _, shas = test_repo
        repo = GitRepository(path)

        issues = [
            make_issue(number=1, title="Issue 1"),
            make_issue(number=2, title="Issue 2"),
            make_issue(number=3, title="Issue 3"),
            make_issue(number=4, title="Issue 4"),
        ]
        prs = [
            make_pr(number=10, merge_commit_sha=shas["pr_10_merge"], closes_issue_numbers=(1,)),
            make_pr(number=20, closes_issue_numbers=(2,)),
        ]

        fake_provider = FakeProvider(issues=issues, pull_requests=prs)

        match_sets = build_all_match_sets(issues, repo, fake_provider)

        # Provider.get_pull_requests must be called exactly once
        assert fake_provider.get_pull_requests_call_count == 1
        assert len(match_sets) == 4
        assert set(match_sets.keys()) == {1, 2, 3, 4}
        assert match_sets[1].issue.number == 1
        assert len(match_sets[1].referencing_commits) == 1
        assert len(match_sets[1].linked_prs) == 1
        assert match_sets[2].issue.number == 2
        assert len(match_sets[2].referencing_commits) == 1
        assert len(match_sets[3].referencing_commits) == 0
        assert match_sets[3].linked_prs == ()
