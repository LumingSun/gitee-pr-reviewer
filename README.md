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
7. The agent analyzes code changes using integrated **Code Review Expert** guidelines
8. The agent generates a professional review report with severity levels (P0-P4)
9. The review report is posted as a comment on the PR via MCP (`mcp__gitee__create_comment`)

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

## New Features: LangChain PR Review Agent

### Overview
The system now includes an advanced **LangChain-based PR Review Agent** that:
- Connects to Gitee via HTTP streamable MCP protocol
- Uses LangChain's `langchain-mcp-adapters` for MCP tool integration
- Integrates **Code Review Expert** skill for professional code analysis
- Supports multiple LLM providers (Claude, OpenAI)
- Generates structured review reports with severity levels

### How the Agent Works
```python
# 1. Webhook triggers PR review
@app.route('/webhook', methods=['POST'])
def webhook():
    if data.get('action') == 'open':
        # Start async PR review in background thread
        threading.Thread(target=process_pr_review_async, args=(data,)).start()

# 2. Agent processes the PR
agent = create_pr_review_agent(gitee_token=GITEE_TOKEN, model_name=LANGCHAIN_MODEL)
review_result = agent.review_pr(owner, repo, pr_number, ...)

# 3. Agent posts review comment
agent.post_review_comment(owner, repo, pr_number, review_report)
```

### Review Report Format
The agent generates professional review reports with:
- **P0 - Critical**: Security vulnerabilities, data loss risks (must block merge)
- **P1 - High**: Logic errors, significant SOLID violations (should fix before merge)
- **P2 - Medium**: Code smells, maintainability concerns (fix or create follow-up)
- **P3 - Low**: Style, naming, minor suggestions (optional improvements)

### Code Review Guidelines
The agent follows comprehensive checklists from `code-review-expert/`:
- **SOLID principles** (SRP, OCP, LSP, ISP, DIP)
- **Security scanning** (XSS, injection, race conditions, auth gaps)
- **Code quality** (error handling, performance, boundary conditions)
- **Removal candidates** (dead code identification)

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `5000` | Server listen port |
| `FLASK_DEBUG` | `0` | Set to `1` for debug mode (never in production) |
| `GITEE_WEBHOOK_SECRET` | (required) | Token matching the webhook password set on Gitee |
| `GITEE_TOKEN` | (required) | Gitee personal access token for MCP API access |
| `LANGCHAIN_MODEL` | `claude-sonnet-4-6` | LLM model for the review agent (claude-* or gpt-*) |
| `ANTHROPIC_API_KEY` | (optional) | Required for Claude models |
| `OPENAI_API_KEY` | (optional) | Required for OpenAI GPT models |

### Gitee Token Setup
1. Go to https://gitee.com/profile/personal_access_tokens
2. Create a new token with appropriate permissions (repo access)
3. Copy the token to `.env` as `GITEE_TOKEN`

### LLM Model Selection
- **Claude models**: Set `LANGCHAIN_MODEL=claude-sonnet-4-6` and provide `ANTHROPIC_API_KEY`
- **OpenAI models**: Set `LANGCHAIN_MODEL=gpt-4` and provide `OPENAI_API_KEY`
- Default is Claude Sonnet 4.6

## Webhook Setup on Gitee

1. Go to your Gitee repository → Settings → Webhooks
2. Add a new webhook with your server's public URL (e.g., `https://your-domain.com/webhook`)
3. Set a **password/token** — this must match `GITEE_WEBHOOK_SECRET`
4. Select event type: **Pull Request**
5. Enable the webhook

## Project Structure

```
.
├── src/                         # Application source code
│   ├── app.py                   # Flask webhook server with PR review integration
│   └── pr_review_agent.py       # LangChain PR Review Agent with MCP integration
├── resources/                   # Static resources
│   └── review_prompt.md         # Review prompt template
├── tests/                       # Test suite
│   ├── test_app.py              # Flask server tests
│   ├── test_pr_agent.py         # PR Agent tests
│   └── fixtures/
│       └── example.json         # Sample webhook payload for testing
├── requirements.txt             # Runtime dependencies (Flask, LangChain, MCP adapters)
├── requirements-dev.txt         # Dev dependencies (pytest, pytest-asyncio, etc.)
├── Dockerfile                   # Container build
├── .dockerignore                # Build context exclusions
├── docker-compose.yml           # Local Docker setup
├── .env.example                 # Environment config template
├── CLAUDE.md                    # Claude Code guidance
└── README.md
```

## Troubleshooting

### PR Review Not Triggering
1. **Check environment variables**: Ensure `GITEE_TOKEN` and `GITEE_WEBHOOK_SECRET` are set
2. **Verify webhook setup**: The webhook must be configured for "Pull Request" events
3. **Check logs**: Look for "PR review not triggered" warnings in server logs
4. **Agent availability**: Ensure `AGENT_AVAILABLE=True` (check LangChain imports)

### MCP Connection Issues
1. **Gitee token permissions**: The token must have repository access permissions
2. **Network connectivity**: Ensure the server can reach `https://api.gitee.com/mcp`
3. **MCP tool discovery**: Check if `mcp__gitee__*` tools are found by the agent

### LLM Model Issues
1. **API keys**: Provide `ANTHROPIC_API_KEY` for Claude or `OPENAI_API_KEY` for GPT
2. **Model name**: Use correct model names like `claude-sonnet-4-6` or `gpt-4`
3. **Provider availability**: Ensure the required LangChain provider package is installed

### Common Errors
- **"GITEE_TOKEN environment variable is required"**: Set the token in `.env`
- **"Failed to import PR review agent"**: Install required packages: `pip install -r requirements.txt`
- **"MCP tool not found"**: Verify Gitee MCP server availability and token permissions

## Development Notes

### Customizing Review Guidelines
1. Modify `resources/review_prompt.md` for the review prompt
2. Adjust severity levels and review criteria in the prompt

### Extending with Additional LLMs
1. Add new provider import in `src/pr_review_agent.py`
2. Extend `create_llm()` method to support the new provider
3. Add corresponding environment variable for API key
