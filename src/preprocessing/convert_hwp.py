"""Sequential HWP/HWPX conversion with a durable, source-preserving journal.

COM runs only inside a bounded child process. Security prompts remain enabled.
The journal and output directories require a single pipeline writer.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber


class ConversionError(RuntimeError):
    """A conversion/cache failure; unsafe cleanup blocks subsequent COM jobs."""

    def __init__(self, message: str, *, unsafe: bool = False):
        super().__init__(message)
        self.unsafe = unsafe


def file_sha256(path: Path) -> str:
    """Hash bytes without changing the file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    """Return a timezone-aware journal timestamp."""
    return datetime.now(timezone.utc).isoformat()


def validate_pdf(path: Path) -> str:
    """Require a PDF header, a readable PDF and at least one page."""
    with path.open("rb") as stream:
        if not stream.read(1024).lstrip().startswith(b"%PDF-"):
            raise ConversionError(f"Not a PDF: {path}")
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            raise ConversionError(f"Converted PDF has zero pages: {path}")
    return file_sha256(path)


def _com_worker(source: str, target: str, connection) -> None:
    """Convert a private source copy; never attach to a user's existing Hwp process."""
    hwp = None
    owned = False
    initialized = False
    dispatch_started = False
    error = None
    cleanup_error = None
    try:
        import pythoncom
        import win32com.client
        import win32process
        pythoncom.CoInitialize()
        initialized = True
        existing_pids = set(win32process.EnumProcesses())
        dispatch_started = True
        hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
        hwnd = int(hwp.XHwpWindows.Item(0).WindowHandle)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid or pid in existing_pids:
            raise ConversionError("Cannot establish a private Hwp process", unsafe=True)
        owned = True
        # No RegisterModule, message suppression, force-open or security changes.
        # Empty format lets Hangul detect HWP/HWPX instead of trusting the suffix.
        if not hwp.Open(source, "", ""):
            raise ConversionError("Hangul Open returned false")
        if not hwp.SaveAs(target, "PDF", ""):
            raise ConversionError("Hangul SaveAs(PDF) returned false")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if hwp is not None and owned:
            try:
                hwp.Clear(1)  # Discard edits to the private input copy.
                hwp.Quit()
                hwp = None
                # Quit may return before process termination; verify bounded cleanup.
                deadline = time.monotonic() + 5
                while pid in win32process.EnumProcesses() and time.monotonic() < deadline:
                    time.sleep(0.1)
                if pid in win32process.EnumProcesses():
                    cleanup_error = "Private Hwp process did not exit; close it manually"
            except Exception as exc:
                cleanup_error = f"Hwp cleanup failed: {type(exc).__name__}: {exc}"
        elif dispatch_started:
            cleanup_error = "Hwp ownership unknown; no Quit or process termination attempted"
        hwp = None
        if initialized:
            pythoncom.CoUninitialize()
        connection.send({"error": error, "cleanup_error": cleanup_error})
        connection.close()


def run_com_conversion(source: Path, target: Path, timeout: float) -> None:
    """Run one bounded COM job; a timeout never kills arbitrary Hangul processes."""
    if os.name != "nt":
        raise ConversionError("New HWP/HWPX conversion requires Windows and Hangul")
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=_com_worker, args=(str(source), str(target), writer))
    try:
        process.start()
        writer.close()
        if not reader.poll(timeout):
            raise ConversionError(
                "COM timeout (possibly a security prompt). Inspect/close the conversion "
                "Hangul instance before retrying; further conversions are blocked", unsafe=True,
            )
        try:
            result = reader.recv()
        except EOFError as exc:
            raise ConversionError("COM worker exited without cleanup confirmation", unsafe=True) from exc
        process.join(5)
        if process.is_alive() or result["cleanup_error"]:
            raise ConversionError(result["cleanup_error"] or "Worker did not exit", unsafe=True)
        if result["error"]:
            raise ConversionError(result["error"])
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.terminate()  # Only the Python worker created here, never Hwp.exe.
            process.join(5)
        reader.close()
        writer.close()


class ConversionManager:
    """Validate and journal conversions; retain historical records across runs."""

    def __init__(self, root: Path, *, timeout: float = 120, runner=run_com_conversion):
        self.root = root.resolve()
        self.directory = self.root / "data" / "converted"
        self.journal_path = self.root / "metadata" / "conversions.json"
        self.timeout = timeout
        self.runner = runner
        self.journal = None
        self.blocked = False
        self.outcomes: dict[str, str] = {}

    def _load(self) -> None:
        """Load lazily so a broken conversion journal does not stop PDF-only work."""
        if self.journal is not None:
            return
        data = {"schema_version": 1, "conversions": {}}
        if self.journal_path.exists():
            data = json.loads(self.journal_path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or not isinstance(data.get("conversions"), dict)
                or any(not isinstance(v, dict) for v in data["conversions"].values())):
            raise ConversionError("Invalid conversion journal; preserved for review")
        self.journal = data
        # A prior interrupted COM job may still own an open Hangul instance.
        self.blocked = any(r.get("conversion_status") in {"RUNNING", "BLOCKED"}
                           for r in data["conversions"].values())

    def _save(self) -> None:
        """Publish a complete journal atomically without pruning older records."""
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                    dir=self.journal_path.parent, suffix=".tmp", delete=False) as stream:
                name = Path(stream.name)
                json.dump(self.journal, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.journal_path)
        finally:
            if name is not None:
                name.unlink(missing_ok=True)

    def _temporary_path(self, relative: str, document_id: str) -> Path:
        """Accept only this document's private staging directory under converted/."""
        path = self.root / relative
        resolved = path.resolve()
        parent = self.directory.resolve()
        if (resolved.parent.parent != parent
                or not resolved.parent.name.startswith(f".{document_id}-")
                or resolved.name != "output.pdf" or path.is_symlink()):
            raise ConversionError("Unsafe temporary path in journal; preserved for review")
        return path

    def _publish_pdf(self, temporary: Path, target: Path) -> None:
        """Create the final name without ever replacing an existing destination."""
        os.link(temporary, target)
        temporary.unlink()

    def prepare(self, source: Path, document_id: str, source_hash: str,
                *, has_extraction: bool = False) -> tuple[Path, str]:
        """Return a verified PDF and its hash, recording an independent outcome."""
        self.outcomes[document_id] = "FAILED"
        self._load()
        if not re.fullmatch(r"DOC-[0-9a-f]{20}", document_id):
            raise ConversionError("Invalid document ID")
        source = source.resolve()
        relative = source.relative_to(self.root).as_posix()
        if source.suffix.lower() not in {".hwp", ".hwpx"}:
            raise ConversionError("Expected HWP or HWPX source")
        if not source.is_relative_to((self.root / "data" / "raw").resolve()):
            raise ConversionError("Source is outside data/raw")
        target = self.directory / f"{document_id}.pdf"
        if target.is_symlink() or self.directory.resolve() != self.directory:
            raise ConversionError("Converted output must not be redirected by a link")
        records = self.journal["conversions"]
        record = records.get(document_id)
        if record is not None:
            expected = {"document_id": document_id, "source_path": relative,
                        "source_sha256": source_hash,
                        "source_format": source.suffix.lower()[1:],
                        "converted_path": target.relative_to(self.root).as_posix()}
            if any(record.get(k) != v for k, v in expected.items()):
                raise ConversionError("Source or conversion identity changed; existing data preserved")
            state = record.get("conversion_status")
            if state == "SUCCESS":
                digest = validate_pdf(target)
                if digest != record.get("converted_sha256"):
                    raise ConversionError("Converted PDF hash changed; preserved for review")
                self.outcomes[document_id] = "REUSED"
                return target, digest
            if state == "READY":
                candidate = target if target.exists() else self._temporary_path(record["temporary_path"], document_id)
                digest = validate_pdf(candidate)
                if digest != record.get("converted_sha256"):
                    raise ConversionError("Interrupted conversion hash mismatch; preserved")
                if candidate != target:
                    self._publish_pdf(candidate, target)
                record["conversion_status"] = "SUCCESS"
                self._save()
                self.outcomes[document_id] = "RECOVERED"
                return target, digest
            if state not in {"FAILED", "RUNNING", "BLOCKED"}:
                raise ConversionError("Unknown journal state; preserved for review")
        if target.exists() or has_extraction:
            raise ConversionError("Existing output has no verified conversion; preserved for review")
        if self.blocked:
            self.outcomes[document_id] = "SKIPPED"
            raise ConversionError("Unconfirmed prior COM cleanup; manual review required")
        self.directory.mkdir(parents=True, exist_ok=True)
        work = self.directory / f".{document_id}-{uuid.uuid4().hex}"
        work.mkdir()
        temporary = work / "output.pdf"
        input_copy = work / source.name
        record = {"document_id": document_id, "source_format": source.suffix.lower()[1:],
                  "source_path": relative, "source_sha256": source_hash,
                  "converted_path": target.relative_to(self.root).as_posix(),
                  "converted_sha256": None, "conversion_status": "RUNNING",
                  "converted_at": None, "attempted_at": utc_now(),
                  "temporary_path": temporary.relative_to(self.root).as_posix()}
        records[document_id] = record
        # Persist intent before COM starts. Unknown shutdowns remain visibly RUNNING.
        self._save()
        ready = False
        try:
            shutil.copyfile(source, input_copy)
            if file_sha256(input_copy) != source_hash:
                raise ConversionError("Source changed while copying")
            self.runner(input_copy, temporary, self.timeout)
            if file_sha256(source) != source_hash:
                raise ConversionError("Original source changed during conversion")
            digest = validate_pdf(temporary)
            record.update(converted_sha256=digest, converted_at=utc_now(), conversion_status="READY")
            self._save()
            ready = True
            self._publish_pdf(temporary, target)
            record["conversion_status"] = "SUCCESS"
            self._save()
            self.outcomes[document_id] = "SUCCESS"
            return target, digest
        except Exception as exc:
            if not ready:
                self.blocked = isinstance(exc, ConversionError) and exc.unsafe
                record.update(conversion_status="BLOCKED" if self.blocked else "FAILED",
                              error=f"{type(exc).__name__}: {exc}")
                self._save()
            raise
        finally:
            # Preserve interrupted/unknown work. Remove only files from this attempt.
            if not self.blocked and record["conversion_status"] in {"SUCCESS", "FAILED"}:
                input_copy.unlink(missing_ok=True)
                temporary.unlink(missing_ok=True)
                if not any(work.iterdir()):
                    work.rmdir()
