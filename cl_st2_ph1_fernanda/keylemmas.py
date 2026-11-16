#!/usr/bin/env python3
"""Compare lemma presence in each ENADE year–chapter group with the rest."""

import argparse
import csv
import ctypes
import errno
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path


PHASE_DIR = Path(__file__).resolve().parent
TAGGED_ROOT_RELATIVE = Path("corpus/05_enade_tagged")
OUTPUT_COLUMNS = (
    "lemma",
    "target_present_files",
    "target_absent_files",
    "target_total_files",
    "target_per_1000_files",
    "comparison_present_files",
    "comparison_absent_files",
    "comparison_total_files",
    "comparison_per_1000_files",
    "difference_per_1000_files",
    "g2",
    "direction",
)
ALGORITHM_VERSION = "1.0"


class KeyLemmaError(Exception):
    """Raised when input or output validation fails."""


class OutputConflict(KeyLemmaError):
    """Raised when an existing output does not match the complete run."""


@dataclass
class TaggedFile:
    year: str
    chapter: str
    target_subdirectory: str
    filename: str
    path: Path
    relative_path: str
    sha256: str
    size_bytes: int
    lemmas: set

    @property
    def group(self):
        return self.year, self.chapter


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def normalize(value):
    value = unicodedata.normalize("NFC", value.strip())
    return unicodedata.normalize("NFC", value.casefold())


def phase_path(value, phase_dir, *, description, must_exist=True):
    path = Path(value)
    if not path.is_absolute():
        path = phase_dir / path
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError, ValueError) as exc:
        raise KeyLemmaError(f"{description} {path}: {exc}") from exc
    phase_root = phase_dir.resolve()
    if not resolved.is_relative_to(phase_root):
        raise KeyLemmaError(f"{description} must be inside the phase directory: {path}")
    if must_exist and not resolved.is_file():
        raise KeyLemmaError(f"{description} is not a regular file: {resolved}")
    return resolved


def phase_relative(path, phase_dir):
    return path.resolve().relative_to(phase_dir.resolve()).as_posix()


def load_config(path, *, description, normalize_values=False):
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise KeyLemmaError(f"Cannot read {description} {path}: {exc}") from exc

    values = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if normalize_values:
            value = normalize(value)
        else:
            value = value.upper()
            if "." in value:
                raise KeyLemmaError(
                    f"{description} {path}:{line_number}: expected a base POS category"
                )
        if value:
            values.add(value)
    if description == "POS configuration" and not values:
        raise KeyLemmaError(f"POS configuration {path} must contain at least one category")
    return data, values


def validate_component(value, field, manifest_path, line_number):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\0" in value
    ):
        raise KeyLemmaError(
            f"Manifest {manifest_path}:{line_number}: {field} must be a safe, non-empty path component"
        )


def parse_manifest(manifest_path, phase_dir, pos_categories, stopwords):
    tagged_root = (phase_dir / TAGGED_ROOT_RELATIVE).resolve()
    try:
        tagged_root.relative_to(phase_dir.resolve())
    except ValueError as exc:
        raise KeyLemmaError(f"Tagged corpus root escapes the phase directory: {tagged_root}") from exc
    if not tagged_root.is_dir():
        raise KeyLemmaError(f"Tagged corpus root is missing or not a directory: {tagged_root}")

    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_text = manifest_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise KeyLemmaError(f"Cannot read UTF-8 manifest {manifest_path}: {exc}") from exc

    records = []
    seen_paths = set()
    seen_identities = set()
    group_subdirectories = {}
    for line_number, line in enumerate(manifest_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: malformed JSON: {exc.msg}"
            ) from exc
        if not isinstance(record, dict):
            raise KeyLemmaError(f"Manifest {manifest_path}:{line_number}: expected a JSON object")

        required = (
            "year", "chapter", "target_subdirectory", "filename",
            "tagged_chapter_path", "tagged_sha256", "tagged_size_bytes", "status",
        )
        missing = [field for field in required if field not in record]
        if missing:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: missing required fields: {', '.join(missing)}"
            )

        year = record["year"]
        if not isinstance(year, str) or re.fullmatch(r"[0-9]{4}", year) is None:
            raise KeyLemmaError(f"Manifest {manifest_path}:{line_number}: year must be a four-digit string")
        for field in ("chapter", "filename"):
            validate_component(record[field], field, manifest_path, line_number)
        for field in ("target_subdirectory", "tagged_chapter_path"):
            if not isinstance(record[field], str) or not record[field].strip():
                raise KeyLemmaError(
                    f"Manifest {manifest_path}:{line_number}: {field} must be a non-empty string"
                )
        if record["target_subdirectory"] != f"{year}_{record['chapter']}":
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: target_subdirectory must be "
                f"{year}_{record['chapter']}"
            )
        group = year, record["chapter"]
        prior_subdirectory = group_subdirectories.setdefault(group, record["target_subdirectory"])
        if prior_subdirectory != record["target_subdirectory"]:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: inconsistent target_subdirectory for {group}"
            )
        if record["status"] != "success":
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: status must be 'success', got {record['status']!r}"
            )
        expected_hash = record["tagged_sha256"]
        if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) is None:
            raise KeyLemmaError(f"Manifest {manifest_path}:{line_number}: invalid tagged_sha256")
        expected_size = record["tagged_size_bytes"]
        if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: tagged_size_bytes must be a non-negative integer"
            )

        tagged_path_text = record["tagged_chapter_path"]
        if "\\" in tagged_path_text or "\0" in tagged_path_text:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: tagged_chapter_path must use portable '/' separators"
            )
        relative_tagged_path = Path(tagged_path_text)
        if relative_tagged_path.is_absolute() or ".." in relative_tagged_path.parts:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: tagged_chapter_path must not escape the phase directory"
            )
        candidate = (phase_dir / relative_tagged_path)
        try:
            resolved_path = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: tagged file is missing or unreadable: "
                f"{tagged_path_text}: {exc}"
            ) from exc
        try:
            resolved_path.relative_to(tagged_root)
        except ValueError as exc:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: tagged path escapes {tagged_root}: {tagged_path_text}"
            ) from exc
        if not resolved_path.is_file():
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: tagged path is not a regular file: {tagged_path_text}"
            )
        canonical_path = resolved_path.as_posix()
        if canonical_path in seen_paths:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: duplicate tagged path: {tagged_path_text}"
            )
        seen_paths.add(canonical_path)

        identity = year, record["chapter"], record["filename"]
        if identity in seen_identities:
            raise KeyLemmaError(
                f"Manifest {manifest_path}:{line_number}: duplicate output identity {identity}"
            )
        seen_identities.add(identity)

        try:
            file_bytes = resolved_path.read_bytes()
        except OSError as exc:
            raise KeyLemmaError(f"Cannot read tagged file {resolved_path}: {exc}") from exc
        actual_hash = sha256_bytes(file_bytes)
        if len(file_bytes) != expected_size or actual_hash.lower() != expected_hash.lower():
            raise KeyLemmaError(
                f"Tagged file {tagged_path_text} does not match manifest size/hash; "
                f"update or repair the tagged file and manifest"
            )
        try:
            tagged_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise KeyLemmaError(f"Tagged file {tagged_path_text} is not valid UTF-8: {exc}") from exc

        lemmas = set()
        for token_line, row in enumerate(tagged_text.splitlines(), start=1):
            if not row.strip():
                continue
            fields = row.split("\t")
            if len(fields) != 3:
                raise KeyLemmaError(
                    f"Tagged file {tagged_path_text}:{token_line}: expected exactly three tab-separated fields"
                )
            surface, tag, lemma_field = fields
            category = tag.split(".", 1)[0].strip().upper()
            if category not in pos_categories:
                continue
            lemma = normalize(lemma_field)
            if not lemma or lemma == "<unknown>":
                lemma = normalize(surface)
            if not lemma or lemma in stopwords or sum(character.isalpha() for character in lemma) < 2:
                continue
            lemmas.add(lemma)

        records.append(TaggedFile(
            year=year,
            chapter=record["chapter"],
            target_subdirectory=record["target_subdirectory"],
            filename=record["filename"],
            path=resolved_path,
            relative_path=phase_relative(resolved_path, phase_dir),
            sha256=actual_hash,
            size_bytes=len(file_bytes),
            lemmas=lemmas,
        ))

    if not records:
        raise KeyLemmaError(f"Manifest {manifest_path} contains no records")
    groups = sorted({item.group for item in records}, key=lambda group: (int(group[0]), group[1]))
    if len(groups) < 2:
        raise KeyLemmaError("At least two distinct year–chapter groups are required")
    return manifest_bytes, records, groups


def g2_statistic(target_present, target_total, comparison_present, comparison_total):
    if target_total <= 0 or comparison_total <= 0:
        raise ValueError("Both target and comparison totals must be positive")
    if not 0 <= target_present <= target_total or not 0 <= comparison_present <= comparison_total:
        raise ValueError("Presence counts must be within their file totals")

    rows = (target_total, comparison_total)
    columns = (target_present + comparison_present,
               target_total + comparison_total - target_present - comparison_present)
    total = sum(rows)
    observed = (
        (target_present, target_total - target_present),
        (comparison_present, comparison_total - comparison_present),
    )
    score = 0.0
    for row_index, row in enumerate(observed):
        for column_index, value in enumerate(row):
            if value == 0:
                continue
            expected = rows[row_index] * columns[column_index] / total
            if expected <= 0:
                raise ValueError("Positive observed cell has a zero expected count")
            score += value * math.log(value / expected)
    score *= 2
    if not math.isfinite(score):
        raise ValueError("G² is not finite")
    if score < -1e-12:
        raise ValueError("G² is negative")
    return max(0.0, score)


def serialize_tsv(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(OUTPUT_COLUMNS)
    for row in rows:
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")


def prepare_run(manifest_value, pos_value, stopwords_value, phase_dir, output_value="corpus/06_enade_keylemmas"):
    phase_dir = Path(phase_dir).resolve()
    manifest_path = phase_path(manifest_value, phase_dir, description="Input manifest")
    pos_path = phase_path(pos_value, phase_dir, description="POS configuration")
    stopwords_path = phase_path(stopwords_value, phase_dir, description="Stopword configuration")
    output_path = phase_path(
        output_value, phase_dir, description="Output path", must_exist=False
    )
    output_relative = phase_relative(output_path, phase_dir)
    if output_relative == ".":
        output_relative = ""
    output_prefix = f"{output_relative}/" if output_relative else ""
    pos_bytes, pos_categories = load_config(pos_path, description="POS configuration")
    stopwords_bytes, stopwords = load_config(
        stopwords_path, description="Stopword configuration", normalize_values=True
    )
    manifest_bytes, records, groups = parse_manifest(
        manifest_path, phase_dir, pos_categories, stopwords
    )

    files_by_group = {group: [] for group in groups}
    vocabulary = set()
    for item in records:
        files_by_group[item.group].append(item)
        vocabulary.update(item.lemmas)
    for group in groups:
        if not files_by_group[group]:
            raise KeyLemmaError(f"Group {group} has no tagged files")

    outputs = {}
    group_provenance = []
    for group in groups:
        target_files = files_by_group[group]
        comparison_groups = [other for other in groups if other != group]
        comparison_files = [item for other in comparison_groups for item in files_by_group[other]]
        if not target_files or not comparison_files:
            raise KeyLemmaError(f"Group {group} has an empty target or comparison set")
        rows = []
        for lemma in vocabulary:
            target_present = sum(lemma in item.lemmas for item in target_files)
            comparison_present = sum(lemma in item.lemmas for item in comparison_files)
            target_total = len(target_files)
            comparison_total = len(comparison_files)
            target_rate = 1000 * target_present / target_total
            comparison_rate = 1000 * comparison_present / comparison_total
            difference = target_rate - comparison_rate
            try:
                g2 = g2_statistic(target_present, target_total, comparison_present, comparison_total)
            except ValueError as exc:
                raise KeyLemmaError(f"Invalid G² for group {group}, lemma {lemma!r}: {exc}") from exc
            direction = (
                "TARGET_HIGHER" if difference > 0 else
                "REFERENCE_HIGHER" if difference < 0 else
                "EQUAL"
            )
            rows.append((
                lemma,
                target_present,
                target_total - target_present,
                target_total,
                target_rate,
                comparison_present,
                comparison_total - comparison_present,
                comparison_total,
                comparison_rate,
                difference,
                g2,
                direction,
            ))
        rows.sort(key=lambda row: (-row[10], -abs(row[9]), row[0]))
        output_rows = [
            (
                row[0], row[1], row[2], row[3], f"{row[4]:.6f}", row[5], row[6], row[7],
                f"{row[8]:.6f}", f"{row[9]:.6f}", f"{row[10]:.8f}", row[11],
            )
            for row in rows
        ]
        output_name = f"{group[0]}_{group[1]}.tsv"
        tsv_bytes = serialize_tsv(output_rows)
        outputs[output_name] = tsv_bytes
        group_provenance.append({
            "year": group[0],
            "chapter": group[1],
            "target_subdirectory": f"{group[0]}_{group[1]}",
            "target_files": len(target_files),
            "comparison_groups": [
                {"year": other[0], "chapter": other[1]} for other in comparison_groups
            ],
            "comparison_files": len(comparison_files),
            "candidate_lemmas": len(vocabulary),
            "output_rows": len(output_rows),
            "tsv_path": f"{output_prefix}{output_name}",
            "tsv_sha256": sha256_bytes(tsv_bytes),
        })

    file_provenance = [
        {
            "path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "year": item.year,
            "chapter": item.chapter,
        }
        for item in sorted(records, key=lambda value: value.relative_path)
    ]
    provenance = {
        "schema_version": 1,
        "algorithm_version": ALGORITHM_VERSION,
        "input_manifest": {
            "path": phase_relative(manifest_path, phase_dir),
            "sha256": sha256_bytes(manifest_bytes),
        },
        "configuration": {
            "pos": {
                "path": phase_relative(pos_path, phase_dir),
                "sha256": sha256_bytes(pos_bytes),
                "categories": sorted(pos_categories),
            },
            "stopwords": {
                "path": phase_relative(stopwords_path, phase_dir),
                "sha256": sha256_bytes(stopwords_bytes),
                "values": sorted(stopwords),
            },
        },
        "method": (
            "Each year-chapter group is compared with all files in every other group; "
            "lemma presence is counted once per file; G² is the unadjusted 2x2 "
            "log-likelihood ratio; rates are per 1,000 files. Significance thresholding "
            "and multiple-testing correction are not applied."
        ),
        "groups": group_provenance,
        "candidate_lemmas": len(vocabulary),
        "validated_file_count": len(records),
        "validated_tagged_files": file_provenance,
        "output_files": [
            {"path": f"{output_prefix}{name}", "sha256": sha256_bytes(content)}
            for name, content in sorted(outputs.items())
        ],
    }
    outputs["keylemmas_run.json"] = (
        json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    summary = {
        "groups": len(groups),
        "files": len(records),
        "candidate_lemmas": len(vocabulary),
        "rows": sum(group["output_rows"] for group in group_provenance),
    }
    return outputs, summary


def verify_output_directory(directory, expected):
    if directory.is_symlink() or not directory.is_dir():
        raise OutputConflict(f"Output destination is not a regular directory: {directory}")
    actual_paths = set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise OutputConflict(f"Unexpected symlink in output destination: {path}")
        if path.is_dir():
            raise OutputConflict(f"Unexpected directory in output destination: {path}")
        if not path.is_file():
            raise OutputConflict(f"Unexpected non-file in output destination: {path}")
        actual_paths.add(path.relative_to(directory).as_posix())
    expected_paths = set(expected)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        raise OutputConflict(
            f"Output conflict at {directory}: missing={missing}, unexpected={extra}; "
            "preserving existing output"
        )
    for relative_path, expected_bytes in expected.items():
        path = directory / relative_path
        try:
            actual_bytes = path.read_bytes()
        except OSError as exc:
            raise OutputConflict(f"Cannot verify existing output {path}: {exc}") from exc
        if actual_bytes != expected_bytes:
            raise OutputConflict(
                f"Existing output differs from this run: {path}; preserving existing output"
            )


def atomic_publish_no_replace(staging, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOTSUP, "atomic no-replace directory publication is unavailable")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100, os.fsencode(staging), -100, os.fsencode(destination), 1
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(destination))


def publish_outputs(output_path, expected):
    if output_path.exists() or output_path.is_symlink():
        verify_output_directory(output_path, expected)
        return "verified existing output; no changes made"

    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.staging-", dir=parent))
    except OSError as exc:
        raise KeyLemmaError(f"Cannot create staging directory beside {output_path}: {exc}") from exc

    try:
        for relative_path, content in expected.items():
            (staging / relative_path).write_bytes(content)
        verify_output_directory(staging, expected)
        atomic_publish_no_replace(staging, output_path)
    except Exception as exc:
        raise KeyLemmaError(
            f"Could not publish outputs: {exc}. Staging directory retained at {staging}"
        ) from exc
    return f"published complete output to {output_path}"


def build_parser():
    parser = argparse.ArgumentParser(
        description="Compare ENADE lemma presence in each year-chapter group with the rest."
    )
    parser.add_argument(
        "--input-manifest",
        default="corpus/05_enade_tagged/enade_tagged_corpus.ndjson",
        help="Tagged-corpus NDJSON manifest",
    )
    parser.add_argument(
        "--output",
        default="corpus/06_enade_keylemmas",
        help="Output directory for group TSVs and run provenance",
    )
    parser.add_argument("--pos-config", default="keylemmas_pos.txt", help="POS category profile")
    parser.add_argument("--stopwords", default="keylemmas_stopwords.txt", help="Stopword profile")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and analyse all inputs without creating or changing output paths",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    phase_dir = Path(PHASE_DIR).resolve()
    try:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = phase_dir / output_path
        raw_output_path = output_path
        output_path = output_path.resolve(strict=False)
        if not output_path.is_relative_to(phase_dir):
            raise KeyLemmaError(f"Output path must be inside the phase directory: {raw_output_path}")
        if raw_output_path.is_symlink():
            raise KeyLemmaError(f"Output destination must not be a symlink: {raw_output_path}")

        expected, summary = prepare_run(
            args.input_manifest, args.pos_config, args.stopwords, phase_dir, output_path
        )
        print(
            f"Validated {summary['groups']} groups, {summary['files']} files, "
            f"{summary['candidate_lemmas']} candidate lemmas, and "
            f"{summary['rows']} total output rows."
        )
        if args.dry_run:
            print("Dry run complete; no output paths were created or changed.")
            return 0
        print(publish_outputs(output_path, expected))
        return 0
    except (KeyLemmaError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(f"keylemmas.py: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())