import asyncio
import json
import os
import threading

from flask import Flask, request, jsonify

from pr_review_agent import review_pr

app = Flask(__name__)

GITEE_WEBHOOK_SECRET = os.getenv('GITEE_WEBHOOK_SECRET', '')


def _run_review_in_background(repo_full_name, pr_number, source_branch,
                              target_branch, title, body):
    """Run async review_pr in a background thread to avoid blocking the webhook."""
    def _runner():
        try:
            asyncio.run(review_pr(
                repo_full_name=repo_full_name,
                pr_id=str(pr_number),
                source_branch=source_branch,
                target_branch=target_branch,
                title=title,
                body=body,
            ))
        except Exception:
            app.logger.exception('Background review failed for %s#%s',
                                 repo_full_name, pr_number)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()


def verify_webhook_token(request):
    """验证 Gitee webhook token (X-Gitee-Token header)."""
    if not GITEE_WEBHOOK_SECRET:
        return True
    token = request.headers.get('X-Gitee-Token', '')
    return token == GITEE_WEBHOOK_SECRET


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if not verify_webhook_token(request):
            app.logger.warning('Webhook token verification failed')
            return jsonify({'error': 'Invalid webhook token'}), 403

        data = request.get_json(silent=True)

        if data is None:
            return jsonify({'error': 'Invalid JSON data'}), 400

        app.logger.info('Received webhook data: %s',
                        json.dumps(data, ensure_ascii=False, indent=2))

        if data.get('action') == 'open':
            title = data.get('title', '').strip()
            number = data.get('number')
            body = data.get('body', '').strip()
            source_branch = data.get('source_branch', '').strip()
            target_branch = data.get('target_branch', '').strip()
            repository = data.get('repository', {}) or {}
            repo_full_name = repository.get('full_name', '')

            app.logger.info('PR open event: title=%s number=%s source=%s target=%s '
                            'repo=%s body_len=%d',
                            title, number, source_branch, target_branch,
                            repo_full_name, len(body))

            if repo_full_name and number:
                _run_review_in_background(
                    repo_full_name=repo_full_name,
                    pr_number=number,
                    source_branch=source_branch,
                    target_branch=target_branch,
                    title=title,
                    body=body,
                )
                app.logger.info('Background review started for %s#%s',
                                repo_full_name, number)
            else:
                app.logger.warning('Missing repo_full_name or number, '
                                   'skipping review')

        return jsonify({'status': 'success', 'message': 'Webhook received'}), 200

    except Exception as e:
        app.logger.error('Error processing webhook: %s', str(e))
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
