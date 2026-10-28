import unittest
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path

from fastapi.testclient import TestClient
from demo_api import create_app


REQUEST = {
    "order": {"event_id": "demo-001", "title": "汽轮机振动超标", "content": "检查轴承",
              "level": "紧急", "unit_no": "#1"},
    "profile": {"user_id": "demo-user", "role": "汽轮机专工",
                "responsible_units": ["#1"], "device_interests": {"TURBINE": 1.0}},
}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / 'test.sqlite3'
        self.client = TestClient(create_app(self.db_path))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_predict_and_history(self):
        self.assertEqual(self.client.get('/orders').json()['total'], 0)
        first = self.client.post('/predict', json=REQUEST)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertGreaterEqual(first.json()['score'], 0.75)
        self.assertIsNone(first.json()['confidence'])
        modified = deepcopy(REQUEST)
        modified['order']['title'] = '修改后的工单'
        second = self.client.post('/predict', json=modified)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()['prediction_id'], second.json()['prediction_id'])
        listing = self.client.get('/orders').json()
        self.assertEqual(listing['total'], 1)
        record = listing['items'][0]
        self.assertEqual(len(record['history']), 2)
        self.assertEqual(record['history'][0]['order']['title'], REQUEST['order']['title'])
        self.assertEqual(record['latest_prediction'], second.json())
        self.assertEqual(self.client.get('/orders?user_id=other').json()['total'], 0)
        self.assertEqual(self.client.get('/orders?offset=1').json()['items'], [])

    def test_invalid_inputs_do_not_write(self):
        for field, value in [('title', ' '), ('level', 'unknown')]:
            body = deepcopy(REQUEST)
            body['order'][field] = value
            self.assertEqual(self.client.post('/predict', json=body).status_code, 422)
        body = deepcopy(REQUEST)
        body['profile']['device_interests']['TURBINE'] = 1.5
        self.assertEqual(self.client.post('/predict', json=body).status_code, 422)
        body = deepcopy(REQUEST)
        body['weights'] = {'device_type': 0.9}
        self.assertEqual(self.client.post('/predict', json=body).status_code, 422)
        self.assertEqual(self.client.get('/orders').json()['total'], 0)
        self.assertEqual(self.client.get('/orders?limit=0').status_code, 422)

    def test_documentation(self):
        self.assertEqual(self.client.get('/docs').status_code, 200)
        schema = self.client.get('/openapi.json').json()
        self.assertIn('/predict', schema['paths'])
        self.assertIn('/orders', schema['paths'])


if __name__ == '__main__':
    unittest.main()
