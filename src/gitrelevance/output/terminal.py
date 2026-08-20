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

# Inline label styles for streaming mode (used per-result, not per-group)
_CLASSIFICATION_LABEL_STYLES: dict[Classification, str] = {
    Classification.RESOLVED: "green",
    Classification.PROBABLY_RESOLVED: "cyan",
    Classification.STILL_RELEVANT: "yellow",
    Classification.OBSOLETE: "red",
    Classification.UNKNOWN: "magenta",
}


class TerminalRenderer:
    """Renders issue analysis results to the terminal using Rich."""

    def __init__(self, console: Console | None = None) -> None:
        """Initialize renderer with an optional Rich Console.

        Args:
            console: Rich Console instance, or None to use default.
        """
        self.console = console or Console()

    # ------------------------------------------------------------------
    # Streaming API (called incrementally as results arrive)
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_repo_info(repo_info: Mapping[str, Any] | Any) -> dict[str, str]:
        """Normalise repo_info into a plain dict with known keys."""
        if isinstance(repo_info, Mapping):
            return {
                "owner": repo_info.get("owner", "unknown"),
                "repo": repo_info.get("repo", repo_info.get("name", "unknown")),
                "branch": repo_info.get("branch", "unknown"),
                "short_sha": str(repo_info.get("short_sha", repo_info.get("head_sha", "unknown")))[:7],
            }
        return {
            "owner": getattr(repo_info, "owner", "unknown"),
            "repo": getattr(repo_info, "repo", getattr(repo_info, "name", "unknown")),
            "branch": getattr(repo_info, "branch", "unknown"),
            "short_sha": str(getattr(repo_info, "short_sha", getattr(repo_info, "head_sha", "unknown")))[:7],
        }

    def render_header(self, repo_info: Mapping[str, Any] | Any, total_issues: int) -> None:
        """Print the repository header before streaming begins.

        Args:
            repo_info: Mapping or object containing repo metadata.
            total_issues: Total number of issues to be analysed.
        """
        info = self._extract_repo_info(repo_info)
        self.console.print("[bold]GitRelevance[/bold]\n")
        self.console.print(f"Repository: github.com/{info['owner']}/{info['repo']}")
        self.console.print(f"Branch: {info['branch']}")
        self.console.print(f"HEAD: {info['short_sha']}\n")
        self.console.print(
            f"Analyzing {total_issues} issue{'s' if total_issues != 1 else ''}...\n"
        )

    def render_result(self, result: AnalysisResult) -> None:
        """Render a single AnalysisResult inline (streaming mode).

        Each result is printed with its classification as an inline label
        rather than being grouped by classification.

        Args:
            result: A single AnalysisResult to render.
        """
        style = _CLASSIFICATION_LABEL_STYLES.get(result.classification, "white")
        conf_pct = int(round(result.confidence * 100))

        self.console.print(
            f"[bold]#{result.issue.number} {result.issue.title}[/bold]"
            f"  [{style}]{result.classification.value}[/{style}]"
            f"  [dim]{conf_pct}%[/dim]"
        )

        if result.evidence:
            for ev in result.evidence:
                line = self._format_evidence_item(ev)
                self.console.print(f"  [green]✓[/green] {line}")
        else:
            self.console.print("  [dim]No evidence[/dim]")
        self.console.print("")

    def render_footer(self) -> None:
        """Print the trailing disclaimer after all results have been streamed."""
        separator = "━" * 40
        self.console.print(f"[dim]{separator}[/dim]\n")
        self.console.print(
            "[dim]* Confidence is a heuristic evidence-strength score (0–100%), not a statistical probability.[/dim]"
        )

    # ------------------------------------------------------------------
    # Batch API (backward-compatible, used by tests and --json fallback)
    # ------------------------------------------------------------------

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
        info = self._extract_repo_info(repo_info)

        # Header
        self.console.print("[bold]GitRelevance[/bold]\n")
        self.console.print(f"Repository: github.com/{info['owner']}/{info['repo']}")
        self.console.print(f"Branch: {info['branch']}")
        self.console.print(f"HEAD: {info['short_sha']}\n")
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
