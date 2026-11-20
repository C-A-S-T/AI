"""Proposal contract and real-input checks; execute only after test approval.

Fixtures read the existing pinned local data and copy it per case. No reviewer
events, revisions, downloads, or source-file updates are performed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from src.policy_compare import review_correction_proposal as proposal


ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path(os.environ.get("CAST_AI_TEST_LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))


class CorrectionProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / proposal.PROPOSAL_PATH
        cls.original = json.loads(cls.path.read_bytes())
        cls.manifest = json.loads((ROOT / proposal.RUN / "source_manifest.json").read_bytes())
        phase = next(x for x in cls.manifest["input_artifacts"] if x["role"] == "PHASE4")
        cls.phase_path = LOCAL / phase["path"]
        cls.phase = json.loads(cls.phase_path.read_bytes())
        cls.pdf_text = {}
        for entry in cls.manifest["input_artifacts"]:
            if entry["role"] == "PARSED":
                parsed = json.loads((ROOT / entry["path"]).read_bytes())
                cls.pdf_text.update({(entry["document_id"], n): p["text"]
                                     for n, p in enumerate(parsed["pages"], 1)})

    def setUp(self):
        self.data = copy.deepcopy(self.original)
        self.baseline = copy.deepcopy(self.phase)
        self.texts = copy.deepcopy(self.pdf_text)

    def validate(self, data=None):
        return proposal.validate_proposal(self.data if data is None else data,
                                          phase4=self.baseline, pdf_text=self.texts)

    def item(self, cid, data=None):
        document = self.data if data is None else data
        return next(x for x in document["p0_items"] + document["related_items"]
                    if x["comparison_id"] == cid)

    def test_valid_analysis_is_not_approval_and_does_not_mutate(self):
        before = copy.deepcopy((self.data, self.baseline, self.texts))
        result = self.validate()
        self.assertEqual(result["status"], "VALID_AI_PROPOSAL_NOT_APPROVAL")
        self.assertEqual((result["p0_items"], result["related_items"]), (13, 2))
        self.assertEqual(result["disposition_counts"],
                         {"RETAIN_PROPOSAL": 2, "REVISE_PROPOSAL": 6,
                          "SPLIT_PROPOSAL": 2, "INSUFFICIENT_EVIDENCE": 3})
        for key in ("humanApproved", "java_import_ready", "gate_trust_updated"):
            self.assertIs(result[key], False)
        self.assertEqual(before, (self.data, self.baseline, self.texts))

    def test_missing_duplicate_unknown_and_cross_bucket_ids(self):
        for case in ("missing", "duplicate", "unknown", "cross_bucket"):
            with self.subTest(case=case):
                data = copy.deepcopy(self.original)
                if case == "missing":
                    data["p0_items"].pop()
                elif case == "duplicate":
                    data["p0_items"][-1] = copy.deepcopy(data["p0_items"][0])
                elif case == "unknown":
                    data["p0_items"][0]["comparison_id"] = "UNKNOWN"
                else:
                    data["p0_items"][0], data["related_items"][0] = (
                        data["related_items"][0], data["p0_items"][0])
                with self.assertRaisesRegex(ValueError, "Proposal ID coverage invalid"):
                    self.validate(data)

    def test_full_snapshot_changes_are_rejected(self):
        for field, value in (("proposed_change_type", "UPDATED"), ("scope_id", "WRONG_SCOPE"),
                             ("adjudication_reason", "Invented reason"), ("change_key", "OTHER")):
            with self.subTest(field=field):
                data = copy.deepcopy(self.original)
                data["p0_items"][0]["baseline_snapshot"][field] = value
                with self.assertRaisesRegex(ValueError, "Baseline snapshot mismatch"):
                    self.validate(data)

    def test_relationship_drift_is_rejected(self):
        for field, value in (("child_ids", []), ("change_group_id", "OTHER"),
                             ("summary_role", "PRIMARY"), ("baseline_scope_id", "OTHER")):
            with self.subTest(field=field):
                data = copy.deepcopy(self.original)
                self.item("DOC_LEASE_ALTERNATIVES", data)["dependencies"][field] = value
                with self.assertRaisesRegex(ValueError, "Baseline relationship mismatch"):
                    self.validate(data)
        data = copy.deepcopy(self.original)
        data["p0_items"][0]["related_comparison_ids"].append("UNKNOWN")
        with self.assertRaisesRegex(ValueError, "Unknown related comparison ID"):
            self.validate(data)

    def test_evidence_page_digest_quote_and_document_errors(self):
        for field, value, message in (
            ("page", 99, "Evidence identity, page or digest mismatch"),
            ("pdf_sha256", "0" * 64, "Evidence identity, page or digest mismatch"),
            ("document_id", "UNKNOWN", "Unknown evidence document"),
            ("quote", "This text does not occur in either PDF", "Evidence quote not in PDF"),
            ("verification", "PAGE_CONFIRMED", "Invalid evidence verification claim"),
        ):
            with self.subTest(field=field):
                data = copy.deepcopy(self.original)
                data["p0_items"][0]["evidence"][0][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.validate(data)

    def test_duplicate_evidence_and_missing_year(self):
        for case in ("duplicate", "one_year"):
            with self.subTest(case=case):
                data = copy.deepcopy(self.original)
                refs = data["p0_items"][0]["evidence"]
                if case == "duplicate":
                    refs.append(copy.deepcopy(refs[0]))
                    message = "Duplicate evidence"
                else:
                    data["p0_items"][0]["evidence"] = [r for r in refs if r["year"] == 2025]
                    message = "Both years need contextual evidence"
                with self.assertRaisesRegex(ValueError, message):
                    self.validate(data)

    def test_inconclusive_and_candidate_not_automatically_finalized(self):
        for cid, new_type in (("RENT_BELOW_CAP_PAYMENT", "UPDATED"),
                              ("DOC_ADMIN_CONSENT", "ADDED")):
            with self.subTest(cid=cid):
                data = copy.deepcopy(self.original)
                self.item(cid, data)["recommendation"]["proposed_change_type"] = new_type
                with self.assertRaisesRegex(ValueError, "Unapproved proposed type change|Unknown proposed type"):
                    self.validate(data)
        data = copy.deepcopy(self.original)
        data["p0_items"][0]["assessment"]["finalization"] = "FINAL"
        with self.assertRaisesRegex(ValueError, "Invalid assessment status"):
            self.validate(data)

    def test_no_event_or_trust_escalation_fields(self):
        for key, value in (("events", []), ("actions", []), ("trusted_provenance_docs", []),
                           ("reviewer_id", "invented-reviewer"), ("final_change_type", "UPDATED")):
            with self.subTest(key=key):
                data = copy.deepcopy(self.original)
                data["p0_items"][0]["recommendation"][key] = value
                with self.assertRaisesRegex(ValueError, "Forbidden event or personal-data field"):
                    self.validate(data)
        for key in ("humanApproved", "java_import_ready"):
            with self.subTest(flag=key):
                data = copy.deepcopy(self.original)
                data[key] = True
                with self.assertRaisesRegex(ValueError, "Approval flags must remain false"):
                    self.validate(data)

    def test_absence_is_ai_analysis_only(self):
        for key, value in (("human_attested", True), ("pages", [1, 2]), ("method", "ABSENCE_REVIEWED")):
            with self.subTest(key=key):
                data = copy.deepcopy(self.original)
                self.item("DOC_ADMIN_CONSENT", data)["absence_analysis"][key] = value
                with self.assertRaisesRegex(ValueError, "Absence analysis is not human attestation"):
                    self.validate(data)

    def test_historical_hashes_and_unknown_times_are_preserved(self):
        for collection, field, value, message in (
            ("source_observations", "remote_sha256", "0" * 64, "Historical source observation changed"),
            ("source_observations", "checked_at", "2026-11-20T12:00:00+09:00", "Historical source observation changed"),
            ("supplemental_sources", "sha256", "0" * 64, "Historical FAQ observation changed"),
            ("supplemental_sources", "checked_at", "2026-11-20T12:00:00+09:00", "Historical FAQ observation changed"),
        ):
            with self.subTest(collection=collection, field=field):
                data = copy.deepcopy(self.original)
                data[collection][0][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.validate(data)

    def test_income_formula_denominator_and_counting_guards(self):
        cases = (
            ("ONE_PERSON_INCOME_THRESHOLDS", "explanation", "보험료가 소득액으로 증가", "Income metric separation missing"),
            ("RENT_CONVERSION_FORMULA", "current_value", "보증금 × 5%", "Formula correction or deduplication missing"),
            ("TIER_DISTRIBUTION", "current_value", "35/30/20/15%", "Selection denominators missing"),
            ("SUSPENSION_EFFECT", "counting_policy", "COUNT_PARENT_AGAIN", "Additional change counting forbidden"),
        )
        for cid, field, value, message in cases:
            with self.subTest(cid=cid):
                data = copy.deepcopy(self.original)
                self.item(cid, data)["recommendation"][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.validate(data)

    def test_p0_counts_exclude_related_items(self):
        self.data["disposition_counts"]["REVISE_PROPOSAL"] = 7
        with self.assertRaisesRegex(ValueError, "P0 disposition counts mismatch"):
            self.validate()

    def test_baseline_coverage_not_weakened(self):
        for case in ("missing_member", "duplicate_member", "unknown_member", "item_count", "group_count"):
            with self.subTest(case=case):
                phase = copy.deepcopy(self.phase)
                comp = phase["comparisons"][0]
                if case == "missing_member":
                    comp["reviewGroups"][0]["comparison_ids"].pop()
                elif case == "duplicate_member":
                    comp["reviewGroups"][0]["comparison_ids"].append(comp["displayItems"][0]["comparison_id"])
                elif case == "unknown_member":
                    comp["reviewGroups"][0]["comparison_ids"].append("UNKNOWN")
                elif case == "item_count":
                    comp["displayItems"].pop()
                else:
                    comp["reviewGroups"].pop()
                message = ("Expected 82 unique baseline items" if case == "item_count"
                           else "Baseline counts changed" if case == "group_count"
                           else "Baseline group coverage invalid")
                with self.assertRaisesRegex(ValueError, message):
                    proposal.validate_proposal(copy.deepcopy(self.original), phase4=phase,
                                               pdf_text=copy.deepcopy(self.pdf_text))

    def test_malformed_objects_and_unknown_fields(self):
        for key, value in (("p0_items", None), ("related_items", [None]), ("baseline_bindings", {})):
            with self.subTest(key=key):
                data = copy.deepcopy(self.original)
                data[key] = value
                with self.assertRaisesRegex(ValueError, "Malformed|Proposal ID coverage|Baseline binding mismatch"):
                    self.validate(data)
        self.data["unexpected"] = "field"
        with self.assertRaisesRegex(ValueError, "Invalid fields: proposal"):
            self.validate()

    def test_personal_data_fields_are_not_policy_requirements(self):
        self.data["p0_items"][0]["recommendation"]["account_number"] = "synthetic-not-a-real-account"
        with self.assertRaisesRegex(ValueError, "Forbidden event or personal-data field"):
            self.validate()
        self.assertIn("주민번호", self.item("DOC_ADMIN_CONSENT", self.original)["recommendation"]["current_value"])

    def test_stage_b_obligations_and_no_automatic_conversion(self):
        self.data["stage_b_followup"].remove("REJECTED_IS_NOT_COMPLETE")
        with self.assertRaisesRegex(ValueError, "Stage B obligations changed"):
            self.validate()
        data = copy.deepcopy(self.original)
        data["p0_items"][0]["event_compatibility"]["automatic_conversion"] = True
        with self.assertRaisesRegex(ValueError, "Automatic or premature event conversion"):
            self.validate(data)

    def test_loader_rejects_corrupted_inputs_without_modifying_files(self):
        targets = [ROOT / proposal.RUN / "source_manifest.json",
                   ROOT / proposal.RUN / "page_analysis.json",
                   ROOT / proposal.RUN / "phase5_v2_review_draft.json", self.phase_path]
        pdf = next(x for x in self.manifest["input_artifacts"] if x["role"] == "PDF")
        targets.append(ROOT / pdf["path"])
        real_read = proposal.read_bytes
        for target in targets:
            with self.subTest(target=str(target)):
                before = hashlib.sha256(target.read_bytes()).hexdigest()

                def corrupted(path, selected=target):
                    raw = real_read(path)
                    return raw + b" " if Path(path) == selected else raw

                with patch.object(proposal, "read_bytes", side_effect=corrupted):
                    with self.assertRaisesRegex(ValueError, "Pinned input digest mismatch|Manifest input digest or size mismatch"):
                        proposal.load_proposal(self.path, project_root=ROOT, local_appdata_root=LOCAL)
                self.assertEqual(before, hashlib.sha256(target.read_bytes()).hexdigest())

    def test_real_loader_is_offline_and_preserves_registered_files(self):
        paths = [self.path, ROOT / proposal.RUN / "source_manifest.json",
                 ROOT / proposal.RUN / "page_analysis.json",
                 ROOT / proposal.RUN / "phase5_v2_review_draft.json"]
        paths += [(ROOT if x["path_base"] == "PROJECT" else LOCAL) / x["path"]
                  for x in self.manifest["input_artifacts"]]
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        with patch("socket.create_connection", side_effect=AssertionError("Network forbidden")):
            result = proposal.load_proposal(self.path, project_root=ROOT, local_appdata_root=LOCAL)
        self.assertEqual(result["status"], "VALID_AI_PROPOSAL_NOT_APPROVAL")
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


if __name__ == "__main__":
    unittest.main()
