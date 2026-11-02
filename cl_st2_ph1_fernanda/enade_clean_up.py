#!/usr/bin/env python3
"""
Deterministic ENADE page-level chapter-of-interest classifier.

This programme enriches corpus/enade_pdf_pages_dataset.ndjson with page-level
metadata identifying whether each page belongs to selected ENADE chapters:

- c4: percepção da prova / percepção sobre a prova
- c5: distribuição dos conceitos / distribuição de conceitos
- c6: análise técnica da prova

It does not modify source manifests, source PDF files, or source text files.
It does not call an LLM.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd


PROGRAMME = "enade_clean_up.py"

DEFAULT_MANIFEST = "corpus/enade_pdf_pages_dataset.ndjson"
DEFAULT_OUTPUT_BASENAME = "corpus/enade_chapters_dataset"
DEFAULT_LOG_FILE = "corpus/enade_clean_up.log"

TARGET_TITLES: dict[str, list[str]] = {
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

CANONICAL_TITLES: dict[str, str] = {
    "c4": "percepção da prova",
    "c5": "distribuição dos conceitos",
    "c6": "análise técnica da prova",
}

STOP_SECTION_TITLES = [
    "anexo",
    "anexos",
    "referência",
    "referências",
    "bibliografia",
    "apêndice",
    "apêndices",
    "glossário",
]

REQUIRED_DEFAULT_COLUMNS = [
    "filename",
    "filepath_ori",
    "page_number",
    "page_filename",
    "page_filepath",
    "page_filename_txt",
    "page_filepath_txt",
]

ENRICHMENT_COLUMNS = [
    "chapter_of_interest",
    "chapter_of_interest_title",
    "chapter_of_interest_variant",
    "chapter_of_interest_status",
    "chapter_of_interest_confidence",
    "page_boundary_role",
    "chapter_start_page",
    "chapter_end_page",
    "chapter_boundary_method",
    "chapter_detection_notes",
    "c4_present",
    "c4_status",
    "c4_start_page",
    "c4_end_page",
    "c4_title_variant",
    "c5_present",
    "c5_status",
    "c5_start_page",
    "c5_end_page",
    "c5_title_variant",
    "c6_present",
    "c6_status",
    "c6_start_page",
    "c6_end_page",
    "c6_title_variant",
]


@dataclass
class BoundaryResult:
    kind: str
    label: str | None = None
    title: str | None = None
    variant: str | None = None
    confidence: str | None = None
    match_text: str | None = None
    notes: str | None = None


@dataclass
class ChapterRange:
    filename: str
    chapter_of_interest: str
    start_page: int
    end_page: int | None
    page_count: int
    title_variant: str | None
    confidence: str | None
    start_match: str | None
    end_reason: str | None
    status: str
    notes: str | None


@dataclass
class ClassificationResult:
    rows: dict[int, dict[str, Any]]
    ranges: list[ChapterRange]
    boundaries: list[dict[str, Any]]
    missing_text_files: int = 0
    unreadable_text_files: int = 0
    ambiguous_document: bool = False
    unsafe_document: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich ENADE PDF page manifest with chapter-of-interest metadata."
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--output-basename", default=DEFAULT_OUTPUT_BASENAME)
    parser.add_argument("--header-lines", type=int, default=10)
    parser.add_argument("--filename-field", default="filename")
    parser.add_argument("--page-number-field", default="page_number")
    parser.add_argument("--page-text-field", default="page_filepath_txt")
    parser.add_argument("--only-filename", default=None)
    parser.add_argument("--limit-documents", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--write-audit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write audit files. Use --no-write-audit to disable.",
    )
    parser.add_argument("--log-file", default=DEFAULT_LOG_FILE)
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Accepted for interface compatibility; outputs are overwritten on normal runs.",
    )
    return parser.parse_args()


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def resolve_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return script_dir() / path


def relpath(path: str | Path) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(script_dir()))
    except ValueError:
        return str(path)


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root.addHandler(file_handler)
    root.addHandler(console_handler)


def validate_args(args: argparse.Namespace, manifest_path: Path, output_basename: Path) -> None:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest does not exist: {manifest_path}")
    if not manifest_path.is_file():
        raise ValueError(f"Manifest is not a file: {manifest_path}")
    if not str(output_basename).strip():
        raise ValueError("--output-basename must not be empty")
    if args.header_lines <= 0:
        raise ValueError("--header-lines must be greater than zero")
    if args.limit_documents is not None and args.limit_documents <= 0:
        raise ValueError("--limit-documents must be greater than zero if supplied")
    output_basename.parent.mkdir(parents=True, exist_ok=True)


def load_ndjson_dataframe(path: Path) -> pd.DataFrame:
    try:
        return pd.read_json(path, orient="records", lines=True)
    except ValueError as exc:
        raise ValueError(f"Could not load NDJSON manifest: {path}: {exc}") from exc


def validate_required_columns(df: pd.DataFrame, required_columns: list[str]) -> None:
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"Required manifest columns are missing: {', '.join(missing)}")


def normalise_for_matching(text: str) -> str:
    text = text or ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[‐‑‒–—―−]+", " ", text)
    text = re.sub(r"[•·●○]+", " ", text)
    text = re.sub(r"\.{3,}", " ... ", text)
    text = re.sub(r"[^\w\s./-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


NORMALISED_TARGET_TITLES = {
    label: [normalise_for_matching(title).replace(" ... ", " ") for title in variants]
    for label, variants in TARGET_TITLES.items()
}

NORMALISED_STOP_SECTION_TITLES = [
    normalise_for_matching(title) for title in STOP_SECTION_TITLES
]


def truncate_text(text: str, max_len: int = 500) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def read_first_lines(path: Path, n: int) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, "text_missing"
    try:
        lines: list[str] = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(n):
                line = handle.readline()
                if line == "":
                    break
                lines.append(line.rstrip("\n"))
        return "\n".join(lines), None
    except OSError as exc:
        return None, f"text_unreadable: {exc}"


def is_toc_like(raw_header: str, normalised_header: str) -> bool:
    raw_lines = [line.strip() for line in raw_header.splitlines() if line.strip()]
    normalised_lines = [
        normalise_for_matching(line) for line in raw_lines if normalise_for_matching(line)
    ]

    if re.search(r"\.{4,}\s*\d+\s*$", raw_header, flags=re.MULTILINE):
        return True
    if re.search(r"\.{5,}", raw_header):
        return True
    if re.search(r"\b(sumario|indice)\b", normalised_header):
        return True

    chapter_entry_count = 0
    for line in normalised_lines:
        if re.search(r"\bcapitulo\s+\d+\b", line) and len(line.split()) <= 12:
            chapter_entry_count += 1
        if re.search(r"\bcapitulo\s+\d+.*\d+$", line) and len(line.split()) <= 15:
            chapter_entry_count += 1

    if chapter_entry_count >= 3:
        return True

    short_title_like = sum(1 for line in normalised_lines if 2 <= len(line.split()) <= 8)
    return len(normalised_lines) >= 6 and short_title_like / max(len(normalised_lines), 1) > 0.75


def is_heading_like(raw_text: str, normalised_text: str) -> bool:
    raw_text = (raw_text or "").strip()
    normalised_text = (normalised_text or "").strip()

    if not normalised_text:
        return False

    words = normalised_text.split()
    if len(words) > 14:
        return False

    if re.search(r"\bcapitulo\s+\d+\b", normalised_text):
        return True

    letters = [ch for ch in raw_text if ch.isalpha()]
    if letters:
        uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
        if uppercase_ratio >= 0.65 and len(words) <= 10:
            return True

    return len(words) <= 7


def variant_in_text(normalised_text: str) -> tuple[str, str] | None:
    for label, variants in NORMALISED_TARGET_TITLES.items():
        for variant in variants:
            if re.search(rf"\b{re.escape(variant)}\b", normalised_text):
                original_variant = TARGET_TITLES[label][variants.index(variant)]
                return label, original_variant
    return None


def detect_target_chapter(raw_header: str, normalised_header: str) -> BoundaryResult | None:
    match = variant_in_text(normalised_header)
    if not match:
        return None

    label, variant = match

    if is_toc_like(raw_header, normalised_header):
        return BoundaryResult(
            kind="toc_ignored",
            label=label,
            title=CANONICAL_TITLES[label],
            variant=variant,
            confidence="low",
            match_text=variant,
            notes="target_title_in_table_of_contents_like_context",
        )

    has_chapter_marker = bool(re.search(r"\bcapitulo\s+\d+\b", normalised_header))
    if has_chapter_marker:
        return BoundaryResult(
            kind="target_chapter",
            label=label,
            title=CANONICAL_TITLES[label],
            variant=variant,
            confidence="high",
            match_text=variant,
            notes="target_title_near_chapter_marker",
        )

    raw_lines = raw_header.splitlines()
    for line in raw_lines:
        normalised_line = normalise_for_matching(line)
        line_match = variant_in_text(normalised_line)
        if line_match and line_match[0] == label and is_heading_like(line, normalised_line):
            return BoundaryResult(
                kind="target_chapter",
                label=label,
                title=CANONICAL_TITLES[label],
                variant=variant,
                confidence="medium",
                match_text=variant,
                notes="target_title_as_standalone_heading",
            )

    return BoundaryResult(
        kind="candidate",
        label=label,
        title=CANONICAL_TITLES[label],
        variant=variant,
        confidence="low",
        match_text=variant,
        notes="target_phrase_present_but_not_heading_like",
    )


def detect_stop_section(raw_header: str, normalised_header: str) -> BoundaryResult | None:
    raw_lines = raw_header.splitlines()[:5]
    for raw_line in raw_lines:
        line = normalise_for_matching(raw_line)
        if not line:
            continue

        words = line.split()
        if len(words) > 8:
            continue

        for stop_title in NORMALISED_STOP_SECTION_TITLES:
            if re.match(rf"^{re.escape(stop_title)}(\s+[ivxlcdm0-9]+)?\b", line):
                if is_heading_like(raw_line, line):
                    return BoundaryResult(
                        kind="stop_section",
                        confidence="high",
                        match_text=raw_line.strip(),
                        notes=f"stop_section_heading:{stop_title}",
                    )

    return None


def detect_other_chapter(raw_header: str, normalised_header: str) -> BoundaryResult | None:
    if is_toc_like(raw_header, normalised_header):
        return None

    has_chapter_marker = bool(re.search(r"\bcapitulo\s+\d+\b", normalised_header))
    if not has_chapter_marker:
        return None

    if variant_in_text(normalised_header):
        return None

    lines = raw_header.splitlines()[:5]
    joined_first_lines = normalise_for_matching("\n".join(lines))

    if re.search(r"\bcapitulo\s+\d+\b", joined_first_lines):
        return BoundaryResult(
            kind="other_chapter",
            confidence="medium",
            match_text="capitulo",
            notes="non_target_chapter_marker_in_header",
        )

    return None


def detect_boundary(raw_header: str) -> BoundaryResult:
    normalised_header = normalise_for_matching(raw_header)

    # Priority order: TOC exclusion via target detection, stop sections,
    # target chapter starts, other chapter starts, candidates, none.
    target = detect_target_chapter(raw_header, normalised_header)
    if target and target.kind == "toc_ignored":
        return target

    stop = detect_stop_section(raw_header, normalised_header)
    if stop:
        return stop

    if target and target.kind == "target_chapter":
        return target

    other = detect_other_chapter(raw_header, normalised_header)
    if other:
        return other

    if target and target.kind == "candidate":
        return target

    return BoundaryResult(kind="none")


def default_page_metadata() -> dict[str, Any]:
    return {
        "chapter_of_interest": "na",
        "chapter_of_interest_title": None,
        "chapter_of_interest_variant": None,
        "chapter_of_interest_status": "outside_chapter_of_interest",
        "chapter_of_interest_confidence": None,
        "page_boundary_role": "outside",
        "chapter_start_page": None,
        "chapter_end_page": None,
        "chapter_boundary_method": None,
        "chapter_detection_notes": None,
    }


def append_note(existing: str | None, note: str | None) -> str | None:
    if not note:
        return existing
    if not existing:
        return note
    if note in existing.split("; "):
        return existing
    return f"{existing}; {note}"


def classify_document_pages(
        group: pd.DataFrame,
        *,
        filename: str,
        base_dir: Path,
        header_lines: int,
        page_number_field: str,
        page_text_field: str,
) -> ClassificationResult:
    rows: dict[int, dict[str, Any]] = {}
    ranges: list[ChapterRange] = []
    boundaries: list[dict[str, Any]] = []
    active_range: ChapterRange | None = None
    current_label = "na"
    current_title: str | None = None
    current_variant: str | None = None
    current_confidence: str | None = None
    current_start_page: int | None = None
    missing_text_files = 0
    unreadable_text_files = 0
    ambiguous_document = False
    unsafe_document = False

    sorted_group = group.sort_values(page_number_field, kind="mergesort")

    for index, row in sorted_group.iterrows():
        page_number = int(row[page_number_field])
        metadata = default_page_metadata()

        text_path = Path(str(row[page_text_field]))
        if not text_path.is_absolute():
            text_path = base_dir / text_path

        raw_header, read_error = read_first_lines(text_path, header_lines)

        if read_error == "text_missing":
            missing_text_files += 1
            metadata["chapter_of_interest_status"] = "text_missing"
            metadata["chapter_detection_notes"] = "page_text_file_missing"
            rows[index] = metadata
            current_label = "na"
            current_title = None
            current_variant = None
            current_confidence = None
            current_start_page = None
            if active_range is not None:
                active_range.end_page = page_number - 1
                active_range.page_count = max(0, active_range.end_page - active_range.start_page + 1)
                active_range.end_reason = "text_missing"
                ranges.append(active_range)
                active_range = None
            continue

        if read_error and read_error.startswith("text_unreadable"):
            unreadable_text_files += 1
            metadata["chapter_of_interest_status"] = "text_unreadable"
            metadata["chapter_detection_notes"] = read_error
            rows[index] = metadata
            current_label = "na"
            current_title = None
            current_variant = None
            current_confidence = None
            current_start_page = None
            if active_range is not None:
                active_range.end_page = page_number - 1
                active_range.page_count = max(0, active_range.end_page - active_range.start_page + 1)
                active_range.end_reason = "text_unreadable"
                ranges.append(active_range)
                active_range = None
            continue

        raw_header = raw_header or ""
        boundary = detect_boundary(raw_header)
        header_sample = truncate_text(raw_header)

        if boundary.kind != "none":
            boundaries.append(
                {
                    "filename": filename,
                    "page_number": page_number,
                    "boundary_kind": boundary.kind,
                    "label": boundary.label,
                    "confidence": boundary.confidence,
                    "matched_variant": boundary.variant,
                    "header_sample": header_sample,
                    "notes": boundary.notes,
                }
            )

        if boundary.kind == "stop_section":
            if active_range is not None:
                active_range.end_page = page_number - 1
                active_range.page_count = max(0, active_range.end_page - active_range.start_page + 1)
                active_range.end_reason = "stop_section"
                ranges.append(active_range)
                active_range = None
            current_label = "na"
            current_title = None
            current_variant = None
            current_confidence = None
            current_start_page = None
            metadata["chapter_boundary_method"] = "stop_section"
            metadata["chapter_detection_notes"] = boundary.notes

        elif boundary.kind == "target_chapter" and boundary.label in TARGET_TITLES:
            if active_range is not None:
                active_range.end_page = page_number - 1
                active_range.page_count = max(0, active_range.end_page - active_range.start_page + 1)
                active_range.end_reason = "next_target_chapter"
                ranges.append(active_range)

            current_label = boundary.label
            current_title = boundary.title
            current_variant = boundary.variant
            current_confidence = boundary.confidence
            current_start_page = page_number

            active_range = ChapterRange(
                filename=filename,
                chapter_of_interest=current_label,
                start_page=page_number,
                end_page=None,
                page_count=0,
                title_variant=current_variant,
                confidence=current_confidence,
                start_match=boundary.match_text,
                end_reason=None,
                status="found",
                notes=boundary.notes,
            )
            metadata["chapter_boundary_method"] = "target_title_header"
            metadata["page_boundary_role"] = "chapter_start"

        elif boundary.kind == "other_chapter":
            if active_range is not None:
                active_range.end_page = page_number - 1
                active_range.page_count = max(0, active_range.end_page - active_range.start_page + 1)
                active_range.end_reason = "other_chapter"
                ranges.append(active_range)
                active_range = None
            current_label = "na"
            current_title = None
            current_variant = None
            current_confidence = None
            current_start_page = None
            metadata["chapter_boundary_method"] = "other_chapter_reset"
            metadata["chapter_detection_notes"] = boundary.notes

        elif boundary.kind == "toc_ignored":
            metadata["chapter_of_interest_status"] = "candidate_boundary"
            metadata["chapter_boundary_method"] = "toc_ignored"
            metadata["chapter_detection_notes"] = boundary.notes

        elif boundary.kind == "candidate":
            metadata["chapter_of_interest_status"] = "candidate_boundary"
            metadata["chapter_boundary_method"] = "candidate_low_confidence"
            metadata["chapter_detection_notes"] = boundary.notes

        is_empty_header = not raw_header.strip()
        if current_label != "na":
            metadata["chapter_of_interest"] = current_label
            metadata["chapter_of_interest_title"] = current_title
            metadata["chapter_of_interest_variant"] = current_variant
            metadata["chapter_of_interest_status"] = "in_chapter_of_interest"
            metadata["chapter_of_interest_confidence"] = current_confidence
            metadata["chapter_start_page"] = current_start_page
            metadata["chapter_boundary_method"] = metadata["chapter_boundary_method"] or "state_propagation"
            if metadata["page_boundary_role"] == "outside":
                metadata["page_boundary_role"] = "chapter_middle"
            if is_empty_header:
                metadata["chapter_detection_notes"] = append_note(
                    metadata["chapter_detection_notes"], "empty_text_inside_active_chapter"
                )
        elif metadata["chapter_of_interest_status"] not in {
            "candidate_boundary",
            "text_missing",
            "text_unreadable",
        }:
            metadata["chapter_of_interest"] = "na"
            metadata["page_boundary_role"] = "outside"
            metadata["chapter_of_interest_status"] = "outside_chapter_of_interest"

        rows[index] = metadata

    if active_range is not None:
        last_page = int(sorted_group.iloc[-1][page_number_field])
        active_range.end_page = last_page
        active_range.page_count = max(0, last_page - active_range.start_page + 1)
        active_range.end_reason = "document_end"
        active_range.status = "partial"
        active_range.notes = append_note(active_range.notes, "range_continues_to_document_end")
        ranges.append(active_range)

    # Fill range end pages and page boundary roles.
    for chapter_range in ranges:
        if chapter_range.end_page is None:
            continue
        for index, row in sorted_group.iterrows():
            page_number = int(row[page_number_field])
            if chapter_range.start_page <= page_number <= chapter_range.end_page:
                row_meta = rows[index]
                if row_meta.get("chapter_of_interest") == chapter_range.chapter_of_interest:
                    row_meta["chapter_end_page"] = chapter_range.end_page
                    if page_number == chapter_range.start_page:
                        row_meta["page_boundary_role"] = "chapter_start"
                    elif page_number == chapter_range.end_page:
                        row_meta["page_boundary_role"] = "chapter_end"
                    else:
                        row_meta["page_boundary_role"] = "chapter_middle"

    # Detect ambiguous duplicate starts for same label.
    starts_by_label: dict[str, int] = {}
    for chapter_range in ranges:
        starts_by_label[chapter_range.chapter_of_interest] = (
                starts_by_label.get(chapter_range.chapter_of_interest, 0) + 1
        )
    duplicate_labels = [label for label, count in starts_by_label.items() if count > 1]
    if duplicate_labels:
        ambiguous_document = True
        for metadata in rows.values():
            metadata["chapter_detection_notes"] = append_note(
                metadata.get("chapter_detection_notes"),
                f"multiple_ranges_detected_for:{','.join(duplicate_labels)}",
            )

    # If no selected chapter was found, use not_found status on otherwise outside pages.
    if not ranges:
        for metadata in rows.values():
            if metadata.get("chapter_of_interest_status") == "outside_chapter_of_interest":
                metadata["chapter_of_interest_status"] = "not_found"
                metadata["chapter_detection_notes"] = append_note(
                    metadata.get("chapter_detection_notes"), "no_target_chapter_found_in_document"
                )

    return ClassificationResult(
        rows=rows,
        ranges=ranges,
        boundaries=boundaries,
        missing_text_files=missing_text_files,
        unreadable_text_files=unreadable_text_files,
        ambiguous_document=ambiguous_document,
        unsafe_document=unsafe_document,
    )


def initialise_enrichment_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in ENRICHMENT_COLUMNS:
        if column in {"c4_present", "c5_present", "c6_present"}:
            df[column] = False
        elif column in {
            "chapter_start_page",
            "chapter_end_page",
            "c4_start_page",
            "c4_end_page",
            "c5_start_page",
            "c5_end_page",
            "c6_start_page",
            "c6_end_page",
        }:
            df[column] = pd.NA
        elif column == "chapter_of_interest":
            df[column] = "na"
        elif column == "chapter_of_interest_status":
            df[column] = "outside_chapter_of_interest"
        elif column == "page_boundary_role":
            df[column] = "outside"
        else:
            df[column] = None
    return df


def derive_document_flags(
        df: pd.DataFrame,
        indices: list[int],
        ranges: list[ChapterRange],
        ambiguous_document: bool,
        unsafe_document: bool,
) -> None:
    by_label: dict[str, list[ChapterRange]] = {"c4": [], "c5": [], "c6": []}
    for chapter_range in ranges:
        by_label.setdefault(chapter_range.chapter_of_interest, []).append(chapter_range)

    for label in ["c4", "c5", "c6"]:
        present_col = f"{label}_present"
        status_col = f"{label}_status"
        start_col = f"{label}_start_page"
        end_col = f"{label}_end_page"
        variant_col = f"{label}_title_variant"

        label_ranges = by_label.get(label, [])
        if unsafe_document:
            status = "unsafe"
        elif ambiguous_document and len(label_ranges) > 1:
            status = "ambiguous"
        elif label_ranges:
            status = "partial" if any(r.status == "partial" for r in label_ranges) else "found"
        else:
            status = "not_found"

        if label_ranges:
            start_page = min(r.start_page for r in label_ranges)
            end_pages = [r.end_page for r in label_ranges if r.end_page is not None]
            end_page = max(end_pages) if end_pages else None
            title_variant = label_ranges[0].title_variant
        else:
            start_page = None
            end_page = None
            title_variant = None

        df.loc[indices, present_col] = bool(label_ranges)
        df.loc[indices, status_col] = status
        df.loc[indices, start_col] = start_page
        df.loc[indices, end_col] = end_page
        df.loc[indices, variant_col] = title_variant


def atomic_write_dataframe_json(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        df.to_json(tmp_path, orient="records", lines=True, force_ascii=False)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_write_json(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def write_outputs(df: pd.DataFrame, output_basename: Path) -> dict[str, Path]:
    output_ndjson = output_basename.with_suffix(".ndjson")
    output_tsv = output_basename.with_suffix(".tsv")
    output_xlsx = output_basename.with_suffix(".xlsx")

    atomic_write_dataframe_json(df, output_ndjson)
    df.to_csv(output_tsv, sep="\t", index=False, encoding="utf-8")

    max_excel_rows = 1_048_576
    if len(df) > max_excel_rows:
        raise ValueError(
            f"Cannot write XLSX: {len(df)} rows exceeds Excel limit {max_excel_rows}"
        )
    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="enade_chapters_dataset", index=False)

    return {
        "ndjson": output_ndjson,
        "tsv": output_tsv,
        "xlsx": output_xlsx,
    }


def write_audit_files(
        range_rows: list[ChapterRange],
        boundary_rows: list[dict[str, Any]],
        output_dir: Path,
) -> dict[str, Path]:
    ranges_path = output_dir / "enade_clean_up_audit_ranges.tsv"
    boundaries_path = output_dir / "enade_clean_up_audit_boundaries.tsv"

    range_dicts = [asdict(row) for row in range_rows]
    pd.DataFrame(
        range_dicts,
        columns=[
            "filename",
            "chapter_of_interest",
            "start_page",
            "end_page",
            "page_count",
            "title_variant",
            "confidence",
            "start_match",
            "end_reason",
            "status",
            "notes",
        ],
    ).to_csv(ranges_path, sep="\t", index=False, encoding="utf-8")

    pd.DataFrame(
        boundary_rows,
        columns=[
            "filename",
            "page_number",
            "boundary_kind",
            "label",
            "confidence",
            "matched_variant",
            "header_sample",
            "notes",
        ],
    ).to_csv(boundaries_path, sep="\t", index=False, encoding="utf-8")

    return {"ranges": ranges_path, "boundaries": boundaries_path}


def build_summary(
        *,
        args: argparse.Namespace,
        manifest_path: Path,
        output_basename: Path,
        input_rows: int,
        output_rows: int,
        documents_total: int,
        documents_processed: int,
        df: pd.DataFrame,
        missing_text_files: int,
        unreadable_text_files: int,
        ambiguous_documents: int,
        unsafe_documents: int,
) -> dict[str, Any]:
    counts = {
        "input_rows": input_rows,
        "output_rows": output_rows,
        "documents_total": documents_total,
        "documents_processed": documents_processed,
        "pages_c4": int((df["chapter_of_interest"] == "c4").sum()),
        "pages_c5": int((df["chapter_of_interest"] == "c5").sum()),
        "pages_c6": int((df["chapter_of_interest"] == "c6").sum()),
        "pages_na": int((df["chapter_of_interest"] == "na").sum()),
        "documents_with_c4": int(df.groupby(args.filename_field)["c4_present"].max().sum()),
        "documents_with_c5": int(df.groupby(args.filename_field)["c5_present"].max().sum()),
        "documents_with_c6": int(df.groupby(args.filename_field)["c6_present"].max().sum()),
        "documents_with_no_target_chapters": int(
            (
                    df.groupby(args.filename_field)[["c4_present", "c5_present", "c6_present"]]
                    .max()
                    .sum(axis=1)
                    == 0
            ).sum()
        ),
        "missing_text_files": missing_text_files,
        "unreadable_text_files": unreadable_text_files,
        "ambiguous_documents": ambiguous_documents,
        "unsafe_documents": unsafe_documents,
    }

    return {
        "programme": PROGRAMME,
        "manifest": relpath(manifest_path),
        "output_basename": relpath(output_basename),
        "dry_run": args.dry_run,
        "header_lines": args.header_lines,
        "filename_field": args.filename_field,
        "page_number_field": args.page_number_field,
        "page_text_field": args.page_text_field,
        "only_filename": args.only_filename,
        "limit_documents": args.limit_documents,
        "counts": counts,
    }


def main() -> int:
    args = parse_args()
    manifest_path = resolve_path(args.manifest)
    output_basename = resolve_path(args.output_basename)
    log_file = resolve_path(args.log_file)

    try:
        validate_args(args, manifest_path, output_basename)
        setup_logging(log_file)

        logging.info("Programme start: %s", PROGRAMME)
        logging.info("Manifest: %s", manifest_path)
        logging.info("Output basename: %s", output_basename)
        logging.info("Header lines: %s", args.header_lines)
        logging.info("Dry run: %s", args.dry_run)

        enade_df_pdf_pages = load_ndjson_dataframe(manifest_path)
        input_rows = len(enade_df_pdf_pages)
        logging.info("Input rows: %s", input_rows)

        required_columns = list(
            dict.fromkeys(
                REQUIRED_DEFAULT_COLUMNS
                + [args.filename_field, args.page_number_field, args.page_text_field]
            )
        )
        validate_required_columns(enade_df_pdf_pages, required_columns)

        documents_total = int(enade_df_pdf_pages[args.filename_field].nunique())
        logging.info("Documents total: %s", documents_total)

        enade_df_pdf_pages["_original_row_order"] = range(len(enade_df_pdf_pages))

        if args.only_filename is not None:
            enade_df_pdf_pages = enade_df_pdf_pages[
                enade_df_pdf_pages[args.filename_field] == args.only_filename
                ].copy()
            if enade_df_pdf_pages.empty:
                raise ValueError(f"--only-filename matched no rows: {args.only_filename}")
            logging.info("Filtered to filename: %s", args.only_filename)

        if args.limit_documents is not None:
            selected_documents = (
                enade_df_pdf_pages[args.filename_field]
                .drop_duplicates()
                .head(args.limit_documents)
                .tolist()
            )
            enade_df_pdf_pages = enade_df_pdf_pages[
                enade_df_pdf_pages[args.filename_field].isin(selected_documents)
            ].copy()
            logging.info("Limited to first %s documents", args.limit_documents)

        documents_processed = int(enade_df_pdf_pages[args.filename_field].nunique())
        logging.info("Documents processed: %s", documents_processed)

        enade_df_pdf_pages = initialise_enrichment_columns(enade_df_pdf_pages)

        all_ranges: list[ChapterRange] = []
        all_boundaries: list[dict[str, Any]] = []
        missing_text_files = 0
        unreadable_text_files = 0
        ambiguous_documents = 0
        unsafe_documents = 0

        for filename, group in enade_df_pdf_pages.groupby(args.filename_field, sort=False):
            result = classify_document_pages(
                group,
                filename=str(filename),
                base_dir=script_dir(),
                header_lines=args.header_lines,
                page_number_field=args.page_number_field,
                page_text_field=args.page_text_field,
            )

            for index, metadata in result.rows.items():
                for key, value in metadata.items():
                    enade_df_pdf_pages.at[index, key] = value

            indices = list(group.index)
            derive_document_flags(
                enade_df_pdf_pages,
                indices,
                result.ranges,
                result.ambiguous_document,
                result.unsafe_document,
            )

            all_ranges.extend(result.ranges)
            all_boundaries.extend(result.boundaries)
            missing_text_files += result.missing_text_files
            unreadable_text_files += result.unreadable_text_files
            ambiguous_documents += int(result.ambiguous_document)
            unsafe_documents += int(result.unsafe_document)

        enade_df_pdf_pages = enade_df_pdf_pages.sort_values(
            "_original_row_order", kind="mergesort"
        ).drop(columns=["_original_row_order"])

        summary = build_summary(
            args=args,
            manifest_path=manifest_path,
            output_basename=output_basename,
            input_rows=input_rows,
            output_rows=len(enade_df_pdf_pages),
            documents_total=documents_total,
            documents_processed=documents_processed,
            df=enade_df_pdf_pages,
            missing_text_files=missing_text_files,
            unreadable_text_files=unreadable_text_files,
            ambiguous_documents=ambiguous_documents,
            unsafe_documents=unsafe_documents,
        )

        summary_path = output_basename.parent / "enade_clean_up_summary.json"

        if args.dry_run:
            logging.info("Dry run enabled: enriched NDJSON/TSV/XLSX will not be written")
            atomic_write_json(summary, summary_path)
            logging.info("Dry-run summary written: %s", summary_path)
        else:
            output_paths = write_outputs(enade_df_pdf_pages, output_basename)
            for label, path in output_paths.items():
                logging.info("Output %s written: %s", label, path)

            if args.write_audit:
                audit_paths = write_audit_files(
                    all_ranges,
                    all_boundaries,
                    output_basename.parent,
                )
                for label, path in audit_paths.items():
                    logging.info("Audit %s written: %s", label, path)

            atomic_write_json(summary, summary_path)
            logging.info("Summary written: %s", summary_path)

        logging.info("Pages c4: %s", summary["counts"]["pages_c4"])
        logging.info("Pages c5: %s", summary["counts"]["pages_c5"])
        logging.info("Pages c6: %s", summary["counts"]["pages_c6"])
        logging.info("Pages na: %s", summary["counts"]["pages_na"])
        logging.info("Missing text files: %s", missing_text_files)
        logging.info("Unreadable text files: %s", unreadable_text_files)
        logging.info("Detected boundaries: %s", len(all_boundaries))
        logging.info("Ambiguous documents: %s", ambiguous_documents)
        logging.info("Unsafe documents: %s", unsafe_documents)
        logging.info("Programme completed")
        return 0

    except KeyboardInterrupt:
        logging.error("Interrupted by user")
        return 130
    except Exception as exc:
        if logging.getLogger().handlers:
            logging.exception("Fatal error: %s", exc)
        else:
            print(f"Fatal error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())