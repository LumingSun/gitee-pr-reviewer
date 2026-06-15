"""Webhook notification utility for sending messages to Feishu/Lark.

This module provides an async function to send text messages
to a configured Feishu webhook URL.
"""

import logging
import os

import httpx

WEBHOOK_URL = os.environ.get("REVIEW_WEBHOOK_URL", "")
HEADERS = {"Content-Type": "application/json"}

logger = logging.getLogger(__name__)

# If no webhook URL is configured, notifications are silently skipped
_notifications_enabled = bool(WEBHOOK_URL)


async def send_notification(message: str) -> None:
    """Send a text message to the configured Feishu webhook.

    Args:
        message: The text content to send.

    If ``REVIEW_WEBHOOK_URL`` is not set, the function is a no-op.
    The function logs errors but does not raise exceptions,
    so a notification failure never blocks the caller.
    """
    if not _notifications_enabled:
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
                WEBHOOK_URL,
                json=payload,
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
        logger.info("Webhook notification sent successfully")
    except Exception:
        logger.exception("Failed to send webhook notification")
