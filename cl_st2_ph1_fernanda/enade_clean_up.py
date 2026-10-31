#!/usr/bin/env python3
"""
Conservative local pre-extraction programme for Brazilian ENADE report TXT files.

This programme reads an immutable NDJSON manifest and extracts exact raw text spans
for selected ENADE chapters into smaller per-chapter TXT files. It does not denoise,
clean, normalise, rewrite, translate, summarise, or otherwise alter extracted text.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROGRAMME = "enade_clean_up.py"
PROGRAMME_VERSION = "1.0.0"

TARGET_CHAPTERS: dict[str, list[str]] = {
    "c4": [
        "percepção sobre a prova",
        "percepção da prova",
    ],
    "c5": [
        "distribuição dos conceitos",
        "distribuição de conceitos",
    ],
    "c6": [
        "análise técnica da prova",
    ],
}

TARGET_LABEL_ORDER = ("c4", "c5", "c6")

FALLBACK_BOUNDARY_TITLES = {
    "anexos",
    "anexo",
    "referencias",
    "referencia",
    "glossario",
}

REPORT_SUCCESS_STATUSES = {
    "success",
    "partial_success",
    "no_target_chapters",
}

CHAPTER_WRITTEN_STATUSES = {
    "found",
    "unsafe_written",
}


@dataclass(frozen=True)
class Config:
    script_dir: Path
    run_id: str
    start_time: str
    manifest: Path
    output: Path
    limit: int | None
    only_filename: str | None
    dry_run: bool
    resume: bool
    reprocess: bool
    filename_field: str
    filepath_field: str
    group_field: str
    manifest_file: Path
    log_file: Path
    summary_file: Path
    cleaned_ndjson: Path
    failures_file: Path
    source_report_manifest_ndjson: Path
    summary_tsv: Path
    metadata_dir: Path
    write_diagnostics: bool
    diagnostics_dir: Path
    allow_unsafe: bool
    min_chapter_chars: int
    max_chapter_chars: int | None
    output_extension: str


@dataclass(frozen=True)
class LineInfo:
    text: str
    start_char: int
    end_char: int
    line_number: int


@dataclass(frozen=True)
class HeadingCandidate:
    raw_heading_text: str
    title_text: str
    normalised_title: str
    chapter_number: str | None
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    source: str
    is_target_candidate: bool
    matched_label: str | None
    matched_variant: str | None
    is_fallback_boundary: bool = False
    rejection_reason: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(path_value: str | Path, base_dir: Path) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def relpath(path: Path, base_dir: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def safe_path_part(value: Any) -> str:
    text = str(value).strip()
    if not text:
        return "_missing"
    text = re.sub(r"[\\/:\*\?\"<>\|\x00-\x1f]", "_", text)
    text = re.sub(r"\s+", "_", text)
    return text or "_missing"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract selected raw chapter spans from ENADE TXT reports.",
    )

    parser.add_argument("--manifest", required=True, help="Input NDJSON ENADE manifest.")
    parser.add_argument("--output", required=True, help="Output directory for extracted chapter TXT files.")

    parser.add_argument("--limit", type=int, default=None, help="Process only first N planned rows after filtering.")
    parser.add_argument("--only-filename", default=None, help="Process only rows whose filename field exactly matches this value.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate extraction without writing chapter TXT files.")
    parser.add_argument("--resume", action="store_true", help="Skip reports whose successful metadata and outputs already exist.")
    parser.add_argument("--reprocess", action="store_true", help="Reprocess even if previous outputs exist.")

    parser.add_argument("--filename-field", default="filename_txt")
    parser.add_argument("--filepath-field", default="filepath_txt")
    parser.add_argument("--group-field", default=None)
    parser.add_argument("--state-field", default=None)

    parser.add_argument("--manifest-file", default=None)
    parser.add_argument("--log-file", default=None)
    parser.add_argument("--summary-file", default=None)
    parser.add_argument("--cleaned-ndjson", default=None)
    parser.add_argument("--failures-file", default=None)

    parser.add_argument("--write-diagnostics", action="store_true")
    parser.add_argument("--diagnostics-dir", default=None)
    parser.add_argument("--allow-unsafe", action="store_true")
    parser.add_argument("--min-chapter-chars", type=int, default=500)
    parser.add_argument("--max-chapter-chars", type=int, default=None)
    parser.add_argument("--output-extension", default=".txt")
    parser.add_argument("--metadata-dir", default=None)

    return parser.parse_args(argv)


def make_config(args: argparse.Namespace) -> Config:
    script_dir = Path(__file__).resolve().parent
    run_id = make_run_id()
    start_time = utc_now_iso()

    group_field = args.group_field or args.state_field or "year"

    manifest = resolve_path(args.manifest, script_dir)
    output = resolve_path(args.output, script_dir)

    manifest_file = resolve_path(args.manifest_file, script_dir) if args.manifest_file else output / "enade_clean_up_manifest.json"
    log_file = resolve_path(args.log_file, script_dir) if args.log_file else output / "enade_clean_up.log"
    summary_file = resolve_path(args.summary_file, script_dir) if args.summary_file else output / "enade_clean_up_summary.json"
    cleaned_ndjson = resolve_path(args.cleaned_ndjson, script_dir) if args.cleaned_ndjson else output / "enade_cleaned_chapters.ndjson"
    failures_file = resolve_path(args.failures_file, script_dir) if args.failures_file else output / "enade_clean_up_failures.ndjson"
    metadata_dir = resolve_path(args.metadata_dir, script_dir) if args.metadata_dir else output / "_enade_clean_up_metadata"
    diagnostics_dir = resolve_path(args.diagnostics_dir, script_dir) if args.diagnostics_dir else output / "_diagnostics"

    return Config(
        script_dir=script_dir,
        run_id=run_id,
        start_time=start_time,
        manifest=manifest,
        output=output,
        limit=args.limit,
        only_filename=args.only_filename,
        dry_run=args.dry_run,
        resume=args.resume,
        reprocess=args.reprocess,
        filename_field=args.filename_field,
        filepath_field=args.filepath_field,
        group_field=group_field,
        manifest_file=manifest_file,
        log_file=log_file,
        summary_file=summary_file,
        cleaned_ndjson=cleaned_ndjson,
        failures_file=failures_file,
        source_report_manifest_ndjson=output / "enade_clean_up_manifest.ndjson",
        summary_tsv=output / "enade_clean_up_summary.tsv",
        metadata_dir=metadata_dir,
        write_diagnostics=args.write_diagnostics,
        diagnostics_dir=diagnostics_dir,
        allow_unsafe=args.allow_unsafe,
        min_chapter_chars=args.min_chapter_chars,
        max_chapter_chars=args.max_chapter_chars,
        output_extension=args.output_extension,
    )


def validate_config(config: Config) -> None:
    if not config.manifest.exists():
        raise ValueError(f"Manifest does not exist: {config.manifest}")
    if not config.manifest.is_file():
        raise ValueError(f"Manifest is not a file: {config.manifest}")
    if config.limit is not None and config.limit <= 0:
        raise ValueError("--limit must be greater than 0.")
    if config.only_filename is not None and not config.only_filename.strip():
        raise ValueError("--only-filename must not be empty.")
    if config.min_chapter_chars < 0:
        raise ValueError("--min-chapter-chars must be >= 0.")
    if config.max_chapter_chars is not None and config.max_chapter_chars <= 0:
        raise ValueError("--max-chapter-chars must be greater than 0.")
    if (
            config.max_chapter_chars is not None
            and config.max_chapter_chars < config.min_chapter_chars
    ):
        raise ValueError("--max-chapter-chars must be >= --min-chapter-chars.")
    if not config.output_extension.startswith("."):
        raise ValueError("--output-extension must start with '.'.")

    config.output.mkdir(parents=True, exist_ok=True)
    config.metadata_dir.mkdir(parents=True, exist_ok=True)
    if config.write_diagnostics:
        config.diagnostics_dir.mkdir(parents=True, exist_ok=True)


def setup_logging(config: Config) -> None:
    config.log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)


def load_manifest_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at manifest line {line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Manifest line {line_number} is not a JSON object.")
            row["_manifest_line_number"] = line_number
            rows.append(row)
    return rows


def filter_rows_by_filename(
        rows: list[dict[str, Any]],
        filename_field: str,
        only_filename: str | None,
) -> list[dict[str, Any]]:
    if only_filename is None:
        return rows

    matched = [row for row in rows if row.get(filename_field) == only_filename]
    if not matched:
        raise ValueError(f"--only-filename matched no rows: {only_filename}")
    if len(matched) > 1:
        logging.warning("--only-filename matched %s rows: %s", len(matched), only_filename)
    return matched


def validate_manifest_row(row: dict[str, Any], config: Config) -> list[str]:
    missing = []
    for field in (config.filename_field, config.filepath_field, config.group_field):
        if field not in row or row.get(field) in (None, ""):
            missing.append(field)
    return missing


def get_report_id(filename: str) -> str:
    return Path(filename).stem


def expected_chapter_output_path(config: Config, group_value: Any, filename: str, chapter_label: str) -> Path:
    stem = Path(filename).stem
    output_name = f"{stem}_{chapter_label}{config.output_extension}"
    return config.output / safe_path_part(group_value) / output_name


def expected_metadata_output_path(config: Config, group_value: Any, filename: str) -> Path:
    return config.metadata_dir / safe_path_part(group_value) / f"{Path(filename).stem}.json"


def read_source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalise_heading_for_match(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    text = text.replace("º", "")
    text = re.sub(r"[–—-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    text = strip_heading_numbering(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_heading_numbering(text: str) -> str:
    text = re.sub(r"^capitulo\s+\d+\s*[:.\-–—]?\s*", "", text)
    text = re.sub(r"^\d+\s*[:.\-–—]?\s+", "", text)
    return text.strip()


NORMALISED_TARGETS: dict[str, dict[str, str]] = {
    label: {normalise_heading_for_match(variant): variant for variant in variants}
    for label, variants in TARGET_CHAPTERS.items()
}


def match_target_title(normalised_title: str) -> tuple[str | None, str | None]:
    for label, variants in NORMALISED_TARGETS.items():
        if normalised_title in variants:
            return label, variants[normalised_title]
    return None, None


def split_lines_with_offsets(text: str) -> list[LineInfo]:
    lines: list[LineInfo] = []
    offset = 0
    for idx, line in enumerate(text.splitlines(keepends=True), start=1):
        end = offset + len(line)
        lines.append(LineInfo(text=line, start_char=offset, end_char=end, line_number=idx))
        offset = end

    if not text:
        return lines

    if text and not text.endswith(("\n", "\r")):
        return lines

    return lines


def line_number_for_offset(line_starts: list[int], offset: int) -> int:
    if not line_starts:
        return 1
    index = bisect.bisect_right(line_starts, offset) - 1
    return max(1, index + 1)


def strip_line_for_detection(line: str) -> str:
    return line.strip().strip("\ufeff")


def without_trailing_toc_page_number(line: str) -> str:
    return re.sub(r"\s+\.{0,}\s*\d{1,4}\s*$", "", line.strip())


def is_integer_line(line: str) -> str | None:
    match = re.fullmatch(r"\s*(\d{1,2})\s*", line)
    if match:
        return match.group(1)
    return None


def is_capitulo_line(line: str) -> str | None:
    match = re.fullmatch(r"\s*cap[íi]tulo\s+(\d{1,2})\s*[:.\-–—]?\s*", line, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def parse_single_line_top_heading(line: str) -> tuple[str | None, str] | None:
    stripped = strip_line_for_detection(line)

    match = re.fullmatch(
        r"(?:cap[íi]tulo\s+)?(\d{1,2})\s+(.{3,140}?)\s*",
        stripped,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    chapter_number = match.group(1)
    title = without_trailing_toc_page_number(match.group(2))

    if re.match(r"^\d+\.\d+", title):
        return None
    if "." in chapter_number:
        return None
    if not title or re.fullmatch(r"\d+", title):
        return None

    return chapter_number, title


def line_looks_like_toc_entry(line: str) -> bool:
    stripped = strip_line_for_detection(line)
    if re.search(r"\.{3,}\s*\d{1,4}\s*$", stripped):
        return True
    if re.search(r"\s+\d{1,4}\s*$", stripped):
        maybe_without_page = without_trailing_toc_page_number(stripped)
        return maybe_without_page != stripped
    return False


def is_subsection_line(line: str) -> bool:
    return bool(re.match(r"\s*\d+\.\d+", line))


def find_toc_region(lines: list[LineInfo]) -> dict[str, Any]:
    toc_start_index: int | None = None

    for index, line in enumerate(lines):
        normalised = normalise_heading_for_match(line.text)
        if normalised in {"sumario", "sumário"}:
            toc_start_index = index
            break

    if toc_start_index is None:
        return {
            "found": False,
            "start_char": None,
            "end_char": 0,
            "start_line": None,
            "end_line": None,
            "reason": "no_sumario_marker",
        }

    max_index = min(len(lines), toc_start_index + 400)
    body_start_index: int | None = None

    for index in range(toc_start_index + 1, max_index):
        stripped = strip_line_for_detection(lines[index].text)
        norm = normalise_heading_for_match(stripped)

        if norm in {"apresentacao", "introducao"} and not line_looks_like_toc_entry(stripped):
            body_start_index = index
            break

        if is_capitulo_line(stripped) and index > toc_start_index + 20:
            body_start_index = index
            break

        parsed = parse_single_line_top_heading(stripped)
        if parsed and index > toc_start_index + 20 and not line_looks_like_toc_entry(stripped):
            body_start_index = index
            break

    if body_start_index is None:
        body_start_index = max_index

    end_line = lines[body_start_index].line_number if body_start_index < len(lines) else lines[-1].line_number
    end_char = lines[body_start_index].start_char if body_start_index < len(lines) else lines[-1].end_char

    return {
        "found": True,
        "start_char": lines[toc_start_index].start_char,
        "end_char": end_char,
        "start_line": lines[toc_start_index].line_number,
        "end_line": end_line,
        "reason": "sumario_marker",
    }


def is_plausible_title_line(line: str) -> bool:
    stripped = strip_line_for_detection(line)
    if not stripped:
        return False
    if len(stripped) > 160:
        return False
    if is_subsection_line(stripped):
        return False
    if is_integer_line(stripped):
        return False
    if is_capitulo_line(stripped):
        return False
    if line_looks_like_toc_entry(stripped):
        return False
    return True


def make_heading_candidate(
        raw_heading_text: str,
        title_text: str,
        chapter_number: str | None,
        start_char: int,
        end_char: int,
        start_line: int,
        end_line: int,
        source: str,
) -> HeadingCandidate:
    normalised_title = normalise_heading_for_match(title_text)
    matched_label, matched_variant = match_target_title(normalised_title)
    is_fallback = normalised_title in FALLBACK_BOUNDARY_TITLES

    return HeadingCandidate(
        raw_heading_text=raw_heading_text,
        title_text=title_text,
        normalised_title=normalised_title,
        chapter_number=chapter_number,
        start_char=start_char,
        end_char=end_char,
        start_line=start_line,
        end_line=end_line,
        source=source,
        is_target_candidate=matched_label is not None,
        matched_label=matched_label,
        matched_variant=matched_variant,
        is_fallback_boundary=is_fallback,
    )


def iter_heading_candidates(lines: list[LineInfo], toc_region: dict[str, Any]) -> list[HeadingCandidate]:
    candidates: list[HeadingCandidate] = []
    body_start_char = int(toc_region.get("end_char") or 0)

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = strip_line_for_detection(line.text)

        if line.start_char < body_start_char:
            index += 1
            continue

        if not stripped:
            index += 1
            continue

        if is_subsection_line(stripped):
            index += 1
            continue

        chapter_number = is_capitulo_line(stripped) or is_integer_line(stripped)
        if chapter_number and index + 1 < len(lines):
            next_line = lines[index + 1]
            next_stripped = strip_line_for_detection(next_line.text)
            if is_plausible_title_line(next_stripped):
                raw = line.text + next_line.text
                candidates.append(
                    make_heading_candidate(
                        raw_heading_text=raw,
                        title_text=next_stripped,
                        chapter_number=chapter_number,
                        start_char=line.start_char,
                        end_char=next_line.end_char,
                        start_line=line.line_number,
                        end_line=next_line.line_number,
                        source="body",
                    )
                )
                index += 2
                continue

        parsed = parse_single_line_top_heading(stripped)
        if parsed and not line_looks_like_toc_entry(stripped):
            chapter_number, title = parsed
            candidates.append(
                make_heading_candidate(
                    raw_heading_text=line.text,
                    title_text=title,
                    chapter_number=chapter_number,
                    start_char=line.start_char,
                    end_char=line.end_char,
                    start_line=line.line_number,
                    end_line=line.line_number,
                    source="body",
                )
            )
            index += 1
            continue

        # Fallback boundaries can be unnumbered top-level headings.
        normalised = normalise_heading_for_match(stripped)
        if normalised in FALLBACK_BOUNDARY_TITLES:
            candidates.append(
                make_heading_candidate(
                    raw_heading_text=line.text,
                    title_text=stripped,
                    chapter_number=None,
                    start_char=line.start_char,
                    end_char=line.end_char,
                    start_line=line.line_number,
                    end_line=line.line_number,
                    source="body",
                )
            )

        index += 1

    candidates.sort(key=lambda candidate: candidate.start_char)
    return candidates


def candidate_to_dict(candidate: HeadingCandidate) -> dict[str, Any]:
    return {
        "raw_heading_text": candidate.raw_heading_text,
        "title_text": candidate.title_text,
        "normalised_title": candidate.normalised_title,
        "chapter_number": candidate.chapter_number,
        "start_char": candidate.start_char,
        "end_char": candidate.end_char,
        "start_line": candidate.start_line,
        "end_line": candidate.end_line,
        "source": candidate.source,
        "is_target_candidate": candidate.is_target_candidate,
        "matched_label": candidate.matched_label,
        "matched_variant": candidate.matched_variant,
        "is_fallback_boundary": candidate.is_fallback_boundary,
        "rejection_reason": candidate.rejection_reason,
    }


def find_peer_end_boundary(
        start: HeadingCandidate,
        candidates: list[HeadingCandidate],
) -> tuple[int | None, str | None, HeadingCandidate | None]:
    for candidate in candidates:
        if candidate.start_char <= start.start_char:
            continue
        if candidate.chapter_number is not None:
            return candidate.start_char, "peer_heading", candidate

    for candidate in candidates:
        if candidate.start_char <= start.start_char:
            continue
        if candidate.is_fallback_boundary:
            return candidate.start_char, "fallback_boundary", candidate

    return None, None, None


def extract_span(text: str, start_char: int, end_char: int) -> str:
    return text[start_char:end_char]


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json_atomic(path: Path, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_text_atomic(path, text)


def write_ndjson_atomic(path: Path, records: Iterable[dict[str, Any]]) -> None:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    write_text_atomic(path, text)


def write_summary_tsv(path: Path, report_records: list[dict[str, Any]]) -> None:
    columns = [
        "year",
        "filename_txt",
        "report_id",
        "chapter_label",
        "status",
        "title_matched",
        "output_path",
        "start_line",
        "end_line",
        "start_char",
        "end_char",
        "char_count",
        "warnings",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", extrasaction="ignore")
            writer.writeheader()

            for report in report_records:
                chapters = report.get("chapters", {})
                for label in TARGET_LABEL_ORDER:
                    chapter = chapters.get(label, {})
                    writer.writerow(
                        {
                            "year": report.get("year") or report.get("group"),
                            "filename_txt": report.get("filename_txt"),
                            "report_id": report.get("report_id"),
                            "chapter_label": label,
                            "status": chapter.get("status"),
                            "title_matched": chapter.get("title_matched"),
                            "output_path": chapter.get("output_path"),
                            "start_line": chapter.get("start_line"),
                            "end_line": chapter.get("end_line"),
                            "start_char": chapter.get("start_char"),
                            "end_char": chapter.get("end_char"),
                            "char_count": chapter.get("char_count"),
                            "warnings": "; ".join(chapter.get("warnings") or []),
                        }
                    )

            handle.flush()
            os.fsync(handle.fileno())

        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def existing_success(metadata_path: Path, config: Config) -> dict[str, Any] | None:
    if config.reprocess or not config.resume:
        return None
    if not metadata_path.exists():
        return None

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    if metadata.get("status") not in REPORT_SUCCESS_STATUSES:
        return None

    for chapter in metadata.get("chapters", {}).values():
        if chapter.get("status") == "found":
            output_path_value = chapter.get("output_path")
            extracted_hash = chapter.get("extracted_text_sha256")
            if not output_path_value or not extracted_hash:
                return None
            output_path = resolve_path(output_path_value, config.script_dir)
            if not output_path.exists():
                return None
            if sha256_text(output_path.read_text(encoding="utf-8", errors="replace")) != extracted_hash:
                return None

    return metadata


def base_chapter_record(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "title_matched": None,
        "title_variant": None,
        "chapter_number_detected": None,
        "output_path": None,
        "extracted_text_sha256": None,
        "start_line": None,
        "end_line": None,
        "start_char": None,
        "end_char": None,
        "char_count": None,
        "warnings": [],
    }


def classify_report_status(chapters: dict[str, dict[str, Any]]) -> str:
    statuses = [chapter.get("status") for chapter in chapters.values()]

    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "ambiguous" for status in statuses):
        return "ambiguous"
    if all(status == "not_found" for status in statuses):
        return "no_target_chapters"

    found_count = sum(status in CHAPTER_WRITTEN_STATUSES for status in statuses)
    non_found_count = sum(status not in CHAPTER_WRITTEN_STATUSES for status in statuses)

    if found_count > 0 and non_found_count == 0:
        return "success"
    if found_count > 0:
        return "partial_success"
    return "success"


def build_failure_record(
        row: dict[str, Any] | None,
        config: Config,
        error_type: str,
        error: str,
) -> dict[str, Any]:
    row = row or {}
    return {
        "filename_txt": row.get(config.filename_field),
        "filepath_txt": row.get(config.filepath_field),
        "year": row.get(config.group_field),
        "status": "failed",
        "error_type": error_type,
        "error": error,
        "manifest_row": row,
        "created_at": utc_now_iso(),
    }


def build_report_failure_metadata(
        row: dict[str, Any],
        config: Config,
        error_type: str,
        error: str,
        duration_seconds: float,
) -> dict[str, Any]:
    filename = row.get(config.filename_field)
    group = row.get(config.group_field)
    source = row.get(config.filepath_field)

    return {
        "filename": filename,
        "filename_txt": filename,
        "report_id": get_report_id(str(filename)) if filename else None,
        "group": group,
        "year": group,
        "status": "failed",
        "input": {
            "manifest_file": relpath(config.manifest, config.script_dir),
            "source_file": source,
        },
        "manifest_row": row,
        "hashes": {
            "manifest_file_sha256": sha256_file(config.manifest) if config.manifest.exists() else None,
            "source_text_sha256": None,
        },
        "chapters": {label: base_chapter_record("failed") for label in TARGET_LABEL_ORDER},
        "created_at": utc_now_iso(),
        "duration_seconds": round(duration_seconds, 4),
        "error_type": error_type,
        "error": error,
    }


def build_consolidated_chapter_record(
        row: dict[str, Any],
        config: Config,
        metadata_path: Path,
        chapter_label: str,
        chapter: dict[str, Any],
        source_text_sha256: str,
) -> dict[str, Any]:
    record = {
        key: value
        for key, value in row.items()
        if key != "_manifest_line_number"
    }

    record["enade_clean_up"] = {
        "chapter_label": chapter_label,
        "chapter_title_matched": chapter.get("title_matched"),
        "chapter_title_variant": chapter.get("title_variant"),
        "chapter_number_detected": chapter.get("chapter_number_detected"),
        "output_file": chapter.get("output_path"),
        "metadata_json": relpath(metadata_path, config.script_dir),
        "status": chapter.get("status"),
        "source_text_sha256": source_text_sha256,
        "extracted_text_sha256": chapter.get("extracted_text_sha256"),
        "start_line": chapter.get("start_line"),
        "end_line": chapter.get("end_line"),
        "start_char": chapter.get("start_char"),
        "end_char": chapter.get("end_char"),
        "char_count": chapter.get("char_count"),
        "cleaned_at": utc_now_iso(),
    }
    return record


def write_diagnostics(
        config: Config,
        group_value: Any,
        filename: str,
        toc_region: dict[str, Any],
        candidates: list[HeadingCandidate],
        chapters: dict[str, dict[str, Any]],
) -> None:
    diagnostic_path = config.diagnostics_dir / safe_path_part(group_value) / f"{Path(filename).stem}_heading_candidates.txt"
    lines = [
        f"programme: {PROGRAMME}",
        f"run_id: {config.run_id}",
        f"filename: {filename}",
        "",
        "table_of_contents_region:",
        json.dumps(toc_region, ensure_ascii=False, indent=2, sort_keys=True),
        "",
        "chapter_decisions:",
        json.dumps(chapters, ensure_ascii=False, indent=2, sort_keys=True),
        "",
        "heading_candidates:",
    ]

    for candidate in candidates:
        lines.append(json.dumps(candidate_to_dict(candidate), ensure_ascii=False, sort_keys=True))

    write_text_atomic(diagnostic_path, "\n".join(lines) + "\n")


def process_row(
        row: dict[str, Any],
        config: Config,
        manifest_hash: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    started = time.monotonic()
    failures: list[dict[str, Any]] = []
    consolidated: list[dict[str, Any]] = []

    filename = str(row.get(config.filename_field))
    group_value = row.get(config.group_field)
    report_id = get_report_id(filename)
    source_path = resolve_path(str(row.get(config.filepath_field)), config.script_dir)
    metadata_path = expected_metadata_output_path(config, group_value, filename)

    skipped_metadata = existing_success(metadata_path, config)
    if skipped_metadata is not None:
        chapters = {}
        for label in TARGET_LABEL_ORDER:
            old = skipped_metadata.get("chapters", {}).get(label, base_chapter_record("skipped_existing")).copy()
            if old.get("status") in CHAPTER_WRITTEN_STATUSES:
                old["status"] = "skipped_existing"
            chapters[label] = old

        report_record = {
            **skipped_metadata,
            "status": "skipped_existing",
            "chapters": chapters,
            "resume_source_metadata": relpath(metadata_path, config.script_dir),
        }
        logging.info("Skipped existing report: %s", filename)
        return report_record, consolidated, failures

    if not source_path.exists():
        message = "Source file not found"
        duration = time.monotonic() - started
        metadata = build_report_failure_metadata(row, config, "missing_source_file", message, duration)
        failures.append(build_failure_record(row, config, "missing_source_file", message))
        if not config.dry_run:
            write_json_atomic(metadata_path, metadata)
        return metadata, consolidated, failures

    if not source_path.is_file():
        message = "Source path is not a file"
        duration = time.monotonic() - started
        metadata = build_report_failure_metadata(row, config, "invalid_source_file", message, duration)
        failures.append(build_failure_record(row, config, "invalid_source_file", message))
        if not config.dry_run:
            write_json_atomic(metadata_path, metadata)
        return metadata, consolidated, failures

    try:
        source_text = read_source_text(source_path)
    except Exception as exc:
        message = f"Could not read source file: {exc}"
        duration = time.monotonic() - started
        metadata = build_report_failure_metadata(row, config, "unreadable_source_file", message, duration)
        failures.append(build_failure_record(row, config, "unreadable_source_file", message))
        if not config.dry_run:
            write_json_atomic(metadata_path, metadata)
        return metadata, consolidated, failures

    if not source_text.strip():
        message = "Source file is empty or whitespace only"
        duration = time.monotonic() - started
        metadata = build_report_failure_metadata(row, config, "empty_source_file", message, duration)
        failures.append(build_failure_record(row, config, "empty_source_file", message))
        if not config.dry_run:
            write_json_atomic(metadata_path, metadata)
        return metadata, consolidated, failures

    source_hash = sha256_text(source_text)
    lines = split_lines_with_offsets(source_text)
    line_starts = [line.start_char for line in lines]
    toc_region = find_toc_region(lines)
    candidates = iter_heading_candidates(lines, toc_region)

    chapters: dict[str, dict[str, Any]] = {}

    for label in TARGET_LABEL_ORDER:
        matched = [candidate for candidate in candidates if candidate.matched_label == label]

        if not matched:
            chapters[label] = base_chapter_record("not_found")
            continue

        if len(matched) > 1:
            record = base_chapter_record("ambiguous")
            record["candidate_count"] = len(matched)
            record["candidates"] = [
                {
                    "raw_heading_text": candidate.raw_heading_text,
                    "start_line": candidate.start_line,
                    "start_char": candidate.start_char,
                    "chapter_number": candidate.chapter_number,
                    "title_variant": candidate.matched_variant,
                }
                for candidate in matched
            ]
            chapters[label] = record
            logging.warning("Ambiguous %s in %s: %s candidates", label, filename, len(matched))
            continue

        start_candidate = matched[0]
        end_char, end_type, end_candidate = find_peer_end_boundary(start_candidate, candidates)
        warnings: list[str] = []

        unsafe = False
        if end_char is None:
            unsafe = True
            end_char = len(source_text)
            end_type = "end_of_file"
            warnings.append("No safe peer-level end boundary found.")
        elif end_type != "peer_heading":
            unsafe = True
            warnings.append(f"End boundary is lower-confidence: {end_type}.")

        span = extract_span(source_text, start_candidate.start_char, end_char)
        char_count = len(span)

        if char_count < config.min_chapter_chars:
            record = base_chapter_record("empty_or_too_short")
            record.update(
                {
                    "title_matched": start_candidate.title_text,
                    "title_variant": start_candidate.matched_variant,
                    "chapter_number_detected": start_candidate.chapter_number,
                    "start_line": start_candidate.start_line,
                    "end_line": line_number_for_offset(line_starts, end_char),
                    "start_char": start_candidate.start_char,
                    "end_char": end_char,
                    "char_count": char_count,
                    "warnings": warnings + [
                        f"Chapter span shorter than minimum {config.min_chapter_chars} characters."
                    ],
                }
            )
            chapters[label] = record
            continue

        if config.max_chapter_chars is not None and char_count > config.max_chapter_chars:
            warnings.append(f"Chapter span longer than maximum {config.max_chapter_chars} characters.")

        if unsafe and not config.allow_unsafe:
            record = base_chapter_record("unsafe")
            record.update(
                {
                    "title_matched": start_candidate.title_text,
                    "title_variant": start_candidate.matched_variant,
                    "chapter_number_detected": start_candidate.chapter_number,
                    "start_line": start_candidate.start_line,
                    "end_line": line_number_for_offset(line_starts, end_char),
                    "start_char": start_candidate.start_char,
                    "end_char": end_char,
                    "char_count": char_count,
                    "warnings": warnings,
                }
            )
            chapters[label] = record
            logging.warning("Unsafe %s in %s", label, filename)
            continue

        output_path = expected_chapter_output_path(config, group_value, filename, label)
        extracted_hash = sha256_text(span)
        status = "unsafe_written" if unsafe else "found"

        record = base_chapter_record(status)
        record.update(
            {
                "title_matched": start_candidate.title_text,
                "title_variant": start_candidate.matched_variant,
                "chapter_number_detected": start_candidate.chapter_number,
                "output_path": relpath(output_path, config.script_dir),
                "extracted_text_sha256": extracted_hash,
                "start_line": start_candidate.start_line,
                "end_line": line_number_for_offset(line_starts, end_char),
                "start_char": start_candidate.start_char,
                "end_char": end_char,
                "char_count": char_count,
                "warnings": warnings,
                "end_boundary_type": end_type,
                "end_boundary_heading": candidate_to_dict(end_candidate) if end_candidate else None,
            }
        )

        if not config.dry_run:
            write_text_atomic(output_path, span)

        chapters[label] = record

    report_status = classify_report_status(chapters)
    duration = time.monotonic() - started

    output_dir = config.output / safe_path_part(group_value)
    metadata = {
        "programme": PROGRAMME,
        "programme_version": PROGRAMME_VERSION,
        "run_id": config.run_id,
        "filename": filename,
        "filename_txt": filename,
        "report_id": report_id,
        "group": group_value,
        "year": group_value,
        "status": report_status,
        "input": {
            "manifest_file": relpath(config.manifest, config.script_dir),
            "source_file": relpath(source_path, config.script_dir),
        },
        "output": {
            "output_dir": relpath(output_dir, config.script_dir),
            "metadata_json": relpath(metadata_path, config.script_dir),
        },
        "manifest_row": row,
        "hashes": {
            "manifest_file_sha256": manifest_hash,
            "source_text_sha256": source_hash,
        },
        "toc_region": toc_region,
        "detected_heading_count": len(candidates),
        "chapters": chapters,
        "created_at": utc_now_iso(),
        "duration_seconds": round(duration, 4),
        "dry_run": config.dry_run,
        "error": None,
    }

    if not config.dry_run:
        write_json_atomic(metadata_path, metadata)

    if config.write_diagnostics:
        write_diagnostics(config, group_value, filename, toc_region, candidates, chapters)

    for label, chapter in sorted(
            chapters.items(),
            key=lambda item: item[1].get("start_char") if item[1].get("start_char") is not None else 10**18,
    ):
        if chapter.get("status") in CHAPTER_WRITTEN_STATUSES and not config.dry_run:
            consolidated.append(
                build_consolidated_chapter_record(
                    row=row,
                    config=config,
                    metadata_path=metadata_path,
                    chapter_label=label,
                    chapter=chapter,
                    source_text_sha256=source_hash,
                )
            )

    logging.info(
        "Processed %s: report_status=%s chapters=%s",
        filename,
        report_status,
        {label: chapter.get("status") for label, chapter in chapters.items()},
    )

    return metadata, consolidated, failures


def make_initial_counts() -> dict[str, int]:
    counts = {
        "manifest_rows_total": 0,
        "manifest_rows_matched": 0,
        "reports_planned": 0,
        "reports_processed": 0,
        "reports_failed": 0,
        "reports_with_any_chapter_found": 0,
        "reports_with_no_target_chapters": 0,
        "chapters_not_found": 0,
        "chapters_ambiguous": 0,
        "chapters_unsafe": 0,
        "chapters_empty_or_too_short": 0,
        "chapter_files_written": 0,
        "reports_skipped_existing": 0,
        "reports_dry_run": 0,
    }

    for label in TARGET_LABEL_ORDER:
        counts[f"chapters_found_{label}"] = 0

    return counts


def update_counts_from_report(counts: dict[str, int], report: dict[str, Any], config: Config) -> None:
    status = report.get("status")

    if status == "failed":
        counts["reports_failed"] += 1
    if status == "no_target_chapters":
        counts["reports_with_no_target_chapters"] += 1
    if status == "skipped_existing":
        counts["reports_skipped_existing"] += 1
    if config.dry_run:
        counts["reports_dry_run"] += 1

    any_written_or_found = False

    for label, chapter in report.get("chapters", {}).items():
        chapter_status = chapter.get("status")

        if chapter_status in {"found", "unsafe_written"}:
            any_written_or_found = True
            counts[f"chapters_found_{label}"] = counts.get(f"chapters_found_{label}", 0) + 1
            if not config.dry_run:
                counts["chapter_files_written"] += 1
        elif chapter_status == "not_found":
            counts["chapters_not_found"] += 1
        elif chapter_status == "ambiguous":
            counts["chapters_ambiguous"] += 1
        elif chapter_status == "unsafe":
            counts["chapters_unsafe"] += 1
        elif chapter_status == "empty_or_too_short":
            counts["chapters_empty_or_too_short"] += 1

    if any_written_or_found:
        counts["reports_with_any_chapter_found"] += 1


def build_summary(config: Config, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "run_id": config.run_id,
        "programme": PROGRAMME,
        "programme_version": PROGRAMME_VERSION,
        "manifest": relpath(config.manifest, config.script_dir),
        "output": relpath(config.output, config.script_dir),
        "cleaned_chapters_ndjson": relpath(config.cleaned_ndjson, config.script_dir),
        "counts": counts,
    }


def build_run_manifest(
        config: Config,
        manifest_hash: str,
        counts: dict[str, int],
        status: str,
        end_time: str,
) -> dict[str, Any]:
    return {
        "run_id": config.run_id,
        "programme": PROGRAMME,
        "programme_version": PROGRAMME_VERSION,
        "start_time": config.start_time,
        "end_time": end_time,
        "status": status,
        "paths": {
            "manifest": relpath(config.manifest, config.script_dir),
            "output": relpath(config.output, config.script_dir),
            "metadata_dir": relpath(config.metadata_dir, config.script_dir),
            "diagnostics_dir": relpath(config.diagnostics_dir, config.script_dir),
            "cleaned_chapters_ndjson": relpath(config.cleaned_ndjson, config.script_dir),
            "source_report_manifest_ndjson": relpath(config.source_report_manifest_ndjson, config.script_dir),
            "failures_ndjson": relpath(config.failures_file, config.script_dir),
            "summary_json": relpath(config.summary_file, config.script_dir),
            "summary_tsv": relpath(config.summary_tsv, config.script_dir),
            "log_file": relpath(config.log_file, config.script_dir),
        },
        "processing": {
            "limit": config.limit,
            "only_filename": config.only_filename,
            "resume": config.resume,
            "reprocess": config.reprocess,
            "dry_run": config.dry_run,
            "allow_unsafe": config.allow_unsafe,
            "write_diagnostics": config.write_diagnostics,
            "filename_field": config.filename_field,
            "filepath_field": config.filepath_field,
            "group_field": config.group_field,
            "output_extension": config.output_extension,
            "min_chapter_chars": config.min_chapter_chars,
            "max_chapter_chars": config.max_chapter_chars,
        },
        "target_chapters": TARGET_CHAPTERS,
        "hashes": {
            "manifest_file_sha256": manifest_hash,
        },
        "counts": counts,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        config = make_config(args)
        validate_config(config)
        setup_logging(config)
    except Exception as exc:
        print(f"{PROGRAMME}: fatal setup error: {exc}", file=sys.stderr)
        return 1

    logging.info("Programme start: %s", PROGRAMME)
    logging.info("Run ID: %s", config.run_id)
    logging.info("Manifest: %s", config.manifest)
    logging.info("Output: %s", config.output)
    logging.info("Fields: filename=%s filepath=%s group=%s", config.filename_field, config.filepath_field, config.group_field)
    logging.info("dry_run=%s resume=%s reprocess=%s allow_unsafe=%s diagnostics=%s", config.dry_run, config.resume, config.reprocess, config.allow_unsafe, config.write_diagnostics)

    if config.resume and config.reprocess:
        logging.warning("--reprocess supplied with --resume; --reprocess takes precedence.")

    counts = make_initial_counts()
    failures: list[dict[str, Any]] = []
    report_records: list[dict[str, Any]] = []
    consolidated_records: list[dict[str, Any]] = []

    try:
        manifest_hash = sha256_file(config.manifest)
        rows = load_manifest_rows(config.manifest)
        counts["manifest_rows_total"] = len(rows)
        logging.info("Manifest hash: %s", manifest_hash)
        logging.info("Manifest rows: %s", len(rows))

        matched_rows = filter_rows_by_filename(rows, config.filename_field, config.only_filename)
        counts["manifest_rows_matched"] = len(matched_rows)

        planned_rows = matched_rows[: config.limit] if config.limit is not None else matched_rows
        counts["reports_planned"] = len(planned_rows)

        logging.info("Matched rows: %s", len(matched_rows))
        logging.info("Planned reports: %s", len(planned_rows))

        for row in planned_rows:
            row_started = time.monotonic()

            missing_fields = validate_manifest_row(row, config)
            if missing_fields:
                message = f"Missing required manifest field(s): {', '.join(missing_fields)}"
                failure = build_failure_record(row, config, "missing_required_manifest_field", message)
                failures.append(failure)
                metadata = build_report_failure_metadata(
                    row=row,
                    config=config,
                    error_type="missing_required_manifest_field",
                    error=message,
                    duration_seconds=time.monotonic() - row_started,
                )
                report_records.append(metadata)
                update_counts_from_report(counts, metadata, config)
                counts["reports_processed"] += 1
                logging.error("%s", message)
                continue

            try:
                report, consolidated, row_failures = process_row(row, config, manifest_hash)
                report_records.append(report)
                consolidated_records.extend(consolidated)
                failures.extend(row_failures)
                update_counts_from_report(counts, report, config)
                counts["reports_processed"] += 1
            except Exception as exc:
                logging.exception("Unexpected row failure")
                failure = build_failure_record(row, config, "unexpected_exception", str(exc))
                failures.append(failure)
                metadata = build_report_failure_metadata(
                    row=row,
                    config=config,
                    error_type="unexpected_exception",
                    error=str(exc),
                    duration_seconds=time.monotonic() - row_started,
                )
                report_records.append(metadata)
                update_counts_from_report(counts, metadata, config)
                counts["reports_processed"] += 1

        write_ndjson_atomic(config.source_report_manifest_ndjson, report_records)
        write_ndjson_atomic(config.cleaned_ndjson, consolidated_records)
        write_ndjson_atomic(config.failures_file, failures)
        write_summary_tsv(config.summary_tsv, report_records)

        summary = build_summary(config, counts)
        write_json_atomic(config.summary_file, summary)

        end_time = utc_now_iso()
        run_status = "success" if not failures else "completed_with_failures"
        run_manifest = build_run_manifest(config, manifest_hash, counts, run_status, end_time)
        write_json_atomic(config.manifest_file, run_manifest)
        write_json_atomic(
            config.output / f"enade_clean_up_manifest_{config.run_id}.json",
            run_manifest,
            )

        logging.info("Final counts: %s", counts)
        logging.info("Programme completion: %s", run_status)

        return 1 if failures else 0

    except KeyboardInterrupt:
        logging.warning("Interrupted by user.")
        return 130
    except Exception as exc:
        logging.exception("Fatal run error: %s", exc)
        try:
            manifest_hash = sha256_file(config.manifest) if config.manifest.exists() else None
            end_time = utc_now_iso()
            run_manifest = build_run_manifest(
                config=config,
                manifest_hash=manifest_hash or "",
                counts=counts,
                status="failed",
                end_time=end_time,
            )
            write_json_atomic(config.manifest_file, run_manifest)
            write_json_atomic(config.summary_file, build_summary(config, counts))
            write_ndjson_atomic(config.failures_file, failures)
        except Exception:
            logging.exception("Could not write fatal-error outputs.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())