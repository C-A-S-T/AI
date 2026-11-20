"""Offline review-input CLI. Commands never authenticate reviewers or publish policy."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .review_v2_contract import require
from .review_v2_input import (
    apply_actions, load_review_context, read_action_request, _revision_dir,
)
from .review_v2_inspect import (
    review_status, review_queue, review_show, review_template, review_history,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 5 v2 offline review input (self-attested; never publication approval)"
    )
    parser.add_argument("--offline", required=True, action="store_true")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--local-appdata-root", type=Path, required=True)
    parser.add_argument("--review-draft", type=Path,
                        help="Pinned initial JSON or existing revision (default: latest)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Current progress and unresolved blockers")
    queue = commands.add_parser("queue", help="Prioritized pending reviews")
    queue.add_argument("--limit", type=int, default=50)
    show = commands.add_parser("show", help="Inspect original evidence and current decision")
    show.add_argument("--type", required=True, choices=(
        "PDF_PAGE", "FINDING", "COMPARISON", "ADDITIONAL_CANDIDATE", "CORRECTION"))
    show.add_argument("--id", required=True)
    show.add_argument("--full-text", action="store_true")
    template = commands.add_parser("template", help="Unattested, incomplete JSON input template")
    template.add_argument("--type", required=True, choices=(
        "PDF_PAGE", "FINDING", "COMPARISON", "ADDITIONAL_CANDIDATE"))
    template.add_argument("--id", required=True)
    template.add_argument("--action", required=True)
    template.add_argument("--output", type=Path,
                          help="Optional new UTF-8 template file outside the project")
    apply = commands.add_parser("apply", help="Validate actions, append to NEW revision only")
    apply.add_argument("--actions-file", type=Path, required=True)
    apply.add_argument("--dry-run", action="store_true")
    history = commands.add_parser("history", help="Read self-attested event history")
    history.add_argument("--type", choices=(
        "PDF_PAGE", "FINDING", "COMPARISON", "ADDITIONAL_CANDIDATE"))
    history.add_argument("--id")
    return parser


def _render(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        context = load_review_context(
            args.project_root, args.local_appdata_root, review_draft=args.review_draft,
        )
        if args.command == "status":
            output = review_status(context)
        elif args.command == "queue":
            output = review_queue(context, limit=args.limit)
        elif args.command == "show":
            output = review_show(context, args.type, args.id,
                                 full_text=args.full_text)
        elif args.command == "history":
            output = review_history(context, subject_type=args.type, subject_id=args.id)
        elif args.command == "template":
            output = review_template(context, args.type, args.id, args.action)
            if args.output is not None:
                target = args.output.absolute()
                require(not target.is_symlink() and not target.exists(),
                        "Template destination already exists")
                require(not target.resolve(strict=False).is_relative_to(context["root"]),
                        "Refusing to create a template inside the project")
                require(not target.resolve(strict=False).is_relative_to(
                    _revision_dir(context["local"])),
                    "Template cannot be placed in the revision directory")
                require(target.parent.exists() and target.parent.is_dir(),
                        "Template destination directory must already exist")
                with target.open("xb") as file:
                    file.write(_render(output))
                output = {"result": "UNATTESTED_TEMPLATE_CREATED", "path": str(target),
                          "warning": "Fill reviewer, time, reasons, references and payload; no review is recorded"}
        elif args.command == "apply":
            request = read_action_request(args.actions_file)
            output = apply_actions(context, request, dry_run=args.dry_run)
        else:
            raise ValueError("Unsupported command")
        sys.stdout.buffer.write(_render(output))
        return 0
    except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
        print(f"PHASE5_V2_INPUT_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
