# AI
C.A.S.T 프로젝트의 AI 레포지토리입니다.

# C.A.S.T. AI - PDF/HWP/HWPX data preparation

AI/data-processing **only**. The Spring Boot backend and PostgreSQL/JPA project are
maintained separately in IntelliJ; there is no backend server or DB migration here.

## What this first phase does

1. Reads PDF/HWP/HWPX originals from `data/raw/<category>/<year>/` without changing the originals.
2. Computes SHA-256 and reports duplicate contents.
3. Extracts per-page text, tables and simple quality signals using `pdfplumber` into `data/parsed/`.
4. Performs conservative whitespace cleanup into `data/cleaned/`.
5. Creates `metadata/documents.json`, `metadata/document_relations.json`, and `reports/ingestion_report.json`.

**Not implemented:** OCR, chunking, embedding, RAG, model training, database writes,
or automatic fact verification. Short/empty/scanned-looking pages and tables are flagged
for human review. This phase prepares documents for later *RAG indexing*, not model training.

## Where to put source documents

- `data/raw/youth-rent/2024|2025|2026/`
- `data/raw/seoul-housing/2025|2026/`
- `data/raw/gyeonggi-housing/2025|2026/`
- `data/raw/student-loan/2025|2026/`

Within each year, additional subfolders are allowed. Keep the original PDF bytes and
relative paths stable after processing. Replacing a processed PDF at the same path
triggers a review error rather than overwriting cached extractions.

## Environment (Windows PowerShell)

Requires Python 3.11+ and PDF-processing dependency installation.

```powershell
cd CAST_AI
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe pipeline.py
```

**Do not run yet:** execution and PDF tests require a separate approval after diff review.

## Optional official source metadata (no Excel)

A PDF does not reliably include the official download URL or enough information to
identify document-to-document relations. Copy `metadata/sources.example.json` to
`metadata/sources.json`, and use each original document's raw-relative path as the key.
The example filenames are placeholders, not automatically downloaded files.

The following fields can be supplied as strings or `null` (do not invent dates/URLs):

- Official source and dates: `source_page_url`, `download_url`, `published_at`,
  `effective_from`, `effective_to`, `organization`
- Document identity: `document_title`, `announcement_title`, `document_role`,
  `program_name`, `announcement_id`, `application_term` (e.g. student-loan semester)
- Optional relationships: `related_documents` is a list of objects with
  `relation_type` and `target_raw_path` (a path relative to `data/raw/`).

Allowed `document_role`: `PRIMARY_NOTICE`, `CORRECTION_NOTICE`, `ATTACHMENT`,
`GUIDELINE`, `FAQ`, `OTHER`.
Allowed relation types: `CORRECTS`, `ATTACHMENT_OF`, `SUPPLEMENTS`.
For instance, a correction PDF may declare `CORRECTS` pointing to its original PDF.
Relationships are **user-provided and unverified by the pipeline**. Missing targets and
self-references produce warnings; no relation is inferred from the filename alone.
`announcement_id` links documents associated with the same announcement only when
someone has confirmed that fact. Official source URLs not supplied produce warnings.

## File safety, incomplete runs and review signals

- Source PDF bytes are never rewritten, renamed or deleted by the pipeline.
- Same-content duplicate PDFs stay in place and are reported, not removed.
- Parsed and cleaned JSON is first written to a same-directory temporary file and
  atomically published. The pipeline assumes a single writer (do not run two copies
  at the same time).
- A crash between publishing `parsed/` and `cleaned/` may leave only `parsed/`.
  On a later run, this is detected and the cleaned output is regenerated from the
  existing matching parsed data (`RECOVERED_CLEANED`). If `cleaned/` exists without
  `parsed/`, or an existing extraction's identity/hash differs, it is preserved
  and flagged for manual review. No automatic cleanup of old files occurs.
- Generated metadata/report JSON is atomically refreshed on each run.
- The parser records per-page character, table and image counts; review statuses
  (`EXTRACTED`, `REVIEW_REQUIRED`, `OCR_REVIEW`) and specific warnings. These are
  heuristic signals, **not proof that a PDF was correctly extracted**. This phase
  does not perform OCR or guarantee that table cells/reading order are correct.
- Generated data and source PDF/HWP/HWPX documents are ignored by Git by default.
- `READY_FOR_NEXT_STAGE` means no basic extraction warning, **not** validated facts.

## Exit codes and reports

| Exit code | `pipeline_status` | Meaning |
|---|---|---|
| `0` | `SUCCESS` | All discovered documents were processed or reused; review warnings may still exist |
| `1` | `PARTIAL_FAILURE` | At least one document succeeded and one failed |
| `2` | `FAILED` | Every document failed, no documents were found, or initial configuration failed |

Failure records and review counts are saved in `reports/ingestion_report.json`.
A failure writing the report or generated index may also cause an uncaught OS error;
in that case check filesystem permissions/free space before re-running.

## Planned next phases (not coded yet)

- Human review of extracted policy details, source identities, and correction/attachment relationships.
- Document/section-aware chunking with page and source references.
- Embeddings, retrieval evaluation, and the integration contract with Spring Boot.
- Evidence-backed Claim verification and an evaluation dataset.

## HWP/HWPX conversion (Windows preprocessing only)

One `python pipeline.py` invocation discovers `.pdf`, `.hwp`, and `.hwpx`
(case-insensitive) under `data/raw/`. PDFs use the existing parser directly.
Hangul documents are converted sequentially into `data/converted/DOC-<id>.pdf`,
then passed to the same parser. Every original still has its own parsed/cleaned
JSON; `metadata/documents.json` lists all successfully processed originals.
Converted PDFs are not registered as separate source documents.

Install requirements only after approval. `pywin32` is declared for Windows only;
a working desktop Hangul installation with COM registration is also required.
No conversion service is added to FastAPI or Linux Docker. PDF-only runs and
verified cached conversions do not initialize COM. New conversions require Windows.

`--conversion-timeout 120` sets the per-document time limit in seconds, including
security prompts and cleanup. Security prompts remain enabled and require the
user's response. No security module is registered, no messages are suppressed,
and no forced-open options are used. The worker opens a private copy under
`converted/`; the original is never passed to COM. Original hashes are checked
before and after conversion. Keep only one pipeline process running at a time.

COM calls are `DispatchEx("HWPFrame.HwpObject")`, `Open(path, "", "")`,
`SaveAs(path, "PDF", "")`, `Clear(1)` and `Quit()`. The empty input format enables
Hangul's format detection. Ownership is checked via `XHwpWindows.Item(0).WindowHandle`
and its process ID before opening the copy. Existing processes are never closed.
API availability, HWPX filters, fonts, table layout and PDF export remain subject
to the installed version and must be verified with separately approved real-file tests.
References: [Hancom automation guide](https://developer.hancom.com/hwpautomation),
[Hancom format-detection guidance](https://forum.developer.hancom.com/t/saveas-pdf/2770),
[HWPX support](https://www.hancom.co.kr/support/faqCenter/faq/detail/2784).

### Conversion journal and recovery

`metadata/conversions.json` is created at runtime, uses `schema_version: 1`, and
maps document IDs under `conversions`. Each record contains original format/path/hash,
converted path/hash, status, attempt time and actual conversion time. Historical
records are retained. Existing source identity fields keep their meanings:
`file_hash_sha256` always identifies the original, including for HWP/HWPX.
HWP/HWPX parsed and cleaned JSON add `source_format` and `converted_sha256`;
document metadata adds `source_format`. These are optional schema-version-1
extensions; consumers must allow additional fields. PDF output fields are unchanged.

- `RUNNING`: recorded before COM; an interrupted run requires manual cleanup review.
- `READY`: PDF is validated and its hash is durable; next run can finish publication
  from the temporary file or verify an already published final file.
- `SUCCESS`: reuse only after verifying identity, PDF hash and at least one page.
- `FAILED`: a safe failure may be retried if the original is unchanged and no final
  PDF or extraction exists. The latest error is recorded.
- `BLOCKED`: cleanup could not be confirmed; new COM jobs are disabled, including
  after restart. PDFs and verified cached conversions can still be processed.

Timeouts terminate only the Python worker, never arbitrary Hangul processes. For
`RUNNING`/`BLOCKED`, inspect and close only the conversion instance manually. After
confirming cleanup, review the journal and outputs before explicitly changing that
record to `FAILED`; retain its identity fields and original error for diagnosis.
This is a manual recovery action, not something the pipeline silently performs.

Changed originals, missing/corrupt successful conversions, untracked final PDFs,
or extraction/conversion hash mismatches are preserved for review, not overwritten.
A partial PDF is never accepted solely because it exists. Prepared publication
uses an exclusive hard link on the same filesystem, followed by unlinking the
staging name, so existing destinations cannot be overwritten. The filesystem must
support hard links (for example NTFS). Interrupted working directories may remain
for inspection; there is no bulk cleanup. The existing parsed-only recovery still
regenerates cleaned JSON after validating the conversion identity.

### Reporting and verification

`scanned_pdf_count`, `scanned_hwp_count` and `scanned_hwpx_count` count originals.
For each of `hwp` and `hwpx`, `*_conversion_success_count`, `*_conversion_failed_count`,
`*_conversion_reused_count`, `*_conversion_recovered_count` and
`*_conversion_skipped_count` describe conversion outcomes independently of parsing.
A conversion can succeed even when later parsing fails. `newly_parsed_count` counts
new successful extractions; `registered_count` includes cached and recovered results.
`failed_count` is the overall document failure count. Existing exit codes remain 0/1/2.
Unsupported extensions are excluded; no HWP/HWPX semantic deduplication is attempted.

Tests in `tests/test_hwp_pipeline.py` use temporary directories, synthetic PDFs and
mock conversion runners. They do not open real Hangul documents or initialize COM.
After separate test approval, run `python -m unittest discover -s tests -v`.
Real HWP/HWPX conversion, Korean paths, tables, damaged documents and security-prompt
behavior require a separate approved test using copies of selected source documents.
No test or real conversion has been executed as part of implementation.

## Table quality review and extraction version 2

New parsed/cleaned output includes `extraction_version: 2`. Existing outputs with
an absent/different version raise `REEXTRACTION_REQUIRED`; they are never silently
reused, migrated or overwritten. Compare new results in a separate test output
root first. Replacing existing extraction files needs separate approval. Conversion
PDF caches remain independent of this parser version.

Page `tables` retain the default pdfplumber result shape. `table_details` align by
`table_index` and add bounding boxes, cell coordinates, extraction method, character
coverage and containment relationships. Repeated ruled/aligned layouts are recorded
under `table_quality.suspected_regions`. Missing tables, incomplete region coverage,
single-row detections, overlaps and diagnostic exceptions produce review warnings.
A `null`/empty cell alone is not an error: it can represent a merged or blank cell.

Incomplete regions also receive line-joining/outer-boundary and text-alignment
alternatives under `table_quality.review_candidates`. They are marked
`UNVERIFIED_NOT_SELECTED`, do not replace `tables`, and must not be concatenated
into a retrieval corpus. Review the rendered page before selecting an alternative.
More tables or higher character coverage do not prove correct column semantics.
The geometry thresholds are heuristics; false positives and false negatives remain
possible. `NOT_FLAGGED` is not a claim that no table exists.

For HWPX, document-level `source_tables` preserve XML section/order IDs, original
IDs, row/column addresses, merged spans and nested-table relationships. Parent cell
text excludes nested-table text to avoid duplication. PDF page mapping is deliberately
absent. These records are marked `SOURCE_STRUCTURE_UNVERIFIED`; source formatting
can also use tables, so a table is not automatically a policy-data record. XML table
presence marks the document for review. Malformed/missing section data, overlapping
cell spans or out-of-bounds cells fail the document visibly. The reader uses only
standard-library ZIP/XML, reads sections in memory with size limits, and does not
extract archive paths to disk. Binary HWP continues to use PDF-based extraction.

Both `source_tables` and page diagnostics survive cleaning. Existing JSON keys and
`schema_version: 1` remain; these are additive fields requiring permissive consumers.
The additional version distinguishes processing semantics from JSON compatibility.

`tests/test_table_quality.py` adds isolated tests for missing/partial/nested tables,
blank/merged cells, original HWPX nesting and spans, unselected alternatives, old
cache rejection and metadata preservation. Implementation does not constitute a
successful rerun on the previously reviewed documents: tests and real-file result
comparison require separate approval. No existing extraction has been replaced.
