"""GitHub provider implementation using PyGithub."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Literal

from diskcache import Cache
from github import Auth, Github, GithubException, RateLimitExceededException

from gitrelevance.config import load_github_token
from gitrelevance.issues.models import Issue, PullRequest
from gitrelevance.providers.base import Provider, RateLimitExceededError

logger = logging.getLogger(__name__)

# Regex pattern to extract closing issue numbers from PR body/title
CLOSING_KEYWORD_PATTERN = re.compile(
    r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+(?:#|gh-)(\d+)",
    re.IGNORECASE,
)


class GitHubProvider:
    """GitHub provider implementing the Provider protocol.

    Provides access to GitHub issues, pull requests, and comments with disk caching
    and rate limit error handling.
    """

    def __init__(
        self,
        owner: str,
        repo: str,
        token: str | None = None,
        cache_dir: str | None = None,
        ttl: int = 900,
        timeout: int = 15,
    ) -> None:
        """Initialize the GitHub provider.

        Args:
            owner: Repository owner or organization name
            repo: Repository name
            token: Optional GitHub Personal Access Token. If None, loaded from GITHUB_TOKEN env var.
            cache_dir: Directory for diskcache storage. If None, uses a temporary directory.
            ttl: Cache TTL in seconds (default: 900 / 15 minutes).
            timeout: HTTP request timeout in seconds (default: 15).
        """
        self.owner = owner
        self.repo_name = repo
        self._token = token or load_github_token()
        self.ttl = ttl
        self.timeout = timeout

        if cache_dir is None:
            cache_dir = os.path.join(tempfile.gettempdir(), "gitrelevance_cache")
        self._cache = Cache(cache_dir)

        # Explicit timeout and retry=0 to prevent indefinite socket hangs and silent backoff sleeping on 403
        if self._token:
            auth = Auth.Token(self._token)
            self._client = Github(
                auth=auth,
                timeout=self.timeout,
                retry=0,
                per_page=100,
            )
        else:
            self._client = Github(
                timeout=self.timeout,
                retry=0,
                per_page=100,
            )

    @staticmethod
    def parse_remote(remote_url: str) -> tuple[str, str] | None:
        """Parse a remote URL into (owner, repo) pair for GitHub repositories.

        Supported URL formats:
        - git@github.com:owner/repo.git
        - https://github.com/owner/repo.git
        - https://github.com/owner/repo
        - github.com/owner/repo

        Args:
            remote_url: Remote URL string

        Returns:
            Tuple of (owner, repo) if valid GitHub URL, None otherwise.
        """
        if not remote_url:
            return None

        url = remote_url.strip()

        patterns = [
            r"^git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$",
            r"^https?://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$",
            r"^github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$",
        ]

        for pattern in patterns:
            match = re.match(pattern, url)
            if match:
                owner, repo = match.group(1), match.group(2)
                return owner, repo

        return None

    def _get_github_repo(self) -> object:
        """Get PyGithub Repository instance."""
        return self._client.get_repo(f"{self.owner}/{self.repo_name}")

    def get_issues(
        self,
        state: Literal["open", "closed", "all"] = "all",
        force_refresh: bool = False,
    ) -> list[Issue]:
        """Fetch repository issues.

        Args:
            state: Issue state filter ("open", "closed", or "all")
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of Issue dataclasses.

        Raises:
            RateLimitExceededError: If GitHub API rate limit is exceeded.
        """
        cache_key = (self.owner, self.repo_name, "issues", state)
        if not force_refresh and self.ttl > 0:
            cached_data = self._cache.get(cache_key)
            if cached_data is not None:
                logger.info("Loaded %d issues from disk cache for %s/%s", len(cached_data), self.owner, self.repo_name)
                return cached_data

        logger.info("Fetching issues from GitHub API for %s/%s (state=%s)...", self.owner, self.repo_name, state)
        try:
            gh_repo = self._get_github_repo()
            gh_issues = gh_repo.get_issues(state=state)

            issues: list[Issue] = []
            for gh_issue in gh_issues:
                # Filter out PRs (PyGithub get_issues returns issues + PRs unless filtered)
                is_pr = False
                raw_data = getattr(gh_issue, "_rawData", None)
                if isinstance(raw_data, dict):
                    is_pr = bool(raw_data.get("pull_request"))
                else:
                    try:
                        is_pr = getattr(gh_issue, "pull_request", None) is not None
                    except (RateLimitExceededException, KeyboardInterrupt):
                        raise
                    except Exception:
                        is_pr = False

                if is_pr:
                    continue

                linked_prs: list[int] = []
                # Check timeline events if available
                if hasattr(gh_issue, "get_timeline"):
                    try:
                        timeline = gh_issue.get_timeline()
                        for event in timeline:
                            event_name = getattr(event, "event", None)
                            if event_name in ("cross-referenced", "connected", "referenced"):
                                source = getattr(event, "source", None)
                                if source and isinstance(source, dict):
                                    issue_info = source.get("issue")
                                    if issue_info and isinstance(issue_info, dict):
                                        if "pull_request" in issue_info or issue_info.get("pull_request") is not None:
                                            pr_num = issue_info.get("number")
                                            if pr_num is not None and int(pr_num) not in linked_prs:
                                                linked_prs.append(int(pr_num))
                                elif source:
                                    issue_info = getattr(source, "issue", None)
                                    if issue_info:
                                        if getattr(issue_info, "pull_request", None) is not None:
                                            pr_num = getattr(issue_info, "number", None)
                                            if pr_num is not None and int(pr_num) not in linked_prs:
                                                linked_prs.append(int(pr_num))
                    except (RateLimitExceededException, KeyboardInterrupt):
                        raise
                    except Exception as e:
                        logger.debug("Could not fetch timeline for issue #%s: %s", gh_issue.number, e)

                issue = Issue(
                    number=gh_issue.number,
                    title=gh_issue.title,
                    body=gh_issue.body or "",
                    state="closed" if gh_issue.state == "closed" else "open",
                    created_at=gh_issue.created_at,
                    closed_at=gh_issue.closed_at,
                    labels=tuple(label.name for label in gh_issue.labels),
                    linked_pr_numbers=tuple(linked_prs),
                )
                issues.append(issue)

            logger.info("Successfully fetched %d issues for %s/%s", len(issues), self.owner, self.repo_name)
            if self.ttl > 0:
                self._cache.set(cache_key, issues, expire=self.ttl)
            return issues

        except RateLimitExceededException as e:
            reset = getattr(e, "reset", None)
            logger.warning("GitHub API rate limit exceeded for %s/%s", self.owner, self.repo_name)
            raise RateLimitExceededError(reset_at=reset) from e
        except GithubException as e:
            if e.status in (403, 429) and "rate limit" in str(e).lower():
                reset = getattr(e, "reset", None)
                logger.warning("GitHub API rate limit exceeded (HTTP %d) for %s/%s", e.status, self.owner, self.repo_name)
                raise RateLimitExceededError(reset_at=reset) from e
            raise

    def get_pull_requests(
        self,
        state: Literal["open", "closed", "all"] = "all",
        force_refresh: bool = False,
    ) -> list[PullRequest]:
        """Fetch repository pull requests.

        Args:
            state: Pull request state filter ("open", "closed", or "all")
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of PullRequest dataclasses.

        Raises:
            RateLimitExceededError: If GitHub API rate limit is exceeded.
        """
        cache_key = (self.owner, self.repo_name, "pull_requests", state)
        if not force_refresh and self.ttl > 0:
            cached_data = self._cache.get(cache_key)
            if cached_data is not None:
                logger.info("Loaded %d pull requests from disk cache for %s/%s", len(cached_data), self.owner, self.repo_name)
                return cached_data

        logger.info("Fetching pull requests from GitHub API for %s/%s (state=%s)...", self.owner, self.repo_name, state)
        t0 = time.perf_counter()
        try:
            gh_repo = self._get_github_repo()

            # Materialize the paginated PR list up-front so we can time it separately
            # from the per-PR metadata extraction.  get_pulls() returns a lazy
            # PaginatedList; each iteration may trigger a page-fetch API call.
            logger.info("  Phase 0: fetching paginated PR list...")
            t_p0 = time.perf_counter()
            gh_prs_list: list[object] = list(gh_repo.get_pulls(state=state))
            t_p1 = time.perf_counter()
            logger.info("  Phase 0: got %d PR objects from API in %.2fs.", len(gh_prs_list), t_p1 - t_p0)

            # ------------------------------------------------------------------
            # Phase 1: Iterate PRs, parse metadata, decide which need file fetch
            # ------------------------------------------------------------------
            # IMPORTANT: Use _rawData dict to read PR properties instead of
            # PyGithub object attributes.  PyGithub's lazy-loading triggers a
            # separate API call for each attribute access (e.g. gh_pr.body)
            # when the PaginatedList did not include it, causing ~1s per PR.
            # Reading from _rawData avoids these per-PR API calls entirely.
            pr_metadata: list[tuple[object, list[int], bool]] = []  # (gh_pr, closes_issues, should_fetch_files)
            for gh_pr in gh_prs_list:
                closes_issues: list[int] = []

                # Read from _rawData to avoid per-PR lazy-load API calls.
                # NOTE: The list endpoint does NOT include a "merged" boolean;
                # it includes "merged_at" (timestamp or null).  We compute
                # "merged" from that.
                raw = getattr(gh_pr, "_rawData", None) or {}
                pr_title = raw.get("title", "") or ""
                pr_body = raw.get("body", "") or ""
                text_to_search = f"{pr_title} {pr_body}"
                for match in CLOSING_KEYWORD_PATTERN.findall(text_to_search):
                    try:
                        num = int(match)
                        if num not in closes_issues:
                            closes_issues.append(num)
                    except ValueError:
                        pass

                is_merged = raw.get("merged_at") is not None
                # Optimization: Skip get_files() for closed unmerged PRs that don't close any issues
                # (avoids thousands of unnecessary API calls for spam/rejected PRs on public repos)
                should_fetch_files = (
                    is_merged
                    or raw.get("state", "open") == "open"
                    or len(closes_issues) > 0
                )
                pr_metadata.append((gh_pr, closes_issues, should_fetch_files))

            t_metadata = time.perf_counter()
            logger.info(
                "Enumerated %d PRs in %.2fs (metadata phase).  %d need file changes fetched.",
                len(pr_metadata),
                t_metadata - t_p1,
                sum(1 for _, _, sf in pr_metadata if sf),
            )

            # ------------------------------------------------------------------
            # Phase 2: Parallel fetch of changed-file lists
            # ------------------------------------------------------------------
            def _fetch_pr_files(pr_obj: object) -> tuple[str, ...]:
                """Fetch the file list for a single PR (I/O-bound, GIL-releasing)."""
                try:
                    return tuple(f.filename for f in pr_obj.get_files())
                except (RateLimitExceededException, KeyboardInterrupt):
                    raise
                except Exception as exc:
                    logger.debug("Could not fetch changed files for PR #%s: %s", pr_obj.number, exc)
                    return ()

            # Build file results map: PR number -> files_changed
            files_map: dict[int, tuple[str, ...]] = {}
            fetchable = [(gh_pr, idx) for idx, (gh_pr, _, sf) in enumerate(pr_metadata) if sf]

            if fetchable:
                max_workers = min(len(fetchable), 8)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_pr_num = {
                        executor.submit(_fetch_pr_files, gh_pr): gh_pr.number
                        for gh_pr, _ in fetchable
                    }
                    for future in as_completed(future_to_pr_num):
                        pr_num = future_to_pr_num[future]
                        files_map[pr_num] = future.result()

            t_files = time.perf_counter()
            logger.info(
                "Fetched file lists for %d PRs in %.2fs (parallel, max_workers=%d).",
                len(files_map),
                t_files - t_metadata,
                min(len(fetchable), 8) if fetchable else 0,
            )

            # ------------------------------------------------------------------
            # Phase 3: Assemble PullRequest dataclass objects
            # ------------------------------------------------------------------
            prs: list[PullRequest] = []
            for gh_pr, closes_issues, should_fetch in pr_metadata:
                files_changed = files_map.get(gh_pr.number, ()) if should_fetch else ()
                raw = getattr(gh_pr, "_rawData", None) or {}
                pr = PullRequest(
                    number=raw.get("number", gh_pr.number),
                    title=raw.get("title", ""),
                    merged=raw.get("merged_at") is not None,
                    merge_commit_sha=raw.get("merge_commit_sha"),
                    closes_issue_numbers=tuple(closes_issues),
                    files_changed=files_changed,
                )
                prs.append(pr)

            logger.info(
                "Successfully fetched %d pull requests for %s/%s in %.2fs total.",
                len(prs), self.owner, self.repo_name, time.perf_counter() - t0,
            )
            if self.ttl > 0:
                self._cache.set(cache_key, prs, expire=self.ttl)
            return prs

        except RateLimitExceededException as e:
            reset = getattr(e, "reset", None)
            logger.warning("GitHub API rate limit exceeded when fetching PRs for %s/%s", self.owner, self.repo_name)
            raise RateLimitExceededError(reset_at=reset) from e
        except GithubException as e:
            if e.status in (403, 429) and "rate limit" in str(e).lower():
                reset = getattr(e, "reset", None)
                logger.warning("GitHub API rate limit exceeded (HTTP %d) when fetching PRs for %s/%s", e.status, self.owner, self.repo_name)
                raise RateLimitExceededError(reset_at=reset) from e
            raise

    def get_issue_comments(
        self,
        issue_number: int,
        force_refresh: bool = False,
    ) -> list[str]:
        """Fetch comment bodies for a given issue.

        Args:
            issue_number: Issue number
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of comment body strings.

        Raises:
            RateLimitExceededError: If GitHub API rate limit is exceeded.
        """
        cache_key = (self.owner, self.repo_name, "comments", issue_number)
        if not force_refresh and self.ttl > 0:
            cached_data = self._cache.get(cache_key)
            if cached_data is not None:
                return cached_data

        try:
            gh_repo = self._get_github_repo()
            gh_issue = gh_repo.get_issue(issue_number)
            comments = [comment.body for comment in gh_issue.get_comments() if comment.body]

            if self.ttl > 0:
                self._cache.set(cache_key, comments, expire=self.ttl)
            return comments

        except RateLimitExceededException as e:
            reset = getattr(e, "reset", None)
            raise RateLimitExceededError(reset_at=reset) from e
        except GithubException as e:
            if e.status in (403, 429) and "rate limit" in str(e).lower():
                reset = getattr(e, "reset", None)
                raise RateLimitExceededError(reset_at=reset) from e
            raise
