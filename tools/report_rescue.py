"""Validate generated-code repairs in a copy, then publish against the exact base."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SOURCE_FILES = {
    "tools/weekend_report.py",
    "tools/build_archive.py",
    "tools/report_charts.js",
    "tools/report_charts.css",
    "tools/race_events.py",
    "tools/wec_report.py",
    "tools/build_portal.py",
}


def command(root, args, include_stderr=False, **kwargs):
    result = subprocess.run(
        args, cwd=root, text=True, capture_output=True, check=True, **kwargs
    )
    return result.stdout + (result.stderr if include_stderr else "")


def patch_paths(root, patch):
    stats = command(root, ["git", "apply", "--numstat", "-z", str(patch)])
    return [item.split("\t", 2)[2] for item in stats.split("\0") if item]


def allowed_output(path):
    return (
        path in SOURCE_FILES
        or path
        in {
            "reports/index.html",
            "reports/current-year.html",
            "reports/f1.html",
            "reports/wec/index.html",
            "reports/catalog/archive-index.json",
        }
        or bool(
            re.fullmatch(
                r"reports/weekend-\d+/weekend-report\.html|"
                r"reports/wec/\d{4}/[0-9a-f]{16}/report\.html|"
                r"reports/wec/\d{4}/event-[0-9a-f]{16}/index\.html",
                path,
            )
        )
    )


def save_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def prepare(root, patch_text, output):
    """The original checkout is never modified, even if code/tests/rendering fail."""
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    validated = output / "validated-rescue.patch"
    validated.unlink(missing_ok=True)
    (output / "validated-rescue.json").unlink(missing_ok=True)
    if not patch_text.strip():
        return {"status": "no_changes"}
    proposal = output / "proposed-rescue.patch"
    proposal.write_text(patch_text, encoding="utf-8")
    try:
        paths = patch_paths(root, proposal)
        if not paths or any(path not in SOURCE_FILES for path in paths):
            return {"status": "rejected", "reason": "outside_report_generator_scope"}
        if any(
            (root / path).is_symlink() or not (root / path).is_file() for path in paths
        ):
            return {"status": "rejected", "reason": "invalid_source_file"}
        command(root, ["git", "diff", "--quiet", "HEAD", "--", "tools", "reports"])
        base = command(root, ["git", "rev-parse", "HEAD"]).strip()
        with tempfile.TemporaryDirectory(prefix="f1-rescue-") as folder:
            candidate = Path(folder) / "candidate"
            shutil.copytree(
                root,
                candidate,
                ignore=shutil.ignore_patterns(
                    ".git",
                    ".venv",
                    "node_modules",
                    "__pycache__",
                    ".pytest_cache",
                    ".claude",
                    ".codex",
                    ".agents",
                    ".env",
                    ".env.*",
                ),
            )
            command(candidate, ["git", "init", "-q"])
            command(candidate, ["git", "add", "--all"])
            command(candidate, ["git", "apply", "--check", str(proposal)])
            command(candidate, ["git", "apply", str(proposal)])
            # Never pass service credentials to modified generation code or tests.
            env = {
                k: v
                for k, v in os.environ.items()
                if k
                not in {
                    "CLAUDE_CODE_OAUTH_TOKEN",
                    "CLAUDE_CONFIG_DIR",
                    "ANTHROPIC_API_KEY",
                    "GITHUB_TOKEN",
                    "GH_TOKEN",
                    "OPENF1_CLIENT_SECRET",
                    "OPENF1_CLIENT_ID",
                }
            }
            log = command(
                candidate,
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tools",
                    "-p",
                    "test_*.py",
                ],
                env=env,
                include_stderr=True,
            )
            if "tools/report_charts.js" in paths:
                log += command(
                    candidate, ["node", "--check", "tools/report_charts.js"], env=env
                )
            log += command(
                candidate,
                [sys.executable, str(Path(__file__).with_name("rebuild_reports.py"))],
                env=env,
            )
            (output / "validation.log").write_text(log, encoding="utf-8")
            untracked = command(
                candidate, ["git", "ls-files", "--others", "--exclude-standard"]
            ).splitlines()
            if any(not allowed_output(path) for path in untracked):
                return {"status": "rejected", "reason": "unexpected_generated_files"}
            if untracked:
                command(candidate, ["git", "add", "-N", "--", *untracked])
            changed = command(candidate, ["git", "diff", "--name-only"]).splitlines()
            if any(not allowed_output(path) for path in changed):
                return {
                    "status": "rejected",
                    "reason": "raw_data_or_unrelated_files_changed",
                    "blocked_files": [
                        path for path in changed if not allowed_output(path)
                    ],
                }
            if any(
                (candidate / path).is_symlink() or not (candidate / path).is_file()
                for path in changed
            ):
                return {"status": "rejected", "reason": "deleted_or_symbolic_files"}
            if "mode change" in command(candidate, ["git", "diff", "--summary"]):
                return {"status": "rejected", "reason": "file_mode_changed"}
            command(candidate, ["git", "diff", "--check"])
            patch = command(candidate, ["git", "diff", "--binary"])
            validated.write_text(patch, encoding="utf-8")
        result = {
            "status": "validated",
            "base_sha": base,
            "sha256": hashlib.sha256(validated.read_bytes()).hexdigest(),
            "changed_files": changed,
        }
        save_json(output / "validated-rescue.json", result)
        return result
    except subprocess.CalledProcessError as error:
        (output / "validation.log").write_text(
            (error.stdout or "") + (error.stderr or ""), encoding="utf-8"
        )
        return {"status": "rejected", "reason": "validation_failed"}
    except (OSError, ValueError, IndexError):
        return {"status": "rejected", "reason": "validation_failed"}


def publish(root, output, base_sha):
    """Reject stale fixes; never force-push or replace a newer report."""
    root, output = Path(root).resolve(), Path(output).resolve()
    try:
        manifest = json.loads(
            (output / "validated-rescue.json").read_text(encoding="utf-8")
        )
        patch = output / "validated-rescue.patch"
        if (
            manifest.get("status") != "validated"
            or manifest.get("base_sha") != base_sha
        ):
            return {"status": "rejected", "reason": "invalid_validation_manifest"}
        if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest.get("sha256"):
            return {"status": "rejected", "reason": "patch_checksum_mismatch"}
        if command(root, ["git", "rev-parse", "HEAD"]).strip() != base_sha:
            return {"status": "rejected", "reason": "checkout_base_mismatch"}
        command(root, ["git", "fetch", "origin", "main"])
        if command(root, ["git", "rev-parse", "FETCH_HEAD"]).strip() != base_sha:
            return {"status": "skipped", "reason": "newer_reports_already_published"}
        paths = patch_paths(root, patch)
        if not paths or any(not allowed_output(path) for path in paths):
            return {"status": "rejected", "reason": "unexpected_patch_files"}
        command(root, ["git", "diff", "--quiet", "HEAD"])
        command(root, ["git", "apply", "--check", str(patch)])
        command(root, ["git", "apply", str(patch)])
        command(root, ["git", "config", "user.name", "github-actions[bot]"])
        command(
            root,
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
        )
        command(root, ["git", "add", "--", *paths])
        command(
            root,
            [
                "git",
                "commit",
                "-m",
                "Apply validated Claude rescue to motorsport reports",
            ],
        )
        command(root, ["git", "push", "origin", "HEAD:main"])
        return {
            "status": "applied",
            "commit": command(root, ["git", "rev-parse", "HEAD"]).strip(),
        }
    except (OSError, ValueError, IndexError, subprocess.CalledProcessError):
        return {"status": "failed", "reason": "publish_failed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    result = publish(Path.cwd(), args.output_dir, args.base_sha)
    save_json(args.output_dir / "publish-status.json", result)
    print("Claude rescue publication: " + result["status"])


if __name__ == "__main__":
    main()
