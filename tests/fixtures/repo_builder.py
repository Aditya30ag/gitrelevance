"""Test fixture for building real temporary Git repositories.

Provides a fluent API for constructing repos with specific commit histories,
branches, and real git revert commits for testing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import git


class RepoBuilder:
    """Builds a real temporary Git repository with a fluent API.

    Example usage:
        repo = (
            RepoBuilder()
            .commit("Initial commit", files={"README.md": "hello"})
            .commit("Add feature", files={"feature.py": "code"})
            .branch("feature")
            .commit("Fix bug", files={"fix.py": "fix"})
            .build()
        )
        # repo is a temporary directory path that will be cleaned up
    """

    def __init__(self, initial_branch: str = "main") -> None:
        self._tmp_dir: str | None = None
        self._repo: git.Repo | None = None
        self._initial_branch = initial_branch

    def commit(
        self, message: str, *, files: dict[str, str] | None = None
    ) -> Self:
        """Add a commit with optional file changes.

        Args:
            message: Commit message
            files: Dict mapping file paths to their content.
                   Creates/overwrites files as needed.

        Returns:
            self for chaining
        """
        if self._repo is None:
            self._tmp_dir = tempfile.mkdtemp(prefix="gitrelevance_test_")
            # Use subprocess to run git init with -b flag for proper default branch
            subprocess.run(
                ["git", "init", "-b", self._initial_branch, self._tmp_dir],
                check=True,
                capture_output=True,
                text=True,
            )
            self._repo = git.Repo(self._tmp_dir)
            # Configure git user for commits
            with self._repo.config_writer() as config:
                config.set_value("user", "name", "Test User")
                config.set_value("user", "email", "test@example.com")

        if files:
            for path, content in files.items():
                full_path = os.path.join(self._tmp_dir, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    f.write(content)
            self._repo.index.add(list(files.keys()))

        self._repo.index.commit(message)
        return self

    def branch(self, name: str) -> Self:
        """Create and checkout a new branch from the current HEAD.

        Args:
            name: Branch name

        Returns:
            self for chaining
        """
        assert self._repo is not None, "Must commit at least once before branching"
        self._repo.git.checkout("-b", name)
        return self

    def checkout(self, branch_or_sha: str) -> Self:
        """Checkout an existing branch or commit.

        Args:
            branch_or_sha: Branch name or commit SHA

        Returns:
            self for chaining
        """
        assert self._repo is not None
        self._repo.git.checkout(branch_or_sha)
        return self

    def revert(self, commit_sha: str, *, no_edit: bool = True) -> Self:
        """Perform a real git revert of the specified commit.

        Uses subprocess so Git itself writes the canonical
        "This reverts commit <sha>." trailer into the commit message —
        the same text that GitNativeRevertDetector searches for.

        Args:
            commit_sha: SHA of the commit to revert
            no_edit: If True, use --no-edit to skip editor prompt

        Returns:
            self for chaining
        """
        assert self._repo is not None
        cmd = ["git", "revert"]
        if no_edit:
            cmd.append("--no-edit")
        cmd.append(commit_sha)
        subprocess.run(
            cmd,
            cwd=self._tmp_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        # Reload the GitPython repo so it sees the new commit
        self._repo = git.Repo(self._tmp_dir)
        return self

    def add_remote(self, name: str, url: str) -> Self:
        """Add a remote to the repository.

        Args:
            name: Remote name (e.g. 'origin')
            url: Remote URL

        Returns:
            self for chaining
        """
        assert self._repo is not None
        self._repo.create_remote(name, url)
        return self

    def build(self) -> str:
        """Finalize and return the path to the temporary repository.

        Returns:
            Path to the temporary git repository directory
        """
        assert self._repo is not None, "Must commit at least once before building"
        return self._tmp_dir

    def build_repo(self) -> git.Repo:
        """Finalize and return the GitPython Repo object.

        Returns:
            The GitPython Repo instance
        """
        assert self._repo is not None, "Must commit at least once before building"
        return self._repo

    def cleanup(self) -> None:
        """Remove the temporary directory and all its contents.

        On Windows, GitPython may hold file handles that prevent immediate
        deletion, so we silently ignore errors.
        """
        if self._tmp_dir and os.path.exists(self._tmp_dir):
            # Close the GitPython repo to release file handles
            if self._repo is not None:
                del self._repo
                self._repo = None
            try:
                shutil.rmtree(self._tmp_dir)
            except OSError:
                pass  # Best effort on Windows
            self._tmp_dir = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: object) -> None:
        self.cleanup()
