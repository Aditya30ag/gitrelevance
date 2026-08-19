"""Terminal renderer using Rich for formatted CLI output."""

from __future__ import annotations

from typing import Any, Mapping
from rich.console import Console
from rich.text import Text

from gitrelevance.models import AnalysisResult, Classification, EvidenceItem

# Display ordering for classifications
CLASSIFICATION_ORDER: list[Classification] = [
    Classification.RESOLVED,
    Classification.PROBABLY_RESOLVED,
    Classification.STILL_RELEVANT,
    Classification.OBSOLETE,
    Classification.UNKNOWN,
]

# Color styles for each classification header
CLASSIFICATION_STYLES: dict[Classification, str] = {
    Classification.RESOLVED: "bold green",
    Classification.PROBABLY_RESOLVED: "bold cyan",
    Classification.STILL_RELEVANT: "bold yellow",
    Classification.OBSOLETE: "bold red",
    Classification.UNKNOWN: "bold magenta",
}


class TerminalRenderer:
    """Renders issue analysis results to the terminal using Rich."""

    def __init__(self, console: Console | None = None) -> None:
        """Initialize renderer with an optional Rich Console.

        Args:
            console: Rich Console instance, or None to use default.
        """
        self.console = console or Console()

    def render(
        self,
        results: list[AnalysisResult],
        repo_info: Mapping[str, Any] | Any,
    ) -> None:
        """Render the complete analysis report to the console.

        Args:
            results: List of AnalysisResult objects.
            repo_info: Mapping or object containing repo metadata:
                       owner, repo (or name), branch, short_sha (or head_sha).
        """
        # Extract repo metadata
        if isinstance(repo_info, Mapping):
            owner = repo_info.get("owner", "unknown")
            repo_name = repo_info.get("repo", repo_info.get("name", "unknown"))
            branch = repo_info.get("branch", "unknown")
            short_sha = repo_info.get("short_sha", repo_info.get("head_sha", "unknown"))[:7]
        else:
            owner = getattr(repo_info, "owner", "unknown")
            repo_name = getattr(repo_info, "repo", getattr(repo_info, "name", "unknown"))
            branch = getattr(repo_info, "branch", "unknown")
            head_sha = getattr(repo_info, "short_sha", getattr(repo_info, "head_sha", "unknown"))
            short_sha = str(head_sha)[:7]

        # Header
        self.console.print("[bold]GitRelevance[/bold]\n")
        self.console.print(f"Repository: github.com/{owner}/{repo_name}")
        self.console.print(f"Branch: {branch}")
        self.console.print(f"HEAD: {short_sha}\n")
        self.console.print(f"Analyzing {len(results)} issue{'s' if len(results) != 1 else ''}...\n")

        # Group results by classification
        grouped: dict[Classification, list[AnalysisResult]] = {c: [] for c in CLASSIFICATION_ORDER}
        for res in results:
            if res.classification in grouped:
                grouped[res.classification].append(res)
            else:
                grouped.setdefault(res.classification, []).append(res)

        # Print each group that has results
        separator = "━" * 40
        for classification in CLASSIFICATION_ORDER:
            items = grouped.get(classification, [])
            if not items:
                continue

            self.console.print(f"[dim]{separator}[/dim]\n")
            style = CLASSIFICATION_STYLES.get(classification, "bold white")
            self.console.print(f"[{style}]{classification.value}[/{style}]\n")

            for res in items:
                # Issue title & number
                self.console.print(f"[bold]#{res.issue.number} {res.issue.title}[/bold]")
                # Confidence percentage
                conf_pct = int(round(res.confidence * 100))
                self.console.print(f"Confidence: {conf_pct}%\n")

                # Evidence items
                if res.evidence:
                    self.console.print("Evidence:")
                    for ev in res.evidence:
                        line = self._format_evidence_item(ev)
                        self.console.print(f"  [green]✓[/green] {line}")
                else:
                    self.console.print("Evidence: None")
                self.console.print("")

        self.console.print(f"[dim]{separator}[/dim]\n")
        self.console.print(
            "[dim]* Confidence is a heuristic evidence-strength score (0–100%), not a statistical probability.[/dim]"
        )

    def _format_evidence_item(self, item: EvidenceItem) -> str:
        """Format an individual evidence item for terminal display.

        Args:
            item: EvidenceItem to format.

        Returns:
            Human-readable string representation with source_ref if applicable.
        """
        desc = item.description
        if item.source_ref:
            # If source_ref is already mentioned in description, don't repeat
            if item.source_ref not in desc:
                return f"{desc} ({item.source_ref})"
        return desc
