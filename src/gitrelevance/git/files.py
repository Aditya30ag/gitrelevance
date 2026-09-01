"""File change tracking and file history operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import git as gitmodule

from gitrelevance.git.commits import Commit
from gitrelevance.git.repository import GitRepository


@dataclass(frozen=True, slots=True)
class FileChange:
    """Represents a change to a file in a commit.

    Attributes:
        path: Current path of the file
        change_type: Type of change (added, modified, deleted, renamed)
        old_path: Previous path if the file was renamed, None otherwise
    """

    path: str
    change_type: Literal["added", "modified", "deleted", "renamed"]
    old_path: str | None


class FileOperations:
    """Provides file-related operations for GitRepository.

    This class wraps a GitRepository to add file-related functionality
    without modifying the main class.
    """

    def __init__(self, repo: GitRepository) -> None:
        """Initialize with a GitRepository instance.

        Args:
            repo: The GitRepository to operate on
        """
        self._repo = repo

    @property
    def _git_repo(self) -> gitmodule.Repo:
        """Access the underlying GitPython repo object."""
        return self._repo._repo  # type: ignore[return-value]

    def _get_head_files(self) -> set[str]:
        """Get or compute cached set of all file paths present at HEAD."""
        if not hasattr(self._repo, "_head_files_cache"):
            head_files: set[str] = set()
            try:
                head_commit = self._git_repo.head.commit
                for item in head_commit.tree.traverse():
                    if item.type == "blob":
                        head_files.add(item.path)
            except Exception:
                pass
            setattr(self._repo, "_head_files_cache", head_files)
        return getattr(self._repo, "_head_files_cache")

    def _get_rename_index(self) -> dict[str, list[tuple[str, str]]]:
        """Get or compute cached repository-wide rename index."""
        if not hasattr(self._repo, "_rename_index_cache"):
            rename_index: dict[str, list[tuple[str, str]]] = {}
            all_renames: list[tuple[str, str]] = []
            try:
                output: str = self._git_repo.git.log(
                    "-M",
                    "--diff-filter=R",
                    "--name-status",
                    "--format=",
                )
                for line in output.splitlines():
                    line = line.strip()
                    if not line or not line.startswith("R"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        old, new = parts[1].strip(), parts[2].strip()
                        all_renames.append((old, new))
            except gitmodule.GitCommandError:
                pass

            # git log returns newest-first; reverse to get chronological order
            all_renames.reverse()

            for old, new in all_renames:
                rename_index.setdefault(old, []).append((old, new))
                if new != old:
                    rename_index.setdefault(new, []).append((old, new))

            setattr(self._repo, "_rename_index_cache", rename_index)
        return getattr(self._repo, "_rename_index_cache")

    def file_exists_at_head(self, path: str) -> bool:
        """Check if a file exists at HEAD.

        Args:
            path: Path to the file relative to repository root

        Returns:
            True if the file exists at HEAD
        """
        head_files = self._get_head_files()
        if head_files:
            return path in head_files
        try:
            self._git_repo.head.commit.tree[path]
            return True
        except (KeyError, Exception):
            return False

    def file_history(self, path: str) -> list[Commit]:
        """Get the history of a file, following renames.

        Uses ``git log --follow`` (not ``git rev-list --follow``, which is
        unsupported) so that rename tracking works correctly.

        Args:
            path: Current path to the file

        Returns:
            List of commits that touched this file, newest first
        """
        try:
            # git log --follow --format=%H emits one sha per commit, newest first.
            # We must call git log (not rev-list); --follow is only a log option.
            output: str = self._git_repo.git.log(
                "--follow",
                "--format=%H",
                "--",
                path,
            )
        except gitmodule.GitCommandError:
            return []

        if not output.strip():
            return []

        commits: list[Commit] = []
        for sha in output.strip().splitlines():
            sha = sha.strip()
            if sha:
                try:
                    git_commit = self._git_repo.commit(sha)
                    commits.append(Commit.from_gitpython(git_commit))
                except Exception:
                    continue
        return commits

    def was_file_deleted(self, path: str) -> bool:
        """Check if a file was deleted (does not exist at HEAD).

        Args:
            path: Path to check

        Returns:
            True if the file does not exist at HEAD but existed in history
        """
        if self.file_exists_at_head(path):
            return False

        deleted_cache = getattr(self._repo, "_was_deleted_cache", None)
        if deleted_cache is None:
            deleted_cache = {}
            setattr(self._repo, "_was_deleted_cache", deleted_cache)

        if path in deleted_cache:
            return deleted_cache[path]

        # Check whether the path ever appeared in commit history
        try:
            output: str = self._git_repo.git.log(
                "--format=%H",
                "--max-count=1",
                "--diff-filter=D",
                "--",
                path,
            )
            # If git log --diff-filter=D finds anything, the file was deleted
            if output.strip():
                deleted_cache[path] = True
                return True
            # Also check if it was ever added at all (it might be renamed out)
            output2: str = self._git_repo.git.log(
                "--follow",
                "--format=%H",
                "--max-count=1",
                "--",
                path,
            )
            res = bool(output2.strip())
            deleted_cache[path] = res
            return res
        except Exception:
            deleted_cache[path] = False
            return False

    def find_renames(self, path: str) -> list[tuple[str, str]]:
        """Find all renames of a file, returning (old_path, new_path) pairs.

        Args:
            path: Current or historical path of the file

        Returns:
            List of (old_path, new_path) tuples showing the rename chain,
            in chronological order (oldest rename first).
        """
        index = self._get_rename_index()
        return list(index.get(path, []))


# Convenience function to get file operations for a repository
def get_file_operations(repo: GitRepository) -> FileOperations:
    """Get a FileOperations instance for a repository.

    Args:
        repo: The GitRepository to get file operations for

    Returns:
        FileOperations instance
    """
    return FileOperations(repo)
