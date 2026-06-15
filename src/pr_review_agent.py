"""Gitee PR review agent using LLM and MCP tools.

This module provides an async PR review pipeline that:
1. Connects to a Gitee MCP server for PR data access
2. Loads a code review skill from a remote source
3. Uses an LLM (DeepSeek or OpenAI Compatible) to analyze PR diffs and produce review reports

The LLM provider is selected via the ``LLM_PROVIDER`` environment variable:
- ``deepseek`` (default): Uses ``ChatDeepSeek`` from ``langchain-deepseek``
- ``openai_compatible``: Uses ``ChatOpenAI`` from ``langchain-openai`` with a custom ``base_url``
"""

import asyncio
import base64
import binascii
import logging
import os
import dotenv

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.tools import tool
from langchain_core.tools.base import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

try:
    from src.webhook_notifier import send_notification
except ModuleNotFoundError:
    # When run directly as a script, ensure the project root is on sys.path
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.webhook_notifier import send_notification

dotenv.load_dotenv()

# ---------------------------------------------------------------------------
# Constants (all values read from .env)
# ---------------------------------------------------------------------------

REVIEW_PROMPT_PATH = os.environ["REVIEW_PROMPT_PATH"]
SKILL_URL = os.environ["CODE_REVIEW_SKILL_URL"]
MCP_URL = os.environ["GITEE_MCP_URL"]
MCP_AUTH_TOKEN = os.environ["GITEE_MCP_AUTH_TOKEN"]
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")
LLM_MODEL = os.environ["DEEPSEEK_MODEL"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

logger = logging.getLogger(__name__)

root_dir = "./resources"
backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)

def create_llm():
    """Create a configured LLM instance based on the provider setting.

    Returns:
        ChatDeepSeek or ChatOpenAI: LLM client ready for use.
    """
    if LLM_PROVIDER == "openai_compatible":
        from langchain_openai import ChatOpenAI

        kwargs = dict(
            model=OPENAI_MODEL,
            temperature=0,
            max_tokens=None,
            timeout=None,
            max_retries=2,
        )
        if OPENAI_BASE_URL:
            kwargs["base_url"] = OPENAI_BASE_URL
        if OPENAI_API_KEY:
            kwargs["api_key"] = OPENAI_API_KEY

        return ChatOpenAI(**kwargs)
    else:
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=LLM_MODEL,
            temperature=0,
            max_tokens=None,
            timeout=None,
            max_retries=2,
            extra_body={"thinking": {"type": "disabled"}}
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


@tool
def decode_base64(file_path: str) -> str:
    """Decode base64-encoded content in a JSON file and replace it with plain text.

    Reads a JSON file, decodes the base64-encoded ``content`` field in place,
    and writes the decoded text back to the same field.
    Use this tool after saving get_file_content results to a temporary JSON file.
    """
    import json

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return f"Error: file not found: {file_path}"
    except json.JSONDecodeError as e:
        return f"Error: failed to parse JSON file {file_path}: {e}"

    encoded = data.get("content", "")
    if not isinstance(encoded, str):
        return f"Error: 'content' field must be a string, got {type(encoded).__name__}"
    encoded = encoded.strip()
    if not encoded:
        return ""

    # Attempt 1: standard base64 with validation
    try:
        raw_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        # Attempt 2: URL-safe base64 (replace -_ with +/) and add padding
        try:
            alt = encoded.replace("-", "+").replace("_", "/")
            padding = 4 - len(alt) % 4
            if padding != 4:
                alt += "=" * padding
            raw_bytes = base64.b64decode(alt, validate=True)
        except (binascii.Error, ValueError) as e:
            return f"Error: failed to decode base64 string: {e}"

    # Decode bytes to UTF-8 text
    try:
        decoded = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return (
            "Error: decoded content is binary (not valid UTF-8 text) "
            "and cannot be returned as a string"
        )

    data["content"] = decoded
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        return f"Error: failed to write decoded content back to {file_path}: {e}"

    return (
        f"Successfully decoded base64 content in {file_path} "
        f"({len(decoded)} characters)"
    )


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

    # Notify: review started
    await send_notification(
        f"🔍 Review 开始: {repo_full_name}#{pr_id} "
        f"({source_branch} -> {target_branch})"
    )

    tools = await get_gitee_tools()
    tools.append(decode_base64)
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
    try:
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
    except Exception as e:
        logger.exception("Agent invocation failed for %s#%s",
                         repo_full_name, pr_id)
        await send_notification(
            f"❌ Review 失败: {repo_full_name}#{pr_id} - {e}"
        )
        raise

    logger.info("Agent finished for %s#%s", repo_full_name, pr_id)
    logger.info("Finished review for %s#%s", repo_full_name, pr_id)

    # Notify: review succeeded, include the last message content
    last_message = ""
    if isinstance(result, dict) and "messages" in result:
        messages = result["messages"]
        if messages:
            last_msg = messages[-1]
            if isinstance(last_msg, dict):
                last_message = last_msg.get("content", str(last_msg))
            else:
                last_message = str(last_msg)
    preview = last_message[:1000]
    if len(last_message) > 1000:
        preview += "…"
    await send_notification(
        f"✅ Review 完成: {repo_full_name}#{pr_id}\n\n{preview}"
    )

    return result


# ---------------------------------------------------------------------------
# Entry point (for manual / local testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a Gitee PR code review via DeepSeek LLM."
    )
    parser.add_argument(
        "--name",
        "--repo",
        dest="repo_full_name",
        required=True,
        help="Repository full name, e.g. 'owner/repo'",
    )
    parser.add_argument(
        "--id",
        "--pr-id",
        dest="pr_id",
        required=True,
        help="Gitee PR number or ID",
    )
    parser.add_argument(
        "--source-branch",
        "-s",
        dest="source_branch",
        required=True,
        help="PR source branch name",
    )
    parser.add_argument(
        "--target-branch",
        "-t",
        dest="target_branch",
        required=True,
        help="PR target branch name",
    )
    parser.add_argument(
        "--title",
        default="",
        help="PR title (optional)",
    )
    parser.add_argument(
        "--body",
        default="",
        help="PR body / description (optional)",
    )

    args = parser.parse_args()

    asyncio.run(
        review_pr(
            repo_full_name=args.repo_full_name,
            pr_id=args.pr_id,
            source_branch=args.source_branch,
            target_branch=args.target_branch,
            title=args.title,
            body=args.body,
        )
    )
