"""Conservative PDF table diagnostics and region-scoped review candidates.

Candidates never silently replace default tables. Character coverage is a warning
signal, not proof of correct cell relationships. Blank/merged cells are legitimate.
"""
from __future__ import annotations

from collections import Counter
import re


def normalized(value: str) -> str:
    """Remove spacing only; preserve digits, punctuation and policy wording."""
    return re.sub(r"\s+", "", value)


def contains(outer, inner, tolerance: float = 2) -> bool:
    """Check containment in PDF coordinates with a small drawing tolerance."""
    return (outer[0] - tolerance <= inner[0] and outer[1] - tolerance <= inner[1]
            and outer[2] + tolerance >= inner[2] and outer[3] + tolerance >= inner[3])


def coverage(region_text: str, rows: list) -> dict:
    """Compare character multisets without assuming table reading order."""
    expected = Counter(normalized(region_text))
    actual = Counter(normalized("".join(cell or "" for row in rows for cell in row)))
    missing = expected - actual
    total = sum(expected.values())
    return {"region_character_count": total, "missing_character_count": sum(missing.values()),
            "character_coverage": round(1 - sum(missing.values()) / total, 4) if total else 1.0}


def suspect_regions(page) -> list[dict]:
    """Find repeated ruled layouts, including tables without closing vertical rules.

    Require multiple horizontal levels plus vertical rules or repeated word
    alignment. A single separator/rectangle does not establish a suspected table.
    """
    lines = [e for e in page.edges if e.get("orientation") == "h" and e["x1"] - e["x0"] >= 30]
    groups = []
    for edge in sorted(lines, key=lambda e: e["top"]):
        matched = None
        for group in reversed(groups):
            last = max(e["top"] for e in group)
            left, right = min(e["x0"] for e in group), max(e["x1"] for e in group)
            overlap = min(right, edge["x1"]) - max(left, edge["x0"])
            if edge["top"] - last <= 100 and overlap >= 0.5 * min(right - left, edge["x1"] - edge["x0"]):
                matched = group
                break
        if matched is None:
            groups.append([edge])
        else:
            matched.append(edge)
    regions = []
    for group in groups:
        levels = {round(e["top"] / 3) for e in group}
        if len(levels) < 3:
            continue
        bbox = (max(page.bbox[0], min(e["x0"] for e in group)),
                max(page.bbox[1], min(e["top"] for e in group)),
                min(page.bbox[2], max(e["x1"] for e in group)),
                min(page.bbox[3], max(e["top"] for e in group)))
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        crop = page.crop(bbox)
        words = crop.extract_words()
        alignments = {}
        for word in words:
            alignments.setdefault(round(word["x0"] / 6), set()).add(round(word["top"] / 4))
        aligned_columns = sum(len(ys) >= 3 for ys in alignments.values())
        verticals = sum(e.get("orientation") == "v" and bbox[0] <= e["x0"] <= bbox[2]
                        and e["bottom"] >= bbox[1] and e["top"] <= bbox[3] for e in page.edges)
        if len(words) >= 4 and (verticals >= 2 or aligned_columns >= 2):
            regions.append({"bbox": list(bbox), "horizontal_levels": len(levels),
                            "vertical_rules": verticals, "aligned_columns": aligned_columns})
    return regions


def extract_tables_with_quality(page) -> tuple[list, list, dict, list[str]]:
    """Return compatible tables, aligned details, diagnostics and review warnings."""
    tables, details, warnings = [], [], []
    quality = {"status": "NOT_FLAGGED", "suspected_regions": [], "review_candidates": [],
               "limitations": "Heuristic checks cannot prove table completeness or correct column mapping"}
    try:
        found = page.find_tables()
        for table in found:
            rows = table.extract()
            index = len(tables)
            region_text = page.crop(table.bbox).extract_text() or ""
            metrics = coverage(region_text, rows)
            flags = []
            if len(rows) <= 1:
                flags.append("SINGLE_ROW_TABLE_REVIEW")
            if metrics["missing_character_count"]:
                flags.append("TABLE_TEXT_NOT_FULLY_CAPTURED")
            tables.append(rows)
            details.append({"table_index": index, "bbox": list(table.bbox),
                            "method": "default_lines", "cells": [list(c) for c in table.cells],
                            "coverage": metrics, "flags": flags, "contained_table_indexes": []})
        for outer in details:
            for inner in details:
                if outer["table_index"] != inner["table_index"] and contains(outer["bbox"], inner["bbox"]):
                    outer["contained_table_indexes"].append(inner["table_index"])
            if outer["contained_table_indexes"]:
                outer["flags"].append("OVERLAPPING_OR_NESTED_TABLES_REVIEW")
        regions = suspect_regions(page)
        quality["suspected_regions"] = regions
        for region in regions:
            bbox = region["bbox"]
            selected = [d["table_index"] for d in details if contains(bbox, d["bbox"])]
            text = page.crop(bbox).extract_text() or ""
            rows = [row for i in selected for row in tables[i]]
            metrics = coverage(text, rows)
            region.update(table_indexes=selected, coverage=metrics, flags=[])
            if not selected:
                region["flags"].append("SUSPECTED_TABLE_NOT_EXTRACTED")
            elif metrics["character_coverage"] < 0.98:
                region["flags"].append("SUSPECTED_TABLE_REGION_INCOMPLETE")
            if not region["flags"]:
                continue
            crop = page.crop(bbox)
            profiles = [("joined_lines_with_outer_bounds", {
                "join_tolerance": 6, "snap_tolerance": 3,
                "explicit_vertical_lines": [bbox[0], bbox[2]]}),
                ("text_alignment", {"vertical_strategy": "text", "horizontal_strategy": "text",
                                     "min_words_vertical": 3, "min_words_horizontal": 2})]
            for method, settings in profiles:
                try:
                    for candidate in crop.find_tables(settings):
                        candidate_rows = candidate.extract()
                        quality["review_candidates"].append({
                            "region_bbox": bbox, "bbox": list(candidate.bbox), "method": method,
                            "tables": candidate_rows, "settings": settings,
                            "coverage": coverage(crop.extract_text() or "", candidate_rows),
                            "selection_status": "UNVERIFIED_NOT_SELECTED"})
                except Exception as exc:
                    region["flags"].append(f"CANDIDATE_EXTRACTION_FAILED:{method}:{type(exc).__name__}")
        for detail in details:
            warnings.extend(f"Table {detail['table_index']}: {flag}" for flag in detail["flags"])
        for i, region in enumerate(regions):
            warnings.extend(f"Table region {i}: {flag}" for flag in region["flags"])
    except Exception as exc:
        warnings.append(f"TABLE_QUALITY_CHECK_FAILED:{type(exc).__name__}: {exc}")
    if tables:
        warnings.append("Extracted table row/column alignment requires review")
    if warnings:
        quality["status"] = "REVIEW_REQUIRED"
    return tables, details, quality, warnings
