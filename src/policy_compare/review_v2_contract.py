"""Phase 5 v2 immutable input contract and draft schema (offline, unapproved).

Do not treat a hash chain, a reviewer ID or an offline remote-hash claim as
authenticated identity or publication authorization.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .review_lineage import RUN_ID, SOURCE_SHA256, DOC_YEARS
from .review_source_manifest import decode_json, read_bytes

POLICY_KEY = "seoul-youth-rent"
DRAFT_TYPE = "POLICY_REVIEW_V2_DRAFT"
REPORT_TYPE = "POLICY_REVIEW_GATE_V2_REPORT"
ANALYSIS_SHA256 = "faa5970b4aa9bbf41cfdee0aad916a3dd806b61fd43ed7f94a3390bdfbb5d34e"
PHASE3_SHA256 = "65713d53c0b77906c6bb96998df1a1cdf5cce4185310df6bf81f05be2090b906"
PHASE4_SHA256 = "250363ecfec5934df1cb621034609b7a796a37e2add530506dbbe332dd8a61a3"
GENESIS = "0" * 64
HEX64 = re.compile(r"^[a-f0-9]{64}$")
MAX_DRAFT_BYTES = 4_000_000


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json_with_digest(path: Path, expected: str | None = None) -> dict[str, Any]:
    raw = read_bytes(Path(path))
    require(len(raw) <= MAX_DRAFT_BYTES, "JSON input too large")
    if expected is not None:
        require(sha256(raw) == expected, f"Unapproved or changed input: {path}")
    return decode_json(raw)


def source_bindings() -> dict[str, str]:
    return {
        "source_manifest_sha256": SOURCE_SHA256,
        "page_analysis_sha256": ANALYSIS_SHA256,
        "phase3_result_sha256": PHASE3_SHA256,
        "phase4_result_sha256": PHASE4_SHA256,
    }


def _ids(values: list[dict], key: str) -> list[str]:
    require(isinstance(values, list), f"Invalid {key} list")
    result = [item[key] for item in values]
    require(all(isinstance(x, str) and x.strip() for x in result)
            and len(result) == len(set(result)), f"Duplicate/invalid {key}")
    return sorted(result)


def expected_scope(manifest: dict, analysis: dict, phase4: dict) -> dict[str, Any]:
    require(manifest.get("status") == "REVIEW_REQUIRED"
            and manifest.get("humanApproved") is False, "Source Manifest not review-only")
    require(analysis.get("source_manifest_sha256") == SOURCE_SHA256
            and analysis.get("humanApproved") is False
            and analysis.get("java_import_ready") is False, "Task B analysis not unapproved")
    require(isinstance(phase4.get("comparisons"), list)
            and len(phase4["comparisons"]) == 1, "Phase 4 comparison count invalid")
    comp = phase4["comparisons"][0]
    require(comp.get("policyKey") == POLICY_KEY
            and comp.get("previousDocumentKey") == list(DOC_YEARS)[0]
            and comp.get("currentDocumentKey") == list(DOC_YEARS)[1]
            and comp.get("humanApproved") is False
            and phase4.get("java_import_ready") is False, "Phase 4 identity or approval changed")
    ids = _ids(comp["displayItems"], "comparison_id")
    tasks = _ids(comp["reviewTasks"], "comparison_id")
    findings = _ids(analysis["findings"], "finding_id")
    candidate_ids = _ids(comp["additionalReviewCandidates"], "candidate_id")
    relations = comp["compoundRelations"]
    groups = comp["reviewGroups"]
    change_keys = comp["summaryChangeKeys"]
    require(len(ids) == 82 and len(tasks) == 22 and set(tasks) <= set(ids),
            "Unexpected comparison/task count")
    require(len(findings) == 8 and len(candidate_ids) == 1 and len(relations) == 2
            and len(groups) == 57 and len(change_keys) == 19,
            "Unexpected baseline review count")
    require(analysis.get("summary", {}).get("source_pages_checked_for_text_parity") == 23,
            "Missing 23-page source analysis")
    require({x["finding_id"] for x in analysis["findings"]} == set(findings),
            "Finding ID mismatch")
    require({r["parent_id"] for r in relations}
            == {i["comparison_id"] for i in comp["displayItems"]
                if i["proposed_change_type"] == "SPLIT_REQUIRED"},
            "Split parent mismatch")
    for rel in relations:
        require(set(rel["child_ids"]) <= set(ids) and len(rel["child_ids"]) >= 2,
                "Unknown split children")
    full = manifest["review_scope"]["full"]
    focused = manifest["review_scope"]["focused"]
    require(set(full) == set(DOC_YEARS) and set(focused) == set(DOC_YEARS),
            "Unexpected PDF scope")
    require(sum(len(pages) for pages in full.values()) == 23
            and sum(len(pages) for pages in focused.values()) == 10,
            "PDF scope count mismatch")
    return {
        "pdf_pages": full,
        "focused_pages": focused,
        "finding_ids": findings,
        "comparison_ids": ids,
        "review_task_ids": tasks,
        "split_relations": [{"parent_id": r["parent_id"], "child_ids": r["child_ids"]}
                            for r in relations],
        "additional_candidate_ids": candidate_ids,
    }


def make_initial_draft(manifest: dict, analysis: dict, phase4: dict) -> dict[str, Any]:
    scope = expected_scope(manifest, analysis, phase4)
    sources = []
    for doc in manifest["documents"]:
        sources.append({
            "document_id": doc["document_id"],
            "local_pdf_sha256": doc["local_pdf"]["sha256"],
            "official_page_url": doc["official_source"]["source_page_url"],
            "official_download_url": doc["official_source"]["download_url"],
            "remote_status": "NOT_CHECKED",
            "remote_sha256": None,
            "remote_checked_at": None,
            "remote_verifier_id": None,
        })
    return {
        "schema_version": 2,
        "artifact_type": DRAFT_TYPE,
        "status": "DRAFT_REVIEW_REQUIRED",
        "run_id": RUN_ID,
        "policy_key": POLICY_KEY,
        "source_bindings": source_bindings(),
        "review_scope": scope,
        "pdf_source_checks": sources,
        "events": [],
        "humanApproved": False,
        "java_import_ready": False,
    }


def validate_draft(draft: dict, manifest: dict, analysis: dict, phase4: dict) -> dict:
    """Validate v2 draft against a reconstructed immutable bootstrap snapshot.

    Only `events` and self-reported remote-check fields may evolve in a new
    revision file. Never overwrite the initial draft in place.
    """
    require(isinstance(draft, dict), "Draft must be a JSON object")
    expected = make_initial_draft(manifest, analysis, phase4)
    require(set(draft) == set(expected), "Unexpected draft fields")
    for key in expected:
        if key not in ("events", "pdf_source_checks"):
            require(draft[key] == expected[key], f"Changed v2 draft binding: {key}")
    checks = draft["pdf_source_checks"]
    require(isinstance(checks, list) and len(checks) == 2, "Expected two official source checks")
    expected_by_doc = {x["document_id"]: x for x in expected["pdf_source_checks"]}
    seen = set()
    for check in checks:
        require(isinstance(check, dict)
                and set(check) == set(next(iter(expected_by_doc.values()))),
                "Malformed source-check record")
        doc = check["document_id"]
        require(doc in expected_by_doc and doc not in seen, "Unknown or repeated source-check document")
        seen.add(doc)
        baseline = expected_by_doc[doc]
        for key in ("document_id", "local_pdf_sha256", "official_page_url",
                    "official_download_url"):
            require(check[key] == baseline[key], "Official source identity changed")
        status = check["remote_status"]
        require(status in {"NOT_CHECKED", "REMOTE_MATCH_SELF_ATTESTED",
                           "MISMATCH_REPORTED", "ACCESS_UNAVAILABLE"},
                "False remote verification status")
        if status == "NOT_CHECKED":
            require(all(check[k] is None for k in
                        ("remote_sha256", "remote_checked_at", "remote_verifier_id")),
                    "Unverified remote check must be empty")
        else:
            require(isinstance(check["remote_checked_at"], str)
                    and isinstance(check["remote_verifier_id"], str)
                    and bool(check["remote_verifier_id"].strip()),
                    "Remote review assertion requires identity/time")
            from .pdf_source_review import _valid_reviewer
            require(_valid_reviewer({"reviewer_id": check["remote_verifier_id"],
                                     "reviewed_at": check["remote_checked_at"]}),
                    "Remote check timestamp invalid")
            if status in ("REMOTE_MATCH_SELF_ATTESTED", "MISMATCH_REPORTED"):
                require(isinstance(check["remote_sha256"], str)
                        and HEX64.fullmatch(check["remote_sha256"]) is not None,
                        "Remote digest invalid")
                require((check["remote_sha256"] == baseline["local_pdf_sha256"])
                        == (status == "REMOTE_MATCH_SELF_ATTESTED"),
                        "Self-report remote comparison disagrees with digest")
            else:
                require(check["remote_sha256"] is None, "Unavailable source cannot have digest")
    require(isinstance(draft["events"], list), "Invalid event list")
    return expected
