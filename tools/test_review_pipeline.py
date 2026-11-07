"""Checks for provider orchestration, data protection and fail-closed promotion."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import review_pipeline as pipeline
import weekend_report as report
from test_weekend_report import snapshot


class PipelineTests(unittest.TestCase):
    def test_optional_missing_keys_promotes_base_without_provider_calls(self):
        self.check_optional_fallback(missing=True)

    def test_optional_provider_failure_promotes_base_without_ai_claim(self):
        self.check_optional_fallback(missing=False)

    def check_optional_fallback(self, missing):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            candidate = root / "staging" / "weekend-2"
            report.save_json(candidate / "data" / "1.json", snapshot())
            report.render(
                report.load_offline(candidate), candidate / "weekend-report.html"
            )
            keys = (
                {}
                if missing
                else {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test"}
            )
            with patch.dict(pipeline.os.environ, keys, clear=True), patch.object(
                pipeline, "claude_call", side_effect=RuntimeError("provider offline")
            ) as provider:
                pipeline.process(root / "staging", root / "reports", optional=True)
                if missing:
                    provider.assert_not_called()
            final_dir = root / "reports" / "weekend-2"
            page = (final_dir / "weekend-report.html").read_text(encoding="utf-8")
            self.assertIn('id="ai-review-status"', page)
            self.assertNotIn('id="ai-editorial"', page)
            self.assertIn('id="chart-time"', page)
            audit = report.load_json(final_dir / "editorial-review.json")
            self.assertIs(audit["approved"], False)
            self.assertEqual(
                audit["status"],
                "skipped_missing_keys" if missing else "failed_optional",
            )

    def setUp(self):
        self.snapshots = [snapshot()]
        self.facts = pipeline.facts_for(self.snapshots)
        self.document = {
            "sentences": [{"id": f["id"], "text": f["template"]} for f in self.facts]
        }
        self.keys = {"openai": "test-key", "anthropic": "test-key"}
        self.models = {"codex": "codex-test", "claude": "claude-test"}

    def test_three_stages_in_order(self):
        events = []

        def codex(key, model, prompt):
            events.append(("codex", prompt["stage"]))
            return dict(self.document, findings=[])

        def claude(key, model, prompt):
            events.append(("claude", prompt["stage"]))
            return dict(self.document, approved=True, findings=[])

        with patch.object(pipeline, "openai_call", side_effect=codex), patch.object(
            pipeline, "claude_call", side_effect=claude
        ):
            audit = pipeline.review(self.snapshots, self.keys, self.models)
        self.assertEqual(
            events,
            [("claude", "draft"), ("codex", "review"), ("claude", "final")],
        )
        self.assertTrue(audit["approved"])
        self.assertIn("codex_review", audit)

    def test_missing_secrets_stop_before_provider(self):
        with patch.object(pipeline, "openai_call") as codex, patch.object(
            pipeline, "claude_call"
        ) as claude:
            with self.assertRaises(RuntimeError):
                pipeline.review(self.snapshots, {}, self.models)
            codex.assert_not_called()
            claude.assert_not_called()

    def test_changed_token_or_new_number_rejected(self):
        for text in [
            "{{session}} 선수는 99명입니다.",
            "{{session}} {{count}} {{count}}",
            "<script>alert(1)</script>",
        ]:
            d = json.loads(json.dumps(self.document))
            d["sentences"][0]["text"] = text
            with self.assertRaises(ValueError):
                pipeline.validate_texts(d, self.facts)

    def test_omitted_or_duplicated_facts_rejected(self):
        for entries in [
            self.document["sentences"][:-1],
            self.document["sentences"] + self.document["sentences"][:1],
        ]:
            with self.assertRaises(ValueError):
                pipeline.validate_texts({"sentences": entries}, self.facts)

    def test_final_rejection_is_not_approved(self):
        with patch.object(
            pipeline, "openai_call", return_value=self.document
        ), patch.object(
            pipeline,
            "claude_call",
            side_effect=[self.document, dict(self.document, approved=False)],
        ):
            with self.assertRaises(ValueError):
                pipeline.review(self.snapshots, self.keys, self.models)

    def run_review(self, codex_output, final_output):
        with patch.object(
            pipeline, "openai_call", return_value=codex_output
        ), patch.object(
            pipeline, "claude_call", side_effect=[self.document, final_output]
        ):
            return pipeline.review(self.snapshots, self.keys, self.models)

    def test_final_approval_must_be_boolean_true(self):
        for approved in ["true", 1, None]:
            final = dict(self.document, approved=approved)
            with self.assertRaises(ValueError):
                self.run_review(self.document, final)

    def test_codex_findings_require_recorded_final_decision(self):
        codex = dict(self.document, findings=["문장 흐름 수정 제안"])
        for final_findings in [None, [], [""], "반영함"]:
            final = dict(self.document, approved=True)
            if final_findings is not None:
                final["findings"] = final_findings
            with self.assertRaises(ValueError):
                self.run_review(codex, final)
        final = dict(self.document, approved=True, findings=["반영: 문장 흐름 수정"])
        self.assertTrue(self.run_review(codex, final)["approved"])

    def test_optional_codex_review_failure_promotes_base(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            candidate = root / "staging" / "weekend-2"
            report.save_json(candidate / "data" / "1.json", snapshot())
            report.render(
                report.load_offline(candidate), candidate / "weekend-report.html"
            )
            with patch.dict(
                pipeline.os.environ,
                {"OPENAI_API_KEY": "test", "ANTHROPIC_API_KEY": "test"},
                clear=True,
            ), patch.object(
                pipeline, "claude_call", return_value=self.document
            ), patch.object(
                pipeline, "openai_call", side_effect=RuntimeError("codex offline")
            ):
                pipeline.process(root / "staging", root / "reports", optional=True)
            final_dir = root / "reports" / "weekend-2"
            page = (final_dir / "weekend-report.html").read_text(encoding="utf-8")
            self.assertNotIn('id="ai-editorial"', page)
            audit = report.load_json(final_dir / "editorial-review.json")
            self.assertEqual(audit["status"], "failed_optional")

    def test_injection_keeps_original_tables_and_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "report.html"
            report.render(self.snapshots, p)
            original = p.read_text(encoding="utf-8")
            final = pipeline.inject(original, {"final": self.document}, self.facts)
            self.assertIn("Test &lt;Driver&gt;", final)
            self.assertIn("2명의", final)
            start = final.index('<section id="ai-editorial">')
            end = final.index("</section>", start) + len("</section>")
            self.assertEqual(final[:start] + final[end:], original)

    def test_provider_error_does_not_replace_previous_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            staging = root / "staging"
            dest = root / "reports"
            candidate = staging / "weekend-2"
            report.save_json(candidate / "data" / "1.json", snapshot())
            report.render(
                report.load_offline(candidate), candidate / "weekend-report.html"
            )
            previous = dest / "weekend-2" / "weekend-report.html"
            previous.parent.mkdir(parents=True)
            previous.write_text("old report")
            with patch.object(
                pipeline, "review", side_effect=RuntimeError("provider offline")
            ):
                with self.assertRaises(RuntimeError):
                    pipeline.process(staging, dest)
            self.assertEqual(previous.read_text(), "old report")

    def test_unchanged_data_reuses_approved_review(self):
        cached = {
            "fingerprint": pipeline.fingerprint(self.snapshots),
            "models": self.models,
            "approved": True,
            "final": self.document,
        }
        with patch.object(pipeline, "openai_call") as call:
            self.assertEqual(
                pipeline.review(self.snapshots, {}, self.models, cached), cached
            )
            call.assert_not_called()

    def test_success_promotes_review_and_preserves_source_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            staging = root / "staging"
            candidate = staging / "weekend-2"
            destination = root / "reports"
            report.save_json(candidate / "data" / "1.json", snapshot())
            report.render(
                report.load_offline(candidate), candidate / "weekend-report.html"
            )
            source_bytes = (candidate / "data" / "1.json").read_bytes()

            def approved(key, model, prompt):
                return {
                    "approved": True,
                    "sentences": [
                        {"id": fact["id"], "text": fact["template"]}
                        for fact in prompt["facts"]
                    ],
                }

            with patch.dict(
                pipeline.os.environ,
                {"OPENAI_API_KEY": "test-key", "ANTHROPIC_API_KEY": "test-key"},
            ), patch.object(
                pipeline, "openai_call", side_effect=approved
            ), patch.object(
                pipeline, "claude_call", side_effect=approved
            ):
                pipeline.process(staging, destination)
            final_dir = destination / "weekend-2"
            self.assertIn(
                'id="ai-editorial"',
                (final_dir / "weekend-report.html").read_text(encoding="utf-8"),
            )
            self.assertEqual((final_dir / "data" / "1.json").read_bytes(), source_bytes)
            self.assertTrue(
                report.load_json(final_dir / "editorial-review.json")["approved"]
            )

    def test_claude_request_opts_into_refusal_fallback(self):
        self.assertEqual(
            set(pipeline.FALLBACK_MODELS),
            {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"},
        )
        response = {
            "stop_reason": "end_turn",
            "content": [
                {"type": "thinking", "thinking": ""},
                {"type": "text", "text": json.dumps(self.document)},
            ],
        }
        with patch.object(pipeline, "post_json", return_value=response) as post:
            for model in pipeline.FALLBACK_MODELS:
                self.assertEqual(pipeline.claude_call("key", model, {}), self.document)
                _, headers, payload = post.call_args.args
                self.assertEqual(
                    headers["anthropic-beta"], "server-side-fallback-2026-07-01"
                )
                self.assertEqual(payload["fallbacks"], "default")
                self.assertEqual(payload["max_tokens"], 16000)
            pipeline.claude_call("key", "claude-haiku-5-5", {})
            _, headers, payload = post.call_args.args
            self.assertNotIn("anthropic-beta", headers)
            self.assertNotIn("fallbacks", payload)

    def test_default_models_are_current(self):
        with patch.dict(pipeline.os.environ, {}, clear=True), patch.object(
            pipeline, "review", side_effect=RuntimeError("stop")
        ) as review, tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / "staging" / "weekend-2"
            report.save_json(candidate / "data" / "1.json", snapshot())
            report.render(
                report.load_offline(candidate), candidate / "weekend-report.html"
            )
            with self.assertRaises(RuntimeError):
                pipeline.process(Path(folder) / "staging", Path(folder) / "reports")
            models = review.call_args.args[2]
        self.assertEqual(models, {"codex": "gpt-6.1-sol", "claude": "claude-opus-5-5"})

    def test_provider_outputs_are_parsed(self):
        response = {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {"type": "output_text", "text": json.dumps(self.document)}
                    ]
                }
            ],
        }
        with patch.object(pipeline, "post_json", return_value=response) as post:
            self.assertEqual(pipeline.openai_call("key", "model", {}), self.document)
            self.assertEqual(post.call_args.args[2]["max_output_tokens"], 16000)
        response = {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(self.document)}],
        }
        with patch.object(pipeline, "post_json", return_value=response):
            self.assertEqual(pipeline.claude_call("key", "model", {}), self.document)


if __name__ == "__main__":
    unittest.main()
