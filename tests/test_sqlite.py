from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from demo_api import create_app, PredictRequest
from test_demo_api import REQUEST


class SQLiteTests(unittest.TestCase):
    def test_restart_feedback_and_user_isolation(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.sqlite3'
            with TestClient(create_app(path)) as client:
                prediction = client.post('/predict', json=REQUEST).json()
                endpoint = f"/predictions/{prediction['prediction_id']}/feedback"
                self.assertEqual(client.post(endpoint, json={
                    'action': 'confirm', 'reviewer': 'demo'}).status_code, 201)
                corrected = client.post(endpoint, json={'action': 'correct', 'reviewer': 'demo',
                    'comment': '演示修正', 'corrected_score': 0, 'corrected_push_type': 'device_group'})
                self.assertEqual(corrected.status_code, 201, corrected.text)
            with TestClient(create_app(path)) as client:
                listing = client.get('/orders').json()
                self.assertEqual(listing['storage'], 'sqlite')
                row = listing['items'][0]
                self.assertEqual(row['latest_prediction'], prediction)
                self.assertEqual(row['effective_result']['score'], 0)
                self.assertEqual(row['effective_result']['source'], 'human')
                self.assertEqual(row['latest_feedback'], corrected.json())
                self.assertEqual(len(row['history'][0]['feedback']), 2)
                other = deepcopy(REQUEST)
                other['profile']['user_id'] = 'other'
                client.post('/predict', json=other)
                self.assertIsNone(client.get('/orders?user_id=other').json()['items'][0]['latest_feedback'])
                row = client.get('/orders?user_id=demo-user').json()['items'][0]
                self.assertEqual(row['effective_result']['review_status'], 'correct')
                self.assertEqual(len(row['history']), 1)
                client.post('/predict', json=REQUEST)
                row = client.get('/orders?user_id=demo-user').json()['items'][0]
                self.assertEqual(row['effective_result']['review_status'], 'pending')
                self.assertIsNone(row['latest_feedback'])
                self.assertEqual(len(row['history'][0]['feedback']), 2)

    def test_validation_and_transaction_rollback(self):
        with TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp) / 'test.sqlite3')) as client:
            self.assertEqual(client.post('/predictions/missing/feedback', json={
                'action': 'confirm', 'reviewer': 'demo'}).status_code, 404)
            prediction = client.post('/predict', json=REQUEST).json()
            endpoint = f"/predictions/{prediction['prediction_id']}/feedback"
            for body in [
                {'action': 'confirm', 'reviewer': 'demo', 'corrected_score': 0.2},
                {'action': 'correct', 'reviewer': 'demo', 'comment': 'missing correction'},
                {'action': 'correct', 'reviewer': 'demo', 'corrected_score': 0.2},
                {'action': 'correct', 'reviewer': 'demo', 'comment': 'bad score', 'corrected_score': 2},
            ]:
                self.assertEqual(client.post(endpoint, json=body).status_code, 422)
            self.assertEqual(client.get('/orders').json()['items'][0]['history'][0]['feedback'], [])
            request = PredictRequest.model_validate(REQUEST).model_dump(mode='json')
            request['order']['title'] = 'must roll back'
            with self.assertRaises(sqlite3.IntegrityError):
                client.app.state.store.save(request, prediction)
            with client.app.state.store.connection() as conn:
                self.assertEqual(conn.execute('SELECT title FROM orders').fetchone()[0], REQUEST['order']['title'])
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM predictions').fetchone()[0], 1)
