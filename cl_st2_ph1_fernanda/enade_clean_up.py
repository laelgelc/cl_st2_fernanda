#!/usr/bin/env python3
"""
enade_clean_up.py

Conservative, auditable ENADE report chapter extractor and cleaner.

This programme:
- never modifies raw input files;
- detects target ENADE chapters by title, not by chapter number;
- avoids table-of-contents matches where possible;
- extracts only chapters of interest;
- applies deterministic conservative cleanup;
- writes Markdown and JSON provenance files;
- writes run-level manifest, summary, and append-only log.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


TOOL_NAME = "enade_clean_up.py"
TOOL_VERSION = "v1"

DEFAULT_INPUT_ROOT = "corpus/01_enade_txt"
DEFAULT_MANIFEST = "corpus/enade_dataset.ndjson"
DEFAULT_OUTPUT_DIR = "corpus/02_enade_clean"
DEFAULT_PROMPT = "denoising_prompts/denoising_v1.md"

TARGET_CHAPTERS = {
    "c4": [
        "percepcao sobre a prova",
        "percepcao da prova",
    ],
    "c5": [
        "distribuicao dos conceitos",
        "distribuicao de conceitos",
    ],
    "c6": [
        "analise tecnica da prova",
    ],
}

WARNING_CODES = {
    "no_target_chapters_found",
    "toc_only_target_headings_found",
    "multiple_body_target_heading_candidates",
    "possible_pdf_font_encoding_corruption",
    "high_control_character_ratio",
    "high_replacement_character_ratio",
    "chapter_span_unusually_short",
    "chapter_span_unusually_long",
    "possible_table_damage",
    "possible_llm_output_truncation",
    "llm_response_invalid_json",
    "llm_response_missing_metadata",
    "llm_response_missing_chapters",
}

CONTROL_SUSPICIOUS_CHARS = set("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19")
PDF_FONT_SUSPICIOUS_CHARS = set("Ǥͳʹ͵.!XW3lA")
ROMAN_RE = re.compile(r"^\s*[ivxlcdmIVXLCDM]+\s*$")
PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
CHAPTER_WORD_RE = re.compile(r"\bcap[ií]tulo\b", re.IGNORECASE)
CHAPTER_NUM_RE = re.compile(
    r"^\s*(?:cap[ií]tulo\s*)?(?P<num>\d{1,2})(?:\s*[-–—.:])?\s+(?P<title>.+?)\s*$",
    re.IGNORECASE,
)
SECTION_NUM_RE = re.compile(r"^\s*\d{1,2}(?:\.\d+){1,4}\s+")
SAME_LEVEL_NUM_RE = re.compile(r"^\s*(?:cap[ií]tulo\s*)?\d{1,2}\s*$", re.IGNORECASE)
DOTTED_LEADER_RE = re.compile(r"(?:\.{3,}|Ǥ{3,})")
ENDS_PAGE_RE = re.compile(r"(?:\.{2,}|Ǥ{2,}|\s)\s*\d{1,4}\s*$")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")


@dataclass
class HeadingCandidate:
    line_index: int
    line_number: int
    text: str
    normalized: str
    kind: str
    level: int
    source_chapter_number: str | None
    label: str | None
    is_target: bool
    is_toc: bool
    suspicious: bool


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


def make_run_id(now: dt.datetime | None = None) -> str:
    now = now or utc_now()
    return now.strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract and clean selected chapters from ENADE text reports."
    )
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Input NDJSON manifest path.")
    parser.add_argument("--input-root", default=DEFAULT_INPUT_ROOT, help="Root directory for raw TXT files.")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Output directory.")
    parser.add_argument("--mode", choices=["local", "llm", "diagnose-only"], default="local")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="LLM denoising prompt path.")
    parser.add_argument("--model", default=None, help="LLM model name for --mode llm.")
    parser.add_argument("--max-output-tokens", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only-filename", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--write-empty", action="store_true")
    parser.add_argument("--fix-hyphenation", dest="fix_hyphenation", action="store_true", default=True)
    parser.add_argument("--no-fix-hyphenation", dest="fix_hyphenation", action="store_false")
    parser.add_argument("--cleanup-level", choices=["conservative", "aggressive"], default="conservative")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--max-retries", type=int, default=3)
    return parser.parse_args()


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(TOOL_NAME)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def normalize_newlines_and_controls(text: str) -> tuple[str, dict[str, int]]:
    stats = {
        "control_chars_removed": 0,
    }

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    text = text.replace("\u00a0", " ")
    text = text.replace("\f", "\n")

    cleaned_chars: list[str] = []
    for char in text:
        if char == "\n":
            cleaned_chars.append(char)
            continue
        category = unicodedata.category(char)
        if category.startswith("C") and char not in ("\n",):
            stats["control_chars_removed"] += 1
            continue
        cleaned_chars.append(char)

    return "".join(cleaned_chars), stats


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_ocr_punctuation(text: str) -> str:
    replacements = {
        "–": "-",
        "—": "-",
        "−": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "Ǥ": ".",
        "ͳ": "1",
        "ʹ": "2",
        "͵": "3",
        "\u2026": "...",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def normalize_for_matching(text: str) -> str:
    text = normalize_ocr_punctuation(text)
    text = strip_accents(text).lower()
    text = re.sub(r"\.{2,}\s*\d{1,4}\s*$", "", text)
    text = re.sub(r"\bcapitulo\b\s*\d{1,2}\s*", "", text)
    text = re.sub(r"^\s*\d{1,2}(?:\.\d+)*\s*", "", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def target_label_for_normalized_title(normalized: str) -> str | None:
    normalized = normalize_for_matching(normalized)
    for label, variants in TARGET_CHAPTERS.items():
        for variant in variants:
            if normalized == variant:
                return label
    return None


def target_label_contained_in_normalized(normalized: str) -> str | None:
    normalized = normalize_for_matching(normalized)
    for label, variants in TARGET_CHAPTERS.items():
        for variant in variants:
            if variant in normalized:
                return label
    return None


def has_suspicious_pdf_chars(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    suspicious_count = sum(1 for char in stripped if char in PDF_FONT_SUSPICIOUS_CHARS or char in CONTROL_SUSPICIOUS_CHARS)
    return suspicious_count / max(len(stripped), 1) > 0.10


def is_toc_line(line: str, line_index: int, in_sumario_block: bool) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if in_sumario_block:
        return True
    if DOTTED_LEADER_RE.search(stripped):
        return True
    if ENDS_PAGE_RE.search(stripped) and len(stripped) < 160:
        return True
    if line_index < 80 and re.search(r"\s+\d{1,4}\s*$", stripped):
        return True
    return False


def uppercase_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def is_probable_heading_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 180:
        return False
    normalized = normalize_for_matching(stripped)
    if target_label_contained_in_normalized(normalized):
        return True
    if CHAPTER_WORD_RE.search(stripped):
        return True
    if re.match(r"^\s*\d{1,2}\s*$", stripped):
        return True
    if re.match(r"^\s*\d{1,2}\s+[A-Za-zÀ-ÿ]", stripped):
        return True
    if SECTION_NUM_RE.match(stripped):
        return True
    if uppercase_ratio(stripped) > 0.72 and len(stripped) <= 120:
        return True
    return False


def detect_body_start_index(lines: list[str]) -> int:
    for index, line in enumerate(lines[:600]):
        normalized = normalize_for_matching(line)
        if normalized == "apresentacao":
            return index
    for index, line in enumerate(lines[:800]):
        if normalize_for_matching(line).startswith("capitulo 1") or re.match(r"^\s*cap[ií]tulo\s+1\b", line, re.I):
            return index
        if re.match(r"^\s*1\s+[A-Za-zÀ-ÿ]", line):
            return index
    return max(0, min(100, len(lines) // 10))


def detect_heading_candidates(lines: list[str]) -> list[dict[str, Any]]:
    candidates: list[HeadingCandidate] = []
    body_start_index = detect_body_start_index(lines)

    in_sumario_block = False
    last_chapter_number: str | None = None

    for index, line in enumerate(lines):
        stripped = line.strip()
        normalized = normalize_for_matching(stripped)

        if normalized == "sumario":
            in_sumario_block = True
        elif index > body_start_index and normalized == "apresentacao":
            in_sumario_block = False
        elif index > body_start_index + 20:
            in_sumario_block = False

        if not stripped:
            continue

        kind = "unknown"
        level = 0
        source_chapter_number: str | None = None
        label: str | None = None
        is_target = False

        current_line_target = target_label_for_normalized_title(normalized)
        contained_target = target_label_contained_in_normalized(normalized)

        chapter_match = CHAPTER_NUM_RE.match(stripped)
        if re.match(r"^\s*cap[ií]tulo\s+\d{1,2}\s*$", stripped, re.I):
            kind = "chapter_number_line"
            level = 1
            source_chapter_number = re.search(r"\d{1,2}", stripped).group(0)  # type: ignore[union-attr]
            last_chapter_number = source_chapter_number
        elif chapter_match and not SECTION_NUM_RE.match(stripped):
            kind = "chapter_heading"
            level = 1
            source_chapter_number = chapter_match.group("num")
            maybe_label = target_label_contained_in_normalized(chapter_match.group("title"))
            if maybe_label:
                label = maybe_label
                is_target = True
            last_chapter_number = source_chapter_number
        elif current_line_target:
            kind = "target_title_line"
            level = 1
            label = current_line_target
            is_target = True
            source_chapter_number = last_chapter_number
        elif contained_target and CHAPTER_WORD_RE.search(stripped):
            kind = "target_combined_heading"
            level = 1
            label = contained_target
            is_target = True
            num = re.search(r"\d{1,2}", stripped)
            source_chapter_number = num.group(0) if num else last_chapter_number
        elif SECTION_NUM_RE.match(stripped):
            kind = "section_heading"
            level = stripped.split()[0].count(".") + 1
        elif is_probable_heading_line(stripped):
            kind = "heading"
            level = 1 if CHAPTER_WORD_RE.search(stripped) else 2

        if kind != "unknown":
            candidates.append(
                HeadingCandidate(
                    line_index=index,
                    line_number=index + 1,
                    text=stripped,
                    normalized=normalized,
                    kind=kind,
                    level=level,
                    source_chapter_number=source_chapter_number,
                    label=label,
                    is_target=is_target,
                    is_toc=is_toc_line(stripped, index, in_sumario_block) or index < body_start_index,
                    suspicious=has_suspicious_pdf_chars(stripped),
                )
            )

    return [asdict(candidate) for candidate in candidates]


def detect_target_chapters(lines: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    candidates = detect_heading_candidates(lines)
    body_start_index = detect_body_start_index(lines)

    target_candidates = [candidate for candidate in candidates if candidate["is_target"]]
    body_targets = [
        candidate
        for candidate in target_candidates
        if not candidate["is_toc"] and candidate["line_index"] >= body_start_index
    ]
    toc_targets = [candidate for candidate in target_candidates if candidate["is_toc"]]

    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in body_targets:
        if candidate["label"]:
            by_label[candidate["label"]].append(candidate)

    selected: list[dict[str, Any]] = []
    for label in TARGET_CHAPTERS:
        matches = sorted(by_label.get(label, []), key=lambda item: item["line_index"])
        if len(matches) > 1:
            warnings.append("multiple_body_target_heading_candidates")
        if matches:
            selected.append(matches[0])

    if not selected and toc_targets:
        warnings.append("toc_only_target_headings_found")

    if not selected:
        warnings.append("no_target_chapters_found")

    selected.sort(key=lambda item: item["line_index"])
    return selected, candidates, sorted(set(warnings))


def is_same_level_chapter_start(lines: list[str], index: int) -> bool:
    line = lines[index].strip()
    if not line:
        return False

    normalized = normalize_for_matching(line)
    if normalized in ("referencias", "anexos", "anexo i", "anexo ii"):
        return True

    if SECTION_NUM_RE.match(line):
        return False

    if re.match(r"^\s*cap[ií]tulo\s+\d{1,2}\b", line, re.I):
        return True

    if re.match(r"^\s*\d{1,2}\s+[A-Za-zÀ-ÿ]", line) and not re.match(r"^\s*\d{1,2}[,.]\d+", line):
        return True

    if re.match(r"^\s*\d{1,2}\s*$", line):
        lookahead = " ".join(l.strip() for l in lines[index + 1 : index + 4])
        if is_probable_heading_line(lookahead):
            return True

    return False


def extract_chapter_spans(lines: list[str], target_headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    if not target_headings:
        return spans

    for target in target_headings:
        start = target["line_index"]
        end = len(lines)

        for index in range(start + 1, len(lines)):
            if is_same_level_chapter_start(lines, index):
                if index == start:
                    continue
                end = index
                break

        text = "\n".join(lines[start:end]).strip()
        spans.append(
            {
                "label": target["label"],
                "matched_title": target["text"],
                "source_chapter_number": target.get("source_chapter_number"),
                "start_line": start + 1,
                "end_line": end,
                "input_chars": len(text),
                "raw_text": text,
                "warnings": [],
            }
        )

    return spans


def detect_encoding_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    if not text:
        return warnings

    replacement_ratio = text.count("\ufffd") / len(text)
    control_count = sum(1 for char in text if char in CONTROL_SUSPICIOUS_CHARS)
    control_ratio = control_count / len(text)
    suspicious_pdf_count = sum(1 for char in text if char in PDF_FONT_SUSPICIOUS_CHARS)
    suspicious_pdf_ratio = suspicious_pdf_count / len(text)

    if replacement_ratio > 0.001:
        warnings.append("high_replacement_character_ratio")
    if control_ratio > 0.0005:
        warnings.append("high_control_character_ratio")
    if suspicious_pdf_ratio > 0.01 or any(char in text for char in ("\x03", "\x04", "\x06", "\x07", "Ǥ", "ͳ", "ʹ", "͵")):
        warnings.append("possible_pdf_font_encoding_corruption")

    return sorted(set(warnings))


def detect_table_like_block(lines: list[str], index: int) -> bool:
    start = max(0, index - 2)
    end = min(len(lines), index + 3)
    window = lines[start:end]

    score = 0
    for line in window:
        stripped = line.strip()
        if not stripped:
            continue
        if re.search(r"\b(Tabela|Quadro|Gr[aá]fico|Fonte)\b", stripped, re.I):
            score += 2
        if len(re.findall(r"\d+(?:[,.]\d+)?%?", stripped)) >= 3:
            score += 2
        if re.search(r"\s{2,}", stripped) and len(stripped.split()) >= 3:
            score += 1
        if "%" in stripped:
            score += 1
    return score >= 3


def is_bullet_or_list_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-•*]|\(?[a-zA-Z]\)|\d+[.)])\s+", line))


def is_caption_or_source_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:Tabela|Quadro|Gr[aá]fico|Figura|Fonte|Notas?|Observa[cç][aã]o)\b", line, re.I))


def is_likely_standalone_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) <= 80 and (
            CHAPTER_WORD_RE.search(stripped)
            or SECTION_NUM_RE.match(stripped)
            or uppercase_ratio(stripped) > 0.70
            or target_label_contained_in_normalized(normalize_for_matching(stripped))
    ):
        return True
    return False


def should_join_lines(prev: str, current: str, in_table: bool) -> bool:
    if in_table:
        return False
    if not prev.strip() or not current.strip():
        return False
    if is_likely_standalone_heading(prev) or is_likely_standalone_heading(current):
        return False
    if is_bullet_or_list_line(prev) or is_bullet_or_list_line(current):
        return False
    if is_caption_or_source_line(prev) or is_caption_or_source_line(current):
        return False
    if prev.rstrip().endswith((".", ":", ";", "!", "?", ")", "]", "%")):
        return False
    if current.lstrip()[0:1].isupper() and len(prev.strip()) < 50:
        return False
    if re.search(r"\s{2,}", prev) or re.search(r"\s{2,}", current):
        return False
    return True


def clean_extracted_text(text: str, options: dict[str, Any]) -> tuple[str, dict[str, int], list[str]]:
    warnings: list[str] = []
    text, control_stats = normalize_newlines_and_controls(text)

    stats = {
        "input_chars": len(text),
        "output_chars": 0,
        "lines_removed_as_page_numbers": 0,
        "blank_lines_collapsed": 0,
        "paragraph_joins": 0,
        "hyphenation_fixes": 0,
        "control_chars_removed": control_stats["control_chars_removed"],
    }

    raw_lines = [line.rstrip() for line in text.split("\n")]
    page_cleaned_lines: list[str] = []

    for index, line in enumerate(raw_lines):
        stripped = line.strip()
        in_table = detect_table_like_block(raw_lines, index)
        if not in_table and (PAGE_NUMBER_RE.match(stripped) or ROMAN_RE.match(stripped)):
            stats["lines_removed_as_page_numbers"] += 1
            continue
        page_cleaned_lines.append(line)

    if options.get("fix_hyphenation", True):
        hyphen_fixed: list[str] = []
        index = 0
        while index < len(page_cleaned_lines):
            line = page_cleaned_lines[index]
            if (
                    index + 1 < len(page_cleaned_lines)
                    and line.rstrip().endswith("-")
                    and page_cleaned_lines[index + 1].strip()
                    and not detect_table_like_block(page_cleaned_lines, index)
            ):
                next_line = page_cleaned_lines[index + 1].lstrip()
                left = line.rstrip()[:-1]
                if re.search(r"[A-Za-zÀ-ÿ]$", left) and re.match(r"^[a-zà-ÿ]", next_line):
                    if len(left.split()[-1]) <= 6:
                        hyphen_fixed.append(left + next_line)
                    else:
                        hyphen_fixed.append(left + "-" + next_line)
                    stats["hyphenation_fixes"] += 1
                    index += 2
                    continue
            hyphen_fixed.append(line)
            index += 1
        page_cleaned_lines = hyphen_fixed

    joined_lines: list[str] = []
    for index, line in enumerate(page_cleaned_lines):
        line = re.sub(r"[ \t]+$", "", line)
        if not joined_lines:
            joined_lines.append(line)
            continue

        previous = joined_lines[-1]
        in_table = detect_table_like_block(page_cleaned_lines, index) or detect_table_like_block(joined_lines, len(joined_lines) - 1)
        if should_join_lines(previous, line, in_table):
            joined_lines[-1] = previous.rstrip() + " " + line.lstrip()
            stats["paragraph_joins"] += 1
        else:
            joined_lines.append(line)

    cleaned = "\n".join(joined_lines)
    before_blank_collapse = cleaned
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    stats["blank_lines_collapsed"] = max(0, before_blank_collapse.count("\n\n\n"))
    cleaned = cleaned.strip() + "\n" if cleaned.strip() else ""
    stats["output_chars"] = len(cleaned)

    if stats["input_chars"] > 0 and stats["output_chars"] < stats["input_chars"] * 0.35:
        warnings.append("possible_table_damage")

    return cleaned, stats, warnings


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_manifest(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in manifest {path} line {line_number}: {exc}") from exc
            if isinstance(parsed, dict):
                entries.append(parsed)
    return entries


def resolve_manifest_path(entry: dict[str, Any], input_root: Path, cwd: Path) -> Path | None:
    for key in ("path", "source_path", "txt_path", "file_path", "filename"):
        value = entry.get(key)
        if not value:
            continue
        candidate = Path(str(value))
        if candidate.is_absolute():
            return candidate
        if candidate.exists():
            return candidate
        if (cwd / candidate).exists():
            return cwd / candidate
        if (input_root / candidate).exists():
            return input_root / candidate
        if candidate.parts and candidate.parts[0] == "corpus":
            return cwd / candidate
        return input_root / candidate.name if len(candidate.parts) == 1 else input_root / candidate
    return None


def discover_input_files(args: argparse.Namespace) -> list[Path]:
    input_root = Path(args.input_root)
    manifest_path = Path(args.manifest)
    cwd = Path.cwd()

    files: list[Path] = []

    if manifest_path.exists():
        entries = load_manifest(manifest_path)
        for entry in entries:
            source = resolve_manifest_path(entry, input_root, cwd)
            if source and source.suffix.lower() == ".txt":
                files.append(source)
    else:
        files = sorted(input_root.rglob("*.txt"))

    deduped: list[Path] = []
    seen: set[str] = set()
    for file in files:
        key = str(file)
        if key not in seen:
            seen.add(key)
            deduped.append(file)

    if args.only_filename:
        deduped = [file for file in deduped if file.name == args.only_filename]

    deduped = sorted(deduped, key=lambda p: str(p))
    if args.limit is not None:
        deduped = deduped[: args.limit]
    return deduped


def infer_output_relative_path(source_path: Path, input_root: Path) -> Path:
    try:
        return source_path.resolve().relative_to(input_root.resolve())
    except ValueError:
        parts = source_path.parts
        year = None
        for part in parts:
            if YEAR_RE.fullmatch(part):
                year = part
                break
        if year:
            return Path(year) / source_path.name
        match = YEAR_RE.search(source_path.name)
        if match:
            return Path(match.group(0)) / source_path.name
        return Path(source_path.name)


def output_paths_for_source(source_path: Path, args: argparse.Namespace) -> tuple[Path, Path]:
    input_root = Path(args.input_root)
    output_dir = Path(args.output_dir)
    relative = infer_output_relative_path(source_path, input_root)
    if relative.suffix.lower() == ".txt":
        relative = relative.with_suffix("")
    md_path = output_dir / relative.with_suffix(".md")
    json_path = output_dir / relative.with_suffix(".json")
    return md_path, json_path


def status_from_warnings_and_chapters(chapters: list[dict[str, Any]], warnings: list[str]) -> str:
    if not chapters:
        return "needs_review" if warnings else "no_target_chapters"
    if any(w in warnings for w in ("possible_pdf_font_encoding_corruption", "toc_only_target_headings_found")):
        return "warning"
    if warnings:
        return "warning"
    return "success"


def build_markdown(source_path: Path, chapters: list[dict[str, Any]]) -> str:
    chunks = [f"# {source_path.stem}", ""]
    for chapter in chapters:
        cleaned_text = chapter.get("cleaned_text", "").strip()
        if not cleaned_text:
            continue
        first_line = cleaned_text.splitlines()[0].strip() if cleaned_text.splitlines() else chapter["matched_title"]
        if not first_line.startswith("#"):
            chunks.append(f"## {first_line}")
            body = "\n".join(cleaned_text.splitlines()[1:]).strip()
            if body:
                chunks.append("")
                chunks.append(body)
        else:
            chunks.append(cleaned_text)
        chunks.append("")
    return "\n".join(chunks).strip() + "\n"


def validate_spans(spans: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    previous_end = 0
    for span in spans:
        start = span["start_line"]
        end = span["end_line"]
        if start > end:
            errors.append("invalid_chapter_span")
        if start < previous_end:
            errors.append("overlapping_chapter_spans")
        previous_end = end
    return errors


def existing_success(json_path: Path) -> bool:
    if not json_path.exists():
        return False
    try:
        record = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return record.get("status") == "success"


def denoise_with_llm(text: str, metadata: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    raise NotImplementedError(
        "LLM denoising is not implemented in this offline v1. "
        "Use --mode local or connect this function to the project's chosen LLM client."
    )


def process_file(source_path: Path, args: argparse.Namespace, run_id: str, logger: logging.Logger) -> tuple[dict[str, Any], str]:
    output_md_path, output_json_path = output_paths_for_source(source_path, args)
    now = utc_now().isoformat().replace("+00:00", "Z")

    record: dict[str, Any] = {
        "source_path": str(source_path),
        "output_markdown_path": str(output_md_path),
        "output_json_path": str(output_json_path),
        "status": "pending",
        "processing_mode": args.mode,
        "chapter_presence": {
            "c4_present": False,
            "c5_present": False,
            "c6_present": False,
        },
        "detected_headings": [],
        "chapters": [],
        "cleanup_stats": {
            "input_chars": 0,
            "candidate_chars": 0,
            "output_chars": 0,
            "lines_removed_as_page_numbers": 0,
            "blank_lines_collapsed": 0,
            "paragraph_joins": 0,
            "hyphenation_fixes": 0,
            "control_chars_removed": 0,
        },
        "warnings": [],
        "errors": [],
        "run_id": run_id,
        "run_metadata": {
            "tool_name": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "processed_at": now,
        },
    }

    markdown_text = ""

    try:
        if not source_path.exists():
            record["status"] = "error"
            record["errors"].append("source_file_missing")
            return record, markdown_text

        text = read_text_file(source_path)
        original_chars = len(text)
        normalized_text, normalization_stats = normalize_newlines_and_controls(text)
        lines = normalized_text.splitlines()

        warnings = detect_encoding_warnings(text)
        target_headings, heading_candidates, detection_warnings = detect_target_chapters(lines)
        warnings.extend(detection_warnings)
        record["detected_headings"] = heading_candidates[:250]

        spans = extract_chapter_spans(lines, target_headings)
        validation_errors = validate_spans(spans)
        record["errors"].extend(validation_errors)

        cleaned_chapters: list[dict[str, Any]] = []
        cumulative_stats = Counter()
        candidate_chars = 0
        output_chars = 0

        for span in spans:
            candidate_chars += span["input_chars"]
            cleaned_text, stats, cleanup_warnings = clean_extracted_text(
                span["raw_text"],
                {
                    "fix_hyphenation": args.fix_hyphenation,
                    "cleanup_level": args.cleanup_level,
                },
            )
            output_chars += len(cleaned_text)
            cumulative_stats.update(stats)

            chapter_warnings = list(span.get("warnings", [])) + cleanup_warnings
            if len(cleaned_text.strip()) < 300:
                chapter_warnings.append("chapter_span_unusually_short")
            if len(cleaned_text) > 250_000:
                chapter_warnings.append("chapter_span_unusually_long")

            cleaned_chapter = {
                key: value
                for key, value in span.items()
                if key != "raw_text"
            }
            cleaned_chapter["output_chars"] = len(cleaned_text)
            cleaned_chapter["warnings"] = sorted(set(chapter_warnings))
            cleaned_chapter["cleaned_text"] = cleaned_text
            cleaned_chapters.append(cleaned_chapter)
            warnings.extend(chapter_warnings)

        for chapter in cleaned_chapters:
            label = chapter.get("label")
            if label in ("c4", "c5", "c6"):
                record["chapter_presence"][f"{label}_present"] = True

        record["chapters"] = [
            {key: value for key, value in chapter.items() if key != "cleaned_text"}
            for chapter in cleaned_chapters
        ]

        cleanup_stats = {
            "input_chars": original_chars,
            "candidate_chars": candidate_chars,
            "output_chars": output_chars,
            "lines_removed_as_page_numbers": cumulative_stats["lines_removed_as_page_numbers"],
            "blank_lines_collapsed": cumulative_stats["blank_lines_collapsed"],
            "paragraph_joins": cumulative_stats["paragraph_joins"],
            "hyphenation_fixes": cumulative_stats["hyphenation_fixes"],
            "control_chars_removed": normalization_stats["control_chars_removed"] + cumulative_stats["control_chars_removed"],
        }
        record["cleanup_stats"] = cleanup_stats

        markdown_text = build_markdown(source_path, cleaned_chapters)

        if args.mode == "llm" and cleaned_chapters:
            try:
                llm_result = denoise_with_llm(markdown_text, record, args)
                markdown_text = llm_result["chapters"]
                record["processing_mode"] = "llm"
            except NotImplementedError as exc:
                record["warnings"].append("llm_response_missing_chapters")
                record["errors"].append(str(exc))
                record["status"] = "error"

        warnings = sorted(set(warnings))
        record["warnings"] = warnings

        if not record["errors"]:
            record["status"] = status_from_warnings_and_chapters(cleaned_chapters, warnings)
        elif record["status"] != "error":
            record["status"] = "error"

        logger.info(
            "Processed %s status=%s c4=%s c5=%s c6=%s warnings=%s",
            source_path,
            record["status"],
            record["chapter_presence"]["c4_present"],
            record["chapter_presence"]["c5_present"],
            record["chapter_presence"]["c6_present"],
            ",".join(record["warnings"]) if record["warnings"] else "-",
        )

    except Exception as exc:
        logger.exception("Failed processing %s", source_path)
        record["status"] = "error"
        record["errors"].append(f"{type(exc).__name__}: {exc}")

    return record, markdown_text


def write_report_outputs(record: dict[str, Any], markdown_text: str, args: argparse.Namespace) -> None:
    if args.dry_run or args.mode == "diagnose-only":
        return

    md_path = Path(record["output_markdown_path"])
    json_path = Path(record["output_json_path"])

    should_write_md = bool(markdown_text.strip()) or args.write_empty
    should_write_json = True

    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    if should_write_md:
        md_path.write_text(markdown_text, encoding="utf-8")

    if should_write_json:
        serializable_record = json.loads(json.dumps(record, ensure_ascii=False))
        json_path.write_text(
            json.dumps(serializable_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            )


def summarize_records(records: list[dict[str, Any]], args: argparse.Namespace, run_id: str, started_at: str, ended_at: str, interrupted: bool = False) -> dict[str, Any]:
    warning_counter: Counter[str] = Counter()
    for record in records:
        warning_counter.update(record.get("warnings", []))

    summary = {
        "files_discovered": len(records),
        "files_selected": len(records),
        "files_processed": len([r for r in records if r.get("status") != "skipped"]),
        "files_written": len([r for r in records if r.get("status") in ("success", "warning") and (r.get("chapters") or args.write_empty)]),
        "files_with_no_target_chapters": len([r for r in records if "no_target_chapters_found" in r.get("warnings", [])]),
        "files_with_warnings": len([r for r in records if r.get("warnings")]),
        "files_failed": len([r for r in records if r.get("status") == "error"]),
        "c4_present": len([r for r in records if r.get("chapter_presence", {}).get("c4_present")]),
        "c5_present": len([r for r in records if r.get("chapter_presence", {}).get("c5_present")]),
        "c6_present": len([r for r in records if r.get("chapter_presence", {}).get("c6_present")]),
        "warning_counts": dict(sorted(warning_counter.items())),
        "interrupted": interrupted,
    }

    return {
        "run_metadata": {
            "run_id": run_id,
            "tool_name": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "mode": args.mode,
            "input_root": args.input_root,
            "input_manifest": args.manifest,
            "output_dir": args.output_dir,
            "started_at": started_at,
            "ended_at": ended_at,
            "dry_run": args.dry_run,
        },
        "summary": summary,
    }


def write_run_outputs(records: list[dict[str, Any]], summary: dict[str, Any], args: argparse.Namespace) -> None:
    if args.dry_run or args.mode == "diagnose-only":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = output_dir / "manifest.ndjson"
    with manifest_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    run_id = summary["run_metadata"]["run_id"]
    summary_path = output_dir / "run_summary.json"
    timestamped_summary_path = output_dir / f"run_summary_{run_id}.json"

    summary_json = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    summary_path.write_text(summary_json, encoding="utf-8")
    timestamped_summary_path.write_text(summary_json, encoding="utf-8")


def validate_configuration(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    input_root = Path(args.input_root)
    manifest = Path(args.manifest)
    output_dir = Path(args.output_dir)

    if args.workers < 1:
        errors.append("--workers must be >= 1")
    if args.limit is not None and args.limit < 1:
        errors.append("--limit must be >= 1")
    if args.max_output_tokens < 1:
        errors.append("--max-output-tokens must be >= 1")
    if args.max_retries < 0:
        errors.append("--max-retries must be >= 0")

    if not input_root.exists():
        errors.append(f"Input root does not exist: {input_root}")

    if args.manifest != DEFAULT_MANIFEST and not manifest.exists():
        errors.append(f"Manifest does not exist: {manifest}")

    if args.mode == "llm":
        if not args.model:
            errors.append("--model is required for --mode llm")
        if not Path(args.prompt).exists():
            errors.append(f"Prompt file does not exist: {args.prompt}")

    if output_dir.exists() and output_dir.is_file():
        errors.append(f"Output directory path is a file: {output_dir}")

    if args.resume and args.reprocess:
        errors.append("--resume and --reprocess cannot be used together")

    return errors


def make_skipped_record(source_path: Path, args: argparse.Namespace, run_id: str, reason: str) -> dict[str, Any]:
    output_md_path, output_json_path = output_paths_for_source(source_path, args)
    return {
        "source_path": str(source_path),
        "output_markdown_path": str(output_md_path),
        "output_json_path": str(output_json_path),
        "status": "skipped",
        "skip_reason": reason,
        "processing_mode": args.mode,
        "chapter_presence": {
            "c4_present": False,
            "c5_present": False,
            "c6_present": False,
        },
        "chapters": [],
        "cleanup_stats": {},
        "warnings": [],
        "errors": [],
        "run_id": run_id,
    }


def main() -> int:
    args = parse_args()
    run_id = make_run_id()
    started = utc_now()
    started_at = started.isoformat().replace("+00:00", "Z")

    config_errors = validate_configuration(args)
    if config_errors:
        for error in config_errors:
            print(f"CONFIG ERROR: {error}", file=sys.stderr)
        return 2

    logger = setup_logging(Path(args.output_dir) / "enade_clean_up.log")
    logger.info("Starting %s run_id=%s mode=%s", TOOL_NAME, run_id, args.mode)
    logger.info("Arguments: %s", vars(args))

    records: list[dict[str, Any]] = []
    interrupted = False

    try:
        files = discover_input_files(args)
        logger.info("Discovered/selected files: %d", len(files))

        for source_path in files:
            output_md_path, output_json_path = output_paths_for_source(source_path, args)

            if args.resume and existing_success(output_json_path):
                logger.info("Skipping successful existing output due to --resume: %s", source_path)
                records.append(make_skipped_record(source_path, args, run_id, "resume_existing_success"))
                continue

            if output_json_path.exists() and not args.overwrite and not args.reprocess and not args.resume and args.mode != "diagnose-only":
                logger.info("Skipping existing output without --overwrite/--reprocess: %s", source_path)
                records.append(make_skipped_record(source_path, args, run_id, "existing_output"))
                continue

            record, markdown_text = process_file(source_path, args, run_id, logger)

            if args.mode == "diagnose-only":
                print(json.dumps(record, ensure_ascii=False, indent=2))
            else:
                if record.get("chapters") or args.write_empty or record.get("status") == "error":
                    write_report_outputs(record, markdown_text, args)

            records.append(record)

    except KeyboardInterrupt:
        interrupted = True
        logger.warning("Interrupted by user")
    finally:
        ended_at = utc_now().isoformat().replace("+00:00", "Z")
        summary = summarize_records(records, args, run_id, started_at, ended_at, interrupted=interrupted)
        write_run_outputs(records, summary, args)
        logger.info("Finished run_id=%s summary=%s", run_id, summary["summary"])

    if interrupted:
        return 130

    failed = any(record.get("status") == "error" for record in records)
    strict_problem = args.strict and any(
        record.get("status") in ("error", "needs_review", "no_target_chapters", "warning")
        or "no_target_chapters_found" in record.get("warnings", [])
        for record in records
    )

    if failed or strict_problem:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())