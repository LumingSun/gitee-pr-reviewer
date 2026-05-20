import json
import os

from flask import Flask, request, jsonify

app = Flask(__name__)

GITEE_WEBHOOK_SECRET = os.getenv('GITEE_WEBHOOK_SECRET', '')


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

            app.logger.info('PR open event: title=%s number=%s source=%s target=%s body_len=%d',
                            title, number, source_branch, target_branch, len(body))

        return jsonify({'status': 'success', 'message': 'Webhook received'}), 200

    except Exception as e:
        app.logger.error('Error processing webhook: %s', str(e))
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=port, debug=debug)
