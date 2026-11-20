import unittest
from wrc_insights import render, duration


class WrcInsightTests(unittest.TestCase):
    entries = [dict(entryId=i, identifier=str(i), driver={'fullName': 'Driver'},
                    codriver={'fullName': '<Co>'}) for i in (1, 2)]

    def test_stage_versus_cumulative_and_interrupted(self):
        rows = [dict(entryId=1, status='Completed', elapsedDurationMs=121400, diffFirstMs=0),
                dict(entryId=2, status='Completed', elapsedDurationMs=122200, diffFirstMs=800)]
        output = render('Rally', 'SS2', 'stage', rows, self.entries,
                        [dict(entryId=2, totalTimeMs=900000)], dict(distance=2, status='Interrupted'))
        for text in ['2분 1.400초', '0.800초', '60.700초/km', '다른 크루', '중단 상태', '&lt;Co&gt;']:
            self.assertIn(text, output)
        self.assertNotIn('<Co>', output)

    def test_daily_inconsistency_is_not_silently_corrected(self):
        rows = [dict(entryId=1, stageTimeMs=100000, penaltyTimeMs=10000,
                     totalTimeMs=100000, diffFirstMs=0)]
        output = render('Rally', 'Day1', 'day', rows, self.entries)
        self.assertIn('1분 50.000초', output)
        self.assertIn('원본 총 시간은 1분 40.000초', output)
        self.assertIn('페널티 반영 최종 순위로 단정하지 않습니다', output)

    def test_final_gap_and_penalty(self):
        rows = [dict(entryId=1, stageTimeMs=100000, penaltyTimeMs=0, totalTimeMs=100000, diffFirstMs=0),
                dict(entryId=2, stageTimeMs=100000, penaltyTimeMs=10000, totalTimeMs=110000, diffFirstMs=10000)]
        output = render('Rally', 'Final', 'final', rows, self.entries)
        self.assertIn('각 SS마다', output)
        self.assertIn('페널티 계산의 실제 예', output)

    def test_shakedown_and_missing_data(self):
        output = render('Rally', 'SD', 'shakedown', [dict(entryId=1, best=60123)], self.entries)
        self.assertIn('1분 0.123초', output)
        self.assertIn('계산 정렬', output)
        self.assertIn('공식 시간 기록이 없습니다', render('Rally', 'SS', 'stage', [], []))
        self.assertEqual(duration(None), '미제공')


if __name__ == '__main__':
    unittest.main()
