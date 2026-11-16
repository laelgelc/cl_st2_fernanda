#!/usr/bin/env python3
"""Deterministic POS tagging and lemmatization pipeline for the ENADE corpus using TreeTagger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import multiprocessing
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from tqdm import tqdm

PHASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = Path("corpus/04_enade")
DEFAULT_OUTPUT_DIR = Path("corpus/05_enade_tagged")
DEFAULT_INPUT_MANIFEST = Path("corpus/04_enade/enade_target_corpus.ndjson")
DEFAULT_TAGGER_CMD = "tree-tagger-portuguese2"

MANIFEST_NDJSON = "enade_tagged_corpus.ndjson"
MANIFEST_TSV = "enade_tagged_corpus.tsv"
MANIFEST_XLSX = "enade_tagged_corpus.xlsx"
FAILURE_NDJSON = "tagging_failures.ndjson"

COLUMNS = (
    "year",
    "chapter",
    "target_subdirectory",
    "filename",
    "source_chapter_path",
    "source_sha256",
    "source_size_bytes",
    "tagged_chapter_path",
    "tagged_sha256",
    "tagged_size_bytes",
    "token_count",
    "tagger_command",
    "status",
    "elapsed_seconds",
    "timestamp",
)

logger = logging.getLogger("tag")


class TagError(Exception):
    """An invalid input, tagger execution failure, or pipeline error."""


@dataclass(frozen=True)
class TagTask:
    year: str
    chapter: str
    target_subdirectory: str
    filename: str
    source_file: Path
    source_rel_path: str
    target_file: Path
    target_rel_path: str


@dataclass
class TaskResult:
    task: TagTask
    success: bool
    source_sha256: str = ""
    source_size_bytes: int = 0
    tagged_sha256: str = ""
    tagged_size_bytes: int = 0
    token_count: int = 0
    tagger_command: str = ""
    status: str = ""
    elapsed_seconds: float = 0.0
    timestamp: str = ""
    error_type: str = ""
    error_message: str = ""


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def escape_xml_tags(text: str) -> str:
    """Escape XML/SGML angle brackets so TreeTagger does not drop text as SGML markup."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def sanitize_text(text: str) -> str:
    """Normalize newlines, strip null bytes, and escape XML brackets."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = normalized.replace("\x00", "")
    return escape_xml_tags(cleaned)


def count_tokens(tagged_text: str) -> int:
    """Count non-empty token lines in TreeTagger 3-column TSV output."""
    count = 0
    for line in tagged_text.splitlines():
        if line.strip():
            count += 1
    return count


def resolve_cli_path(value: str | Path, base_dir: Path = PHASE_DIR) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def relative_manifest_path(path: Path, base_dir: Path = PHASE_DIR) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def resolve_tagger_command(tagger_cmd: str | None = None) -> list[str]:
    """Resolve TreeTagger executable command into an argument list."""
    if tagger_cmd:
        parts = shlex.split(tagger_cmd)
        if parts:
            cmd = parts[0]
            if Path(cmd).is_file() or shutil.which(cmd):
                return parts
            return parts

    env_cmd = os.environ.get("TREETAGGER_CMD")
    if env_cmd:
        return shlex.split(env_cmd)

    treetagger_home = os.environ.get("TREETAGGER_HOME")
    if treetagger_home:
        home_path = Path(treetagger_home)
        for cand in ("tree-tagger-portuguese2", "tree-tagger-portuguese", "tree-tagger"):
            cand_path = home_path / "cmd" / cand
            if cand_path.is_file() and os.access(cand_path, os.X_OK):
                return [str(cand_path)]
            cand_bin = home_path / "bin" / cand
            if cand_bin.is_file() and os.access(cand_bin, os.X_OK):
                return [str(cand_bin)]

    for cand in ("tree-tagger-portuguese2", "tree-tagger-portuguese", "tree-tagger"):
        if shutil.which(cand):
            return [cand]

    return shlex.split(tagger_cmd or DEFAULT_TAGGER_CMD)


def preflight_tagger_check(tagger_cmd: list[str]) -> tuple[bool, str]:
    """Test tagger binary with a dummy Portuguese sentence."""
    test_text = "O ENADE avalia o ensino superior.\n"
    escaped = sanitize_text(test_text)
    try:
        proc = subprocess.run(
            tagger_cmd,
            input=escaped,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return False, f"Tagger returned exit code {proc.returncode}: {proc.stderr.strip()}"
        if not proc.stdout.strip():
            return False, "Tagger produced empty output on preflight test input."
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _parse_manifest_discovery(manifest_path: Path, output_dir: Path, base_dir: Path) -> list[TagTask]:
    tasks: list[TagTask] = []
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TagError(f"Cannot read input manifest {manifest_path}: {exc}") from exc

    for line_idx, line in enumerate(text.splitlines(), start=1):
        line_str = line.strip()
        if not line_str:
            continue
        try:
            record = json.loads(line_str)
        except json.JSONDecodeError as exc:
            raise TagError(f"{manifest_path}, line {line_idx}: invalid JSON: {exc}") from exc

        year = str(record.get("year", ""))
        chapter = str(record.get("chapter", ""))
        target_sub = str(record.get("target_subdirectory", f"{year}_{chapter}"))
        source_rel = record.get("target_chapter_path")

        if source_rel:
            source_file = resolve_cli_path(source_rel, base_dir)
            filename = source_file.name
        else:
            filename_stem = str(record.get("filename_stem", ""))
            filename = f"{filename_stem}.txt"
            source_file = base_dir / "corpus" / "04_enade" / target_sub / filename
            source_rel = relative_manifest_path(source_file, base_dir)

        target_file = output_dir / target_sub / filename
        target_rel = relative_manifest_path(target_file, base_dir)

        tasks.append(
            TagTask(
                year=year,
                chapter=chapter,
                target_subdirectory=target_sub,
                filename=filename,
                source_file=source_file,
                source_rel_path=source_rel,
                target_file=target_file,
                target_rel_path=target_rel,
            )
        )
    return tasks


def _parse_directory_discovery(input_dir: Path, output_dir: Path, base_dir: Path) -> list[TagTask]:
    tasks: list[TagTask] = []
    if not input_dir.exists() or not input_dir.is_dir():
        raise TagError(f"Input directory not found or not a directory: {input_dir}")

    for entry in sorted(input_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith(".") or entry.name.startswith("_"):
            continue
        match = re.match(r"^(\d{4})_(c\d+)$", entry.name)
        if match:
            year, chapter = match.groups()
        else:
            year = ""
            chapter = ""

        target_sub = entry.name
        for infile in sorted(entry.glob("*.txt")):
            if not infile.is_file():
                continue
            filename = infile.name
            target_file = output_dir / target_sub / filename
            source_rel = relative_manifest_path(infile, base_dir)
            target_rel = relative_manifest_path(target_file, base_dir)

            tasks.append(
                TagTask(
                    year=year,
                    chapter=chapter,
                    target_subdirectory=target_sub,
                    filename=filename,
                    source_file=infile,
                    source_rel_path=source_rel,
                    target_file=target_file,
                    target_rel_path=target_rel,
                )
            )
    return tasks


def discover_tasks(
    input_dir: Path,
    output_dir: Path,
    input_manifest: Path | None = None,
    base_dir: Path = PHASE_DIR,
) -> list[TagTask]:
    """Collect tagging tasks via manifest ingestion or directory traversal."""
    if input_manifest is not None and input_manifest.exists() and input_manifest.is_file():
        tasks = _parse_manifest_discovery(input_manifest, output_dir, base_dir)
    else:
        tasks = _parse_directory_discovery(input_dir, output_dir, base_dir)

    tasks.sort(key=lambda t: (t.year, t.chapter, t.filename))
    return tasks


def tag_document(
    task: TagTask,
    tagger_cmd: list[str],
    resume: bool = False,
    timeout: int = 600,
) -> TaskResult:
    """Worker function to tag a single chapter document with fault containment."""
    start_time = time.time()
    ts = _utc_timestamp()
    cmd_str = " ".join(tagger_cmd)

    if not task.source_file.exists() or not task.source_file.is_file():
        return TaskResult(
            task=task,
            success=False,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type="FileNotFoundError",
            error_message=f"Source file not found: {task.source_file}",
        )

    try:
        source_sha, source_size = _sha256_file(task.source_file)
    except OSError as exc:
        return TaskResult(
            task=task,
            success=False,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type="ReadError",
            error_message=f"Cannot read source file {task.source_file}: {exc}",
        )

    if resume and task.target_file.exists() and task.target_file.is_file() and task.target_file.stat().st_size > 0:
        try:
            tagged_sha, tagged_size = _sha256_file(task.target_file)
            target_text = task.target_file.read_text(encoding="utf-8")
            tok_count = count_tokens(target_text)
            return TaskResult(
                task=task,
                success=True,
                source_sha256=source_sha,
                source_size_bytes=source_size,
                tagged_sha256=tagged_sha,
                tagged_size_bytes=tagged_size,
                token_count=tok_count,
                tagger_command=cmd_str,
                status="skipped",
                elapsed_seconds=round(time.time() - start_time, 4),
                timestamp=ts,
            )
        except Exception as exc:
            logger.warning("Failed reading existing output %s for resume check: %s", task.target_file, exc)

    try:
        raw_text = task.source_file.read_text(encoding="utf-8")
    except Exception as exc:
        return TaskResult(
            task=task,
            success=False,
            source_sha256=source_sha,
            source_size_bytes=source_size,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type="UnicodeDecodeError",
            error_message=f"Source text decode failed for {task.source_file}: {exc}",
        )

    preprocessed = sanitize_text(raw_text)

    try:
        proc = subprocess.run(
            tagger_cmd,
            input=preprocessed,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return TaskResult(
            task=task,
            success=False,
            source_sha256=source_sha,
            source_size_bytes=source_size,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type="TimeoutExpired",
            error_message=f"Tagging timed out after {timeout} seconds",
        )
    except Exception as exc:
        return TaskResult(
            task=task,
            success=False,
            source_sha256=source_sha,
            source_size_bytes=source_size,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    if proc.returncode != 0:
        err_msg = proc.stderr.strip() or f"Subprocess returned exit status {proc.returncode}"
        return TaskResult(
            task=task,
            success=False,
            source_sha256=source_sha,
            source_size_bytes=source_size,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type="TreeTaggerSubprocessError",
            error_message=err_msg,
        )

    tagged_output = proc.stdout
    tok_count = count_tokens(tagged_output)

    try:
        task.target_file.parent.mkdir(parents=True, exist_ok=True)
        task.target_file.write_text(tagged_output, encoding="utf-8")
        tagged_sha, tagged_size = _sha256_file(task.target_file)
    except OSError as exc:
        if task.target_file.exists():
            try:
                task.target_file.unlink()
            except OSError:
                pass
        return TaskResult(
            task=task,
            success=False,
            source_sha256=source_sha,
            source_size_bytes=source_size,
            status="failure",
            tagger_command=cmd_str,
            timestamp=ts,
            error_type="WriteError",
            error_message=f"Cannot write target file {task.target_file}: {exc}",
        )

    elapsed = round(time.time() - start_time, 4)
    return TaskResult(
        task=task,
        success=True,
        source_sha256=source_sha,
        source_size_bytes=source_size,
        tagged_sha256=tagged_sha,
        tagged_size_bytes=tagged_size,
        token_count=tok_count,
        tagger_command=cmd_str,
        status="success",
        elapsed_seconds=elapsed,
        timestamp=ts,
    )


def _generate_xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise TagError("The XLSX export requires openpyxl. Please install it before running.") from exc

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "tagged_chapters"
    fixed_time = datetime(2000, 1, 1, 0, 0, 0)
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time
    workbook.properties.creator = ""
    workbook.properties.lastModifiedBy = ""

    worksheet.append(COLUMNS)
    for row in rows:
        values = [row.get(col, "") for col in COLUMNS]
        worksheet.append(values)
        for col_idx, col in enumerate(COLUMNS, start=1):
            cell = worksheet.cell(worksheet.max_row, col_idx)
            if col not in {"source_size_bytes", "tagged_size_bytes", "token_count", "elapsed_seconds"}:
                cell.number_format = "@"
                cell.data_type = "s"

    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def write_manifests(
    results: list[TaskResult],
    output_dir: Path,
) -> None:
    """Publish canonical provenance manifests and failure records."""
    output_dir.mkdir(parents=True, exist_ok=True)
    success_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []

    for r in results:
        if r.success:
            success_rows.append(
                {
                    "year": r.task.year,
                    "chapter": r.task.chapter,
                    "target_subdirectory": r.task.target_subdirectory,
                    "filename": r.task.filename,
                    "source_chapter_path": r.task.source_rel_path,
                    "source_sha256": r.source_sha256,
                    "source_size_bytes": r.source_size_bytes,
                    "tagged_chapter_path": r.task.target_rel_path,
                    "tagged_sha256": r.tagged_sha256,
                    "tagged_size_bytes": r.tagged_size_bytes,
                    "token_count": r.token_count,
                    "tagger_command": r.tagger_command,
                    "status": r.status,
                    "elapsed_seconds": r.elapsed_seconds,
                    "timestamp": r.timestamp,
                }
            )
        else:
            failure_rows.append(
                {
                    "year": r.task.year,
                    "chapter": r.task.chapter,
                    "filename": r.task.filename,
                    "source_chapter_path": r.task.source_rel_path,
                    "error_type": r.error_type,
                    "error_message": r.error_message,
                    "timestamp": r.timestamp,
                }
            )

    ndjson_path = output_dir / MANIFEST_NDJSON
    tsv_path = output_dir / MANIFEST_TSV
    xlsx_path = output_dir / MANIFEST_XLSX
    fail_path = output_dir / FAILURE_NDJSON

    ndjson_content = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in success_rows
    )
    ndjson_path.write_text(ndjson_content, encoding="utf-8")

    tsv_out = io.StringIO(newline="")
    writer = csv.writer(tsv_out, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)
    for row in success_rows:
        writer.writerow([row.get(col, "") for col in COLUMNS])
    tsv_path.write_text(tsv_out.getvalue(), encoding="utf-8")

    xlsx_bytes = _generate_xlsx_bytes(success_rows)
    xlsx_path.write_bytes(xlsx_bytes)

    if failure_rows:
        fail_content = "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in failure_rows
        )
        fail_path.write_text(fail_content, encoding="utf-8")
    elif fail_path.exists():
        fail_path.unlink()


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tag and lemmatize ENADE target corpus with TreeTagger Portuguese model."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Base directory containing assembled ENADE chapters (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Destination directory for tagged outputs and manifests (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=DEFAULT_INPUT_MANIFEST,
        help=f"Path to stage-4 target manifest (default: {DEFAULT_INPUT_MANIFEST})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, multiprocessing.cpu_count() - 1),
        help="Number of parallel worker processes (default: cpu_count - 1)",
    )
    parser.add_argument(
        "--tagger-cmd",
        type=str,
        default=DEFAULT_TAGGER_CMD,
        help=f"Custom TreeTagger command or binary name (default: {DEFAULT_TAGGER_CMD})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and tagger preflight without writing output files",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip tagging for valid existing non-empty output files",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional path for detailed execution log file",
    )
    return parser.parse_args(args)


def main(cli_args: list[str] | None = None) -> int:
    args = parse_args(cli_args)

    if args.log_file:
        log_path = resolve_cli_path(args.log_file, PHASE_DIR)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=str(log_path),
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    base_dir = PHASE_DIR
    input_dir = resolve_cli_path(args.input_dir, base_dir)
    output_dir = resolve_cli_path(args.output_dir, base_dir)
    input_manifest = resolve_cli_path(args.input_manifest, base_dir) if args.input_manifest else None

    tagger_cmd = resolve_tagger_command(args.tagger_cmd)
    workers = max(1, min(64, args.workers))

    print("==================================================")
    print("ENADE Corpus Tagging & Lemmatization Pipeline")
    print("==================================================")
    print(f"Base Directory:     {base_dir}")
    print(f"Input Directory:    {input_dir}")
    print(f"Output Directory:   {output_dir}")
    print(f"Input Manifest:     {input_manifest if input_manifest and input_manifest.exists() else '(Directory discovery)'}")
    print(f"Tagger Command:     {' '.join(tagger_cmd)}")
    print(f"Workers:            {workers}")
    print(f"Resume Mode:        {args.resume}")
    print(f"Dry Run Mode:       {args.dry_run}\n")

    preflight_ok, preflight_err = preflight_tagger_check(tagger_cmd)
    if not preflight_ok:
        if args.dry_run:
            print(f"WARNING: TreeTagger preflight probe failed: {preflight_err}\n")
        else:
            print(f"ERROR: TreeTagger preflight probe failed: {preflight_err}", file=sys.stderr)
            return 1
    else:
        print("✓ TreeTagger preflight check passed.\n")

    try:
        tasks = discover_tasks(input_dir, output_dir, input_manifest, base_dir)
    except TagError as exc:
        print(f"ERROR during task discovery: {exc}", file=sys.stderr)
        return 1

    total_tasks = len(tasks)
    print(f"Discovered {total_tasks} chapter documents for processing.")

    if total_tasks == 0:
        print("No tasks to process. Exiting.")
        return 0

    if args.dry_run:
        resumable_count = 0
        for task in tasks:
            if task.target_file.exists() and task.target_file.stat().st_size > 0:
                resumable_count += 1
        print(f"Dry-run evaluation:")
        print(f"  - Total candidate files: {total_tasks}")
        print(f"  - Already tagged (resumable): {resumable_count}")
        print(f"  - Pending tagging: {total_tasks - resumable_count if args.resume else total_tasks}")
        print("\nDry run completed successfully. No files were written.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[TaskResult] = []
    success_count = 0
    skipped_count = 0
    failure_count = 0

    start_batch_time = time.time()

    if workers == 1:
        for task in tqdm(tasks, desc="Tagging chapters", unit="file"):
            res = tag_document(task, tagger_cmd, resume=args.resume)
            results.append(res)
            if res.success:
                if res.status == "skipped":
                    skipped_count += 1
                else:
                    success_count += 1
            else:
                failure_count += 1
                print(f"FAILED: {task.filename} - {res.error_message}", file=sys.stderr)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_task = {
                executor.submit(tag_document, task, tagger_cmd, args.resume): task
                for task in tasks
            }
            with tqdm(total=total_tasks, desc="Tagging chapters", unit="file") as pbar:
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        res = future.result()
                    except Exception as exc:
                        res = TaskResult(
                            task=task,
                            success=False,
                            status="failure",
                            tagger_command=" ".join(tagger_cmd),
                            timestamp=_utc_timestamp(),
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
                    results.append(res)
                    if res.success:
                        if res.status == "skipped":
                            skipped_count += 1
                        else:
                            success_count += 1
                    else:
                        failure_count += 1
                        print(f"FAILED: {task.filename} - {res.error_message}", file=sys.stderr)
                    pbar.update(1)

    results.sort(key=lambda r: (r.task.year, r.task.chapter, r.task.filename))

    write_manifests(results, output_dir)

    total_duration = time.time() - start_batch_time
    total_tokens = sum(r.token_count for r in results if r.success)

    print("\n==================================================")
    print("Tagging Run Summary")
    print("==================================================")
    print(f"Total Chapters Processed: {total_tasks}")
    print(f"  - Newly Tagged:         {success_count}")
    print(f"  - Skipped (--resume):   {skipped_count}")
    print(f"  - Failures:             {failure_count}")
    print(f"Total Tokens Tagged:      {total_tokens:,}")
    print(f"Elapsed Time:             {total_duration:.2f}s")
    print(f"Manifests published to:   {output_dir}")
    print("==================================================\n")

    return 0 if failure_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
