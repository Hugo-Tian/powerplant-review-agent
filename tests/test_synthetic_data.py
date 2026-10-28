import json
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from fastapi.testclient import TestClient

from core.inference import PushPredictor, UserProfile, WorkOrder
from demo_api import create_app, PredictRequest
from scripts.generate_demo_data import ROOT, generate, to_predict_request

# 模拟工单字段需与旧版 PostgreSQL 的 EventCreate 一致，旧代码已归档到 _legacy/
sys.path.insert(0, str(ROOT / '_legacy'))
from modules.events.schemas import EventCreate  # noqa: E402


class SyntheticDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'data/synthetic/dataset.json').read_text(encoding='utf-8'))

    def test_reproducible_schema_and_relations(self):
        self.assertEqual(self.data, generate())
        self.assertEqual(len(self.data['orders']), 320)
        self.assertEqual(len({o['event_no'] for o in self.data['orders']}), 320)
        self.assertTrue(self.data['metadata']['synthetic'])
        catalogs = self.data['catalogs']
        for order in self.data['orders']:
            self.assertEqual(set(order), set(EventCreate.model_fields))
            EventCreate.model_validate(order)
            for field, table in [('plant_id', 'plants'), ('unit_id', 'units'),
                                 ('device_type_id', 'device_types'),
                                 ('manufacturer_id', 'manufacturers'), ('model_id', 'device_models')]:
                self.assertTrue(order[field] is None or order[field] in {r['id'] for r in catalogs[table]})
            if order['model_id'] is not None:
                model = next(m for m in catalogs['device_models'] if m['id'] == order['model_id'])
                self.assertEqual(model['manufacturer_id'], order['manufacturer_id'])
                self.assertEqual(model['device_type_id'], order['device_type_id'])
        self.assertEqual({o['level'] for o in self.data['orders']}, {'一般', '重要', '紧急', '建议'})

    def test_all_generated_requests_through_api(self):
        requests = json.loads((ROOT / 'data/synthetic/predict_requests.json').read_text(encoding='utf-8'))
        expected = [to_predict_request(o, self.data['catalogs'], self.data['profiles'][0])
                    for o in self.data['orders']]
        self.assertEqual(requests, expected)
        with TemporaryDirectory() as tmp, TestClient(create_app(Path(tmp) / 'test.sqlite3')) as client:
            for request in requests:
                PredictRequest.model_validate(request)
                response = client.post('/predict', json=request)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertTrue(0 <= result['score'] <= 1)
                self.assertIsNone(result['confidence'])
                if request['order']['level'] == '紧急':
                    self.assertGreaterEqual(result['score'], 0.75)
            self.assertEqual(client.get('/orders').json()['total'], 320)
            first = client.get('/orders?limit=200').json()['items']
            second = client.get('/orders?offset=200&limit=200').json()['items']
            self.assertEqual(len(first) + len(second), 320)

    def test_personalization_and_sparse_input(self):
        predictor = PushPredictor()
        profiles = [UserProfile(**p) for p in self.data['profiles']]
        for device_id, specialist in [(1, 0), (4, 1), (3, 2)]:
            source = next(o for o in self.data['orders']
                          if o['device_type_id'] == device_id and o['level'] == '一般'
                          and o['unit_id'] != 1)
            order = WorkOrder(**to_predict_request(source, self.data['catalogs'], self.data['profiles'][0])['order'])
            scores = [predictor.predict(order, p)['score'] for p in profiles]
            self.assertGreater(scores[specialist], max(s for i, s in enumerate(scores) if i != specialist))
        sparse = self.data['orders'][0]
        order = WorkOrder(**to_predict_request(sparse, self.data['catalogs'], self.data['profiles'][0])['order'])
        self.assertEqual(predictor.predict(order, profiles[0])['score'], 0)


if __name__ == '__main__':
    unittest.main()
