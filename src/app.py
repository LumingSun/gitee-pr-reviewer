import asyncio
import json
import logging
import os
import random
import threading
import time

from flask import Flask, request, jsonify

from src.pr_review_agent import review_pr

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
app.logger.setLevel(logging.INFO)

GITEE_WEBHOOK_SECRET = os.getenv('GITEE_WEBHOOK_SECRET', '')
REVIEW_TRIGGER_MENTION = os.getenv('REVIEW_TRIGGER_MENTION', '@ReviewAI')
MAX_REVIEW_RETRIES = int(os.getenv('MAX_REVIEW_RETRIES', '3'))


def _run_review_in_background(repo_full_name, pr_number, source_branch,
                              target_branch, title, body):
    """Run async review_pr in a background thread with retry logic."""
    def _runner():
        for attempt in range(1, MAX_REVIEW_RETRIES + 1):
            try:
                asyncio.run(review_pr(
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

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()


def verify_webhook_token(request):
    """验证 Gitee webhook token (X-Gitee-Token header)."""
    if not GITEE_WEBHOOK_SECRET:
        return True
    token = request.headers.get('X-Gitee-Token', '')
    return token == GITEE_WEBHOOK_SECRET


def _safe_strip(value):
    """Safely strip a string, handling None values."""
    return (value or '').strip()


def _parse_open_payload(data):
    """Extract PR review fields from an 'open' action webhook payload."""
    repository = data.get('repository', {}) or {}
    return {
        'repo_full_name': repository.get('full_name', ''),
        'pr_number': data.get('number'),
        'title': _safe_strip(data.get('title')),
        'body': _safe_strip(data.get('body')),
        'source_branch': _safe_strip(data.get('source_branch')),
        'target_branch': _safe_strip(data.get('target_branch')),
    }


def _parse_comment_payload(data):
    """Extract PR review fields from a 'comment' action webhook payload."""
    pr_data = data.get('pull_request', {}) or {}
    repository = data.get('repository', {}) or {}
    return {
        'repo_full_name': repository.get('full_name', ''),
        'pr_number': pr_data.get('number'),
        'title': _safe_strip(pr_data.get('title')),
        'body': _safe_strip(pr_data.get('body')),
        'source_branch': _safe_strip(
            (pr_data.get('head', {}) or {}).get('ref')),
        'target_branch': _safe_strip(
            (pr_data.get('base', {}) or {}).get('ref')),
    }


@app.before_request
def log_request():
    """Log every incoming request for diagnostics, redacting sensitive fields."""
    headers = dict(request.headers)
    if 'X-Gitee-Token' in headers:
        headers['X-Gitee-Token'] = '***'
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
    fields = {
        'repo_full_name': '',
        'pr_number': None,
        'source_branch': '',
        'target_branch': '',
        'title': '',
        'body': '',
    }

    if data.get('action') == 'open':
        triggered = True
        fields = _parse_open_payload(data)
        app.logger.info('PR open event: title=%s number=%s source=%s target=%s '
                        'repo=%s body_len=%d',
                        fields['title'], fields['pr_number'],
                        fields['source_branch'], fields['target_branch'],
                        fields['repo_full_name'], len(fields['body']))

    elif (data.get('action') == 'comment'
          and data.get('noteable_type') == 'PullRequest'
          and REVIEW_TRIGGER_MENTION in data.get('comment', {}).get('body', '').lower()):
        triggered = True
        fields = _parse_comment_payload(data)
        app.logger.info('PR comment trigger: title=%s number=%s source=%s '
                        'target=%s repo=%s body_len=%d',
                        fields['title'], fields['pr_number'],
                        fields['source_branch'], fields['target_branch'],
                        fields['repo_full_name'], len(fields['body']))

    if fields['repo_full_name'] and fields['pr_number']:
        _run_review_in_background(**fields)
        app.logger.info('Background review started for %s#%s',
                        fields['repo_full_name'], fields['pr_number'])
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
        'Configure Gitee webhook URL to https://<host>/webhook')
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
