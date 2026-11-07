import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import build_archive
import weekend_report as report
from test_weekend_report import snapshot


class ArchiveTests(unittest.TestCase):
    def test_accumulation_and_catalog_missing_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = snapshot("Practice 1")
            item["session"].update(
                year=2025, country_name="Australia", location="Melbourne"
            )
            missing = dict(item["session"], session_key=3, session_name="Practice 2")
            report.save_json(
                root / "catalog" / "sessions.json", [item["session"], missing]
            )
            report.save_json(root / "weekend-2" / "data" / "1.json", item)
            original = (root / "weekend-2" / "data" / "1.json").read_bytes()
            build_archive.build(root)
            text = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn("호주 그랑프리", text)
            self.assertNotIn("ARCHIVE_DATA", text)
            entries = json.loads(
                text.split("const entries=", 1)[1].split(";const year=", 1)[0]
            )
            downloaded = next(e for e in entries if e["key"] == 1)
            html = gzip.decompress(base64.b64decode(downloaded["payload"])).decode()
            self.assertIn("2025 호주 그랑프리", html)
            self.assertIsNone(next(e for e in entries if e["key"] == 3)["payload"])
            build_archive.build(root)
            self.assertEqual(
                (root / "weekend-2" / "data" / "1.json").read_bytes(), original
            )
