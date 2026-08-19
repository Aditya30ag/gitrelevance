"""GitRepository class for accessing Git repository data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

import git
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from gitrelevance.git.commits import Commit


class NotAGitRepositoryError(Exception):
    """Raised when the provided path is not a valid Git repository."""

    def __init__(self, path: str) -> None:
        """Initialize the exception.

        Args:
            path: The path that was not a valid Git repository
        """
        self.path = path
        super().__init__(f"Not a Git repository: {path}")


class GitRepository:
    """A read-only wrapper around a GitPython repository.

    This class provides a clean interface for reading Git repository data
    without modifying the .git directory.

    Attributes:
        path: Absolute path to the repository root
        _repo: The underlying GitPython Repo object
    """

    def __init__(self, path: str) -> None:
        """Initialize the GitRepository.

        Args:
            path: Path to the Git repository root (or a directory within it)

        Raises:
            NotAGitRepositoryError: If the path is not a valid Git repository
        """
        try:
            self._repo = git.Repo(path, search_parent_directories=True)
            self.path = str(self._repo.working_dir)
        except (InvalidGitRepositoryError, NoSuchPathError, git.exc.GitError) as e:
            raise NotAGitRepositoryError(path) from e

    def current_branch(self) -> str:
        """Get the name of the current branch.

        Returns:
            Name of the current branch (without 'refs/heads/' prefix)

        Raises:
            RuntimeError: If in detached HEAD state
        """
        if self._repo.head.is_detached:
            raise RuntimeError("Repository is in detached HEAD state")
        return self._repo.active_branch.name

    def head_commit(self) -> Commit:
        """Get the commit at HEAD.

        Returns:
            Commit object for HEAD

        Raises:
            RuntimeError: If there are no commits yet
        """
        try:
            return Commit.from_gitpython(self._repo.head.commit)
        except (TypeError, AttributeError):
            raise RuntimeError("Repository has no commits yet")

    def remote_url(self, name: str = "origin") -> str | None:
        """Get the URL of a remote.

        Args:
            name: Name of the remote (default: "origin")

        Returns:
            Remote URL if the remote exists, None otherwise
        """
        try:
            remote = self._repo.remote(name)
            if remote.refs:
                return str(remote.url)
            return str(remote.url) if remote.url else None
        except (ValueError, AttributeError):
            return None

    def get_commit(self, sha: str) -> Commit | None:
        """Get a commit by its SHA.

        Args:
            sha: Full or abbreviated commit SHA

        Returns:
            Commit object if found, None otherwise
        """
        try:
            commit = self._repo.commit(sha)
            return Commit.from_gitpython(commit)
        except (git.BadName, ValueError):
            return None

    def commit_exists(self, sha: str) -> bool:
        """Check if a commit exists.

        Args:
            sha: Full or abbreviated commit SHA

        Returns:
            True if the commit exists, False otherwise
        """
        return self.get_commit(sha) is not None

    def is_ancestor(self, ancestor_sha: str, descendant_sha: str) -> bool:
        """Check if one commit is an ancestor of another.

        Args:
            ancestor_sha: Potential ancestor commit SHA
            descendant_sha: Potential descendant commit SHA

        Returns:
            True if ancestor_sha is an ancestor of descendant_sha

        Raises:
            git.GitCommandError: If either commit doesn't exist
        """
        # Use git merge-base --is-ancestor which returns 0 if true, 1 if false
        try:
            self._repo.git.merge_base("--is-ancestor", ancestor_sha, descendant_sha)
            return True  # git command succeeded, so it is an ancestor
        except git.GitCommandError:
            return False  # exit code 1 means not an ancestor

    def commits_since(self, since: datetime | None = None) -> Iterator[Commit]:
        """Get commits since a given datetime.

        Args:
            since: Optional datetime to filter commits from. If None, returns all commits.

        Yields:
            Commit objects in reverse chronological order
        """
        kwargs: dict[str, object] = {"reverse": False}  # newest first

        if since is not None:
            # Ensure we have timezone-aware datetime
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            kwargs["since"] = since

        for commit in self._repo.iter_commits(**kwargs):
            yield Commit.from_gitpython(commit)
