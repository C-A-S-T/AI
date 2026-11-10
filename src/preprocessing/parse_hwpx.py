"""Read original HWPX table cells without assigning rendered PDF page numbers."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

MAX_SECTION_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def local_name(element: ET.Element) -> str:
    """Ignore namespace prefixes while retaining structural element names."""
    return element.tag.rsplit("}", 1)[-1]


def cell_text(element: ET.Element) -> str:
    """Keep paragraph boundaries and exclude nested-table text from its parent cell."""
    if local_name(element) == "tbl":
        return ""
    if local_name(element) == "t":
        return (element.text or "") + "".join(cell_text(child) + (child.tail or "") for child in element)
    if local_name(element) in {"lineBreak", "br"}:
        return "\n"
    if local_name(element) == "tab":
        return "\t"
    text = "".join(cell_text(child) for child in element)
    return text + ("\n" if local_name(element) == "p" else "")


def read_source_tables(path: Path) -> list[dict]:
    """Preserve addresses/spans and nesting; malformed structure fails visibly.

    Read XML in memory; never extract archive paths to disk. Limits bound the
    decompressed section data. Source tables are independent of PDF page tables.
    """
    records: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        sections = [i for i in archive.infolist()
                    if re.fullmatch(r"Contents/section[0-9]+\.xml", i.filename)]
        if not sections or len({i.filename for i in sections}) != len(sections):
            raise ValueError("HWPX sections missing or duplicated")
        if sum(i.file_size for i in sections) > MAX_TOTAL_BYTES:
            raise ValueError("HWPX sections exceed size limit")
        for info in sorted(sections, key=lambda i: int(re.search(r"section([0-9]+)", i.filename)[1])):
            if info.file_size > MAX_SECTION_BYTES:
                raise ValueError("HWPX section exceeds size limit")
            payload = archive.read(info)
            # ElementTree does not resolve external entities; reject DTDs as well.
            if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
                raise ValueError("HWPX XML declarations are not supported")
            root = ET.fromstring(payload)
            ordinal = 0

            def visit(node: ET.Element, parent_id: str | None = None,
                      parent_cell: dict | None = None) -> None:
                """Walk each nested table once, retaining the containing cell address."""
                nonlocal ordinal
                if local_name(node) != "tbl":
                    for child in node:
                        visit(child, parent_id, parent_cell)
                    return
                ordinal += 1
                table_id = f"{info.filename}#table-{ordinal}"
                rows, columns = int(node.attrib["rowCnt"]), int(node.attrib["colCnt"])
                if rows < 1 or columns < 1:
                    raise ValueError("HWPX table has invalid dimensions")
                record = {"table_id": table_id, "source_id": node.get("id"),
                          "section_path": info.filename, "parent_table_id": parent_id,
                          "parent_cell": parent_cell, "row_count": rows,
                          "column_count": columns, "cells": [],
                          "verification_status": "SOURCE_STRUCTURE_UNVERIFIED"}
                records.append(record)
                occupied = []
                for row in node:
                    if local_name(row) != "tr":
                        continue
                    for cell in row:
                        if local_name(cell) != "tc":
                            continue
                        children = {local_name(c): c for c in cell}
                        address, span = children["cellAddr"], children["cellSpan"]
                        x, y = int(address.attrib["colAddr"]), int(address.attrib["rowAddr"])
                        width, height = int(span.attrib["colSpan"]), int(span.attrib["rowSpan"])
                        if min(x, y) < 0 or min(width, height) < 1 or x + width > columns or y + height > rows:
                            raise ValueError("HWPX cell exceeds table dimensions")
                        bounds = (x, y, x + width, y + height)
                        if any(x < b[2] and bounds[2] > b[0] and y < b[3] and bounds[3] > b[1] for b in occupied):
                            raise ValueError("HWPX cell spans overlap")
                        occupied.append(bounds)
                        record["cells"].append({"row": y, "column": x, "row_span": height,
                                                "column_span": width, "text": cell_text(cell).strip(),
                                                "is_header": cell.get("header") == "1"})
                        for child in cell:
                            visit(child, table_id, {"row": y, "column": x})
            visit(root)
    return records
