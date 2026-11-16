"""Build the final, audited ENADE chapter corpus and its manifests."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


PHASE_DIR = Path(__file__).resolve().parent
DEFAULT_SELECTION = Path("corpus/enade_chapters_clean_up_revised_dataset.ndjson")
DEFAULT_METADATA = Path("corpus/enade_dataset.ndjson")
DEFAULT_STATUS = Path("corpus/03_enade_selected_chapters_denoised/chapter_status.ndjson")
DEFAULT_OUTPUT = Path("corpus/04_enade")
MANIFEST_NAMES = (
    "enade_target_corpus.ndjson",
    "enade_target_corpus.tsv",
    "enade_target_corpus.xlsx",
)
COLUMNS = (
    "year",
    "chapter",
    "target_subdirectory",
    "filename_stem",
    "discipline",
    "mnemonic",
    "source_pdf_filename",
    "source_pdf_path",
    "selected_pages",
    "selected_page_count",
    "denoised_source_path",
    "target_chapter_path",
    "chapter_sha256",
    "chapter_size_bytes",
    "denoise_status",
    "corpus_status",
    "boundary_review_flag_count",
    "review_note_count",
    "chapter_status_path",
    "page_selection_manifest_path",
    "page_selection_manifest_sha256",
    "source_metadata_manifest_path",
    "source_metadata_manifest_sha256",
    "chapter_status_manifest_sha256",
)
PAGE_PATTERN = re.compile(r"_page_(\d+)\.txt$", re.IGNORECASE)
YEAR_PATTERN = re.compile(r"\d{4}\Z")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class OrganiserError(Exception):
    """An invalid input or unsafe publication condition."""


@dataclass(frozen=True)
class CopyItem:
    source: Path
    target_relative: str
    sha256: str
    size_bytes: int
    identity: tuple[str, str, str]


@dataclass(frozen=True)
class BuildPlan:
    base_dir: Path
    output_dir: Path
    output_relative: str
    rows: list[dict[str, Any]]
    copies: list[CopyItem]
    manifest_bytes: dict[str, bytes]
    selected_page_count: int


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value}")


def read_ndjson(path: Path) -> tuple[list[tuple[int, dict[str, Any]]], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OrganiserError(f"Cannot read input manifest {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OrganiserError(f"Input manifest {path} is not valid UTF-8: {exc}") from exc

    records: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise OrganiserError(f"Malformed JSON in {path}, line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise OrganiserError(f"Expected a JSON object in {path}, line {line_number}")
        records.append((line_number, record))
    if not records:
        raise OrganiserError(f"Input manifest is empty: {path}")
    return records, raw


def _required_string(record: dict[str, Any], key: str, path: Path, line: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise OrganiserError(f"{path}, line {line}: required field {key!r} must be a non-empty string")
    if value != value.strip():
        raise OrganiserError(f"{path}, line {line}: field {key!r} must not have leading or trailing whitespace")
    return value


def _safe_component(value: str, label: str) -> str:
    if (not value or value in {".", ".."} or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(char in '<>:"|?*' for char in value)
            or value.endswith((".", " "))):
        raise OrganiserError(f"Unsafe {label} path component {value!r}; use a single portable filename component")
    if value.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        raise OrganiserError(f"Unsafe {label} path component {value!r}; it is reserved on Windows")
    return value


def _relative_parts(value: str, label: str) -> tuple[str, ...]:
    normalized = value.replace("\\", "/")
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(normalized)
    if normalized.startswith("/") or posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise OrganiserError(f"{label} must be relative to the phase directory, not absolute: {value!r}")
    raw_parts = normalized.split("/")
    if not raw_parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise OrganiserError(f"Unsafe relative {label}: {value!r}")
    return tuple(_safe_component(part, label) for part in raw_parts)


def _relative_manifest_path(path: Path, base_dir: Path, label: str) -> str:
    try:
        relative = path.resolve().relative_to(base_dir.resolve())
    except (OSError, ValueError) as exc:
        raise OrganiserError(f"{label} resolves outside the phase directory: {path}") from exc
    return relative.as_posix()


def _resolve_phase_file(value: str, base_dir: Path, label: str) -> tuple[Path, str]:
    parts = _relative_parts(value, label)
    lexical_path = base_dir.joinpath(*parts)
    try:
        resolved = lexical_path.resolve(strict=True)
        resolved.relative_to(base_dir.resolve())
        mode = resolved.stat().st_mode
    except (OSError, ValueError) as exc:
        raise OrganiserError(f"{label} {value!r} is missing, unreadable, or resolves outside the phase directory: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise OrganiserError(f"{label} is not a regular file: {value!r}")
    try:
        with resolved.open("rb") as stream:
            stream.read(1)
    except OSError as exc:
        raise OrganiserError(f"{label} is not readable: {value!r}: {exc}") from exc
    return resolved, PurePosixPath(*parts).as_posix()


def _resolve_cli_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise OrganiserError(f"Cannot read chapter file {path}: {exc}") from exc
    return digest.hexdigest(), size


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _page_number(page_path: str, manifest: Path, line: int) -> int:
    basename = re.split(r"[\\/]", page_path)[-1]
    match = PAGE_PATTERN.search(basename)
    if match is None:
        raise OrganiserError(
            f"{manifest}, line {line}: page path {page_path!r} must end with '_page_<number>.txt'"
        )
    number = int(match.group(1))
    if number <= 0:
        raise OrganiserError(f"{manifest}, line {line}: page number must be positive in {page_path!r}")
    return number


def _positive_page_list(value: Any, label: str, identity: tuple[str, str, str]) -> list[int]:
    if not isinstance(value, list) or not value:
        raise OrganiserError(f"Chapter group {identity!r}: {label} must be a non-empty list of page numbers")
    if any(not isinstance(page, int) or isinstance(page, bool) or page <= 0 for page in value):
        raise OrganiserError(f"Chapter group {identity!r}: {label} must contain positive integers")
    if len(set(value)) != len(value):
        raise OrganiserError(f"Chapter group {identity!r}: {label} contains duplicate page numbers")
    return value


def _validate_empty_page_list(record: dict[str, Any], key: str, identity: tuple[str, str, str]) -> None:
    value = record.get(key)
    if not isinstance(value, list):
        raise OrganiserError(f"Chapter group {identity!r}: status field {key!r} must be a list")
    if value:
        raise OrganiserError(f"Chapter group {identity!r}: cannot include a chapter with {key}={value!r}")


def _normalised_destination(relative_path: str) -> str:
    return "/".join(unicodedata.normalize("NFC", part).casefold()
                     for part in PurePosixPath(relative_path).parts)


def _check_destination_collisions(destinations: Iterable[tuple[str, tuple[str, str, str]]]) -> None:
    seen: dict[str, tuple[str, str, str]] = {}
    for destination, identity in destinations:
        key = _normalised_destination(destination)
        if key in seen:
            raise OrganiserError(
                f"Target path collision between chapter groups {seen[key]!r} and {identity!r}: {destination!r}"
            )
        seen[key] = identity


def _manifest_xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise OrganiserError(
            "The XLSX export requires openpyxl. Install it in the configured Python environment before publishing."
        ) from exc

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "chapters"
    fixed_time = datetime(2000, 1, 1, 0, 0, 0)
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time
    workbook.properties.creator = ""
    workbook.properties.lastModifiedBy = ""
    worksheet.append(COLUMNS)
    for row in rows:
        values = [_format_manifest_value(column, row[column]) for column in COLUMNS]
        worksheet.append(values)
        for column_index, column in enumerate(COLUMNS, start=1):
            cell = worksheet.cell(worksheet.max_row, column_index)
            if column not in {"selected_page_count", "chapter_size_bytes",
                              "boundary_review_flag_count", "review_note_count"}:
                cell.number_format = "@"
                cell.data_type = "s"
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _format_manifest_value(column: str, value: Any) -> Any:
    if column == "selected_pages":
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def _serialize_manifests(rows: list[dict[str, Any]]) -> dict[str, bytes]:
    ndjson = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    ).encode("utf-8")

    tsv_output = io.StringIO(newline="")
    writer = csv.writer(tsv_output, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_format_manifest_value(column, row[column]) for column in COLUMNS])
    tsv = tsv_output.getvalue().encode("utf-8")

    return {
        MANIFEST_NAMES[0]: ndjson,
        MANIFEST_NAMES[1]: tsv,
        MANIFEST_NAMES[2]: _manifest_xlsx_bytes(rows),
    }


def _build_metadata_index(records: list[tuple[int, dict[str, Any]]], path: Path) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for line, record in records:
        source_path = _required_string(record, "filepath_ori", path, line)
        normalized_path = PurePosixPath(*_relative_parts(source_path, "source PDF path")).as_posix()
        if normalized_path in index:
            raise OrganiserError(f"Duplicate source metadata path {normalized_path!r} in {path}, line {line}")
        year = _required_string(record, "year", path, line)
        if not YEAR_PATTERN.fullmatch(year):
            raise OrganiserError(f"{path}, line {line}: year must be a four-digit string, got {year!r}")
        index[normalized_path] = {
            "year": year,
            "filename_ori": _required_string(record, "filename_ori", path, line),
            "mnemonic": _required_string(record, "mnemonic", path, line),
            "discipline": _required_string(record, "discipline", path, line),
        }
    return index


def build_plan(
    selection_path: Path,
    metadata_path: Path,
    status_path: Path,
    output_dir: Path,
    base_dir: Path = PHASE_DIR,
) -> BuildPlan:
    base_dir = base_dir.resolve()
    selection_path = selection_path.resolve()
    metadata_path = metadata_path.resolve()
    status_path = status_path.resolve()
    output_dir = Path(output_dir)
    if output_dir.is_symlink():
        raise OrganiserError(f"Output directory must not be a symlink: {output_dir}")
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(base_dir)
    except ValueError as exc:
        raise OrganiserError(f"Output directory must resolve inside the phase directory: {output_dir}") from exc
    if output_dir == base_dir:
        raise OrganiserError("Output directory cannot be the phase directory itself")

    selection_records, selection_bytes = read_ndjson(selection_path)
    metadata_records, metadata_bytes = read_ndjson(metadata_path)
    status_records, status_bytes = read_ndjson(status_path)
    selected_groups: dict[tuple[str, str, str], list[int]] = {}
    seen_pages: set[tuple[tuple[str, str, str], int]] = set()
    selected_page_count = 0
    for line, record in selection_records:
        chapter = _required_string(record, "chapter_of_interest", selection_path, line)
        filename_stem = _required_string(record, "filename_stem", selection_path, line)
        source_path = _required_string(record, "filepath_ori", selection_path, line)
        page_path = _required_string(record, "chapter_page_filepath_txt", selection_path, line)
        normalized_source = PurePosixPath(*_relative_parts(source_path, "source PDF path")).as_posix()
        _safe_component(chapter, "chapter")
        _safe_component(filename_stem, "filename stem")
        identity = (normalized_source, filename_stem, chapter)
        page = _page_number(page_path, selection_path, line)
        page_identity = (identity, page)
        if page_identity in seen_pages:
            raise OrganiserError(f"{selection_path}, line {line}: duplicate selected page identity {identity!r}, page {page}")
        seen_pages.add(page_identity)
        selected_groups.setdefault(identity, []).append(page)
        selected_page_count += 1
    if not selected_groups:
        raise OrganiserError(f"Selection manifest contains no selected pages: {selection_path}")
    for pages in selected_groups.values():
        pages.sort()

    metadata_index = _build_metadata_index(metadata_records, metadata_path)
    status_index: dict[tuple[str, str, str], tuple[dict[str, Any], str]] = {}
    for line, record in status_records:
        group = record.get("group")
        if not isinstance(group, dict):
            raise OrganiserError(f"{status_path}, line {line}: status record must contain a group object")
        source_path = _required_string(group, "filepath_ori", status_path, line)
        filename_stem = _required_string(group, "filename_stem", status_path, line)
        chapter = _required_string(group, "chapter_of_interest", status_path, line)
        normalized_source = PurePosixPath(*_relative_parts(source_path, "status source PDF path")).as_posix()
        identity = (normalized_source, filename_stem, chapter)
        if identity in status_index:
            raise OrganiserError(f"{status_path}, line {line}: duplicate chapter status identity {identity!r}")
        output_value = _required_string(record, "output_path", status_path, line)
        status_index[identity] = (record, output_value)

    missing_status = set(selected_groups) - set(status_index)
    extra_status = set(status_index) - set(selected_groups)
    if missing_status or extra_status:
        details = []
        if missing_status:
            details.append(f"missing status groups: {sorted(missing_status)!r}")
        if extra_status:
            details.append(f"unexpected status groups: {sorted(extra_status)!r}")
        raise OrganiserError("Selection and chapter-status group sets differ; " + "; ".join(details))

    output_relative = _relative_manifest_path(output_dir, base_dir, "output directory")
    output_relative_parts = _relative_parts(output_relative, "output directory")
    rows_and_copies: list[tuple[dict[str, Any], CopyItem]] = []
    destinations: list[tuple[str, tuple[str, str, str]]] = []
    source_resolved_paths: set[Path] = set()

    for identity, selected_pages in selected_groups.items():
        source_pdf_path, filename_stem, chapter = identity
        metadata = metadata_index.get(source_pdf_path)
        if metadata is None:
            raise OrganiserError(f"No source metadata row matches source PDF path {source_pdf_path!r}")
        source_pdf, normalized_pdf_path = _resolve_phase_file(source_pdf_path, base_dir, "source PDF")
        source_resolved_paths.add(source_pdf)

        status, output_value = status_index[identity]
        if status.get("status") != "complete" or status.get("complete") is not True:
            raise OrganiserError(f"Chapter group {identity!r} is not marked complete in {status_path}")
        if status.get("scope_limited") is True:
            raise OrganiserError(f"Chapter group {identity!r} has scope_limited=true and cannot be published as complete")
        status_pages = _positive_page_list(status.get("selected_pages"), "selected_pages", identity)
        if set(status_pages) != set(selected_pages):
            raise OrganiserError(
                f"Chapter group {identity!r}: selected pages differ; selection={selected_pages!r}, status={sorted(status_pages)!r}"
            )
        for key in ("failed_pages", "unattempted_pages", "failed_or_missing_pages"):
            _validate_empty_page_list(status, key, identity)
        boundary_flags = status.get("boundary_review_flags")
        if not isinstance(boundary_flags, list):
            raise OrganiserError(f"Chapter group {identity!r}: boundary_review_flags must be a list")
        review_note_count = status.get("review_note_count")
        if not isinstance(review_note_count, int) or isinstance(review_note_count, bool) or review_note_count < 0:
            raise OrganiserError(f"Chapter group {identity!r}: review_note_count must be a non-negative integer")

        denoised_source, denoised_source_relative = _resolve_phase_file(output_value, base_dir, "denoised chapter")
        source_resolved_paths.add(denoised_source)
        filename = _safe_component(denoised_source.name, "assembled chapter filename")
        chapter_dir = _safe_component(f"{metadata['year']}_{chapter}", "target directory")
        target_relative = PurePosixPath(*output_relative_parts, chapter_dir, filename).as_posix()
        destinations.append((target_relative, identity))
        chapter_hash, chapter_size = _sha256_file(denoised_source)

        row = {
            "year": metadata["year"],
            "chapter": chapter,
            "target_subdirectory": chapter_dir,
            "filename_stem": filename_stem,
            "discipline": metadata["discipline"],
            "mnemonic": metadata["mnemonic"],
            "source_pdf_filename": metadata["filename_ori"],
            "source_pdf_path": normalized_pdf_path,
            "selected_pages": sorted(selected_pages),
            "selected_page_count": len(selected_pages),
            "denoised_source_path": denoised_source_relative,
            "target_chapter_path": target_relative,
            "chapter_sha256": chapter_hash,
            "chapter_size_bytes": chapter_size,
            "denoise_status": "complete",
            "corpus_status": "accepted_subject_to_audit",
            "boundary_review_flag_count": len(boundary_flags),
            "review_note_count": review_note_count,
            "chapter_status_path": _relative_manifest_path(status_path, base_dir, "chapter status manifest"),
            "page_selection_manifest_path": _relative_manifest_path(selection_path, base_dir, "page selection manifest"),
            "page_selection_manifest_sha256": _sha256_bytes(selection_bytes),
            "source_metadata_manifest_path": _relative_manifest_path(metadata_path, base_dir, "source metadata manifest"),
            "source_metadata_manifest_sha256": _sha256_bytes(metadata_bytes),
            "chapter_status_manifest_sha256": _sha256_bytes(status_bytes),
        }
        copy = CopyItem(denoised_source, target_relative, chapter_hash, chapter_size, identity)
        rows_and_copies.append((row, copy))

    _check_destination_collisions(destinations)
    for destination, identity in destinations:
        resolved_destination = (base_dir / PurePosixPath(destination)).resolve(strict=False)
        if resolved_destination in source_resolved_paths:
            raise OrganiserError(f"Target for chapter group {identity!r} would overwrite an input/source file: {destination}")

    rows_and_copies.sort(key=lambda item: (
        int(item[0]["year"]), item[0]["chapter"], item[0]["source_pdf_path"], item[0]["target_chapter_path"]
    ))
    rows = [item[0] for item in rows_and_copies]
    copies = [item[1] for item in rows_and_copies]
    manifests = _serialize_manifests(rows)
    return BuildPlan(base_dir, output_dir, output_relative, rows, copies, manifests, selected_page_count)


def _expected_directories(plan: BuildPlan) -> set[str]:
    output_parts = PurePosixPath(plan.output_relative)
    directories: set[str] = set()
    for copy in plan.copies:
        path = PurePosixPath(copy.target_relative).relative_to(output_parts).parent
        while str(path) not in {".", ""}:
            directories.add(path.as_posix())
            path = path.parent
    return directories


def _expected_files(plan: BuildPlan) -> set[str]:
    output_parts = PurePosixPath(plan.output_relative)
    files = {PurePosixPath(copy.target_relative).relative_to(output_parts).as_posix() for copy in plan.copies}
    files.update(MANIFEST_NAMES)
    return files


def _validate_xlsx(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise OrganiserError("Cannot validate XLSX because openpyxl is unavailable") from exc
    try:
        workbook = load_workbook(path, data_only=False, read_only=False)
    except Exception as exc:
        raise OrganiserError(f"Cannot read staged XLSX manifest {path}: {exc}") from exc
    try:
        if workbook.sheetnames != ["chapters"]:
            raise OrganiserError(f"XLSX manifest {path} must contain only the 'chapters' worksheet")
        worksheet = workbook["chapters"]
        if worksheet.freeze_panes != "A2" or worksheet.auto_filter.ref != worksheet.dimensions:
            raise OrganiserError(f"XLSX manifest {path} is missing its frozen header or autofilter")
        if tuple(cell.value for cell in worksheet[1]) != COLUMNS:
            raise OrganiserError(f"XLSX manifest {path} has an unexpected header")
        if worksheet.max_row != len(rows) + 1:
            raise OrganiserError(f"XLSX manifest {path} has {worksheet.max_row - 1} rows, expected {len(rows)}")
        for row_index, row in enumerate(rows, start=2):
            expected_values = [_format_manifest_value(column, row[column]) for column in COLUMNS]
            cells = worksheet[row_index]
            if any(cell.data_type == "f" for cell in cells):
                raise OrganiserError(f"XLSX manifest {path} contains a formula at row {row_index}")
            if [cell.value for cell in cells] != expected_values:
                raise OrganiserError(f"XLSX manifest {path} row {row_index} differs from the canonical manifest")
    finally:
        workbook.close()


def _validate_stage(stage: Path, plan: BuildPlan) -> None:
    output_parts = PurePosixPath(plan.output_relative)
    expected_files = _expected_files(plan)
    expected_dirs = _expected_directories(plan)
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for path in stage.rglob("*"):
        relative = path.relative_to(stage).as_posix()
        if path.is_symlink():
            raise OrganiserError(f"Staged corpus contains an unexpected symlink: {relative}")
        if path.is_dir():
            actual_dirs.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise OrganiserError(f"Staged corpus contains a non-regular entry: {relative}")
    if actual_files != expected_files:
        raise OrganiserError(
            f"Staged file set differs from plan; missing={sorted(expected_files - actual_files)!r}, "
            f"unexpected={sorted(actual_files - expected_files)!r}"
        )
    if actual_dirs != expected_dirs:
        raise OrganiserError(
            f"Staged directory set differs from plan; missing={sorted(expected_dirs - actual_dirs)!r}, "
            f"unexpected={sorted(actual_dirs - expected_dirs)!r}"
        )

    for copy in plan.copies:
        staged_relative = PurePosixPath(copy.target_relative).relative_to(output_parts)
        staged_file = stage / staged_relative
        digest, size = _sha256_file(staged_file)
        if digest != copy.sha256 or size != copy.size_bytes:
            raise OrganiserError(f"Copied chapter failed SHA-256/size verification: {staged_file}")

    for name, expected in plan.manifest_bytes.items():
        manifest_path = stage / name
        try:
            actual = manifest_path.read_bytes()
        except OSError as exc:
            raise OrganiserError(f"Cannot read staged manifest {manifest_path}: {exc}") from exc
        if actual != expected:
            raise OrganiserError(f"Staged manifest differs from deterministic output: {manifest_path}")

    try:
        ndjson_rows = [json.loads(line) for line in (stage / MANIFEST_NAMES[0]).read_text(encoding="utf-8").splitlines()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OrganiserError(f"Cannot parse staged NDJSON manifest: {exc}") from exc
    if ndjson_rows != plan.rows:
        raise OrganiserError("Staged NDJSON rows differ from the expected chapter plan")
    try:
        with (stage / MANIFEST_NAMES[1]).open("r", encoding="utf-8", newline="") as stream:
            tsv_rows = list(csv.DictReader(stream, delimiter="\t"))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise OrganiserError(f"Cannot parse staged TSV manifest: {exc}") from exc
    expected_tsv_rows = [
        {column: str(_format_manifest_value(column, row[column])) for column in COLUMNS}
        for row in plan.rows
    ]
    if tsv_rows != expected_tsv_rows:
        raise OrganiserError("Staged TSV rows differ from the expected chapter plan")
    _validate_xlsx(stage / MANIFEST_NAMES[2], plan.rows)


def _target_matches_plan(plan: BuildPlan) -> bool:
    target = plan.output_dir
    if not target.exists():
        return False
    if target.is_symlink() or not target.is_dir():
        raise OrganiserError(f"Output path exists but is not a regular directory: {target}")
    expected_files = _expected_files(plan)
    expected_dirs = _expected_directories(plan)
    actual_files: set[str] = set()
    actual_dirs: set[str] = set()
    for path in target.rglob("*"):
        if path.is_symlink():
            raise OrganiserError(f"Existing target contains a symlink; preserving it and stopping: {path}")
        relative = path.relative_to(target).as_posix()
        if path.is_dir():
            actual_dirs.add(relative)
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise OrganiserError(f"Existing target contains a non-regular entry; preserving it: {path}")
    if actual_files != expected_files or actual_dirs != expected_dirs:
        return False

    for copy in plan.copies:
        target_file = plan.base_dir / PurePosixPath(copy.target_relative)
        digest, size = _sha256_file(target_file)
        if digest != copy.sha256 or size != copy.size_bytes:
            return False
    for name, expected in plan.manifest_bytes.items():
        target_manifest = target / name
        try:
            if target_manifest.read_bytes() != expected:
                return False
        except OSError:
            return False
    _validate_xlsx(target / MANIFEST_NAMES[2], plan.rows)
    return True


def copy_and_verify(copy: CopyItem, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with copy.source.open("rb") as source, target.open("xb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
    except OSError as exc:
        raise OrganiserError(f"Cannot copy {copy.source} to {target}: {exc}") from exc
    digest, size = _sha256_file(target)
    if digest != copy.sha256 or size != copy.size_bytes:
        raise OrganiserError(f"Copied chapter failed SHA-256/size verification: {target}")


def publish(plan: BuildPlan) -> str:
    if plan.output_dir.exists():
        if _target_matches_plan(plan):
            return "unchanged"
        raise OrganiserError(
            f"Output directory already exists and differs from the expected corpus: {plan.output_dir}. "
            "It was preserved; choose a separate destination or archive it manually before rebuilding."
        )

    parent = plan.output_dir.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        parent.resolve().relative_to(plan.base_dir)
    except (OSError, ValueError) as exc:
        raise OrganiserError(f"Cannot create a safe output parent for {plan.output_dir}: {exc}") from exc

    stage = parent / f".{plan.output_dir.name}.staging-{uuid.uuid4().hex}"
    try:
        stage.mkdir()
    except OSError as exc:
        raise OrganiserError(f"Cannot create staging directory beside {plan.output_dir}: {exc}") from exc

    try:
        for copy in plan.copies:
            staged_relative = PurePosixPath(copy.target_relative).relative_to(PurePosixPath(plan.output_relative))
            copy_and_verify(copy, stage / staged_relative)
        for name, content in plan.manifest_bytes.items():
            manifest_path = stage / name
            with manifest_path.open("xb") as stream:
                stream.write(content)
        _validate_stage(stage, plan)
        if plan.output_dir.exists():
            raise OrganiserError(f"Output directory appeared during publication; staging preserved at {stage}")
        os.rename(stage, plan.output_dir)
        return "published"
    except Exception as exc:
        if isinstance(exc, OrganiserError):
            raise OrganiserError(f"{exc} Staging directory retained for diagnosis: {stage}") from exc
        raise OrganiserError(f"Publication failed: {exc}. Staging directory retained for diagnosis: {stage}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate, organise, and publish the selected ENADE chapters and target-corpus manifests."
    )
    parser.add_argument("--input-manifest", default=str(DEFAULT_SELECTION), help="Revised page-selection NDJSON")
    parser.add_argument("--metadata-manifest", default=str(DEFAULT_METADATA), help="Source metadata NDJSON")
    parser.add_argument("--chapter-status", default=str(DEFAULT_STATUS), help="Denoising chapter-status NDJSON")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Target corpus directory")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the plan without writing files")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    selection = _resolve_cli_path(args.input_manifest, PHASE_DIR)
    metadata = _resolve_cli_path(args.metadata_manifest, PHASE_DIR)
    status = _resolve_cli_path(args.chapter_status, PHASE_DIR)
    output = Path(args.output_dir)
    if not output.is_absolute():
        output = PHASE_DIR / output
    try:
        plan = build_plan(selection, metadata, status, output, PHASE_DIR)
        if args.dry_run:
            if plan.output_dir.exists() and not _target_matches_plan(plan):
                raise OrganiserError(
                    f"Output directory already exists and differs from the expected corpus: {plan.output_dir}. "
                    "It was preserved; choose a separate destination or archive it manually before rebuilding."
                )
            print(
                f"Dry run successful: {plan.selected_page_count:,} selected pages across "
                f"{len(plan.rows):,} complete chapters."
            )
            print(f"Planned target: {plan.output_dir}")
            print(f"Manifests: {', '.join(MANIFEST_NAMES)}")
            print("No files or directories were created.")
            return 0
        outcome = publish(plan)
        if outcome == "unchanged":
            print(f"Verified identical corpus; no files changed: {plan.output_dir}")
        else:
            print(
                f"Published {len(plan.rows):,} chapters from {plan.selected_page_count:,} selected pages to "
                f"{plan.output_dir}"
            )
        return 0
    except OrganiserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Error: filesystem operation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())