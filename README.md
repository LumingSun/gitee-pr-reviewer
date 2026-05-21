# Gitee PR Reviewer

Automated pull request review service for Gitee. Receives PR webhook events from Gitee, then invokes the Gitee MCP server and code review AI to analyze code changes and post review reports back to the PR.

## How It Works

```
┌─────────┐    webhook      ┌──────────────┐               ┌──────────────┐
│  Gitee  │ ──────────────→ │ Flask Server │               │ Gitee MCP    │
│  (PR)   │                 │ (this repo)  │               │ Server       │
└─────────┘                 └──────────────┘               └──────────────┘
                                   │                              │
                                   │ trigger                      │ fetch diff
                                   ▼                              │ post comment
                            ┌──────────────┐          MCP         │
                            │ LangChain PR │ ←────────────────────┘
                            │ Review Agent │
                            └──────────────┘
                                   │
                                   │ uses
                                   ▼
                            ┌──────────────┐
                            │ Code Review  │
                            │ Expert Skill │
                            └──────────────┘
```

1. Developer opens a PR on Gitee
2. Gitee sends a webhook POST to this service (action: "open")
3. Flask server validates the webhook token and parses PR metadata
4. In a background thread, the service triggers the **LangChain PR Review Agent**
5. The agent connects to Gitee MCP server using HTTP streamable MCP protocol
6. The agent fetches PR details and diff via MCP tools (`mcp__gitee__get_pull_detail`, `mcp__gitee__get_diff_files`)
7. The agent analyzes code changes using integrated **Code Review Expert** skills
8. The agent generates a professional review report with severity levels (P0-P4)
9. The review report is posted as a comment on the PR via MCP (`mcp__gitee__create_comment`)

## External Dependencies

This project depends on the **Gitee MCP Server**, which must be started locally first. The service connects to the MCP Server via the HTTP streamable MCP protocol to fetch PR diffs and post review comments.

### Starting the Gitee MCP Server

```bash
./bin/mcp-gitee --token <your-gitee-token> --transport http --enabled-toolsets="get_file_content,compare_branches_tags,list_repo_pulls,get_pull_detail,get_diff_files,create_comment"
```

Parameter details:

| Parameter | Description |
|-----------|-------------|
| `--token` | Gitee personal access token, same as `GITEE_TOKEN` in `.env` |
| `--transport http` | Use HTTP streamable transport protocol; the MCP Server listens on an HTTP endpoint for the service to connect |
| `--enabled-toolsets` | Enabled tool sets: `get_diff_files` (fetch PR changes), `create_comment` (post review comments), `get_pull_detail` (fetch PR details), etc. |

The MCP Server starts on `http://localhost:8000/mcp` by default, and this service connects to it at that address.

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (optional)

### Local Development

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Copy and edit environment config
cp .env.example .env

# Run the server
python -m src.app
```

The server starts on `http://localhost:5000`.

### Docker

```bash
docker-compose up --build
```

### Running Tests

```bash
# Run Flask server tests
pytest tests/test_app.py -v

# Run PR Agent tests
pytest tests/test_pr_agent.py -v

# Run all tests
pytest -v
```

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Server listen port |
| `FLASK_DEBUG` | `0` | Set to `1` for debug mode (never in production) |
| `GITEE_WEBHOOK_SECRET` | (required) | Token matching the webhook password set on Gitee |
| `GITEE_TOKEN` | (required) | Gitee personal access token for MCP API access |

### Gitee Token Setup
1. Go to https://gitee.com/profile/personal_access_tokens
2. Create a new token with appropriate permissions (repo access)
3. Copy the token to `.env` as `GITEE_TOKEN`

## Webhook Setup on Gitee

1. Go to your Gitee repository → Settings → Webhooks
2. Add a new webhook with your server's public URL (e.g., `https://your-domain.com/webhook`)
3. Set a **password/token** — this must match `GITEE_WEBHOOK_SECRET`
4. Select event type: **Pull Request**
5. Enable the webhook

## Development Notes

### Customizing Review Guidelines
1. Modify `resources/review_prompt.md` for the review prompt
2. Adjust severity levels and review criteria in the prompt