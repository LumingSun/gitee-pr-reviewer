"""Unit tests for platform adapters (GiteeAdapter and GiteaAdapter)."""

import hashlib
import hmac
import json

import pytest

from src.platform_adapter import (
    GiteaAdapter,
    GiteeAdapter,
    PrFields,
    get_platform_adapter,
)


class TestGetPlatformAdapter:
    def test_gitee(self):
        adapter = get_platform_adapter("gitee")
        assert isinstance(adapter, GiteeAdapter)
        assert adapter.name == "gitee"

    def test_gitea(self):
        adapter = get_platform_adapter("gitea")
        assert isinstance(adapter, GiteaAdapter)
        assert adapter.name == "gitea"

    def test_case_insensitive(self):
        adapter = get_platform_adapter("GITEA")
        assert adapter.name == "gitea"

    def test_unsupported_platform(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_platform_adapter("github")


# ===================================================================
# GiteeAdapter
# ===================================================================


class TestGiteeAdapter:
    @pytest.fixture
    def adapter(self):
        return GiteeAdapter()

    def test_properties(self, adapter):
        assert adapter.name == "gitee"
        assert adapter.webhook_secret_env == "GITEE_WEBHOOK_SECRET"
        assert adapter.mcp_url_env == "GITEE_MCP_URL"
        assert adapter.mcp_auth_token_env == "GITEE_MCP_AUTH_TOKEN"
        assert adapter.get_review_prompt_path() == "resources/review_prompt.md"

    def test_verify_token_valid(self, adapter):
        headers = {"X-Gitee-Token": "secret123"}
        assert adapter.verify_webhook_token(headers, b"", "secret123") is True

    def test_verify_token_invalid(self, adapter):
        headers = {"X-Gitee-Token": "wrong"}
        assert adapter.verify_webhook_token(headers, b"", "secret123") is False

    def test_verify_token_missing(self, adapter):
        assert adapter.verify_webhook_token({}, b"", "secret123") is False

    def test_verify_no_secret_configured(self, adapter):
        assert adapter.verify_webhook_token({}, b"", "") is True

    def test_parse_open_payload(self, adapter):
        data = {
            "number": 42,
            "title": "Fix bug",
            "body": "Description",
            "source_branch": "fix-bug",
            "target_branch": "main",
            "repository": {"full_name": "owner/repo"},
        }
        fields = adapter.parse_open_payload(data)
        assert fields.repo_full_name == "owner/repo"
        assert fields.pr_number == 42
        assert fields.title == "Fix bug"
        assert fields.body == "Description"
        assert fields.source_branch == "fix-bug"
        assert fields.target_branch == "main"

    def test_parse_open_payload_empty_repo(self, adapter):
        fields = adapter.parse_open_payload({"number": 1})
        assert fields.repo_full_name == ""

    def test_parse_comment_payload(self, adapter):
        data = {
            "repository": {"full_name": "owner/repo"},
            "pull_request": {
                "number": 42,
                "title": "Fix bug",
                "body": "Description",
                "head": {"ref": "fix-bug"},
                "base": {"ref": "main"},
            },
        }
        fields = adapter.parse_comment_payload(data)
        assert fields.repo_full_name == "owner/repo"
        assert fields.pr_number == 42
        assert fields.source_branch == "fix-bug"
        assert fields.target_branch == "main"

    def test_parse_comment_payload_missing_nested(self, adapter):
        data = {"repository": {"full_name": "owner/repo"}, "pull_request": {}}
        fields = adapter.parse_comment_payload(data)
        assert fields.source_branch == ""
        assert fields.target_branch == ""

    def test_match_open_action(self, adapter):
        assert adapter.match_open_action({"action": "open"}) is True
        assert adapter.match_open_action({"action": "opened"}) is False
        assert adapter.match_open_action({"action": "comment"}) is False

    def test_match_comment_action(self, adapter):
        assert (
            adapter.match_comment_action(
                {"action": "comment", "noteable_type": "PullRequest"}
            )
            is True
        )
        assert adapter.match_comment_action({"action": "comment"}) is False
        assert adapter.match_comment_action({"action": "open"}) is False


# ===================================================================
# GiteaAdapter
# ===================================================================


class TestGiteaAdapter:
    @pytest.fixture
    def adapter(self):
        return GiteaAdapter()

    def test_properties(self, adapter):
        assert adapter.name == "gitea"
        assert adapter.webhook_secret_env == "GITEA_WEBHOOK_SECRET"
        assert adapter.mcp_url_env == "GITEA_MCP_URL"
        assert adapter.mcp_auth_token_env == "GITEA_MCP_AUTH_TOKEN"
        assert adapter.get_review_prompt_path() == "resources/review_prompt_gitea.md"

    def test_verify_token_valid(self, adapter):
        secret = "mysecret"
        body = b'{"action":"opened"}'
        expected = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        headers = {"X-Gitea-Signature": expected}
        assert adapter.verify_webhook_token(headers, body, secret) is True

    def test_verify_token_invalid(self, adapter):
        headers = {"X-Gitea-Signature": "invalid"}
        assert (
            adapter.verify_webhook_token(headers, b"body", "secret") is False
        )

    def test_verify_token_missing(self, adapter):
        assert adapter.verify_webhook_token({}, b"body", "secret") is False

    def test_verify_no_secret_configured(self, adapter):
        assert adapter.verify_webhook_token({}, b"body", "") is True

    def test_parse_open_payload(self, adapter):
        data = {
            "repository": {"full_name": "owner/repo"},
            "pull_request": {
                "number": 42,
                "title": "Fix auth bug",
                "body": "Description",
                "head": {"ref": "fix-auth"},
                "base": {"ref": "main"},
            },
        }
        fields = adapter.parse_open_payload(data)
        assert fields.repo_full_name == "owner/repo"
        assert fields.pr_number == 42
        assert fields.title == "Fix auth bug"
        assert fields.source_branch == "fix-auth"
        assert fields.target_branch == "main"

    def test_parse_open_payload_missing_repo(self, adapter):
        fields = adapter.parse_open_payload({"pull_request": {"number": 1}})
        assert fields.repo_full_name == ""

    def test_parse_comment_payload(self, adapter):
        data = {
            "repository": {"full_name": "owner/repo"},
            "issue": {
                "number": 42,
                "title": "Fix auth bug",
                "body": "Description",
                "pull_request": {"head": "fix-auth", "base": "main"},
            },
        }
        fields = adapter.parse_comment_payload(data)
        assert fields.repo_full_name == "owner/repo"
        assert fields.pr_number == 42
        assert fields.title == "Fix auth bug"
        assert fields.source_branch == "fix-auth"
        assert fields.target_branch == "main"

    def test_parse_comment_payload_no_pull_request_key(self, adapter):
        data = {
            "repository": {"full_name": "owner/repo"},
            "issue": {"number": 42, "title": "Fix bug"},
        }
        fields = adapter.parse_comment_payload(data)
        assert fields.source_branch == ""
        assert fields.target_branch == ""

    def test_match_open_action(self, adapter):
        assert adapter.match_open_action({"action": "opened"}) is True
        assert adapter.match_open_action({"action": "open"}) is False
        assert adapter.match_open_action({"action": "created"}) is False

    def test_match_comment_action(self, adapter):
        assert (
            adapter.match_comment_action(
                {
                    "action": "created",
                    "issue": {"pull_request": {"head": "fix"}},
                }
            )
            is True
        )
        assert (
            adapter.match_comment_action({"action": "created", "issue": {}})
            is False
        )
        assert adapter.match_comment_action({"action": "opened"}) is False


# ===================================================================
# PrFields dataclass
# ===================================================================


class TestPrFields:
    def test_defaults(self):
        fields = PrFields()
        assert fields.repo_full_name == ""
        assert fields.pr_number is None
        assert fields.title == ""
        assert fields.body == ""
        assert fields.source_branch == ""
        assert fields.target_branch == ""
