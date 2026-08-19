# GitRelevance

> Analyze whether historical GitHub issues are still relevant to a codebase, using Git history as evidence.

[![CI](https://github.com/gitrelevance/gitrelevance/actions/workflows/ci.yml/badge.svg)](https://github.com/gitrelevance/gitrelevance/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: >=3.10](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## What is GitRelevance?

In long-lived repositories, issue trackers often accumulate hundreds of historical bug reports and feature requests. Over time, code is refactored, features are deprecated, or fixes are merged without closing the original issue.

**GitRelevance** audits your open and closed GitHub issues against your local Git history. It automatically correlates commit messages, pull request merges, file renames, deletions, and reverts to determine whether an issue is:
- **`RESOLVED`** — A fix commit exists in `HEAD` history and was not reverted.
- **`PROBABLY_RESOLVED`** — A fixing PR was merged or substantial fix evidence was detected.
- **`STILL_RELEVANT`** — The issue is open and related code still actively exists in the tree.
- **`OBSOLETE`** — The files or feature referenced by the issue were deleted without replacement.
- **`UNKNOWN`** — No correlating commits or evidence exist in local Git history.

Every classification is backed by an explicit, human-readable list of evidence items and a confidence score.

---

## Installation

```bash
pip install gitrelevance
```

For development:
```bash
git clone https://github.com/gitrelevance/gitrelevance.git
cd gitrelevance
pip install -e ".[dev]"
```

Requires Python ≥ 3.10.

---

## Quick Start (CLI)

Run `gitrelevance analyze` from inside any local Git clone of a GitHub repository:

```bash
# Analyze all repository issues
gitrelevance analyze

# Filter by state (open, closed, all)
gitrelevance analyze --state open

# Filter by issue creation date
gitrelevance analyze --since 2024-01-01

# Output structured JSON for automation or CI pipelines
gitrelevance analyze --json
```

### Example Terminal Output

```
GitRelevance

Repository: github.com/owner/my-repo
Branch: main
HEAD: a81f23c

Analyzing 24 issues...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESOLVED

#21 Login crashes after token expiration
Confidence: 96%

Evidence:
  ✓ Fix commit is present in HEAD history (a81f23c)
  ✓ Issue referenced in commit message (a81f23c)
  ✓ All related files exist at HEAD
  ✓ No revert of fix commit detected (a81f23c)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

* Confidence is a heuristic evidence-strength score (0–100%), not a statistical probability.
```

---

## How Classification Works

GitRelevance evaluates evidence through a multi-stage deterministic pipeline:

```
┌─────────────────┐     ┌─────────────────────┐
│ Local Git Repo  │     │ GitHub API Provider │
└────────┬────────┘     └──────────┬──────────┘
         │                         │
         ▼                         ▼
  ┌───────────────────────────────────────┐
  │ Matcher (Correlates commits & PRs)    │
  └──────────────────┬────────────────────┘
                     │
                     ▼
  ┌───────────────────────────────────────┐
  │ Current-State Analysis (HEAD status)  │
  └──────────────────┬────────────────────┘
                     │
                     ▼
  ┌───────────────────────────────────────┐
  │ Evidence Collection (Signed weights)  │
  └──────────────────┬────────────────────┘
                     │
                     ▼
  ┌───────────────────────────────────────┐
  │ Confidence & Classifier Decision Tree │
  └──────────────────┬────────────────────┘
                     │
                     ▼
  ┌───────────────────────────────────────┐
  │ Output (Terminal with Rich or JSON)   │
  └───────────────────────────────────────┘
```

### Evidence Rules & Signed Weights
- **Fix commit in HEAD history** (`+3`): A commit referencing `#N` or `GH-N` is an ancestor of `HEAD`.
- **Linked PR merged** (`+2`): A pull request linked to or closing issue `#N` was merged into the repository.
- **Related files exist at HEAD** (`+2`): All files modified by the issue's commits/PRs still exist.
- **No revert detected** (`+1`): The fix commit was not undone by a subsequent `git revert`.
- **Related files deleted without replacement** (`-3`): Referenced files were deleted in git history and not renamed.
- **Fix commit later reverted** (`-3`): Git's native revert trailer (`This reverts commit <sha>.`) indicates the fix was undone.

### Confidence Score (Evidence Strength)

Confidence is computed as an **evidence-strength heuristic** normalized and clamped to `[0.05, 0.98]`.

```text
Confidence = 0.50 + (sum(Weights) / (2 × MAX_ABS_WEIGHT))

> **Important Note:** Confidence is **NOT** a calibrated Bayesian probability. A confidence of 95% indicates an overwhelming accumulation of strong supporting evidence in the Git tree, not that the classification is statistically 95% likely to be correct.

---

## GitHub Authentication & Rate Limits

GitRelevance works unauthenticated for public repositories out of the box.

To analyze private repositories or avoid GitHub's unauthenticated API rate limits (60 requests/hour), supply a personal access token via the `GITHUB_TOKEN` environment variable or a local `.env` file:

```bash
export GITHUB_TOKEN="ghp_yourPersonalAccessTokenHere"
gitrelevance analyze
```

---

## Python API Usage

GitRelevance can also be integrated directly into Python scripts:

```python
from gitrelevance.git.repository import GitRepository
from gitrelevance.providers.github import GitHubProvider
from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.output.terminal import TerminalRenderer
from gitrelevance.output.json import to_json

# 1. Initialize Git repository and GitHub provider
repo = GitRepository(".")
owner, repo_name = GitHubProvider.parse_remote(repo.remote_url("origin"))
provider = GitHubProvider(owner=owner, repo=repo_name)

# 2. Run analysis
engine = AnalysisEngine(repo, provider)
results = engine.analyze(state="open")

# 3. Render results
for result in results:
    print(f"#{result.issue.number} {result.issue.title} -> {result.classification.value} ({result.confidence:.0%})")
```

---

## Running Tests

```bash
# Run complete test suite
pytest -v

# Run individual test layers
pytest tests/git/           # Git abstraction layer
pytest tests/providers/     # Provider layer
pytest tests/analysis/      # Evidence & classification unit tests
pytest tests/output/        # Terminal & JSON rendering tests
pytest tests/cli/           # Typer CLI tests
pytest tests/scenarios/     # End-to-end repository scenarios
```

---

## Adding a Scenario Test

To add a new end-to-end scenario test:
1. Create `tests/scenarios/test_scenario_<name>.py`.
2. Import `FakeProvider`, `make_issue`, `make_pr`, and assertion helpers from `tests.scenarios.conftest`.
3. Use `RepoBuilder` to construct a real temporary Git repository.
4. Execute `AnalysisEngine(repo, provider).analyze()` and assert on the `AnalysisResult` fields.

```python
from gitrelevance.analysis.engine import AnalysisEngine
from gitrelevance.git.repository import GitRepository
from gitrelevance.models import Classification
from tests.fixtures.repo_builder import RepoBuilder
from tests.scenarios.conftest import FakeProvider, make_issue

def test_my_custom_scenario():
    builder = RepoBuilder().commit("Initial", files={"app.py": "code"})
    path = builder.build()
    try:
        repo = GitRepository(path)
        issue = make_issue(number=99, title="Custom issue", state="closed")
        results = AnalysisEngine(repo, FakeProvider(issues=[issue])).analyze()
        assert results[0].classification == Classification.UNKNOWN
    finally:
        builder.cleanup()
```

---

## License

This project is licensed under the [MIT License](LICENSE).
