"""Configuration and environment loading."""

from __future__ import annotations

import os

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    # Try loading .env if python-dotenv is installed
    load_dotenv()
except ImportError:
    pass


def load_github_token() -> str | None:
    """Load GitHub Personal Access Token from environment.

    Reads GITHUB_TOKEN environment variable. Returns None if not set.

    Returns:
        The token string if set in environment, None otherwise.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token or not token.strip():
        return None
    return token.strip()
