"""Tests for file operations (FileOperations mixin)."""

from __future__ import annotations


import pytest

from gitrelevance.git.repository import GitRepository
from gitrelevance.git.files import FileOperations, get_file_operations
from tests.fixtures.repo_builder import RepoBuilder


@pytest.fixture
def repo_with_files() -> tuple[str, RepoBuilder]:
    """A repo with several files across commits."""
    builder = (
        RepoBuilder()
        .commit("Initial commit", files={"README.md": "# Hello", "src/main.py": "print('hello')"})
        .commit("Add config", files={"config.yaml": "key: value"})
        .commit("Modify main", files={"src/main.py": "print('modified')"})
    )
    path = builder.build()
    yield path, builder
    builder.cleanup()


@pytest.fixture
def repo_with_deleted_file() -> tuple[str, RepoBuilder]:
    """A repo where a file is added then properly deleted via git rm."""
    builder2 = RepoBuilder().commit("Add file", files={"temp.txt": "temporary"})
    path2 = builder2.build()

    # Stage the deletion properly: remove from index, then commit
    import git as gitmodule
    repo = gitmodule.Repo(path2)
    # index.remove stages the deletion; working_tree=True also removes from disk
    repo.index.remove(["temp.txt"], working_tree=True)
    repo.index.commit("Delete file")

    yield path2, builder2
    builder2.cleanup()


@pytest.fixture
def repo_with_renamed_file() -> tuple[str, RepoBuilder]:
    """A repo where a file is renamed using git mv."""
    builder = RepoBuilder()
    builder.commit("Initial commit", files={"old_name.py": "content"})
    path = builder.build()
    # Perform a git mv
    import git as gitmodule
    repo = gitmodule.Repo(path)
    repo.index.move(["old_name.py", "new_name.py"])
    repo.index.commit("Rename file")
    yield path, builder
    builder.cleanup()


class TestFileExistsAtHead:
    def test_existing_file(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        assert file_ops.file_exists_at_head("README.md") is True

    def test_nonexistent_file(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        assert file_ops.file_exists_at_head("nonexistent.py") is False

    def test_nested_file(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        assert file_ops.file_exists_at_head("src/main.py") is True


class TestWasFileDeleted:
    def test_deleted_file(self, repo_with_deleted_file: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_deleted_file
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        assert file_ops.was_file_deleted("temp.txt") is True

    def test_existing_file_not_deleted(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        assert file_ops.was_file_deleted("README.md") is False

    def test_never_existed(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        assert file_ops.was_file_deleted("never_existed.txt") is False


class TestFileHistory:
    def test_file_history(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        history = file_ops.file_history("src/main.py")
        # main.py was touched in commit 1 and commit 3
        assert len(history) == 2
        messages = [c.message for c in history]
        assert "Initial commit" in messages
        assert "Modify main" in messages

    def test_file_history_follows_renames(self, repo_with_renamed_file: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_renamed_file
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        history = file_ops.file_history("new_name.py")
        # Should find both the original commit and the rename commit
        assert len(history) == 2


class TestFindRenames:
    def test_find_renames(self, repo_with_renamed_file: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_renamed_file
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        renames = file_ops.find_renames("new_name.py")
        # Should find at least one rename: old_name.py -> new_name.py
        assert len(renames) >= 1
        assert ("old_name.py", "new_name.py") in renames

    def test_no_renames(self, repo_with_files: tuple[str, RepoBuilder]) -> None:
        path, _ = repo_with_files
        repo = GitRepository(path)
        file_ops = get_file_operations(repo)
        renames = file_ops.find_renames("README.md")
        assert renames == []
