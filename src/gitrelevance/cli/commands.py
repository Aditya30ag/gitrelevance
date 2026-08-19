"""CLI commands implementation for GitRelevance using Typer."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

import typer
from rich.console import Console

from gitrelevance import config
from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository, NotAGitRepositoryError
from gitrelevance.output.json import to_json
from gitrelevance.output.terminal import TerminalRenderer
from gitrelevance.providers.base import Provider
from gitrelevance.providers.github import GitHubProvider

app = typer.Typer(
    name="gitrelevance",
    help="Analyze whether historical GitHub issues are still relevant using Git history as evidence.",
    no_args_is_help=True,
)


@app.callback()
def callback() -> None:
    """GitRelevance: Analyze historical GitHub issues using Git history."""
    pass


# Optional seam for dependency injection in tests
_provider_override: Provider | None = None
_provider_factory: Callable[[str, str, str | None], Provider] | None = None


def set_provider_override(provider: Provider | None) -> None:
    """Set a global provider override for testing."""
    global _provider_override
    _provider_override = provider


def set_provider_factory(factory: Callable[[str, str, str | None], Provider] | None) -> None:
    """Set a global provider factory for testing."""
    global _provider_factory
    _provider_factory = factory


@app.command()
def analyze(
    state: str = typer.Option(
        "all",
        "--state",
        "-s",
        help="Filter issue state: open, closed, or all.",
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Filter issues created on or after date (YYYY-MM-DD).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON instead of formatted terminal tables.",
    ),
    path: str = typer.Option(
        ".",
        "--path",
        "-p",
        help="Path to local Git repository (defaults to current directory).",
        hidden=True,
    ),
) -> None:
    """Analyze repository issues against local Git history."""
    console = Console(stderr=True if json_output else False)

    # 1. Detect local Git repository
    try:
        repo = GitRepository(path)
    except NotAGitRepositoryError:
        console.print(
            f"[bold red]Error:[/bold red] Directory '{path}' is not a Git repository. "
            "Please run gitrelevance from within a git repository or pass a valid repository path."
        )
        raise typer.Exit(code=1)

    # 2. Detect remote URL and parse owner/repo
    remote_url = repo.remote_url("origin")
    if not remote_url:
        console.print(
            "[bold red]Error:[/bold red] No 'origin' remote found in the repository. "
            "GitRelevance requires a GitHub remote to correlate issues."
        )
        raise typer.Exit(code=1)

    # Parse GitHub owner/repo
    parsed = GitHubProvider.parse_remote(remote_url)
    if not parsed:
        console.print(
            f"[bold red]Error:[/bold red] Remote URL '{remote_url}' is not a recognized GitHub URL. "
            "Currently only GitHub-hosted repositories are supported."
        )
        raise typer.Exit(code=1)

    owner, repo_name = parsed

    # 3. Construct provider
    token = config.load_github_token()
    if _provider_override is not None:
        provider = _provider_override
    elif _provider_factory is not None:
        provider = _provider_factory(owner, repo_name, token)
    else:
        provider = GitHubProvider(owner=owner, repo=repo_name, token=token)

    # Validate state option
    state_normalized = state.lower()
    if state_normalized not in ("open", "closed", "all"):
        console.print(
            f"[bold red]Error:[/bold red] Invalid state '{state}'. Must be 'open', 'closed', or 'all'."
        )
        raise typer.Exit(code=1)

    # 4. Parse --since filter if supplied
    since_dt: datetime | None = None
    if since:
        try:
            # Parse YYYY-MM-DD
            parsed_date = datetime.strptime(since.strip(), "%Y-%m-%d")
            since_dt = parsed_date.replace(tzinfo=timezone.utc)
        except ValueError:
            console.print(
                f"[bold red]Error:[/bold red] Invalid date format for --since: '{since}'. "
                "Expected format: YYYY-MM-DD (e.g. 2024-01-01)."
            )
            raise typer.Exit(code=1)

    # 5. Run AnalysisEngine
    engine = AnalysisEngine(repo, provider)
    try:
        results = engine.analyze(state=state_normalized)  # type: ignore[arg-type]
    except Exception as e:
        console.print(f"[bold red]Analysis failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    # 6. Apply client-side --since filter
    # Note: Filtering client-side is performed here; future optimization may
    # push this down to provider.get_issues(since=...) for API efficiency.
    if since_dt is not None:
        results = [r for r in results if r.issue.created_at >= since_dt]

    # Gather repository summary information
    try:
        branch = repo.current_branch()
    except Exception:
        branch = "detached"

    try:
        head_commit = repo.head_commit()
        short_sha = head_commit.short_sha
    except Exception:
        short_sha = "unknown"

    repo_info = {
        "branch": branch,
        "owner": owner,
        "remote_url": remote_url,
        "repo": repo_name,
        "short_sha": short_sha,
    }

    # 7. Render output
    if json_output:
        json_str = to_json(results, repo_info)
        typer.echo(json_str)
    else:
        out_console = Console()
        renderer = TerminalRenderer(out_console)
        renderer.render(results, repo_info)


def main() -> None:
    """CLI entry point function."""
    app()


if __name__ == "__main__":
    main()
