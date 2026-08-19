"""Tests for commit reference index and revert detection."""

from __future__ import annotations

import pytest

from gitrelevance.git.repository import GitRepository
from gitrelevance.git.history import (
    build_commit_reference_index,
    commits_referencing,
    GitNativeRevertDetector,
    default_revert_detector,
)
from tests.fixtures.repo_builder import RepoBuilder


@pytest.fixture
def repo_with_issue_refs() -> tuple[str, RepoBuilder]:
    """A repo with commits referencing issue numbers."""
    builder = (
        RepoBuilder()
        .commit("Fix #1: login bug", files={"auth.py": "fix"})
        .commit("GH-2: add tests", files={"test_auth.py": "test"})
        .commit("Refactor code", files={"utils.py": "refactor"})
        .commit("Fix #1: edge case", files={"auth.py": "edge"})
        .commit("Close #3: docs", files={"README.md": "docs"})
        .commit("GH-1: another fix", files={"auth.py": "another"})
    )
    path = builder.build()
    yield path, builder
    builder.cleanup()


@pytest.fixture
def repo_with_revert() -> tuple[str, RepoBuilder]:
    """A repo with a real git revert."""
    builder = (
        RepoBuilder()
        .commit("Add feature", files={"feature.py": "feature code"})
        .commit("Another commit", files={"other.py": "other"})
    )
    path = builder.build()

    # Get the SHA of the first commit to revert
    import git
    g = git.Repo(path)
    first_sha = list(g.iter_commits(reverse=True))[0].hexsha

    # Revert it
    builder.revert(first_sha)

    yield path, builder, first_sha
    builder.cleanup()


@pytest.fixture
def repo_with_fake_revert() -> tuple[str, RepoBuilder]:
    """A repo with a commit that mentions 'revert' but isn't a real git revert."""
    builder = (
        RepoBuilder()
        .commit("Add feature", files={"feature.py": "feature code"})
        .commit(
            "Revert: manually undo feature",
            files={"feature.py": "# reverted manually"},
        )
    )
    path = builder.build()

    import git
    g = git.Repo(path)
    first_sha = list(g.iter_commits(reverse=True))[0].hexsha

    yield path, builder, first_sha
    builder.cleanup()


class TestBuildCommitReferenceIndex:
    def test_index_structure(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        index = build_commit_reference_index(repo)
        assert isinstance(index, dict)
        assert 1 in index
        assert 2 in index
        assert 3 in index

    def test_issue_1_references(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        index = build_commit_reference_index(repo)
        # Issue #1 is referenced in 3 commits
        assert len(index[1]) == 3
        messages = [c.message for c in index[1]]
        assert "Fix #1: login bug" in messages
        assert "Fix #1: edge case" in messages
        assert "GH-1: another fix" in messages

    def test_issue_2_references(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        index = build_commit_reference_index(repo)
        assert len(index[2]) == 1
        assert index[2][0].message == "GH-2: add tests"

    def test_nonexistent_issue(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        index = build_commit_reference_index(repo)
        assert 999 not in index


class TestCommitsReferencing:
    def test_commits_referencing(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        commits = commits_referencing(repo, 1)
        assert len(commits) == 3

    def test_commits_referencing_nonexistent(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        commits = commits_referencing(repo, 999)
        assert commits == []


class TestIndexCaching:
    def test_index_is_cached(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        """Verify the index is cached and not rebuilt on second call."""
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)

        index1 = build_commit_reference_index(repo)
        index2 = build_commit_reference_index(repo)

        # Same object - not rebuilt
        assert index1 is index2

    def test_commits_referencing_uses_cache(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        """Verify commits_referencing uses the cached index."""
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)

        # Build the index first
        build_commit_reference_index(repo)

        # Now calling commits_referencing should not rebuild
        index_before = id(getattr(repo, "_gitrelevance_commit_reference_index"))
        commits_referencing(repo, 1)
        index_after = id(getattr(repo, "_gitrelevance_commit_reference_index"))

        assert index_before == index_after


class TestGitNativeRevertDetector:
    def test_detects_real_revert(self, repo_with_revert: tuple[str, object]) -> None:
        path, _, first_sha = repo_with_revert
        repo = GitRepository(path)
        detector = GitNativeRevertDetector()
        reverts = detector.find_reverts_of(repo, first_sha)
        assert len(reverts) == 1
        # The revert commit message should contain "Revert"
        assert "Revert" in reverts[0].message

    def test_does_not_detect_fake_revert(self, repo_with_fake_revert: tuple[str, object]) -> None:
        path, _, first_sha = repo_with_fake_revert
        repo = GitRepository(path)
        detector = GitNativeRevertDetector()
        reverts = detector.find_reverts_of(repo, first_sha)
        # The second commit mentions "revert" in its message but isn't a real git revert
        assert len(reverts) == 0

    def test_no_reverts_for_unreverted_commit(self, repo_with_issue_refs: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_issue_refs
        repo = GitRepository(path)
        detector = GitNativeRevertDetector()
        commits = list(repo.commits_since(None))
        reverts = detector.find_reverts_of(repo, commits[0].sha)
        assert reverts == []


class TestDefaultRevertDetector:
    def test_returns_singleton(self) -> None:
        d1 = default_revert_detector()
        d2 = default_revert_detector()
        assert d1 is d2

    def test_is_git_native(self) -> None:
        d = default_revert_detector()
        assert isinstance(d, GitNativeRevertDetector)
