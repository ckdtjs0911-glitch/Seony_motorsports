import unittest

from race_events import event_label, race_events, render_race_events
from test_weekend_report import snapshot
import weekend_report as report


class RaceEventTests(unittest.TestCase):
    def test_flag_and_safety_labels(self):
        for record, label in [
            ({"flag": "RED"}, "레드 플래그"),
            ({"flag": "DOUBLE_YELLOW"}, "더블 옐로 플래그"),
            ({"flag": "YELLOW"}, "옐로 플래그"),
            ({"message": "SAFETY CAR DEPLOYED"}, "세이프티카 투입"),
            ({"message": "VIRTUAL SAFETY CAR ENDING"}, "VSC 종료 예고"),
            ({"message": "SAFETY CAR IN THIS LAP"}, "SC 철수 예고"),
            ({"message": "RACE WILL RESUME AT 15:45"}, "재출발 예정"),
            ({"message": "RESUMPTION ORDER: 1, 2"}, "재출발 순서 안내"),
        ]:
            self.assertEqual(event_label(record), label)
        self.assertIsNone(event_label({"message": None}))
        self.assertIsNone(event_label({"flag": "GREEN", "scope": "Sector"}))

    def test_only_race_and_observed_race_window(self):
        item = snapshot("Race")
        item["data"]["race_control"] = [
            {"date": "2024-12-31T12:11:00+00:00", "flag": "RED"},
            {
                "date": "2025-01-01T12:11:00+00:00",
                "flag": "YELLOW",
                "message": "YELLOW",
            },
        ]
        self.assertEqual(len(race_events(item)), 1)
        self.assertEqual(race_events(snapshot("Practice 1")), [])
        self.assertEqual(render_race_events(snapshot(), []), "")

    def test_retirements_use_result_not_missing_laps(self):
        item = snapshot("Race")
        item["data"]["session_result"][0].update(dnf=True, number_of_laps=3)
        page = render_race_events(item, report.summarize(item))
        self.assertIn("DNF", page)
        self.assertIn("DNS", page)
        self.assertIn("미확인", page)
        self.assertIn("Test &lt;Driver&gt;", page)
        self.assertNotIn("RETIRED LAP 3", page)


if __name__ == "__main__":
    unittest.main()
