import json
import threading
import time

import pytest

from src.app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(scope="module")
def example_data():
    with open('tests/fixtures/example.json', 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture(scope="module")
def example_comment_data():
    with open('tests/fixtures/example2.json', 'r', encoding='utf-8') as f:
        return json.load(f)


class TestWebhookToken:
    def test_valid_token(self, client, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', 'KWDB@2026!')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json',
                               headers={'X-Gitee-Token': 'KWDB@2026!'})
        assert response.status_code == 200

    def test_invalid_token_returns_403(self, client, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', 'KWDB@2026!')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json',
                               headers={'X-Gitee-Token': 'wrong-token'})
        assert response.status_code == 403
        assert 'Invalid webhook token' in response.get_json()['error']

    def test_missing_token_returns_403(self, client, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', 'KWDB@2026!')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json')
        assert response.status_code == 403

    def test_no_secret_configured_allows_all(self, client, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json')
        assert response.status_code == 200


class TestWebhookResponse:
    def test_webhook_response(self, client, example_data, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        response = client.post('/webhook',
                               data=json.dumps(example_data),
                               content_type='application/json')
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['status'] == 'success'
        assert 'Webhook received' in result['message']

    def test_open_action_fields(self, client, example_data, caplog, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        data = dict(example_data)
        data['action'] = 'open'
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps(data),
                                   content_type='application/json')
        assert response.status_code == 200
        assert 'PR open event:' in caplog.text
        assert data['title'] in caplog.text
        assert str(data['number']) in caplog.text

    def test_other_action_does_not_log_pr_open(self, client, example_data, caplog, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        data = dict(example_data)
        data['action'] = 'closed'
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps(data),
                                   content_type='application/json')
        assert response.status_code == 200
        assert 'PR open event:' not in caplog.text

    def test_invalid_json_returns_400(self, client, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        response = client.post('/webhook',
                               data='not json',
                               content_type='application/json')
        assert response.status_code == 400

    def test_missing_fields_defaults(self, client, caplog, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps({'action': 'open'}),
                                   content_type='application/json')
        assert response.status_code == 200
        log_text = caplog.text
        assert 'title=' in log_text
        assert 'number=None' in log_text

    def test_comment_with_reviewai_triggers_review(self, client, example_comment_data, caplog, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        data = dict(example_comment_data)
        data['action'] = 'comment'
        data['noteable_type'] = 'PullRequest'
        data['comment'] = dict(data.get('comment', {}))
        data['comment']['body'] = 'Please review this @ReviewAI thanks'
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps(data),
                                   content_type='application/json')
        assert response.status_code == 200
        assert 'PR comment trigger:' in caplog.text

    def test_comment_not_pullrequest_does_not_trigger(self, client, example_comment_data, caplog, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        data = dict(example_comment_data)
        data['action'] = 'comment'
        data['noteable_type'] = 'Issue'
        data['comment'] = dict(data.get('comment', {}))
        data['comment']['body'] = '@ReviewAI please review'
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps(data),
                                   content_type='application/json')
        assert response.status_code == 200
        assert 'PR comment trigger:' not in caplog.text

    def test_comment_without_reviewai_does_not_trigger(self, client, example_comment_data, caplog, monkeypatch):
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        # example2.json has comment.body = " @LumingSun  " -- no @ReviewAI
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps(example_comment_data),
                                   content_type='application/json')
        assert response.status_code == 200
        assert 'PR comment trigger:' not in caplog.text


class TestReviewRetry:
    """Tests for the retry mechanism in _run_review_in_background."""

    def test_retry_on_failure(self, client, example_data, monkeypatch):
        """Review should be retried on failure and eventually succeed."""
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        monkeypatch.setattr('src.app.MAX_REVIEW_RETRIES', 3)

        call_count = 0
        done = threading.Event()

        async def mock_review_pr(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError(f'Transient failure #{call_count}')
            done.set()

        monkeypatch.setattr('src.app.review_pr', mock_review_pr)

        response = client.post('/webhook',
                               data=json.dumps(example_data),
                               content_type='application/json')
        assert response.status_code == 200
        assert done.wait(timeout=10), 'Review did not complete in time'
        assert call_count == 3

    def test_all_retries_exhausted(self, client, example_data, monkeypatch):
        """When all retries fail, all attempts should be made."""
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        monkeypatch.setattr('src.app.MAX_REVIEW_RETRIES', 3)

        call_count = 0
        done = threading.Event()

        async def mock_review_pr(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                done.set()
            raise RuntimeError(f'Persistent failure #{call_count}')

        monkeypatch.setattr('src.app.review_pr', mock_review_pr)

        response = client.post('/webhook',
                               data=json.dumps(example_data),
                               content_type='application/json')
        assert response.status_code == 200
        assert done.wait(timeout=15), 'Retries did not complete in time'
        assert call_count == 3

    def test_first_attempt_succeeds(self, client, example_data, monkeypatch):
        """When the first attempt succeeds, only one attempt should be made."""
        monkeypatch.setattr('src.app.GITEE_WEBHOOK_SECRET', '')
        monkeypatch.setattr('src.app.MAX_REVIEW_RETRIES', 3)

        call_count = 0
        done = threading.Event()

        async def mock_review_pr(**kwargs):
            nonlocal call_count
            call_count += 1
            done.set()

        monkeypatch.setattr('src.app.review_pr', mock_review_pr)

        response = client.post('/webhook',
                               data=json.dumps(example_data),
                               content_type='application/json')
        assert response.status_code == 200
        assert done.wait(timeout=5), 'Review did not complete in time'
        assert call_count == 1
