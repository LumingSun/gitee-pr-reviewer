# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-platform automated PR review service. A Flask webhook receiver that listens for PR events from **Gitee** or **Gitea**, extracts PR metadata, then invokes the platform-specific **MCP server** and **code review skill** to perform automated code review and post review reports back to the PR.

### Core Flow

```
PR event → Webhook (Flask) → Platform Adapter → MCP + Code Review Skill → Post review to PR
```

The platform (Gitee or Gitea) is selected at runtime via the `PLATFORM` environment variable.

## Commands

```bash
# Install runtime dependencies
pip install -r requirements.txt

# Install dev dependencies (includes test tools)
pip install -r requirements-dev.txt

# Run the dev server (debug off by default, set FLASK_DEBUG=1 for debug mode)
PLATFORM=gitee python -m src.app

# Run all tests
pytest tests/ -v

# Run a single test class
pytest tests/test_app.py::TestWebhookToken -v

# Run with Docker Compose
docker-compose up --build
```

## Architecture

```
src/
  app.py                # Flask webhook server — single entry point
  platform_adapter.py   # Platform adapter (GiteeAdapter / GiteaAdapter)
  pr_review_agent.py    # PR review agent with MCP + LLM
resources/
  review_prompt.md      # Review prompt template (Gitee)
  review_prompt_gitea.md# Review prompt template (Gitea)
tests/
  test_app.py           # pytest tests (Gitee + Gitea)
  test_platform_adapter.py  # Adapter unit tests
  fixtures/
    example.json        # Sample Gitee webhook payload
    gitea_example.json  # Sample Gitea webhook payload
requirements.txt        # Runtime dependencies
requirements-dev.txt    # Dev dependencies
```

### Endpoints

- **`POST /webhook`** — Receives PR webhook JSON. Validates the platform-specific auth header, parses the payload, and when action matches PR open/comment, extracts PR details and triggers the review pipeline.

### Platform Adapter

The `PlatformAdapter` ABC (in `src/platform_adapter.py`) abstracts all platform-specific logic:

| Aspect | GiteeAdapter | GiteaAdapter |
|--------|-------------|--------------|
| Auth header | `X-Gitee-Token` (plain comparison) | `X-Gitea-Signature` (HMAC-SHA256) |
| Open action | `action == "open"` | `action == "opened"` |
| Open payload | Fields at top level | Fields nested under `pull_request` |
| Comment action | `action == "comment"` + `noteable_type == "PullRequest"` | `action == "created"` + `issue.pull_request` present |
| MCP tools | `get_pull_detail`, `get_diff_files`, `create_comment` | `get_pull_request_by_index`, `get_pull_request_diff`, `create_issue_comment` |

### Webhook Authentication

- **Gitee**: Verifies `X-Gitee-Token` header against `GITEE_WEBHOOK_SECRET`.
- **Gitea**: Verifies `X-Gitea-Signature` header (HMAC-SHA256 of request body) against `GITEA_WEBHOOK_SECRET`.
- When the webhook secret is not configured (empty), verification is skipped — useful for local development.

## Configuration

The server reads these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PLATFORM` | `gitee` | Platform selection: `gitee` or `gitea` |
| `PORT` | `5000` | Flask server port |
| `FLASK_DEBUG` | `0` | Set to `1` to enable debug mode |
| `GITEE_WEBHOOK_SECRET` | (empty) | Gitee webhook secret (when `PLATFORM=gitee`) |
| `GITEA_WEBHOOK_SECRET` | (empty) | Gitea webhook secret (when `PLATFORM=gitea`) |
| `REVIEW_TRIGGER_MENTION` | `@ReviewAI` | Mention text that triggers review on PR comment |
| `MAX_REVIEW_RETRIES` | `3` | Max retry attempts for failed reviews |

Copy `.env.example` to `.env` and fill in values.

## Integration Notes

- The review pipeline is triggered asynchronously — the webhook returns `200` immediately and processes the review in the background to avoid webhook timeouts.
- The platform-specific MCP server must be configured and accessible at runtime for PR diff fetching and comment posting.
- When running inside Claude Code, the `gitee-pr-review` skill is available as a built-in skill.
