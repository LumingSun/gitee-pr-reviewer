import asyncio
import json
import logging
import os
import random
import threading
import time

from flask import Flask, request, jsonify

from src.platform_adapter import PrFields, get_platform_adapter
from src.pr_review_agent import review_pr
from src.webhook_notifier import send_notification

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
app.logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Platform selection
# ---------------------------------------------------------------------------
PLATFORM = os.getenv('PLATFORM', 'gitee').strip().lower()
adapter = get_platform_adapter(PLATFORM)
app.logger.info('Platform: %s (adapter=%s)', PLATFORM, type(adapter).__name__)

WEBHOOK_SECRET = os.getenv(adapter.webhook_secret_env, '')
REVIEW_TRIGGER_MENTION = os.getenv('REVIEW_TRIGGER_MENTION', '@ReviewAI')
MAX_REVIEW_RETRIES = int(os.getenv('MAX_REVIEW_RETRIES', '3'))


def _run_review_in_background(repo_full_name, pr_number, source_branch,
                              target_branch, title, body):
    """Run async review_pr in a background thread with retry logic."""
    def _runner():
        for attempt in range(1, MAX_REVIEW_RETRIES + 1):
            try:
                asyncio.run(review_pr(
                    platform=PLATFORM,
                    repo_full_name=repo_full_name,
                    pr_id=str(pr_number),
                    source_branch=source_branch,
                    target_branch=target_branch,
                    title=title,
                    body=body,
                ))
                return
            except Exception as e:
                if attempt < MAX_REVIEW_RETRIES:
                    delay = (2 ** attempt) + random.uniform(0, 1)
                    app.logger.warning(
                        'Review attempt %d/%d failed for %s#%s: %s. '
                        'Retrying in %.1fs...',
                        attempt, MAX_REVIEW_RETRIES,
                        repo_full_name, pr_number, e, delay)
                    time.sleep(delay)
                else:
                    app.logger.exception(
                        'All %d attempts failed for %s#%s',
                        MAX_REVIEW_RETRIES, repo_full_name, pr_number)
                    asyncio.run(send_notification(
                        f"Review failed: {repo_full_name}#{pr_number} - "
                        f"all {MAX_REVIEW_RETRIES} retries exhausted: {e}"
                    ))

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()


def verify_webhook_token(request):
    """Verify the webhook token/signature for the active platform."""
    if not WEBHOOK_SECRET:
        return True
    return adapter.verify_webhook_token(
        request.headers,
        request.get_data(),
        WEBHOOK_SECRET,
    )


def _get_comment_body(data):
    """Extract comment body text using the adapter's comment body path."""
    path = adapter.get_comment_body_path()
    val = data
    for key in path:
        if isinstance(val, dict):
            val = val.get(key, {}) or {}
        else:
            return ''
    return (val or '').strip() if isinstance(val, str) else ''


@app.before_request
def log_request():
    """Log every incoming request for diagnostics, redacting sensitive fields."""
    headers = dict(request.headers)
    auth_header = adapter.get_auth_header_name()
    if auth_header in headers:
        headers[auth_header] = '***'
    raw_body = request.get_data(as_text=True)[:500]
    try:
        body_json = json.loads(raw_body)
        if isinstance(body_json, dict) and 'password' in body_json:
            body_json['password'] = '***'
        body = json.dumps(body_json)
    except Exception:
        body = raw_body
    app.logger.info(
        '>>> REQUEST %s %s from %s\n'
        '    Headers: %s\n'
        '    Body: %s',
        request.method, request.path, request.remote_addr,
        headers,
        body,
    )


def _handle_webhook():
    """Process webhook payload: verify token, parse JSON, trigger review."""
    if not verify_webhook_token(request):
        app.logger.warning('Webhook token verification failed')
        return jsonify({'error': 'Invalid webhook token'}), 403

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid JSON data'}), 400

    app.logger.info('Webhook payload: action=%s number=%s',
                    data.get('action'), data.get('number'))

    triggered = False
    fields = PrFields()

    if adapter.match_open_action(data):
        triggered = True
        fields = adapter.parse_open_payload(data)
        app.logger.info(
            '%s PR open event: title=%s number=%s source=%s target=%s '
            'repo=%s body_len=%d',
            adapter.name.upper(),
            fields.title, fields.pr_number,
            fields.source_branch, fields.target_branch,
            fields.repo_full_name, len(fields.body))

    elif (adapter.match_comment_action(data)
          and REVIEW_TRIGGER_MENTION.lower() in _get_comment_body(data).lower()):
        triggered = True
        fields = adapter.parse_comment_payload(data)
        app.logger.info(
            '%s PR comment trigger: title=%s number=%s source=%s '
            'target=%s repo=%s body_len=%d',
            adapter.name.upper(),
            fields.title, fields.pr_number,
            fields.source_branch, fields.target_branch,
            fields.repo_full_name, len(fields.body))

    if fields.repo_full_name and fields.pr_number:
        _run_review_in_background(
            repo_full_name=fields.repo_full_name,
            pr_number=fields.pr_number,
            source_branch=fields.source_branch,
            target_branch=fields.target_branch,
            title=fields.title,
            body=fields.body,
        )
        app.logger.info('Background review started for %s#%s',
                        fields.repo_full_name, fields.pr_number)
    elif triggered:
        app.logger.warning('Missing repo_full_name or number, '
                           'skipping review')

    return jsonify({'status': 'success', 'message': 'Webhook received'}), 200


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        return _handle_webhook()
    except Exception as e:
        app.logger.error('Error processing webhook: %s', str(e))
        return jsonify({'error': str(e)}), 500


@app.route('/', methods=['POST'])
def catch_webhook():
    app.logger.warning(
        'Webhook received at / (root path). '
        'Configure webhook URL to https://<host>/webhook')
    try:
        return _handle_webhook()
    except Exception as e:
        app.logger.error('Error processing webhook at /: %s', str(e))
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'

    ssl_cert = os.getenv('SSL_CERT_PATH', '')
    ssl_key = os.getenv('SSL_KEY_PATH', '')
    ssl_context = (ssl_cert, ssl_key) if (ssl_cert and ssl_key) else None

    app.run(host='0.0.0.0', port=port, debug=debug, ssl_context=ssl_context)
