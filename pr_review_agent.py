"""Gitee PR review agent using DeepSeek LLM and MCP tools.

This module provides an async PR review pipeline that:
1. Connects to a Gitee MCP server for PR data access
2. Loads a code review skill from a remote source
3. Uses DeepSeek LLM to analyze PR diffs and produce review reports
"""

import asyncio
import logging
import os
from urllib.request import urlopen

import dotenv
from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
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


def load_skill_files() -> dict:
    """Download the code review skill and wrap it for the agent.

    Returns:
        dict: Skills files mapping for the deep agent, keyed by virtual path.

    Raises:
        URLError: If the skill URL cannot be reached.
    """
    with urlopen(SKILL_URL) as response:
        skill_content = response.read().decode("utf-8")

    return {
        "/skills/code-review-expert/SKILL.md": create_file_data(skill_content),
    }


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

async def get_gitee_tools() -> list[BaseTool]:
    """Create an MCP client for Gitee and return its available tools.

    Returns:
        list[BaseTool]: Tools exposed by the Gitee MCP server.
    """
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
    return await mcp_client.get_tools(server_name="gitee")


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
    tools = await get_gitee_tools()
    prompt = load_review_prompt()
    skills_files = load_skill_files()
    llm = create_llm()

    agent = create_deep_agent(
        model=llm,
        tools=tools,
        skills=["/skills/"],
        system_prompt=prompt,
    )

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
            "files": skills_files,
        }
    )

    logging.info("Finished review for %s#%s", repo_full_name, pr_id)
    return result


# ---------------------------------------------------------------------------
# Entry point (for manual / local testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(
        review_pr(
            repo_full_name="LumingSun/kwdb",
            pr_id="3",
            source_branch="test-pr",
            target_branch="master",
            title="test-remove-later",
            body="  ",
        )
    )
