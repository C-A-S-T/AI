# AI
C.A.S.T 프로젝트의 AI 레포지토리입니다.

# C.A.S.T. AI - PDF data preparation

AI/data-processing **only**. The Spring Boot backend and PostgreSQL/JPA project are
maintained separately in IntelliJ; there is no backend server or DB migration here.

## What this first phase does

1. Reads PDFs from `data/raw/<category>/<year>/` without changing the originals.
2. Computes SHA-256 and reports duplicate contents.
3. Extracts per-page text, tables and simple quality signals using `pdfplumber` into `data/parsed/`.
4. Performs conservative whitespace cleanup into `data/cleaned/`.
5. Creates `metadata/documents.json`, `metadata/document_relations.json`, and `reports/ingestion_report.json`.

**Not implemented:** OCR, chunking, embedding, RAG, model training, database writes,
or automatic fact verification. Short/empty/scanned-looking pages and tables are flagged
for human review. This phase prepares documents for later *RAG indexing*, not model training.

## Where to put PDFs

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
`metadata/sources.json`, and use each PDF's raw-relative path as the key.
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
- Generated data and source PDFs are ignored by Git by default.
- `READY_FOR_NEXT_STAGE` means no basic extraction warning, **not** validated facts.

## Exit codes and reports

| Exit code | `pipeline_status` | Meaning |
|---|---|---|
| `0` | `SUCCESS` | All discovered PDFs were processed or reused; review warnings may still exist |
| `1` | `PARTIAL_FAILURE` | At least one PDF succeeded and one failed |
| `2` | `FAILED` | Every PDF failed, no PDFs were found, or initial configuration failed |

Failure records and review counts are saved in `reports/ingestion_report.json`.
A failure writing the report or generated index may also cause an uncaught OS error;
in that case check filesystem permissions/free space before re-running.

## Planned next phases (not coded yet)

- Human review of extracted policy details, source identities, and correction/attachment relationships.
- Document/section-aware chunking with page and source references.
- Embeddings, retrieval evaluation, and the integration contract with Spring Boot.
- Evidence-backed Claim verification and an evaluation dataset.
