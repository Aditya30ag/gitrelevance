"""Output rendering modules for terminal and JSON output."""

from __future__ import annotations

from gitrelevance.output.json import to_json
from gitrelevance.output.terminal import TerminalRenderer

__all__ = ["TerminalRenderer", "to_json"]
