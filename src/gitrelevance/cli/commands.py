"""CLI commands implementation for GitRelevance using Typer."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Literal, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from gitrelevance import config
from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository, NotAGitRepositoryError
from gitrelevance.output.json import to_json
from gitrelevance.output.terminal import TerminalRenderer
from gitrelevance.providers.base import Provider, RateLimitExceededError
from gitrelevance.providers.github import GitHubProvider

app = typer.Typer(
    name="gitrelevance",
    help="Analyze whether historical GitHub issues are still relevant using Git history as evidence.",
    no_args_is_help=True,
)


@app.callback()
def callback(
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose debug logging.",
    ),
) -> None:
    """GitRelevance: Analyze historical GitHub issues using Git history."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


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
    token: Optional[str] = typer.Option(
        None,
        "--token",
        "-t",
        "--api-key",
        help="GitHub Personal Access Token or API key for authenticated requests.",
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
    err_console = Console(stderr=True)

    # 1. Detect local Git repository
    try:
        repo = GitRepository(path)
    except NotAGitRepositoryError:
        err_console.print(
            f"[bold red]Error:[/bold red] Directory '{path}' is not a Git repository. "
            "Please run gitrelevance from within a git repository or pass a valid repository path."
        )
        raise typer.Exit(code=1)

    # 2. Detect remote URL and parse owner/repo
    remote_url = repo.remote_url("origin")
    if not remote_url:
        err_console.print(
            "[bold red]Error:[/bold red] No 'origin' remote found in the repository. "
            "GitRelevance requires a GitHub remote to correlate issues."
        )
        raise typer.Exit(code=1)

    # Parse GitHub owner/repo
    parsed = GitHubProvider.parse_remote(remote_url)
    if not parsed:
        err_console.print(
            f"[bold red]Error:[/bold red] Remote URL '{remote_url}' is not a recognized GitHub URL. "
            "Currently only GitHub-hosted repositories are supported."
        )
        raise typer.Exit(code=1)

    owner, repo_name = parsed

    # 3. Construct provider
    resolved_token = token or config.load_github_token()
    if _provider_override is not None:
        provider = _provider_override
    elif _provider_factory is not None:
        provider = _provider_factory(owner, repo_name, resolved_token)
    else:
        if not resolved_token and not json_output:
            err_console.print(
                "[yellow]Note:[/yellow] Running in unauthenticated mode (GITHUB_TOKEN / --token not set). "
                "GitHub API rate limit is 60 requests/hour."
            )
        provider = GitHubProvider(owner=owner, repo=repo_name, token=resolved_token)

    # Validate state option
    state_normalized = state.lower()
    if state_normalized not in ("open", "closed", "all"):
        err_console.print(
            f"[bold red]Error:[/bold red] Invalid state '{state}'. Must be 'open', 'closed', or 'all'."
        )
        raise typer.Exit(code=1)

    # 4. Parse --since filter if supplied
    since_dt: datetime | None = None
    if since:
        try:
            parsed_date = datetime.strptime(since.strip(), "%Y-%m-%d")
            since_dt = parsed_date.replace(tzinfo=timezone.utc)
        except ValueError:
            err_console.print(
                f"[bold red]Error:[/bold red] Invalid date format for --since: '{since}'. "
                "Expected format: YYYY-MM-DD (e.g. 2024-01-01)."
            )
            raise typer.Exit(code=1)

    # 5. Run AnalysisEngine
    engine = AnalysisEngine(repo, provider)

    # Gather repository summary information (needed for both output modes)
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

    t_start = time.perf_counter()

    try:
        if json_output:
            # ---- JSON mode: collect all results, serialize at the end ----
            results = list(engine.analyze_streaming(state=state_normalized))  # type: ignore[arg-type]

            # Apply client-side --since filter
            if since_dt is not None:
                results = [r for r in results if r.issue.created_at >= since_dt]

            results.sort(key=lambda r: r.issue.number)

            json_str = to_json(results, repo_info)
            typer.echo(json_str)

        else:
            # ---- Terminal mode: stream results with live progress ----
            out_console = Console()
            renderer = TerminalRenderer(out_console)

            # Pre-fetch issue count for progress bar (cached after first call)
            all_issues = provider.get_issues(state=state_normalized)  # type: ignore[arg-type]
            if since_dt is not None:
                visible_issues = [i for i in all_issues if i.created_at >= since_dt]
            else:
                visible_issues = all_issues
            total = len(visible_issues)

            renderer.render_header(repo_info, total)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=err_console,
                transient=True,
            ) as progress:
                task = progress.add_task("Analyzing issues...", total=total)

                for result in engine.analyze_streaming(state=state_normalized):  # type: ignore[arg-type]
                    # Apply client-side --since filter
                    if since_dt is not None and result.issue.created_at < since_dt:
                        progress.advance(task)
                        continue

                    progress.advance(task)
                    renderer.render_result(result)

            renderer.render_footer()

            elapsed = time.perf_counter() - t_start
            err_console.print(
                f"[dim]Analysis completed in {elapsed:.1f}s ({len(visible_issues)} issues shown).[/dim]"
            )

    except RateLimitExceededError as e:
        reset_info = f" Reset time: {e.reset_at}" if getattr(e, "reset_at", None) else ""
        err_console.print(
            f"\n[bold red]GitHub API Rate Limit Exceeded:[/bold red]{reset_info}\n"
            "To resolve this, set your GitHub personal access token:\n"
            "  [bold]export GITHUB_TOKEN='ghp_yourTokenHere'[/bold]\n"
            "Authenticated requests receive 5,000 requests/hour."
        )
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Analysis interrupted by user.[/yellow]")
        raise typer.Exit(code=130)
    except Exception as e:
        err_console.print(f"[bold red]Analysis failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command(name="auth")
def auth(
    token: Optional[str] = typer.Option(
        None,
        "--token",
        "-t",
        "--api-key",
        help="GitHub Personal Access Token or API key to store.",
    ),
) -> None:
    """Configure and store GitHub Personal Access Token / API key."""
    console = Console()
    if not token:
        token = typer.prompt("Enter your GitHub Personal Access Token", hide_input=True)

    if token and token.strip():
        saved_path = config.save_github_token(token.strip())
        console.print(f"[green]✓ Token saved successfully to {saved_path}[/green]")
    else:
        console.print("[red]Error: Token cannot be empty.[/red]")
        raise typer.Exit(code=1)


def main() -> None:
    """CLI entry point function."""
    app()


if __name__ == "__main__":
    main()
