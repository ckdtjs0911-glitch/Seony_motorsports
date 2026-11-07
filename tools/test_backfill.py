import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backfill_openf1 as backfill
import weekend_report as report
from test_weekend_report import snapshot


class BackfillTests(unittest.TestCase):
    def test_resume_reuses_verified_compressed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reports = root / "reports"
            item = snapshot("Practice 1")
            item["session"].update(
                year=2025, country_name="Australia", location="Melbourne"
            )
            report.save_json(reports / "catalog" / "sessions.json", [item["session"]])
            report.save_json(reports / "catalog" / "meetings.json", [])

            def fetch(endpoint, params):
                return item["data"].get(endpoint, [])

            with patch.object(report, "fetch", side_effect=fetch) as api:
                backfill.run(root / "raw", reports)
                self.assertTrue(
                    any(c.args[0] == "car_data" for c in api.call_args_list)
                )
                self.assertTrue(
                    any(c.args[0] == "location" for c in api.call_args_list)
                )
            with patch.object(report, "fetch") as api:
                backfill.run(root / "raw", reports)
                api.assert_not_called()
            self.assertTrue((root / "raw" / "1" / "car_data-driver-1.json.gz").exists())
            self.assertTrue((reports / "weekend-2" / "data" / "1.json").exists())
