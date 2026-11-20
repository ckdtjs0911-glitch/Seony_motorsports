import unittest

from wec_insights import prepare, comparison_stats, render, seconds


class InsightTests(unittest.TestCase):
    def row(self, number, lap, elapsed, value=90, **extra):
        return dict(NUMBER=number, LAP_NUMBER=str(lap), ELAPSED=elapsed,
                    DRIVER_NAME='A', CLASS='HYPERCAR', TEAM='Team', seconds=value,
                    pace_eligible=lap > 1, pit_in=False, pit_seconds=None,
                    FLAG_AT_FL='GF', **extra)

    def test_same_time_window_is_not_same_lap_number(self):
        cars = prepare([self.row('7', 2, '3:00', 90), self.row('7', 3, '4:30', 91),
                        self.row('007', 5, '3:05', 95), self.row('007', 6, '4:40', 97)])
        self.assertEqual([c['number'] for c in cars], ['7', '007'])
        a, b = [comparison_stats(c, 3, 4) for c in cars]
        self.assertEqual((a['n'], a['median']), (1, 90))
        self.assertEqual((b['n'], b['median']), (1, 95))

    def test_outlap_without_pit_time_and_missing_elapsed(self):
        rows = [self.row('1', 2, '3:00'), self.row('1', 3, '4:30'),
                self.row('1', 4, '6:00'), self.row('1', 5, '')]
        rows[1]['pit_in'] = True
        rows[1]['pace_eligible'] = False
        car = prepare(rows)[0]
        self.assertFalse(car['points'][2]['eligible'])
        self.assertEqual(car['points'][2]['segment'], 2)
        self.assertEqual(comparison_stats(car)['n'], 1)
        self.assertIsNone(car['points'][3]['t'])

    def test_driver_change_starts_relative_lap_and_keeps_missing_lap_gap(self):
        rows = [self.row('1', 2, '3:00'), self.row('1', 4, '6:00'), self.row('1', 5, '7:30')]
        rows[2]['DRIVER_NAME'] = 'B'
        car = prepare(rows)[0]
        self.assertEqual([p['relative'] for p in car['points']], [1, 3, 1])
        self.assertEqual(car['driver_changes'], 1)
        self.assertEqual(comparison_stats(car, segment=2)['n'], 1)

    def test_race_class_gap_and_unsafe_html(self):
        results = [dict(NUMBER='7', CLASS='HYPERCAR', TEAM='<script>', STATUS='Classified', LAPS='100', TIME="6:00'00.000"),
                   dict(NUMBER='007', CLASS='HYPERCAR', TEAM='B', STATUS='Classified', LAPS='100', TIME="6:00'05.607")]
        output = render({'session': '202611081100_Race'}, [self.row('7', 2, '3:00')], results)
        self.assertIn('5.607초', output)
        self.assertIn('CHAPTER 00', output)
        self.assertNotIn('TEAM":"<script>', output)
        self.assertIn('&lt;script&gt;', output)
        self.assertEqual(seconds("6:01'33.199"), 21693.199)


if __name__ == '__main__':
    unittest.main()
