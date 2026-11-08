import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import claude_report_review as review


class ClaudeReportReviewTests(unittest.TestCase):
    def run_review(self, responses=None, authenticated=True):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        output = Path(folder.name)
        with patch.dict("os.environ", {}, clear=True), patch.object(
            review, "changed_reports", return_value=["reports/weekend-1/data/2.json"]
        ), patch.object(
            review.shutil, "which", return_value="/bin/claude"
        ), patch.object(
            review.subprocess, "run", side_effect=responses
        ) as run:
            status = review.run_reviews(".", output, local_login=authenticated)
        self.assertEqual(json.loads((output / "status.json").read_text()), status)
        return status, output, run

    def test_missing_auth_does_not_call_claude_or_block_reports(self):
        status, _, run = self.run_review(authenticated=False)
        run.assert_not_called()
        for item in status["reviews"].values():
            self.assertEqual(
                item, {"status": "skipped", "reason": "missing_claude_auth"}
            )

    def test_first_failure_still_runs_second_review_without_saving_diagnostics(self):
        responses = [
            subprocess.CompletedProcess([], 1, "sensitive diagnostic", "secret"),
            subprocess.CompletedProcess([], 0, '{"result":"검토 완료"}'),
        ]
        status, output, run = self.run_review(responses)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(status["reviews"]["review"]["status"], "failed")
        self.assertEqual(status["reviews"]["rescue"]["status"], "completed")
        self.assertEqual((output / "rescue.md").read_text(), "검토 완료\n")
        self.assertIn("일반 검토 결과가 없어", run.call_args_list[1].kwargs["input"])
        self.assertNotIn("sensitive", (output / "status.json").read_text())
        for call in run.call_args_list:
            command = call.args[0]
            self.assertIn("Read,Glob,Grep", command)
            self.assertIn("mcp__*", command)
            self.assertIn("--strict-mcp-config", command)
            self.assertNotIn("--dangerously-skip-permissions", command)

    def test_api_error_is_never_recorded_as_success(self):
        response = subprocess.CompletedProcess(
            [], 0, '{"is_error":true,"result":"secret error"}'
        )
        status, output, _ = self.run_review([response, response])
        self.assertTrue(
            all(x["status"] == "failed" for x in status["reviews"].values())
        )
        self.assertEqual(list(output.glob("*.md")), [])

    def test_rescue_receives_review_findings_and_obsolete_stage_is_not_run(self):
        response = subprocess.CompletedProcess([], 0, '{"result":"실제 발견사항"}')
        status, output, run = self.run_review([response, response])
        self.assertEqual(list(status["reviews"]), ["review", "rescue"])
        prompt = run.call_args_list[1].kwargs["input"]
        self.assertIn("실제 발견사항", prompt)
        self.assertIn("unified diff", prompt)
        self.assertNotIn("adversarial-review", prompt)
        self.assertTrue((output / "rescue.md").exists())

    def test_automatic_mode_validates_structured_patch_and_records_result(self):
        responses = [
            subprocess.CompletedProcess([], 0, '{"result":"발견사항"}'),
            subprocess.CompletedProcess(
                [],
                0,
                json.dumps(
                    {"structured_output": {"summary": "수정", "patch": "diff patch"}}
                ),
            ),
        ]
        with tempfile.TemporaryDirectory() as folder, patch.object(
            review, "changed_reports", return_value=["reports/index.html"]
        ), patch.object(review.shutil, "which", return_value="claude"), patch.object(
            review.subprocess, "run", side_effect=responses
        ) as run, patch.object(
            review, "prepare", return_value={"status": "validated"}
        ) as prepare:
            status = review.run_reviews(
                ".", folder, local_login=True, apply=True, compare_ref="base"
            )
            self.assertEqual(status["repair"]["status"], "validated")
            self.assertEqual(prepare.call_args.args[1], "diff patch")
            self.assertIn("--json-schema", run.call_args_list[1].args[0])

    def test_old_reviews_are_removed_when_new_run_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            for mode in review.MODES:
                (output / f"{mode}.md").write_text("outdated review")
            (output / "adversarial-review.md").write_text("obsolete stage")
            with patch.object(review, "changed_reports", return_value=[]):
                status = review.run_reviews(".", output)
            self.assertEqual(list(output.glob("*.md")), [])
            self.assertTrue(
                all(
                    x["reason"] == "no_changed_reports"
                    for x in status["reviews"].values()
                )
            )


class ClaudeComparisonFailureTests(unittest.TestCase):
    def test_git_failure_is_recorded_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            review,
            "changed_reports",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            status = review.run_reviews(".", folder)
            self.assertTrue((Path(folder) / "status.json").exists())
            self.assertTrue(
                all(x["status"] == "failed" for x in status["reviews"].values())
            )

    def test_error_categories_do_not_include_raw_error_or_token(self):
        for error, expected in (
            ("API Error: 401 token-secret-value", "claude_authentication_failed"),
            ("You've hit your limit token-secret-value", "claude_usage_limit"),
            ("API Error: 403 token-secret-value", "claude_access_denied"),
            ("model_not_found token-secret-value", "claude_model_unavailable"),
            ("Connection error token-secret-value", "claude_connection_failed"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(review.failure_reason(error), expected)
                self.assertNotIn("token-secret-value", review.failure_reason(error))


if __name__ == "__main__":
    unittest.main()
