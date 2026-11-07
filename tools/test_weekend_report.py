"""Offline behavioral checks for report generation and collection failures."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import weekend_report as report


def snapshot(name="Qualifying"):
    return {
        "session": {
            "session_name": name,
            "session_key": 1,
            "meeting_key": 2,
            "date_start": "2025-01-01T12:00:00+00:00",
            "date_end": "2025-01-01T13:00:00+00:00",
        },
        "status": "test",
        "data": {
            "drivers": [
                {"driver_number": 1, "full_name": "Test <Driver>", "team_name": "Team"},
                {"driver_number": 2, "full_name": "No laps", "team_name": "Team"},
            ],
            "session_result": [
                {"driver_number": 1, "position": 1, "duration": [82.1, 81.2, 80.3]},
                {"driver_number": 2, "position": None, "dns": True},
            ],
            "laps": [
                {
                    "driver_number": 1,
                    "lap_number": 2,
                    "lap_duration": 80.0,
                    "date_start": "2025-01-01T12:10:00+00:00",
                },
                {
                    "driver_number": 1,
                    "lap_number": 3,
                    "lap_duration": 82.0,
                    "date_start": "2025-01-01T12:12:00+00:00",
                },
            ],
            "race_control": [
                {"message": "CAR 1 (TST) TIME 1:20.000 DELETED - TRACK LIMITS LAP 2"}
            ],
            "stints": [],
            "pit": [],
        },
    }


class ReportTests(unittest.TestCase):
    def test_tyre_mapping_boundaries_missing_and_conflicts(self):
        stints = [
            {"lap_start": 1, "lap_end": 5, "compound": "SOFT"},
            {"lap_start": 5, "lap_end": 10, "compound": "MEDIUM"},
            {"lap_start": 11, "lap_end": None, "compound": "HARD"},
        ]
        self.assertEqual(report.tyre_for_lap(stints, 1), "SOFT")
        self.assertEqual(report.tyre_for_lap(stints, 5), "UNKNOWN")
        self.assertEqual(report.tyre_for_lap(stints, 6), "MEDIUM")
        self.assertEqual(report.tyre_for_lap(stints, 10), "MEDIUM")
        self.assertEqual(report.tyre_for_lap(stints, 11), "UNKNOWN")

    def test_chart_laps_include_tyre_and_all_drivers_get_verdict(self):
        item = snapshot()
        item["data"]["stints"] = [
            {
                "driver_number": 1,
                "stint_number": 1,
                "lap_start": 1,
                "lap_end": 3,
                "compound": "SOFT",
            }
        ]
        rows = report.summarize(item)
        self.assertEqual(rows[0]["laps"][0]["tyre"], "SOFT")
        text = report.render_verdicts("Qualifying", rows)
        self.assertEqual(text.count("<tr data-search="), 2)
        self.assertIn("DNS", text)
        self.assertIn("1:22.000", text)

    def test_sector_values_and_missing_sectors_are_preserved(self):
        item = snapshot()
        item["data"]["laps"][0].update(
            duration_sector_1=18.926,
            duration_sector_2=35.123,
            duration_sector_3=None,
        )
        lap = report.summarize(item)[0]["laps"][0]
        self.assertEqual(lap["s1"], 18.926)
        self.assertEqual(lap["s2"], 35.123)
        self.assertIsNone(lap["s3"])

    def test_all_drivers_and_deleted_laps(self):
        rows = report.summarize(snapshot())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fastest"], 82.0)
        self.assertEqual(rows[0]["median"], 82.0)
        self.assertEqual(rows[1]["status"], "DNS")
        self.assertIsNone(rows[1]["fastest"])

    def test_qualifying_uses_official_phase_array(self):
        row = report.summarize(snapshot())[0]
        self.assertEqual(row["q"], [82.1, 81.2, 80.3])
        item = snapshot()
        item["data"]["session_result"][0]["duration"] = 80.3
        self.assertEqual(report.summarize(item)[0]["q"], [None, None, None])

    def test_stint_sample_excludes_pit_entry(self):
        item = snapshot()
        item["data"]["stints"] = [
            {
                "driver_number": 1,
                "stint_number": 1,
                "lap_start": 1,
                "lap_end": 3,
                "compound": "MEDIUM",
            }
        ]
        item["data"]["pit"] = [
            {"driver_number": 1, "lap_number": 3, "date": "2025-01-01T12:12:05+00:00"}
        ]
        row = report.summarize(item)[0]
        self.assertEqual(row["pits"], 1)
        self.assertEqual(row["stints"][0]["sample_count"], 0)
        self.assertIsNone(row["median"])

    def test_html_escapes_names_and_embeds_chart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.html"
            report.render([snapshot()], path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("Test &lt;Driver&gt;", text)
            self.assertIn("1:20.300", text)
            self.assertNotIn("@@", text)
            self.assertIn('id="chart-time"', text)
            self.assertNotIn("REPORT_ROWS", text)

    def test_failed_refresh_preserves_last_success(self):
        item = snapshot()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "weekend-2" / "data" / "1.json"
            report.save_json(path, item)
            before = path.read_bytes()
            with patch.object(
                report,
                "fetch",
                side_effect=[[item["session"]], requests.ConnectionError("offline")],
            ):
                code = report.collect(2, root)
            self.assertEqual(code, 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn(
                "갱신 실패",
                (root / "weekend-2" / "weekend-report.html").read_text(
                    encoding="utf-8"
                ),
            )

    def test_empty_results_are_retried_not_saved(self):
        item = snapshot()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def fetch(endpoint, params):
                return (
                    [item["session"]]
                    if endpoint == "sessions"
                    else item["data"].get(endpoint, [])
                    if endpoint != "session_result"
                    else []
                )

            with patch.object(report, "fetch", side_effect=fetch):
                self.assertEqual(report.collect(2, root), 1)
            self.assertFalse((root / "weekend-2" / "data" / "1.json").exists())

    def test_non_ascii_names_round_trip_as_utf8(self):
        item = snapshot()
        item["data"]["drivers"][0]["full_name"] = "Sergio Pérez — 세르히오"
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report.save_json(root / "data" / "1.json", item)
            self.assertEqual(report.load_json(root / "data" / "1.json"), item)
            report.render(report.load_offline(root), root / "report.html")
            text = (root / "report.html").read_bytes().decode("utf-8")
            self.assertIn("Sergio Pérez — 세르히오", text)

    def test_null_race_control_message_is_ignored(self):
        item = snapshot()
        item["data"]["race_control"].append({"message": None})
        self.assertEqual(report.summarize(item)[0]["fastest"], 82.0)

    def test_timestamps_are_shown_in_readable_utc(self):
        self.assertEqual(
            report.display_time("2026-11-06T23:14:26.123+00:00"),
            "2026-11-06 23:14 UTC",
        )
        self.assertEqual(report.display_time("미기록"), "미기록")


if __name__ == "__main__":
    unittest.main()
