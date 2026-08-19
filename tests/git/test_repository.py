"""Tests for GitRepository class."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from gitrelevance.git.repository import GitRepository, NotAGitRepositoryError
from tests.fixtures.repo_builder import RepoBuilder


@pytest.fixture
def simple_repo() -> tuple[str, RepoBuilder]:
    """A simple repo with 3 commits on main."""
    builder = (
        RepoBuilder()
        .commit("First commit", files={"README.md": "# Hello"})
        .commit("Second commit", files={"file.txt": "content"})
        .commit("Third commit", files={"another.py": "print('hi')"})
    )
    path = builder.build()
    yield path, builder
    builder.cleanup()


@pytest.fixture
def repo_with_branch() -> tuple[str, RepoBuilder]:
    """A repo with a main branch and a feature branch."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "init"})
        .branch("feature")
        .commit("Feature commit", files={"feature.py": "code"})
    )
    path = builder.build()
    yield path, builder
    builder.cleanup()


@pytest.fixture
def repo_with_remote() -> tuple[str, RepoBuilder]:
    """A repo with a remote configured."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "init"})
        .add_remote("origin", "https://github.com/test/repo.git")
    )
    path = builder.build()
    yield path, builder
    builder.cleanup()


class TestCurrentBranch:
    def test_default_branch(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        assert repo.current_branch() == "main"

    def test_on_feature_branch(self, repo_with_branch: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_branch
        repo = GitRepository(path)
        assert repo.current_branch() == "feature"


class TestHeadCommit:
    def test_head_commit(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        head = repo.head_commit()
        assert head.message == "Third commit"
        assert head.short_sha == head.sha[:7]
        assert isinstance(head.date, datetime)
        assert head.date.tzinfo is not None  # timezone-aware

    def test_head_commit_has_files(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        head = repo.head_commit()
        assert "another.py" in head.files_changed


class TestRemoteUrl:
    def test_with_remote(self, repo_with_remote: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_remote
        repo = GitRepository(path)
        assert repo.remote_url("origin") == "https://github.com/test/repo.git"

    def test_no_remote(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        assert repo.remote_url("origin") is None

    def test_nonexistent_remote(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        assert repo.remote_url("nonexistent") is None


class TestGetCommit:
    def test_existing_commit(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, builder = simple_repo
        repo = GitRepository(path)
        # Get the first commit SHA from the builder's repo
        first_commit = list(builder.build_repo().iter_commits(reverse=True))[0]
        commit = repo.get_commit(first_commit.hexsha)
        assert commit is not None
        assert commit.message == "First commit"

    def test_nonexistent_commit(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        assert repo.get_commit("0000000000000000000000000000000000000000") is None


class TestCommitExists:
    def test_existing(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, builder = simple_repo
        repo = GitRepository(path)
        first_commit = list(builder.build_repo().iter_commits(reverse=True))[0]
        assert repo.commit_exists(first_commit.hexsha) is True

    def test_nonexistent(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        assert repo.commit_exists("0000000000000000000000000000000000000000") is False


class TestIsAncestor:
    def test_true_case(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, builder = simple_repo
        repo = GitRepository(path)
        commits = list(builder.build_repo().iter_commits(reverse=True))
        # First commit is ancestor of third
        assert repo.is_ancestor(commits[0].hexsha, commits[2].hexsha) is True

    def test_false_case(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, builder = simple_repo
        repo = GitRepository(path)
        commits = list(builder.build_repo().iter_commits(reverse=True))
        # Third commit is NOT ancestor of first
        assert repo.is_ancestor(commits[2].hexsha, commits[0].hexsha) is False

    def test_self_is_ancestor(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, builder = simple_repo
        repo = GitRepository(path)
        commits = list(builder.build_repo().iter_commits(reverse=True))
        # A commit is an ancestor of itself
        assert repo.is_ancestor(commits[0].hexsha, commits[0].hexsha) is True


class TestCommitsSince:
    def test_all_commits(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, _ = simple_repo
        repo = GitRepository(path)
        commits = list(repo.commits_since(None))
        assert len(commits) == 3
        # Newest first
        assert commits[0].message == "Third commit"
        assert commits[2].message == "First commit"

    def test_with_since_date(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        path, builder = simple_repo
        repo = GitRepository(path)
        # Use a date far in the future to get no commits
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        commits = list(repo.commits_since(future))
        assert len(commits) == 0

        # Use a date far in the past to get all commits
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        commits_all = list(repo.commits_since(past))
        assert len(commits_all) == 3


class TestGitDirectoryUntouched:
    def test_git_dir_unchanged(self, simple_repo: tuple[str, RepoBuilder]) -> None:
        """Verify that the .git directory is not modified by any operations."""
        path, _ = simple_repo
        git_dir = os.path.join(path, ".git")

        # Record initial state of .git directory
        initial_files = set()
        for root, dirs, files in os.walk(git_dir):
            for f in files:
                initial_files.add(os.path.relpath(os.path.join(root, f), git_dir))

        repo = GitRepository(path)
        # Perform various read operations
        repo.current_branch()
        repo.head_commit()
        repo.get_commit(list(repo.commits_since(None))[0].sha)
        repo.commit_exists(list(repo.commits_since(None))[0].sha)
        list(repo.commits_since(None))

        # Record final state
        final_files = set()
        for root, dirs, files in os.walk(git_dir):
            for f in files:
                final_files.add(os.path.relpath(os.path.join(root, f), git_dir))

        # .git directory should not have gained new files
        # (timestamps may change but no new files should appear)
        new_files = final_files - initial_files
        # Filter out lock files that Git may create temporarily
        new_files = {f for f in new_files if not f.endswith(".lock")}
        assert len(new_files) == 0, f"New files appeared in .git: {new_files}"


class TestNotAGitRepositoryError:
    def test_non_git_directory(self, tmp_path: object) -> None:
        with pytest.raises(NotAGitRepositoryError):
            GitRepository("/nonexistent/path")

    def test_non_git_directory_real(self, tmp_path: object) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with pytest.raises(NotAGitRepositoryError):
                GitRepository(td)
