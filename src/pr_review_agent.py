"""Gitee PR review agent using DeepSeek LLM and MCP tools.

This module provides an async PR review pipeline that:
1. Connects to a Gitee MCP server for PR data access
2. Loads a code review skill from a remote source
3. Uses DeepSeek LLM to analyze PR diffs and produce review reports
"""

import asyncio
import logging
import os
import dotenv

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.tools.base import BaseTool
from langchain_deepseek import ChatDeepSeek
from langchain_mcp_adapters.client import MultiServerMCPClient

dotenv.load_dotenv()

# ---------------------------------------------------------------------------
# Constants (all values read from .env)
# ---------------------------------------------------------------------------

REVIEW_PROMPT_PATH = os.environ["REVIEW_PROMPT_PATH"]
SKILL_URL = os.environ["CODE_REVIEW_SKILL_URL"]
MCP_URL = os.environ["GITEE_MCP_URL"]
MCP_AUTH_TOKEN = os.environ["GITEE_MCP_AUTH_TOKEN"]
LLM_MODEL = os.environ["DEEPSEEK_MODEL"]

logger = logging.getLogger(__name__)

root_dir = "./resources"
backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)

def create_llm() -> ChatDeepSeek:
    """Create a configured DeepSeek LLM instance.

    Returns:
        ChatDeepSeek: LLM client ready for use.
    """
    return ChatDeepSeek(
        model=LLM_MODEL,
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )


def load_review_prompt() -> str:
    """Load the review prompt from the configured file path.

    Returns:
        str: Review prompt template content.

    Raises:
        FileNotFoundError: If the prompt file is not found.
    """
    with open(REVIEW_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

async def get_gitee_tools() -> list[BaseTool]:
    """Create an MCP client for Gitee and return its available tools.

    Returns:
        list[BaseTool]: Tools exposed by the Gitee MCP server.
    """
    logger.info("Connecting to Gitee MCP: %s", MCP_URL)
    headers = {}
    if MCP_AUTH_TOKEN:
        headers["Authorization"] = MCP_AUTH_TOKEN

    mcp_client = MultiServerMCPClient(
        {
            "gitee": {
                "url": MCP_URL,
                "transport": "streamable_http",
                "headers": headers,
            }
        }
    )
    tools = await mcp_client.get_tools(server_name="gitee")
    logger.info("Gitee MCP connected: %d tools loaded", len(tools))
    return tools


async def review_pr(
    pr_id: str,
    source_branch: str,
    target_branch: str,
    title: str,
    body: str,
    repo_full_name="owner/repo",
) -> str:
    """Run an automated code review on a pull request.

    Args:
        repo_full_name: Repository path (e.g. ``owner/repo``).
        pr_id: Gitee PR number or ID.
        source_branch: The PR source branch name.
        target_branch: The PR target branch name.
        title: PR title.
        body: PR description / body text.

    Returns:
        str: The agent's review result text.
    """
    logger.info("Starting review: repo=%s pr=%s source=%s -> target=%s",
                repo_full_name, pr_id, source_branch, target_branch)

    tools = await get_gitee_tools()
    prompt = load_review_prompt()
    logger.info("Review prompt loaded from %s (%d chars)",
                REVIEW_PROMPT_PATH, len(prompt))

    llm = create_llm()
    logger.info("Creating agent: model=%s tools=%d", LLM_MODEL, len(tools))

    agent = create_deep_agent(
        model=llm,
        tools=tools,
        backend=backend,
        skills=["skills"],
        system_prompt=prompt,
    )

    logger.info("Invoking agent for %s#%s ...", repo_full_name, pr_id)
    result = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Please review the following PR:\n"
                        f"Repository: {repo_full_name}\n"
                        f"PR ID: {pr_id}\n"
                        f"Title: {title}\n"
                        f"Body: {body}\n"
                        f"Source Branch: {source_branch}\n"
                        f"Target Branch: {target_branch}"
                    ),
                }
            ],
        }
    )

    logger.info("Agent finished for %s#%s", repo_full_name, pr_id)
    logger.info("Finished review for %s#%s", repo_full_name, pr_id)
    return result


# ---------------------------------------------------------------------------
# Entry point (for manual / local testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        review_pr(
            repo_full_name="LumingSun/kwdb",
            pr_id="11",
            source_branch="test-pr",
            target_branch="master",
            title="",
            body="  ",
        )
    )
