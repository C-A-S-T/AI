"""Offline review gate CLI: read-only checks and exclusive output creation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.policy_compare.pdf_source_review import DOCUMENT_IDS
from src.policy_compare.review_approval_gate import (
    EXPECTED_PHASE4_SHA256, evaluate_gate, read_json, source_hash,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 5 offline policy review gate")
    parser.add_argument("--phase4-result", required=True, type=Path)
    parser.add_argument("--review-draft", required=True, type=Path)
    parser.add_argument("--previous-pdf", type=Path, default=None)
    parser.add_argument("--current-pdf", type=Path, default=None)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--offline", action="store_true", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_paths = [args.phase4_result, args.review_draft]
    pdf_paths = {DOCUMENT_IDS[0]: args.previous_pdf, DOCUMENT_IDS[1]: args.current_pdf}
    source_paths.extend(p for p in pdf_paths.values() if p is not None)
    try:
        output = args.output.resolve()
        if output in {p.resolve() for p in source_paths}:
            raise ValueError("Output path overlaps input file")
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"Refusing to overwrite output: {args.output}")
        before = [source_hash(p) for p in source_paths]
        phase4 = read_json(args.phase4_result, EXPECTED_PHASE4_SHA256)
        draft = read_json(args.review_draft)
        report = evaluate_gate(phase4, draft, pdf_paths)
        after = [source_hash(p) for p in source_paths]
        if before != after:
            raise ValueError("Input changed during review check; no output written")
        content = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as handle:
            try:
                handle.write(content)
            except BaseException:
                handle.close()
                args.output.unlink(missing_ok=True)
                raise
        summary = report["summary"]
        print("PHASE5_OFFLINE_GATE=PASS")
        print(f"REVIEW_ITEMS={summary['comparison_items']}")
        print(f"APPROVED_ITEM_CLAIMS={summary['approved_item_claims']}")
        print(f"REVIEW_TASKS_PENDING={summary['unresolved_task_approvals_missing']}")
        print(f"PDF_TARGETS_PENDING={summary['pdf_targets_unconfirmed']}")
        print(f"PUBLICATION_REVIEW_ELIGIBLE={report['eligible_for_authenticated_publication_review']}")
        print(f"BLOCKERS={len(report['blockers'])}")
        print(f"OUTPUT_PATH={args.output}")
        print(f"OUTPUT_SHA256={source_hash(args.output)}")
        print("HUMAN_APPROVED=False")
        print("JAVA_IMPORT_READY=False")
        print("OPENAI_MODE=OFFLINE")
        print("JAVA_DB_IMPORT=NOT_EXECUTED")
        return 0
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(f"PHASE5_OFFLINE_GATE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
