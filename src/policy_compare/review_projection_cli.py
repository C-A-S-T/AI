"""Offline-only CLI for a version-bound Phase 4 review presentation draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.policy_compare.review_projection import build_review_projection, sha256_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review-only Phase 4 presentation projection")
    parser.add_argument("--phase3-result", type=Path, required=True)
    parser.add_argument("--supplemental-evidence", type=Path, required=True)
    parser.add_argument("--previous-cleaned", type=Path, required=True)
    parser.add_argument("--current-cleaned", type=Path, required=True)
    parser.add_argument("--review-notes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", required=True,
                        help="Required acknowledgement: no network, API, Java or DB access")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_paths = [args.phase3_result, args.supplemental_evidence,
                    args.previous_cleaned, args.current_cleaned, args.review_notes]
    try:
        if any(args.output.resolve() == path.resolve() for path in source_paths):
            raise ValueError("Output path overlaps a source file")
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError(f"Refusing to overwrite existing output: {args.output}")
        before = [sha256_file(path) for path in source_paths]
        result = build_review_projection(
            phase3_result_path=args.phase3_result,
            supplemental_path=args.supplemental_evidence,
            previous_cleaned_path=args.previous_cleaned,
            current_cleaned_path=args.current_cleaned,
            review_notes_path=args.review_notes,
        )
        after = [sha256_file(path) for path in source_paths]
        if before != after:
            raise ValueError("Source changed during projection: no output written")
        encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as file:
            try:
                file.write(encoded)
            except BaseException:
                file.close()
                args.output.unlink(missing_ok=True)
                raise
        summary = result["comparisons"][0]["summary"]
        print("PHASE4_PROJECTION=PASS")
        print(f"DISPLAY_ITEMS={summary['review_items']}")
        print(f"SUPPLEMENTAL_DISPLAY_FILLS={summary['supplemental_display_fills']}")
        print(f"ADDED_CANDIDATES_PRESERVED={summary['unchanged_unverified_added_candidates']}")
        print(f"COMPOUND_PARENTS={summary['compound_parents']}")
        print(f"REVIEW_TASKS={summary['review_tasks']}")
        print(f"SUMMARY_CHANGE_KEYS={summary['representative_change_keys']}")
        print(f"OUTPUT_PATH={args.output}")
        print(f"OUTPUT_SHA256={sha256_file(args.output)}")
        print("RESULT_STATUS=REVIEW_REQUIRED")
        print("HUMAN_APPROVED=False")
        print("JAVA_IMPORT_READY=False")
        print("OPENAI_MODE=OFFLINE")
        print("JAVA_DB_IMPORT=NOT_EXECUTED")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"PHASE4_PROJECTION_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
