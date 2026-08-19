"""Git analysis modules for GitRelevance."""

from gitrelevance.git.commits import Commit
from gitrelevance.git.files import FileChange
from gitrelevance.git.repository import GitRepository
from gitrelevance.git.history import (
    build_commit_reference_index,
    commits_referencing,
    RevertDetector,
    GitNativeRevertDetector,
    default_revert_detector,
)

__all__ = [
    "Commit",
    "FileChange",
    "GitRepository",
    "build_commit_reference_index",
    "commits_referencing",
    "RevertDetector",
    "GitNativeRevertDetector",
    "default_revert_detector",
]
