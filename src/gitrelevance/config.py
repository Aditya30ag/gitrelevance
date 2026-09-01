"""Configuration and environment loading."""

from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".gitrelevance"
TOKEN_FILE = CONFIG_DIR / "token"

try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    # Try loading .env if python-dotenv is installed
    load_dotenv()
except ImportError:
    pass


def load_github_token() -> str | None:
    """Load GitHub Personal Access Token or API key.

    Checks environment variables (GITHUB_TOKEN, GH_TOKEN, GITHUB_API_KEY)
    and falls back to persistent token file (~/.gitrelevance/token).

    Returns:
        The token string if found, None otherwise.
    """
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_API_KEY"):
        token = os.getenv(var)
        if token and token.strip():
            return token.strip()

    if TOKEN_FILE.is_file():
        try:
            content = TOKEN_FILE.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass

    return None


def save_github_token(token: str) -> Path:
    """Save GitHub Personal Access Token or API key to user config directory.

    Args:
        token: The token/API key string to save.

    Returns:
        Path to the saved token file.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token.strip(), encoding="utf-8")
    return TOKEN_FILE
