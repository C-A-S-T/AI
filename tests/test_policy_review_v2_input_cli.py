"""Synthetic-only CLI behavior; no real source, PDF, approval or network."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.policy_compare.review_v2_input_cli import build_parser, main
from src.policy_compare.review_v2_gate import evaluate_gate_v2
from src.policy_compare.review_v2_decision import replay_events
from test_policy_review_v2_contract import DOCS, synthetic_inputs


class InputCliTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()

    def context(self, root, local):
        report = evaluate_gate_v2(self.m, self.a, self.p4, self.d,
                                  pdf_text=self.text)
        state = replay_events(self.d["events"], self.m, self.a, self.p4,
                              self.d["review_scope"], self.text)
        return {"root": root, "local": local, "draft": self.d,
                "draft_path": root / "initial.json", "draft_sha256": "a" * 64,
                "state": state, "report": report,
                "manifest": self.m, "analysis": self.a, "phase4": self.p4,
                "pdf_text": self.text}

    def invoke(self, ctx, args):
        out = io.BytesIO()
        console = io.TextIOWrapper(out, encoding="utf-8")
        with patch("src.policy_compare.review_v2_input_cli.load_review_context",
                   return_value=ctx), patch(
                       "src.policy_compare.review_v2_input_cli.sys.stdout", console):
            code = main(["--offline", "--project-root", str(ctx["root"]),
                         "--local-appdata-root", str(ctx["local"])] + args)
            console.flush()
        return code, json.loads(out.getvalue().decode("utf-8")) if code == 0 else {}

    def test_offline_flag_required(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["--project-root", "x",
                                       "--local-appdata-root", "y", "status"])

    def test_status_is_read_only_and_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"; local = Path(d) / "local"
            root.mkdir(); local.mkdir()
            code, result = self.invoke(self.context(root, local), ["status"])
            self.assertEqual(code, 0)
            self.assertEqual(result["pdf_pages"]["total"], 23)
            self.assertFalse(result["humanApproved"])
            self.assertFalse((local / "CAST_AI").exists())

    def test_queue_shows_focused_pdf_before_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"; local = Path(d) / "local"
            root.mkdir(); local.mkdir()
            code, result = self.invoke(self.context(root, local),
                                       ["queue", "--limit", "3"])
            self.assertEqual(code, 0)
            self.assertEqual(result["returned"], 3)
            self.assertTrue(all(x["type"] == "PDF_PAGE" and x["focused"]
                                for x in result["items"]))

    def test_show_pdf_reports_verified_parsed_text_not_attestation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"; local = Path(d) / "local"
            root.mkdir(); local.mkdir()
            code, result = self.invoke(self.context(root, local),
                                       ["show", "--type", "PDF_PAGE",
                                        "--id", f"{DOCS[0]}:4"])
            self.assertEqual(code, 0)
            self.assertIn("Official evidence", result["text"])
            self.assertEqual(result["status"], "PENDING_REVIEW")

    def test_template_is_blank_and_written_only_to_new_user_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"; local = Path(d) / "local"
            root.mkdir(); local.mkdir()
            ctx = self.context(root, local)
            target = Path(d) / "template.json"
            code, result = self.invoke(ctx, ["template", "--type", "PDF_PAGE",
                                             "--id", f"{DOCS[0]}:4",
                                             "--action", "PAGE_CONFIRMED",
                                             "--output", str(target)])
            self.assertEqual(code, 0)
            self.assertEqual(result["result"], "UNATTESTED_TEMPLATE_CREATED")
            value = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(value["actions"][0]["reviewer_id"], "")
            self.assertEqual(ctx["draft"]["events"], [])

    def test_history_starts_empty(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"; local = Path(d) / "local"
            root.mkdir(); local.mkdir()
            code, result = self.invoke(self.context(root, local), ["history"])
            self.assertEqual(code, 0)
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["events"], [])

    def test_apply_dry_run_uses_existing_validator(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"; local = Path(d) / "local"
            root.mkdir(); local.mkdir()
            ctx = self.context(root, local)
            expected = {"result": "VALIDATED_DRY_RUN", "event_count": 1,
                        "humanApproved": False, "java_import_ready": False}
            with patch("src.policy_compare.review_v2_input_cli.read_action_request",
                       return_value={"expected_draft_sha256": "a" * 64,
                                     "actions": []}), patch(
                       "src.policy_compare.review_v2_input_cli.apply_actions",
                       return_value=expected) as apply_mock:
                code, result = self.invoke(ctx, ["apply", "--actions-file", str(Path(d) / "a.json"),
                                                 "--dry-run"])
                self.assertEqual(code, 0)
                self.assertEqual(result["result"], "VALIDATED_DRY_RUN")
                self.assertTrue(apply_mock.call_args.kwargs["dry_run"])
                self.assertFalse((local / "CAST_AI").exists())


if __name__ == "__main__":
    unittest.main()
