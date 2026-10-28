from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

import math

from core.profile_builder import SATURATION, behavior_weight, build_profile
from demo_api import create_app
from test_demo_api import REQUEST

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


class ProfileBuilderTests(unittest.TestCase):
    def test_decay_and_dwell_follow_legacy_formula(self):
        fresh = behavior_weight('query', None, NOW, NOW)
        old = behavior_weight('query', None, NOW - timedelta(days=14), NOW)
        self.assertEqual(fresh, 1.0)
        self.assertAlmostEqual(old, 0.4966, places=3)
        self.assertGreater(behavior_weight('detail', 120, NOW, NOW), 2.0)
        self.assertEqual(behavior_weight('download', 120, NOW, NOW), 3.0)

    def test_routing_normalisation_floor_and_role_fallback(self):
        user = {'user_id': 'u', 'role': '汽轮机专工', 'responsible_units': ['#1'],
                'device_interests': {'TURBINE': 1.0}, 'fault_interests': {'FAULT_VIBRATION': 0.2}}
        behaviors = [
            {'action_type': 'download', 'occurred_at': NOW, 'tags': [
                {'code': 'FWP', 'category': 'device_type'}, {'code': 'MFR_DFST', 'category': 'manufacturer'}]},
            {'action_type': 'query', 'occurred_at': NOW.isoformat(), 'tags': [
                {'code': 'FAULT_VIBRATION'}, {'code': 'KW_BEARING'}]},
        ]
        p = build_profile(user, behaviors, now=NOW)
        sat = lambda w: round(1 - math.exp(-w / SATURATION), 4)  # noqa: E731
        self.assertEqual(p.device_interests['FWP'], sat(3.0))         # one download
        self.assertEqual(p.device_interests['TURBINE'], 1.0)          # base floor kept
        self.assertEqual(p.device_interests['DEH_CTRL'], 0.3)         # role fallback
        self.assertEqual(p.mfr_interests, {'MFR_DFST': sat(3.0)})
        self.assertEqual(p.fault_interests, {'FAULT_VIBRATION': 0.2})  # one query (0.1175) stays below base 0.2
        self.assertEqual(p.keyword_interests, {'KW_BEARING': sat(1.0)})
        self.assertEqual(p.personal_tags[0], '汽轮机专工')
        self.assertIn('故障处理:FAULT_VIBRATION', p.personal_tags)

    def test_few_clicks_never_saturate(self):
        clicks = lambda n: [{'action_type': 'detail', 'occurred_at': NOW, 'tags': [{'code': 'MFR_SEC'}]}] * n  # noqa: E731
        two = build_profile({'user_id': 'u'}, clicks(2), now=NOW).mfr_interests['MFR_SEC']
        ten = build_profile({'user_id': 'u'}, clicks(10), now=NOW).mfr_interests['MFR_SEC']
        self.assertAlmostEqual(two, 0.39, delta=0.01)
        self.assertGreater(ten, 0.9)
        self.assertLess(ten, 1.0)

    def test_no_behavior_returns_base(self):
        p = build_profile({'user_id': 'u', 'role': '', 'mfr_interests': {'MFR_SEC': 0.4}}, [], now=NOW)
        self.assertEqual(p.mfr_interests, {'MFR_SEC': 0.4})
        self.assertEqual(p.device_interests, {})


class BehaviorApiTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.client = TestClient(create_app(Path(tmp.name) / 'test.sqlite3'))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_predict_registers_user_and_behavior_updates_profile(self):
        self.assertEqual(self.client.post('/predict', json=REQUEST).status_code, 200)
        users = self.client.get('/users').json()
        self.assertEqual([u['user_id'] for u in users], ['demo-user'])
        before = self.client.get('/users/demo-user/profile').json()
        self.assertFalse(before['cached'])
        self.assertTrue(self.client.get('/users/demo-user/profile').json()['cached'])
        self.assertNotIn('KW_BEARING', before['profile']['keyword_interests'])

        # Tags are derived from the order's stored prediction when not supplied.
        b = self.client.post('/behaviors', json={'user_id': 'demo-user', 'action_type': 'detail',
                                                 'event_id': 'demo-001', 'stay_sec': 60})
        self.assertEqual(b.status_code, 201, b.text)
        self.assertIn('KW_BEARING', [t['code'] for t in b.json()['tags']])
        after = self.client.get('/users/demo-user/profile').json()
        self.assertFalse(after['cached'])  # behavior invalidated cache
        self.assertEqual(after['behavior_count'], 1)
        self.assertAlmostEqual(after['profile']['keyword_interests']['KW_BEARING'], 1 - math.exp(-2 * 1.41 / 8), delta=0.01)
        self.assertEqual(len(self.client.get('/users/demo-user/behaviors').json()), 1)

        # Old behaviour outside the window is stored but not used.
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        self.client.post('/behaviors', json={'user_id': 'demo-user', 'action_type': 'query',
                                             'tags': [{'code': 'MFR_SEC'}], 'occurred_at': old})
        rebuilt = self.client.post('/users/demo-user/profile/rebuild').json()
        self.assertEqual(rebuilt['behavior_count'], 1)
        self.assertEqual(len(self.client.get('/users/demo-user/behaviors?days=60').json()), 2)

    def test_predict_by_user_id_and_push_run(self):
        self.client.put('/users/u1', json={'role': '汽轮机专工', 'responsible_units': ['#2'],
                                           'device_interests': {'TURBINE': 1.0}})
        order = dict(REQUEST['order'], level='一般', unit_no='#1')
        first = self.client.post('/predict', json={'order': order, 'user_id': 'u1'})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.client.post('/predict', json={'order': order}).status_code, 422)
        self.assertEqual(self.client.post('/predict', json={**REQUEST, 'user_id': 'u1'}).status_code, 422)
        self.assertEqual(self.client.post('/predict', json={'order': order, 'user_id': 'nobody'}).status_code, 404)

        run = self.client.post('/push/run', json={'user_id': 'u1'}).json()
        self.assertEqual(run['users'][0], {'user_id': 'u1', 'scored': 1, 'saved': 0,
                                           'unchanged': 1, 'above_threshold': 1})
        # Taking responsibility for #1 changes the role dimension -> new prediction saved.
        self.client.put('/users/u1', json={'role': '汽轮机专工', 'responsible_units': ['#1'],
                                           'device_interests': {'TURBINE': 1.0}})
        run = self.client.post('/push/run', json={'user_id': 'u1', 'threshold': 0.99}).json()
        self.assertEqual(run['users'][0]['saved'], 1)
        self.assertEqual(run['users'][0]['above_threshold'], 0)
        row = self.client.get('/orders?user_id=u1').json()['items'][0]
        self.assertEqual(len(row['history']), 2)
        self.assertEqual(row['latest_prediction']['breakdown']['role'], 1.0)
        self.assertEqual(row['effective_result']['review_status'], 'pending')

        # A second user gets the same stored orders pushed.
        self.client.post('/users', json={'user_id': 'u2', 'role': '锅炉专工'})
        run = self.client.post('/push/run', json={}).json()
        self.assertEqual({u['user_id']: u['saved'] for u in run['users']}, {'u1': 0, 'u2': 1})

    def test_validation(self):
        self.assertEqual(self.client.post('/behaviors', json={'user_id': 'x', 'action_type': 'query'}).status_code, 404)
        self.client.post('/users', json={'user_id': 'x'})
        self.assertEqual(self.client.post('/behaviors', json={'user_id': 'x', 'action_type': 'jump'}).status_code, 422)
        self.assertEqual(self.client.post('/behaviors', json={'user_id': 'x', 'action_type': 'detail',
                                                              'stay_sec': -1}).status_code, 422)
        self.assertEqual(self.client.put('/users/x', json={'device_interests': {'A': 2}}).status_code, 422)
        self.assertEqual(self.client.get('/users/missing/profile').status_code, 404)
        # POST /users never overwrites an existing user.
        self.client.post('/users', json={'user_id': 'x', 'role': '锅炉专工'})
        self.assertEqual(self.client.get('/users/x').json()['role'], '')


if __name__ == '__main__':
    unittest.main()
