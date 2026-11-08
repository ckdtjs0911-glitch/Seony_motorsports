"""Regenerate F1, WEC and the portal from saved records without collecting data."""

import json
import sys
from pathlib import Path


def rebuild(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / "tools"))
    reports = root / "reports"
    directories = [
        directory
        for directory in sorted(reports.glob("weekend-*"))
        if any((directory / "data").glob("*.json"))
    ]
    if directories:
        import weekend_report as f1
        import build_archive

        for directory in directories:
            f1.render(f1.load_offline(directory), directory / "weekend-report.html")
        build_archive.build(reports)

    wec_root = reports / "wec"
    sources = sorted(wec_root.glob("[0-9][0-9][0-9][0-9]/*/source.json"))
    if sources:
        import wec_report as wec

        for source in sources:
            entry = json.loads(source.read_text(encoding="utf-8"))
            directory = source.parent
            rows = json.loads((directory / "laps.json").read_text(encoding="utf-8"))
            classification_file = directory / "classification.csv"
            classification = (
                wec.parse_classification(classification_file.read_bytes())
                if classification_file.exists()
                else None
            )
            wec.write(
                directory / "report.html",
                wec.render(entry, rows, entry["files"], classification),
            )
        wec.build_index(wec_root)

    if (root / "tools" / "build_portal.py").exists():
        import build_portal

        build_portal.build()


if __name__ == "__main__":
    rebuild(Path.cwd())
