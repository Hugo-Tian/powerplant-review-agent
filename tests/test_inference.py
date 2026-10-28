import unittest

from core.inference import PushPredictor, UserProfile, WorkOrder
from core.matching import MatchingEngine


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.profile = UserProfile('demo', '汽轮机专工', ['#1'],
                                   {'TURBINE': 1.0}, {}, {}, {}, [])

    def test_existing_formula(self):
        tags = [dict(code='TURBINE', name='汽轮机', category='device_type', confidence=0.95)]
        result = PushPredictor(text_enabled=False).predict(
            WorkOrder('a', '汽轮机检修', '', '一般', '#1'), self.profile, tags=tags)
        self.assertEqual(result['score'], 0.5325)
        self.assertEqual(result['push_type'], 'personal')
        self.assertIsNone(result['confidence'])

    def test_emergency_floor_without_tags(self):
        result = MatchingEngine().score('a', self.profile, [], None, '紧急')
        self.assertEqual(result.score, 0.75)
        self.assertEqual(result.push_type, 'emergency')

    def test_manufacturer_bonus(self):
        self.profile.mfr_interests = {'MFR_DFST': 1}
        tags = [dict(code='MFR_DFST', name='东方汽轮机', category='manufacturer', confidence=1)]
        result = MatchingEngine().score('a', self.profile, tags, None, '一般')
        self.assertEqual(result.score, 0.3)

    def test_raw_text_ranking(self):
        predictor = PushPredictor()
        orders = [WorkOrder('low', '例行记录', '无新增事项', '一般'),
                  WorkOrder('high', '汽轮机振动超标', '东方汽轮机轴承检查', '紧急', '#1')]
        results = predictor.rank(orders, self.profile)
        self.assertEqual([r['event_id'] for r in results], ['high', 'low'])
        self.assertTrue(results[0]['tags'])
        self.assertEqual(results[0]['rank'], 1)
        self.assertEqual(predictor.rank(orders, self.profile, limit=0), [])
        self.assertEqual(len(predictor.rank(orders, self.profile, threshold=0.75)), 1)
        self.assertEqual(results, predictor.rank(orders, self.profile))


if __name__ == '__main__':
    unittest.main()
