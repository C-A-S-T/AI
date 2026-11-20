"""Offline, read-only Phase 5 v2 review gate CLI; exclusive report output only.

Example (AFTER separate execution approval):
python -B -m src.policy_compare.review_v2_cli --offline \
  --project-root ... --local-appdata-root ... --review-draft ... --output ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .review_lineage import load_page_analysis, load_verified_inputs
from .review_source_manifest import resolve_input
from .review_v2_contract import (
    ANALYSIS_SHA256, PHASE3_SHA256, PHASE4_SHA256,
    load_json_with_digest, require, sha256,
)
from .review_v2_gate import evaluate_gate_v2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 5 v2 offline review gate (unapproved)")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--local-appdata-root", required=True, type=Path)
    parser.add_argument("--review-draft", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--offline", required=True, action="store_true")
    return parser


def _source_path(manifest: dict, role: str, root: Path, local: Path) -> Path:
    records = [r for r in manifest["input_artifacts"] if r["role"] == role]
    require(len(records) == 1, f"Manifest must contain exactly one {role}")
    source = records[0]
    base = root if source["path_base"] == "PROJECT" else local
    return resolve_input(base, source["path"])


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = args.project_root.resolve(strict=True)
        local = args.local_appdata_root.resolve(strict=True)
        base = resolve_input(root, "metadata/policy_review_runs/seoul_youth_rent_2025_2026/20261117_v1")
        manifest_path = base / "source_manifest.json"
        analysis_path = base / "page_analysis.json"
        draft_path = args.review_draft.resolve(strict=True)
        output = args.output.resolve(strict=False)
        allowed_output_root = (local / "CAST_AI" / "policy_compare_reviews" / "v2").resolve()
        require(output.is_relative_to(allowed_output_root),
                "Output must be a new file under LOCALAPPDATA/CAST_AI/policy_compare_reviews/v2")
        require(not output.exists() and not output.is_symlink(), "Refusing to overwrite report")
        require(not output.parent.is_symlink(), "Output parent cannot be a symlink")

        # This validation reads ALL 20 source artifacts, independently verifies
        # the two actual PDFs and requires an exact Task-B reconstruction.
        analysis = load_page_analysis(analysis_path, manifest_path,
                                      project_root=root, local_appdata_root=local)
        manifest, records = load_verified_inputs(manifest_path, project_root=root,
                                                 local_appdata_root=local)
        require(sha256(analysis_path.read_bytes()) == ANALYSIS_SHA256,
                "Analysis SHA256 mismatch")
        phase3_path = _source_path(manifest, "PHASE3", root, local)
        phase4_path = _source_path(manifest, "PHASE4", root, local)
        phase3 = load_json_with_digest(phase3_path, PHASE3_SHA256)
        phase4 = load_json_with_digest(phase4_path, PHASE4_SHA256)
        require(phase3.get("status") == "REVIEW_REQUIRED"
                and phase3.get("java_import_ready") is False,
                "Phase 3 status changed")
        draft = load_json_with_digest(draft_path)
        pdf_text = {
            (doc, i): page["text"]
            for doc in (d["document_id"] for d in manifest["documents"])
            for i, page in enumerate(records[("PARSED", doc)]["pages"], start=1)
        }
        # No trusted provenance is available through this offline CLI.
        report = evaluate_gate_v2(manifest, analysis, phase4, draft, pdf_text=pdf_text)

        paths = [manifest_path, analysis_path, phase3_path, phase4_path, draft_path]
        for record in manifest["input_artifacts"]:
            base_root = root if record["path_base"] == "PROJECT" else local
            paths.append(resolve_input(base_root, record["path"]))
        paths = sorted(set(p.resolve() for p in paths))
        require(output not in paths, "Output overlaps a protected source")
        before = {p: sha256(p.read_bytes()) for p in paths}
        for path, digest in before.items():
            require(sha256(path.read_bytes()) == digest, "Input changed during evaluation")
        blob = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never replace another report or any existing file.
        with output.open("xb") as stream:
            stream.write(blob)
        print("PHASE5_V2_OFFLINE_GATE=PASS")
        print(f"INPUT_ARTIFACTS={len(manifest['input_artifacts'])}")
        print(f"PDF_PAGES={report['summary']['pdf_pages_total']}")
        print(f"FINDINGS={report['summary']['findings_total']}")
        print(f"COMPARISONS={report['summary']['comparisons_total']}")
        print(f"BLOCKERS={len(report['blockers'])}")
        print(f"PUBLICATION_REVIEW_ELIGIBLE={report['eligible_for_authenticated_publication_review']}")
        print(f"OUTPUT_PATH={output}")
        print(f"OUTPUT_SHA256={sha256(blob)}")
        print("HUMAN_APPROVED=False")
        print("JAVA_IMPORT_READY=False")
        print("JAVA_DB_IMPORT=NOT_EXECUTED")
        return 0
    except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
        print(f"PHASE5_V2_OFFLINE_GATE_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
