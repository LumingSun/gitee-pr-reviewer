"""Webhook notification utility for sending messages to Feishu/Lark.

This module provides an async function to send text messages
to a configured Feishu webhook URL.
"""

import logging
import os

import httpx

HEADERS = {"Content-Type": "application/json"}

logger = logging.getLogger(__name__)


def _get_webhook_url() -> str:
    """Lazily read REVIEW_WEBHOOK_URL from the environment.

    Using lazy evaluation instead of a module-level constant ensures
    that the .env file is loaded *before* this function is first called,
    regardless of import order in the entry point.
    """
    return os.environ.get("REVIEW_WEBHOOK_URL", "")


async def send_notification(message: str) -> None:
    """Send a text message to the configured Feishu webhook.

    Args:
        message: The text content to send.

    If ``REVIEW_WEBHOOK_URL`` is not set, the function is a no-op.
    The function logs errors but does not raise exceptions,
    so a notification failure never blocks the caller.
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        return

    payload = {
        "msg_type": "text",
        "content": {
            "text": message,
        },
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                webhook_url,
                json=payload,
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
        logger.info("Webhook notification sent successfully")
    except Exception:
        logger.exception("Failed to send webhook notification")
