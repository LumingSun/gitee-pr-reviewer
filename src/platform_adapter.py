"""Platform adapter for Gitee/Gitea differences.

Encapsulates all platform-specific logic so the rest of the codebase can
work against a single ``PlatformAdapter`` interface.
"""

import hashlib
import hmac
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalised PR metadata  (used internally, not by Flask routes directly)
# ---------------------------------------------------------------------------


@dataclass
class PrFields:
    """Normalised PR metadata extracted from any platform webhook payload."""

    repo_full_name: str = ""
    pr_number: Optional[int] = None
    title: str = ""
    body: str = ""
    source_branch: str = ""
    target_branch: str = ""


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _safe_strip(value) -> str:
    """Safely strip a string, handling None values."""
    return (value or "").strip()


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class PlatformAdapter(ABC):
    """Interface each platform must implement."""

    # -- metadata -----------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Platform identifier, e.g. ``"gitee"``, ``"gitea"``."""

    @property
    @abstractmethod
    def webhook_secret_env(self) -> str:
        """Env var name holding the webhook secret."""

    @property
    @abstractmethod
    def mcp_url_env(self) -> str:
        """Env var name holding the MCP server URL."""

    @property
    @abstractmethod
    def mcp_auth_token_env(self) -> str:
        """Env var name holding the MCP auth token."""

    # -- webhook auth -------------------------------------------------------

    @abstractmethod
    def verify_webhook_token(self, headers: dict, body: bytes, secret: str) -> bool:
        """Verify the authenticity of an incoming webhook request."""

    # -- payload parsing ----------------------------------------------------

    @abstractmethod
    def parse_open_payload(self, data: dict) -> PrFields:
        """Extract PR fields from an ``open`` / ``opened`` webhook payload."""

    @abstractmethod
    def parse_comment_payload(self, data: dict) -> PrFields:
        """Extract PR fields from a ``comment`` / ``created`` webhook payload."""

    # -- MCP / prompt -------------------------------------------------------

    @abstractmethod
    def get_review_prompt_path(self) -> str:
        """Path to the platform-specific review prompt template."""

    # -- action matching ----------------------------------------------------

    @abstractmethod
    def match_open_action(self, data: dict) -> bool:
        """Return ``True`` if *data* represents a PR-open event."""

    @abstractmethod
    def match_comment_action(self, data: dict) -> bool:
        """Return ``True`` if *data* represents a PR-comment event."""

    # -- helpers ------------------------------------------------------------

    @abstractmethod
    def get_auth_header_name(self) -> str:
        """Name of the HTTP header carrying the auth token / signature."""

    @abstractmethod
    def get_comment_body_path(self) -> list[str]:
        """JSON path to the comment body field for mention detection,
        e.g. ``["comment", "body"]`` for Gitee, ``["comment", "body"]`` for Gitea."""


# ===================================================================
# Gitee
# ===================================================================


class GiteeAdapter(PlatformAdapter):
    """Adapter for Gitee (gitee.com)."""

    name = "gitee"
    webhook_secret_env = "GITEE_WEBHOOK_SECRET"
    mcp_url_env = "GITEE_MCP_URL"
    mcp_auth_token_env = "GITEE_MCP_AUTH_TOKEN"

    def verify_webhook_token(self, headers: dict, body: bytes, secret: str) -> bool:
        token = headers.get("X-Gitee-Token", "")
        return token == secret

    def parse_open_payload(self, data: dict) -> PrFields:
        repository = data.get("repository", {}) or {}
        return PrFields(
            repo_full_name=repository.get("full_name", ""),
            pr_number=data.get("number"),
            title=_safe_strip(data.get("title")),
            body=_safe_strip(data.get("body")),
            source_branch=_safe_strip(data.get("source_branch")),
            target_branch=_safe_strip(data.get("target_branch")),
        )

    def parse_comment_payload(self, data: dict) -> PrFields:
        pr_data = data.get("pull_request", {}) or {}
        repository = data.get("repository", {}) or {}
        return PrFields(
            repo_full_name=repository.get("full_name", ""),
            pr_number=pr_data.get("number"),
            title=_safe_strip(pr_data.get("title")),
            body=_safe_strip(pr_data.get("body")),
            source_branch=_safe_strip(
                (pr_data.get("head", {}) or {}).get("ref")
            ),
            target_branch=_safe_strip(
                (pr_data.get("base", {}) or {}).get("ref")
            ),
        )

    def get_review_prompt_path(self) -> str:
        return "resources/review_prompt.md"

    def get_auth_header_name(self) -> str:
        return "X-Gitee-Token"

    def get_comment_body_path(self) -> list[str]:
        return ["comment", "body"]

    def match_open_action(self, data: dict) -> bool:
        return data.get("action") == "open"

    def match_comment_action(self, data: dict) -> bool:
        return (
            data.get("action") == "comment"
            and data.get("noteable_type") == "PullRequest"
        )


# ===================================================================
# Gitea
# ===================================================================


class GiteaAdapter(PlatformAdapter):
    """Adapter for Gitea (self-hosted Git service, GitHub-compatible API)."""

    name = "gitea"
    webhook_secret_env = "GITEA_WEBHOOK_SECRET"
    mcp_url_env = "GITEA_MCP_URL"
    mcp_auth_token_env = "GITEA_MCP_AUTH_TOKEN"

    def verify_webhook_token(self, headers: dict, body: bytes, secret: str) -> bool:
        signature = headers.get("X-Gitea-Signature", "")
        if not secret:
            return True
        expected = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_open_payload(self, data: dict) -> PrFields:
        pr_data = data.get("pull_request", {}) or {}
        repository = data.get("repository", {}) or {}
        return PrFields(
            repo_full_name=repository.get("full_name", ""),
            pr_number=pr_data.get("number"),
            title=_safe_strip(pr_data.get("title")),
            body=_safe_strip(pr_data.get("body")),
            source_branch=_safe_strip(
                (pr_data.get("head", {}) or {}).get("ref")
            ),
            target_branch=_safe_strip(
                (pr_data.get("base", {}) or {}).get("ref")
            ),
        )

    def parse_comment_payload(self, data: dict) -> PrFields:
        # Gitea PR comments: issue object with pull_request key present
        issue = data.get("issue", {}) or {}
        repository = data.get("repository", {}) or {}
        return PrFields(
            repo_full_name=repository.get("full_name", ""),
            pr_number=issue.get("number"),
            title=_safe_strip(issue.get("title")),
            body=_safe_strip(issue.get("body")),
            # Gitea issue objects for PRs also have pull_request sub-object
            # with head/base refs, but these may not always be present in
            # comment webhooks. Fall back to empty strings.
            source_branch=_safe_strip(
                (issue.get("pull_request", {}) or {}).get("head", "")
            ),
            target_branch=_safe_strip(
                (issue.get("pull_request", {}) or {}).get("base", "")
            ),
        )

    def get_review_prompt_path(self) -> str:
        return "resources/review_prompt_gitea.md"

    def get_auth_header_name(self) -> str:
        return "X-Gitea-Signature"

    def get_comment_body_path(self) -> list[str]:
        return ["comment", "body"]

    def match_open_action(self, data: dict) -> bool:
        return data.get("action") == "opened"

    def match_comment_action(self, data: dict) -> bool:
        # Gitea PR comments come as "created" action on an issue with pull_request
        return (
            data.get("action") == "created"
            and bool((data.get("issue", {}) or {}).get("pull_request"))
        )


# ===================================================================
# Factory
# ===================================================================


_ADAPTER_REGISTRY: dict[str, type[PlatformAdapter]] = {
    "gitee": GiteeAdapter,
    "gitea": GiteaAdapter,
}


def get_platform_adapter(platform: str) -> PlatformAdapter:
    """Return the platform adapter instance for *platform*.

    Raises:
        ValueError: If *platform* is not recognised.
    """
    platform = platform.strip().lower()
    cls = _ADAPTER_REGISTRY.get(platform)
    if cls is None:
        msg = f"Unsupported platform: {platform!r}.  Choose from: {list(_ADAPTER_REGISTRY)}"
        raise ValueError(msg)
    return cls()
