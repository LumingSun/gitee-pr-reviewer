# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gitee automated PR review service. A Flask webhook receiver that listens for Gitee PR events, extracts PR metadata, then invokes the **Gitee MCP server** and **code review skill** to perform automated code review and post review reports back to the PR.

### Core Flow

```
Gitee PR event → Webhook (Flask) → Parse PR info → Gitee MCP + Code Review Skill → Post review to PR
```

## Commands

```bash
# Install runtime dependencies
pip install -r requirements.txt

# Install dev dependencies (includes test tools)
pip install -r requirements-dev.txt

# Run the dev server (debug off by default, set FLASK_DEBUG=1 for debug mode)
python app.py

# Run all tests
pytest test_app.py -v

# Run a single test class
pytest test_app.py::TestWebhookToken -v

# Run with Docker Compose
docker-compose up --build
```

## Architecture

```
app.py                  # Flask webhook server — single entry point
test_app.py             # pytest tests (9 tests covering auth, parsing, edge cases)
example.json            # Sample Gitee webhook payload (test fixture)
requirements.txt        # Runtime dependencies (Flask, Werkzeug)
requirements-dev.txt    # Dev dependencies (pytest, pytest-flask)
```

### Endpoints

- **`POST /webhook`** — Receives Gitee PR webhook JSON. Validates the `X-Gitee-Token` header, parses the payload, and when `action == "open"`, extracts PR details and triggers the review pipeline.

### Webhook Authentication

The server verifies the `X-Gitee-Token` header against `GITEE_WEBHOOK_SECRET`. Requests with missing or invalid tokens get `403`. When `GITEE_WEBHOOK_SECRET` is not configured (empty), token verification is skipped — useful for local development.

### Webhook Payload

The Gitee webhook sends a JSON payload containing PR metadata. Key fields used:

| Field | Description |
|-------|-------------|
| `action` | Event type (`open`, `update`, `close`, etc.) |
| `number` | PR number (integer) |
| `title` | PR title |
| `body` | PR description |
| `source_branch` | Source branch name |
| `target_branch` | Target branch name |
| `repository.full_name` | Repo path (e.g. `owner/repo`) |
| `pull_request.html_url` | PR URL |
| `pull_request.diff_url` | PR diff URL |

## Configuration

The server reads these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Flask server port |
| `FLASK_DEBUG` | `0` | Set to `1` to enable debug mode (never in Docker/production) |
| `GITEE_WEBHOOK_SECRET` | (empty) | Secret token matching Gitee webhook password; empty = skip verification |

Copy `.env.example` to `.env` and fill in values.

## Integration Notes

- The review pipeline is triggered asynchronously — the webhook returns `200` immediately and processes the review in the background to avoid Gitee webhook timeouts.
- The Gitee MCP server must be configured and accessible at runtime for PR diff fetching and comment posting.
- When running inside Claude Code, the `gitee-pr-review` skill is available as a built-in skill.
