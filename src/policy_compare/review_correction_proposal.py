"""Read-only AI correction proposals; never review actions, revisions or approvals.

The file loader pins all existing inputs before checking proposal snapshots and
quotes. Structural validity does not establish semantic correctness or identity.
"""
from __future__ import annotations

import copy
import hashlib
import io
import re
from collections import Counter
from pathlib import Path

from .review_source_manifest import decode_json, read_bytes, resolve_input

RUN = "metadata/policy_review_runs/seoul_youth_rent_2025_2026/20261117_v1/"
PROPOSAL_PATH = (
    "metadata/policy_review_runs/seoul_youth_rent_2025_2026/"
    "20261120_correction_v1/correction_proposals.json"
)
BINDINGS = {
    "source_manifest_sha256": "a916e643d17b56b24ebf21e3fa0c3ba27b0cab65fa889bfc2752efb15e2ef9f9",
    "page_analysis_sha256": "faa5970b4aa9bbf41cfdee0aad916a3dd806b61fd43ed7f94a3390bdfbb5d34e",
    "phase3_result_sha256": "65713d53c0b77906c6bb96998df1a1cdf5cce4185310df6bf81f05be2090b906",
    "phase4_result_sha256": "250363ecfec5934df1cb621034609b7a796a37e2add530506dbbe332dd8a61a3",
    "initial_draft_sha256": "7acc1dbf9c0e07034ec661c7fc90f8aa4835d8dae92af583086000060b6761db",
}
DOCS = {
    "DOC-211f45df17b98569c5f1": (2025, 10, "6288e029484140bff4e7a3a5de64691d8230f07b04bae47d7dbcb25300cd0df4"),
    "DOC-543adbc0ebc09e5ce628": (2026, 13, "80de4494292b3d7526749bddf12509843d4ffd9a8ae2d944a32cb33c008e0f1d"),
}
SOURCE_URLS = {
    2025: ("https://housing.seoul.go.kr/site/main/board/notice/12478",
           "https://housing.seoul.go.kr/site/main/file/download/uu/8ae2302eaf1c4ef8bb378287786c3d9e", 395107),
    2026: ("https://housing.seoul.go.kr/site/main/board/notice/12667",
           "https://housing.seoul.go.kr/site/main/file/download/uu/da39f9221c574254a6c8bc52327495f5", 413817),
}
FAQ_SOURCES = {
    "FAQ_2025": (2025, "https://housing.seoul.go.kr/site/main/file/download/uu/63d9bfeaf7c54c2c9eca09d9c5d77b38",
                 "4f49dc33335e5a87a055d4fd6a4cf39cbd7c88a6ff728b2567403a4fe19b468f", 356063, 19, "Q45"),
    "FAQ_2026": (2026, "https://housing.seoul.go.kr/site/main/file/download/uu/ba90cf52ce02456e9ce2f43303d81914",
                 "749d68eab00c69096a33df572dac58b80d0cd40b88cd63f71d58449e0790f4dc", 361411, 25, "Q51"),
}
DISPOSITIONS = {
    "PREVIOUS_BENEFICIARY_RESTRICTION": "INSUFFICIENT_EVIDENCE",
    "RENT_BELOW_CAP_PAYMENT": "INSUFFICIENT_EVIDENCE",
    "ONE_PERSON_INCOME_THRESHOLDS": "REVISE_PROPOSAL",
    "SIMILAR_SUPPORT_EXCLUSION": "INSUFFICIENT_EVIDENCE",
    "DOC_LEASE_ALTERNATIVES": "SPLIT_PROPOSAL",
    "DOC_ADMIN_CONSENT": "REVISE_PROPOSAL",
    "SUSPENSION_EFFECT": "SPLIT_PROPOSAL",
    "NEW_SPECIAL_APPLICATION_GROUPS": "REVISE_PROPOSAL",
    "OBJECTION_DOCUMENT_LIMITATION": "REVISE_PROPOSAL",
    "GOV_SUPPORT_REFUND_ON_OVERLAP": "REVISE_PROPOSAL",
    "SIMILAR_SUPPORT_SAME_MONTH_STOP": "RETAIN_PROPOSAL",
    "SUSPENSION_NO_RESUME": "RETAIN_PROPOSAL",
    "ADMIN_CONSENT_ALTERNATIVES": "REVISE_PROPOSAL",
}
RELATED = {"RENT_CONVERSION_FORMULA", "TIER_DISTRIBUTION"}
COUNTS = {"RETAIN_PROPOSAL": 2, "REVISE_PROPOSAL": 6,
          "SPLIT_PROPOSAL": 2, "INSUFFICIENT_EVIDENCE": 3}
PROPOSED_TYPES = {
    "MAINTAINED", "UPDATED", "ADDED_CANDIDATE", "REMOVED_CANDIDATE",
    "INCONCLUSIVE", "SPLIT_REQUIRED", "WORDING_ONLY", "ANNUAL_SCHEDULE",
}
TRUST = {"ai_analysis": "PROPOSAL_ONLY", "human_attestation": "NOT_RECORDED",
         "authenticated_approval": "NOT_GRANTED", "gate_trust_updated": False}
TIME = {"checked_at": None, "time_status": "UNKNOWN",
        "time_reason": "EXACT_TIMESTAMP_NOT_CAPTURED_IN_PRIOR_TOOL_RESULT"}
FOLLOWUP = ["REJECTED_IS_NOT_COMPLETE", "EVIDENCED_NONCHANGE_RESOLUTION",
            "SEPARATE_SUBSTANTIVE_SCHEDULE_WORDING_SUMMARIES"]
FORBIDDEN_KEYS = {
    "actions", "events", "review_events", "reviewer_id", "reviewed_at",
    "event_hash", "previous_event_hash", "trusted_provenance_docs",
    "attested_pages", "final_change_type", "account_number", "resident_number", "person_name",
}


def require(condition: bool, message: str) -> None:
    """Reject without repairing or changing any input."""
    if not condition:
        raise ValueError(message)


def fields(value, keys: str, label: str) -> None:
    require(isinstance(value, dict) and set(value) == set(keys.split()),
            "Invalid fields: " + label)


def strings(value, label: str, *, nonempty: bool = True) -> None:
    require(isinstance(value, list) and (bool(value) or not nonempty)
            and all(isinstance(x, str) and x.strip() for x in value),
            "Invalid string list: " + label)
    require(len(value) == len(set(value)), "Duplicate strings: " + label)


def _claims(value) -> None:
    """Reject event/approval fields and recognizable resident-number patterns.

    This is not a general personal-data detector. Human inspection is still
    required for names or account numbers appearing in otherwise ordinary prose.
    """
    if isinstance(value, dict):
        require(not set(value) & FORBIDDEN_KEYS, "Forbidden event or personal-data field")
        for key, child in value.items():
            if key in {"humanApproved", "human_approved", "java_import_ready", "pdf_visual_reviewed"}:
                require(child is False, "Human approval or visual claim forbidden")
            _claims(child)
    elif isinstance(value, list):
        for child in value:
            _claims(child)
    elif isinstance(value, str):
        require(re.search(r"(?<!\d)\d{6}-[1-8]\d{6}(?!\d)", value) is None,
                "Potential resident registration number")


def dependencies_for(item: dict, comp: dict) -> dict:
    """Capture actual immutable scope, parent/children and deduplication links."""
    cid = item["comparison_id"]
    relation = next((x for x in comp["compoundRelations"] if x["parent_id"] == cid), None)
    return {
        "baseline_scope_id": item["scope_id"], "change_group_id": item["change_group_id"],
        "change_key": item["change_key"], "summary_role": item["summary_role"],
        "parent_comparison_id": item["parent_comparison_id"],
        "child_ids": list(relation["child_ids"]) if relation else [],
        "same_change_key_ids": sorted(x["comparison_id"] for x in comp["displayItems"]
                                    if x["change_key"] == item["change_key"] and x["comparison_id"] != cid),
    }


def _sources(proposal: dict) -> None:
    sources = proposal["source_observations"]
    require(isinstance(sources, list) and len(sources) == 2, "Expected two source observations")
    require({x["document_id"] for x in sources} == set(DOCS), "Source identity mismatch")
    for source in sources:
        fields(source, "document_id source_page_url download_url size_bytes local_sha256 remote_sha256 "
               "status recorded_from checked_at time_status time_reason", "source observation")
        year, _, digest = DOCS[source["document_id"]]
        page, download, size = SOURCE_URLS[year]
        expected = dict(document_id=source["document_id"], source_page_url=page, download_url=download,
                        size_bytes=size, local_sha256=digest, remote_sha256=digest,
                        status="PRIOR_SESSION_BYTES_MATCH_REPORTED",
                        recorded_from="PRIOR_CONVERSATION_TOOL_RESULT", **TIME)
        require(source == expected, "Historical source observation changed")
    sources = proposal["supplemental_sources"]
    require(isinstance(sources, list) and len(sources) == 2, "Expected two FAQ observations")
    require({x["source_id"] for x in sources} == set(FAQ_SOURCES), "FAQ identity mismatch")
    for source in sources:
        fields(source, "source_id year url sha256 size_bytes page question quote status "
               "checked_at time_status time_reason recorded_from", "FAQ")
        year, url, digest, size, page, question = FAQ_SOURCES[source["source_id"]]
        expected = dict(source_id=source["source_id"], year=year, url=url, sha256=digest,
                        size_bytes=size, page=page, question=question,
                        quote="예시) 월세 108,000원은 100,000원으로 입력",
                        status="PRIOR_SESSION_BYTES_OBSERVED_NOT_REVALIDATED",
                        recorded_from="PRIOR_CONVERSATION_TOOL_RESULT", **TIME)
        require(source == expected, "Historical FAQ observation changed")


def _validate(proposal: dict, phase4: dict, pdf_text: dict) -> dict:
    fields(proposal, "schema_version artifact_type proposal_run_id policy_key status baseline_bindings "
           "trust source_observations supplemental_sources p0_items related_items disposition_counts "
           "stage_b_followup humanApproved java_import_ready", "proposal")
    require(type(proposal["schema_version"]) is int and proposal["schema_version"] == 1,
            "Invalid schema version")
    require(proposal["artifact_type"] == "POLICY_CORRECTION_PROPOSALS"
            and proposal["proposal_run_id"] == "seoul_youth_rent_2025_2026_20261120_correction_v1"
            and proposal["policy_key"] == "seoul-youth-rent"
            and proposal["status"] == "AI_ANALYSIS_PROPOSAL", "Invalid proposal identity")
    require(proposal["baseline_bindings"] == BINDINGS, "Baseline binding mismatch")
    require(proposal["trust"] == TRUST, "Trust boundary changed")
    require(proposal["humanApproved"] is False and proposal["java_import_ready"] is False,
            "Approval flags must remain false")
    _claims(proposal)
    _sources(proposal)
    require(proposal["stage_b_followup"] == FOLLOWUP, "Stage B obligations changed")
    require(len(phase4["comparisons"]) == 1, "Invalid comparison count")
    comp = phase4["comparisons"][0]
    require(phase4["java_import_ready"] is False and comp["humanApproved"] is False,
            "Baseline approval changed")
    original_items = comp["displayItems"]
    items = {x["comparison_id"]: x for x in original_items}
    require(len(items) == len(original_items) == 82, "Expected 82 unique baseline items")
    require(len(comp["reviewGroups"]) == 57 and len(comp["reviewTasks"]) == 22
            and len(comp["summaryChangeKeys"]) == 19
            and len(comp["compoundRelations"]) == 2
            and len(comp["additionalReviewCandidates"]) == 1, "Baseline counts changed")
    require(Counter(cid for g in comp["reviewGroups"] for cid in g["comparison_ids"])
            == Counter(items.keys()), "Baseline group coverage invalid")
    for key, ids in (("p0_items", set(DISPOSITIONS)), ("related_items", RELATED)):
        entries = proposal[key]
        require(isinstance(entries, list) and len(entries) == len(ids)
                and {x["comparison_id"] for x in entries} == ids, "Proposal ID coverage invalid")
        for entry in entries:
            fields(entry, "comparison_id baseline_snapshot recommendation evidence absence_analysis "
                   "dependencies related_comparison_ids assessment event_compatibility", "item")
            cid = entry["comparison_id"]
            original = items[cid]
            require(entry["baseline_snapshot"] == original, "Baseline snapshot mismatch: " + cid)
            require(entry["dependencies"] == dependencies_for(original, comp),
                    "Baseline relationship mismatch: " + cid)
            links = entry["related_comparison_ids"]
            strings(links, "related_comparison_ids")
            require(set(links) <= set(items) and cid not in links, "Unknown related comparison ID")
            rec = entry["recommendation"]
            fields(rec, "proposed_change_type previous_value current_value explanation scope_note "
                   "target_fields counting_policy unresolved_questions", "recommendation")
            require(rec["proposed_change_type"] in PROPOSED_TYPES, "Unknown proposed type")
            expected_type = "UPDATED" if cid == "ONE_PERSON_INCOME_THRESHOLDS" else original["proposed_change_type"]
            require(rec["proposed_change_type"] == expected_type, "Unapproved proposed type change")
            for name in ("previous_value", "current_value", "explanation", "scope_note"):
                require(isinstance(rec[name], str) and rec[name].strip(), "Missing recommendation text")
            require(rec["counting_policy"] == "PRESERVE_BASELINE_NO_ADDITIONAL_COUNT",
                    "Additional change counting forbidden")
            strings(rec["target_fields"], "target_fields", nonempty=False)
            require(set(rec["target_fields"]) <= {
                "previous.value", "current.value", "adjudication_reason", "scope_id",
                "previous.supplemental_quotes", "current.supplemental_quotes",
            }, "Unknown correction target field")
            require(bool(rec["target_fields"]) == (cid != "TIER_DISTRIBUTION"),
                    "Unexpected target field coverage")
            strings(rec["unresolved_questions"], "unresolved_questions")
            if cid == "ONE_PERSON_INCOME_THRESHOLDS":
                require({"INCOME_ASSESSMENT_METHOD", "INCOME_ELIGIBILITY"} <= set(links)
                        and "직접 증감 비교 불가" in rec["explanation"], "Income metric separation missing")
            if cid == "RENT_CONVERSION_FORMULA":
                require(rec["current_value"] == "보증금 금액 × 4.5% ÷ 12개월"
                        and "RENT_CONVERSION_RATE" in links, "Formula correction or deduplication missing")
            if cid == "TIER_DISTRIBUTION":
                require("15,000" in rec["previous_value"] and "12,000" in rec["current_value"],
                        "Selection denominators missing")
            assessment = entry["assessment"]
            fields(assessment, "disposition severity verification_status finalization", "assessment")
            disposition = DISPOSITIONS.get(cid, "REVISE_PROPOSAL" if cid == "RENT_CONVERSION_FORMULA"
                                           else "RETAIN_PROPOSAL")
            require(assessment["disposition"] == disposition, "Disposition mismatch")
            require(assessment["severity"] in {"LOW", "MEDIUM", "HIGH"}
                    and assessment["verification_status"] == "AI_SOURCE_ANALYSIS_HUMAN_UNATTESTED"
                    and assessment["finalization"] == "NOT_FINAL", "Invalid assessment status")
            absence = entry["absence_analysis"]
            fields(absence, "document_id pages method conclusion human_attested", "absence analysis")
            conclusion = ("NOT_IDENTIFIED_IN_MAIN_NOTICE_ONLY"
                          if original["proposed_change_type"] == "ADDED_CANDIDATE" else "NOT_APPLICABLE")
            require(absence == dict(document_id="DOC-211f45df17b98569c5f1", pages=list(range(1, 11)),
                                    method="PRIOR_AI_FULL_DOCUMENT_TEXT_REVIEW", conclusion=conclusion,
                                    human_attested=False), "Absence analysis is not human attestation")
            compatibility = entry["event_compatibility"]
            fields(compatibility, "automatic_conversion status prerequisites supplemental_source_ids",
                   "event compatibility")
            status = ("INSUFFICIENT_EVIDENCE" if disposition == "INSUFFICIENT_EVIDENCE"
                      else "HUMAN_REVIEW_AND_STAGE_B_REQUIRED")
            require(compatibility["automatic_conversion"] is False
                    and compatibility["status"] == status
                    and compatibility["prerequisites"] == ["EXPLICIT_HUMAN_REVIEW", "SEPARATE_EXECUTION_APPROVAL"]
                    and compatibility["supplemental_source_ids"] == (
                        ["FAQ_2025", "FAQ_2026"] if cid == "RENT_BELOW_CAP_PAYMENT" else []),
                    "Automatic or premature event conversion")
            refs = entry["evidence"]
            require(isinstance(refs, list) and refs, "Evidence required")
            seen = set()
            for ref in refs:
                fields(ref, "document_id year pdf_sha256 page quote verification", "evidence")
                doc = ref["document_id"]
                require(doc in DOCS, "Unknown evidence document")
                year, count, digest = DOCS[doc]
                require(type(ref["page"]) is int and 1 <= ref["page"] <= count
                        and ref["year"] == year and ref["pdf_sha256"] == digest,
                        "Evidence identity, page or digest mismatch")
                require(isinstance(ref["quote"], str) and ref["quote"].strip(), "Empty evidence quote")
                normalized = " ".join(ref["quote"].split())
                page_key = (doc, ref["page"])
                require(page_key in pdf_text and normalized in " ".join(pdf_text[page_key].split()),
                        "Evidence quote not in PDF")
                identity = (*page_key, normalized)
                require(identity not in seen, "Duplicate evidence")
                seen.add(identity)
                require(ref["verification"] == "AI_TEXT_OBSERVATION_NOT_HUMAN_ATTESTATION",
                        "Invalid evidence verification claim")
            require({x["document_id"] for x in refs} == set(DOCS), "Both years need contextual evidence")
    require(proposal["disposition_counts"] == COUNTS
            and dict(Counter(x["assessment"]["disposition"] for x in proposal["p0_items"])) == COUNTS,
            "P0 disposition counts mismatch")
    return {"status": "VALID_AI_PROPOSAL_NOT_APPROVAL", "p0_items": 13, "related_items": 2,
            "disposition_counts": copy.deepcopy(COUNTS), "humanApproved": False,
            "java_import_ready": False, "gate_trust_updated": False,
            "semantic_judgment": "HUMAN_REVIEW_REQUIRED"}


def validate_proposal(proposal: dict, *, phase4: dict, pdf_text: dict) -> dict:
    """Validate supplied objects without mutation; use load_proposal for real files.

    This in-memory API cannot authenticate caller-supplied dictionaries. Validity
    means source-text/structure consistency, never a final policy determination.
    """
    try:
        return _validate(proposal, phase4, pdf_text)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError("Malformed proposal or baseline structure") from exc


def load_proposal(path: Path, *, project_root: Path, local_appdata_root: Path) -> dict:
    """Verify 20 pinned inputs, fixed run artifacts and original PDF quotes.

    No network, CLI, events, revision writes or gate evaluation. The FAQ records
    are historical measurements and are explicitly not revalidated by this loader.
    """
    root, local = Path(project_root), Path(local_appdata_root)

    def pinned(file: Path, digest: str) -> dict:
        raw = read_bytes(file)
        require(hashlib.sha256(raw).hexdigest() == digest, "Pinned input digest mismatch: " + str(file))
        return decode_json(raw)

    manifest = pinned(resolve_input(root, RUN + "source_manifest.json"), BINDINGS["source_manifest_sha256"])
    records, pdf_bytes = {}, {}
    require(len(manifest["input_artifacts"]) == 20, "Expected 20 manifest inputs")
    for entry in manifest["input_artifacts"]:
        base = root if entry["path_base"] == "PROJECT" else local
        raw = read_bytes(resolve_input(base, entry["path"]))
        require(len(raw) == entry["size_bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"],
                "Manifest input digest or size mismatch: " + entry["role"])
        if entry["role"] == "PDF":
            pdf_bytes[entry["document_id"]] = raw
        elif entry["role"] in {"PHASE3", "PHASE4"}:
            require(hashlib.sha256(raw).hexdigest() == BINDINGS[entry["role"].lower() + "_result_sha256"],
                    "Phase result binding mismatch")
            records[entry["role"]] = decode_json(raw)
    pinned(resolve_input(root, RUN + "page_analysis.json"), BINDINGS["page_analysis_sha256"])
    initial = pinned(resolve_input(root, RUN + "phase5_v2_review_draft.json"), BINDINGS["initial_draft_sha256"])
    require(initial["events"] == [] and initial["humanApproved"] is False
            and initial["java_import_ready"] is False, "Initial draft changed")
    import pdfplumber

    pdf_text = {}
    require(set(pdf_bytes) == set(DOCS), "Missing source PDF")
    for doc, raw in pdf_bytes.items():
        require(hashlib.sha256(raw).hexdigest() == DOCS[doc][2], "PDF digest mismatch")
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            require(len(pdf.pages) == DOCS[doc][1], "PDF page count mismatch")
            for number, page in enumerate(pdf.pages, 1):
                pdf_text[(doc, number)] = page.extract_text() or ""
    proposal = decode_json(read_bytes(Path(path)))
    return validate_proposal(proposal, phase4=records["PHASE4"], pdf_text=pdf_text)
