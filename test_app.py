import json

import pytest

from app import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(scope="module")
def example_data():
    with open('example.json', 'r', encoding='utf-8') as f:
        return json.load(f)


class TestWebhookToken:
    def test_valid_token(self, client, monkeypatch):
        monkeypatch.setattr('app.GITEE_WEBHOOK_SECRET', 'KWDB@2026!')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json',
                               headers={'X-Gitee-Token': 'KWDB@2026!'})
        assert response.status_code == 200

    def test_invalid_token_returns_403(self, client, monkeypatch):
        monkeypatch.setattr('app.GITEE_WEBHOOK_SECRET', 'KWDB@2026!')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json',
                               headers={'X-Gitee-Token': 'wrong-token'})
        assert response.status_code == 403
        assert 'Invalid webhook token' in response.get_json()['error']

    def test_missing_token_returns_403(self, client, monkeypatch):
        monkeypatch.setattr('app.GITEE_WEBHOOK_SECRET', 'KWDB@2026!')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json')
        assert response.status_code == 403

    def test_no_secret_configured_allows_all(self, client, monkeypatch):
        monkeypatch.setattr('app.GITEE_WEBHOOK_SECRET', '')
        response = client.post('/webhook',
                               data=json.dumps({'action': 'open'}),
                               content_type='application/json')
        assert response.status_code == 200


class TestWebhookResponse:
    def test_webhook_response(self, client, example_data):
        response = client.post('/webhook',
                               data=json.dumps(example_data),
                               content_type='application/json')
        assert response.status_code == 200
        result = json.loads(response.data)
        assert result['status'] == 'success'
        assert 'Webhook received' in result['message']

    def test_open_action_fields(self, client, example_data, caplog):
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

    def test_other_action_does_not_log_pr_open(self, client, example_data, caplog):
        data = dict(example_data)
        data['action'] = 'closed'
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps(data),
                                   content_type='application/json')
        assert response.status_code == 200
        assert 'PR open event:' not in caplog.text

    def test_invalid_json_returns_400(self, client, monkeypatch):
        monkeypatch.setattr('app.GITEE_WEBHOOK_SECRET', '')
        response = client.post('/webhook',
                               data='not json',
                               content_type='application/json')
        assert response.status_code == 400

    def test_missing_fields_defaults(self, client, caplog):
        with caplog.at_level('INFO'):
            response = client.post('/webhook',
                                   data=json.dumps({'action': 'open'}),
                                   content_type='application/json')
        assert response.status_code == 200
        log_text = caplog.text
        assert 'title=' in log_text
        assert 'number=None' in log_text
