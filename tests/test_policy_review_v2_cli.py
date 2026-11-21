"""CLI argument/offline no-overwrite safety checks using temporary directories."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.review_v2_cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_parser_requires_explicit_offline(self):
        parser = build_parser()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(["--project-root", "x", "--local-appdata-root", "y",
                                   "--review-draft", "z", "--output", "t"])

    def test_parser_accepts_offline(self):
        args = build_parser().parse_args([
            "--project-root", "x", "--local-appdata-root", "y",
            "--review-draft", "z", "--output", "t", "--offline",
        ])
        self.assertTrue(args.offline)

    def test_no_files_created_when_inputs_are_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            local = Path(tmp) / "local"
            root.mkdir()
            local.mkdir()
            output = local / "CAST_AI" / "policy_compare_reviews" / "v2" / "report.json"
            with contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--project-root", str(root), "--local-appdata-root", str(local),
                           "--review-draft", str(root / "missing.json"),
                           "--output", str(output), "--offline"])
            self.assertEqual(rc, 1)
            self.assertFalse(output.exists())

    def test_project_output_location_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            local = Path(tmp) / "local"
            root.mkdir()
            local.mkdir()
            output = root / "out.json"
            with contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--project-root", str(root), "--local-appdata-root", str(local),
                           "--review-draft", str(root / "missing.json"),
                           "--output", str(output), "--offline"])
            self.assertEqual(rc, 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
