"""Commit dataclass representing a Git commit."""

from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Commit:
    """Represents a Git commit with its metadata.

    Attributes:
        sha: Full commit SHA hash
        short_sha: Abbreviated SHA (first 7 characters)
        message: Full commit message
        author: Author name
        date: Commit date as timezone-aware datetime
        files_changed: Tuple of file paths changed in this commit
    """

    sha: str
    short_sha: str
    message: str
    author: str
    date: datetime
    files_changed: tuple[str, ...]

    @classmethod
    def from_gitpython(cls, git_commit: object) -> "Commit":
        """Create a Commit from a GitPython Commit object.

        Args:
            git_commit: A GitPython commit object

        Returns:
            Commit instance with converted data
        """
        # Ensure timezone-aware datetime
        commit_date = git_commit.committed_date
        if isinstance(commit_date, (int, float)):
            dt = datetime.fromtimestamp(commit_date, tz=timezone.utc)
        elif hasattr(commit_date, "tzinfo"):
            if commit_date.tzinfo is None:
                dt = commit_date.replace(tzinfo=timezone.utc)
            else:
                dt = commit_date
        else:
            dt = datetime.now(tz=timezone.utc)

        # Get files changed via commit stats (works for all commits without extra diff walk)
        try:
            files_changed: tuple[str, ...] = tuple(git_commit.stats.files.keys())
        except Exception:
            files_changed = ()

        return cls(
            sha=git_commit.hexsha,
            short_sha=git_commit.hexsha[:7],
            message=git_commit.message.rstrip("\n"),
            author=str(git_commit.author),
            date=dt,
            files_changed=files_changed,
        )
