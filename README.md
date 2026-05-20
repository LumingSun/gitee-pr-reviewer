# Gitee PR Reviewer

Automated pull request review service for Gitee. Receives PR webhook events from Gitee, then invokes the Gitee MCP server and code review AI to analyze code changes and post review reports back to the PR.

## How It Works

```
┌─────────┐    webhook     ┌──────────────┐    MCP API     ┌──────────────┐
│  Gitee  │ ──────────────→ │ Flask Server │ ────────────→ │ Gitee MCP    │
│  (PR)   │                 │ (this repo)  │               │ Server       │
└─────────┘                 └──────────────┘               └──────────────┘
                                   │                              │
                                   │ trigger                      │ fetch diff
                                   ▼                              │ post comment
                            ┌──────────────┐                      │
                            │ Code Review  │ ←────────────────────┘
                            │ AI / Skill   │
                            └──────────────┘
```

1. Developer opens a PR on Gitee
2. Gitee sends a webhook POST to this service
3. The service parses PR metadata from the webhook payload
4. The service calls Gitee MCP to fetch the PR diff and related data
5. The code review AI analyzes the changes and generates a review
6. The review report is posted as a comment on the PR via Gitee MCP

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
python app.py
```

The server starts on `http://localhost:5000`.

### Docker

```bash
docker-compose up --build
```

### Running Tests

```bash
pytest test_app.py -v
```

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Server listen port |
| `FLASK_DEBUG` | `0` | Set to `1` for debug mode (never in production) |
| `GITEE_WEBHOOK_SECRET` | (required) | Token matching the webhook password set on Gitee |

## Webhook Setup on Gitee

1. Go to your Gitee repository → Settings → Webhooks
2. Add a new webhook with your server's public URL (e.g., `https://your-domain.com/webhook`)
3. Set a **password/token** — this must match `GITEE_WEBHOOK_SECRET`
4. Select event type: **Pull Request**
5. Enable the webhook

## Project Structure

```
.
├── app.py                 # Flask webhook server
├── test_app.py            # Tests (9 test cases)
├── example.json           # Sample webhook payload for testing
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # Dev dependencies (pytest, etc.)
├── Dockerfile             # Container build
├── .dockerignore          # Build context exclusions
├── docker-compose.yml     # Local Docker setup
├── .env.example           # Environment config template
├── CLAUDE.md              # Claude Code guidance
└── README.md
```
