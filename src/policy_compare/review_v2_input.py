"""Offline Phase 5 v2 review input: explicit human assertions, append-only revisions.

No remote network, automatic PDF confirmation, authenticated approval, Java import
or mutation of any existing review draft/source is performed by this module.
"""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .review_decision import event_hash
from .review_lineage import load_page_analysis, load_verified_inputs
from .review_source_manifest import resolve_input
from .review_v2_contract import (
    ANALYSIS_SHA256, PHASE3_SHA256, PHASE4_SHA256, GENESIS,
    load_json_with_digest, require, sha256,
)
from .review_v2_decision import (
    COMPARISON_ACTIONS, CANDIDATE_ACTIONS, replay_events,
)
from .review_v2_gate import evaluate_gate_v2
from .review_v2_source import FINDING_ACTIONS, PAGE_ACTIONS

REVIEW_RELATIVE = (
    "metadata/policy_review_runs/seoul_youth_rent_2025_2026/20261117_v1"
)
REVISION_NAME = re.compile(r"^review_rev_(\d{4})\.json$")
EVENT_NAME = re.compile(r"^EV-(\d{6})$")
MAX_ACTION_BYTES = 1_000_000
ACTION_FIELDS = {
    "event_type", "subject_id", "action", "reviewer_id", "reviewed_at",
    "reason", "source_references", "payload",
}
ACTIONS = {
    "PDF_PAGE": PAGE_ACTIONS,
    "FINDING": FINDING_ACTIONS,
    "COMPARISON": COMPARISON_ACTIONS,
    "ADDITIONAL_CANDIDATE": CANDIDATE_ACTIONS,
}


def _revision_dir(local_root: Path) -> Path:
    return local_root / "CAST_AI" / "policy_compare_reviews" / "v2" / "revisions"


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def _check_storage_path(local_root: Path, path: Path) -> None:
    """Reject symlink/reparse redirection through revision root and descendants."""
    base = local_root.resolve(strict=True)
    target = path.absolute()
    require(_inside(target, base), "Review path must remain within LocalAppData")
    current = base
    for part in target.relative_to(base).parts:
        current = current / part
        require(not current.is_symlink(), "Symlinked review storage path rejected")
        if current.exists():
            require(current.resolve() == current.absolute(),
                    "Reparsed review storage path rejected")


def _revisions(local_root: Path) -> list[tuple[int, Path]]:
    directory = _revision_dir(local_root)
    _check_storage_path(local_root, directory)
    if not directory.exists():
        return []
    require(directory.is_dir(), "Revision storage path is not a directory")
    result = []
    for child in directory.iterdir():
        match = REVISION_NAME.fullmatch(child.name)
        if match:
            _check_storage_path(local_root, child)
            require(child.is_file() and not child.is_symlink(),
                    "Revision file is not a regular file")
            result.append((int(match.group(1)), child))
    result.sort()
    require(len({number for number, _ in result}) == len(result),
            "Duplicate revision sequence")
    return result


def _source_path(manifest: dict, role: str, project: Path, local: Path) -> Path:
    records = [entry for entry in manifest["input_artifacts"] if entry["role"] == role]
    require(len(records) == 1, f"Expected one {role} artifact")
    entry = records[0]
    require(entry["path_base"] in ("PROJECT", "LOCALAPPDATA"),
            "Unknown input base")
    return resolve_input(project if entry["path_base"] == "PROJECT" else local,
                         entry["path"])


def load_review_context(
    project_root: Path, local_appdata_root: Path,
    *, review_draft: Path | None = None,
) -> dict[str, Any]:
    """Read and byte-verify all 20 pinned inputs; never create or edit a file."""
    root = Path(project_root).resolve(strict=True)
    local = Path(local_appdata_root).resolve(strict=True)
    review = resolve_input(root, REVIEW_RELATIVE)
    manifest_path = review / "source_manifest.json"
    analysis_path = review / "page_analysis.json"
    analysis = load_page_analysis(
        analysis_path, manifest_path, project_root=root, local_appdata_root=local,
    )
    require(sha256(analysis_path.read_bytes()) == ANALYSIS_SHA256,
            "Changed Task-B analysis")
    manifest, records = load_verified_inputs(
        manifest_path, project_root=root, local_appdata_root=local,
    )
    phase3 = load_json_with_digest(_source_path(manifest, "PHASE3", root, local),
                                   PHASE3_SHA256)
    require(phase3.get("status") == "REVIEW_REQUIRED"
            and phase3.get("java_import_ready") is False,
            "Unapproved Phase 3 baseline changed")
    phase4 = load_json_with_digest(_source_path(manifest, "PHASE4", root, local),
                                   PHASE4_SHA256)
    pdf_text = {
        (doc, i): page["text"]
        for doc in (entry["document_id"] for entry in manifest["documents"])
        for i, page in enumerate(records[("PARSED", doc)]["pages"], start=1)
    }
    initial_path = review / "phase5_v2_review_draft.json"
    versions = _revisions(local)
    latest = versions[-1][1] if versions else initial_path
    source = latest if review_draft is None else Path(review_draft).resolve(strict=True)
    require(source == initial_path.resolve(strict=True)
            or source in (path.resolve(strict=True) for _, path in versions),
            "Input draft must be the pinned initial JSON or a stored revision")
    raw = source.read_bytes()
    require(len(raw) <= 4_000_000, "Review draft too large")
    draft = load_json_with_digest(source)
    report = evaluate_gate_v2(manifest, analysis, phase4, draft, pdf_text=pdf_text)
    state = replay_events(draft["events"], manifest, analysis, phase4,
                          draft["review_scope"], pdf_text)
    return {
        "root": root, "local": local, "manifest": manifest,
        "analysis": analysis, "phase4": phase4, "records": records,
        "pdf_text": pdf_text, "draft": draft, "draft_path": source,
        "draft_sha256": sha256(raw), "latest_path": latest.resolve(strict=True),
        "next_revision": versions[-1][0] + 1 if versions else 1,
        "state": state, "report": report,
    }


def _event_sequence(events: list[dict]) -> int:
    # Preserve pre-existing event IDs without claiming the old IDs have a
    # particular format. Never reuse a sequence already present in the history.
    numbers = [int(match.group(1)) for event in events
               if isinstance(event, dict)
               for match in [EVENT_NAME.fullmatch(str(event.get("event_id", "")))]
               if match]
    return max(numbers, default=0) + 1


def make_review_events(draft: dict, actions: list[dict]) -> tuple[dict, list[str]]:
    """Append ONLY explicit reviewed facts; require all user-authored fields."""
    require(isinstance(actions, list) and bool(actions), "Actions must be nonempty")
    require(len(actions) <= 200, "Too many actions in one revision")
    result = copy.deepcopy(draft)
    events = result["events"]
    used = {e["event_id"] for e in events}
    number = _event_sequence(events)
    created = []
    for action in actions:
        require(isinstance(action, dict) and set(action) == ACTION_FIELDS,
                "Invalid action fields")
        kind = action["event_type"]
        require(kind in ACTIONS and action["action"] in ACTIONS[kind],
                "Unsupported event/action")
        require(isinstance(action["subject_id"], str) and action["subject_id"].strip(),
                "Review subject required")
        require(isinstance(action["reviewer_id"], str) and action["reviewer_id"].strip()
                and isinstance(action["reviewed_at"], str) and action["reviewed_at"].strip()
                and isinstance(action["reason"], str) and action["reason"].strip(),
                "Explicit reviewer, review time and reason are required")
        require(isinstance(action["source_references"], list)
                and isinstance(action["payload"], dict),
                "Invalid source references or payload")
        while True:
            require(number <= 999999, "Event ID sequence exhausted")
            identifier = f"EV-{number:06d}"
            number += 1
            if identifier not in used:
                break
        event = {
            "schema_version": 2, "event_id": identifier,
            "event_type": kind, "subject": {"type": kind,
                                              "id": action["subject_id"]},
            "action": action["action"], "reviewer_id": action["reviewer_id"],
            "reviewed_at": action["reviewed_at"], "reason": action["reason"],
            "source_references": copy.deepcopy(action["source_references"]),
            "payload": copy.deepcopy(action["payload"]),
            "source_bindings": copy.deepcopy(draft["source_bindings"]),
            "previous_event_hash": events[-1]["event_hash"] if events else GENESIS,
        }
        event["event_hash"] = event_hash(event)
        events.append(event)
        used.add(identifier)
        created.append(identifier)
    return result, created


def _save_new_revision(local: Path, target: Path, data: bytes) -> None:
    """Write complete bytes, then atomically link under a never-used name.

    NTFS and POSIX local hard links provide no-overwrite publication. A crash
    cannot leave a partially written *revision*; any temporary file is cleaned
    on ordinary errors. If the filesystem disallows links, fail closed.
    """
    directory = _revision_dir(local)
    _check_storage_path(local, directory)
    directory.mkdir(parents=True, exist_ok=True)
    _check_storage_path(local, directory)
    require(not target.exists() and not target.is_symlink(),
            "Revision destination already exists")
    fd, tmp_name = tempfile.mkstemp(prefix=".cast-review-", suffix=".tmp", dir=directory)
    temporary = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def apply_actions(
    context: dict, request: dict,
    *, dry_run: bool = False,
) -> dict[str, Any]:
    """Validate the entire chain in memory; publish only a new numbered revision."""
    require(isinstance(request, dict)
            and set(request) == {"expected_draft_sha256", "actions"},
            "Invalid apply request")
    require(request["expected_draft_sha256"] == context["draft_sha256"],
            "Stale draft SHA256; reload status/template")
    require(context["draft_path"] == context["latest_path"],
            "Only the latest review revision may be extended")
    draft, identifiers = make_review_events(context["draft"], request["actions"])
    gate = evaluate_gate_v2(context["manifest"], context["analysis"],
                            context["phase4"], draft, pdf_text=context["pdf_text"])
    number = context["next_revision"]
    require(1 <= number <= 9999, "Revision number exhausted")
    target = _revision_dir(context["local"]) / f"review_rev_{number:04d}.json"
    _check_storage_path(context["local"], target)
    data = (json.dumps(draft, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    require(len(data) <= 4_000_000, "Revision JSON exceeds maximum size")
    if not dry_run:
        # Detect stale source/revision even if another writer arrived between
        # validation and publication. A concurrent writer to the SAME next
        # filename is also rejected by the exclusive hard link.
        require(context["draft_path"].is_file()
                and sha256(context["draft_path"].read_bytes()) == context["draft_sha256"],
                "Draft changed before saving")
        current_versions = _revisions(context["local"])
        current_latest = (current_versions[-1][1] if current_versions
                          else context["draft_path"])
        require(current_latest == context["latest_path"],
                "Newer revision exists; reload review")
        # All immutable registered input SHA-256 constraints are rechecked.
        for entry in context["manifest"]["input_artifacts"]:
            base = context["root"] if entry["path_base"] == "PROJECT" else context["local"]
            source = resolve_input(base, entry["path"])
            require(sha256(source.read_bytes()) == entry["sha256"],
                    "Pinned source changed during review")
        _save_new_revision(context["local"], target, data)
    return {
        "result": "VALIDATED_DRY_RUN" if dry_run else "REVISION_CREATED",
        "revision_path": str(target), "revision_sha256": sha256(data),
        "added_event_ids": identifiers,
        "event_count": len(draft["events"]),
        "blockers": [x["code"] for x in gate["blockers"]],
        "eligible_for_authenticated_publication_review":
            gate["eligible_for_authenticated_publication_review"],
        "humanApproved": False, "java_import_ready": False,
    }


def read_action_request(path: Path) -> dict:
    raw = Path(path).read_bytes()
    require(len(raw) <= MAX_ACTION_BYTES, "Action request too large")
    require(raw and not raw.startswith((b"\xff\xfe", b"\xfe\xff")),
            "Use UTF-8 for action request")
    def reject_duplicates(pairs):
        result = {}
        for key, val in pairs:
            require(key not in result, f"Duplicate request JSON key: {key}")
            result[key] = val
        return result

    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    try:
        value = json.loads(raw.decode("utf-8-sig"),
                           object_pairs_hook=reject_duplicates,
                           parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid action JSON: {exc}") from exc
    require(isinstance(value, dict), "Action request must be an object")
    return value
