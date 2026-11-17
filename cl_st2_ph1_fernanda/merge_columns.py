#!/usr/bin/env python3
"""Merge validated clean keyword columns into the headerless SAS matrix."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath


PHASE_DIR = Path(__file__).resolve().parent
CLEAN_DIR = Path("columns_clean")
COLUMNS_DIR = Path("columns")
FILE_IDS = Path("file_ids.txt")
KEYWORD_INDEX = Path("index_keywords.txt")
COLUMNS_MANIFEST = Path("columns_run.json")
OUTPUT_FILE = Path("sas/counts.txt")
PROVENANCE_FILE = Path("sas/merge_columns_run.json")
GROUP_RE = re.compile(r"^\d{4}_c\d+$")
KEYWORD_ID_RE = re.compile(r"^\d{6}$")
DOCUMENT_ID_RE = re.compile(r"^t\d{6}$")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def resolve_cli_path(value, phase_dir):
    path = Path(value)
    if not path.is_absolute():
        path = phase_dir / path
    return Path(os.path.abspath(path))


def display_path(path, phase_dir):
    try:
        return path.relative_to(phase_dir).as_posix()
    except ValueError:
        return path.as_posix()


def read_regular_file(path, description):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} must be a regular, non-symlink file: {path}")
    return path.read_bytes()


def verify_manifest_artifact(manifest_outputs, relative_path, path):
    record = manifest_outputs.get(relative_path)
    if not isinstance(record, dict):
        raise ValueError(f"Missing output record in columns manifest: {relative_path}")
    expected_hash = record.get("sha256")
    expected_size = record.get("size_bytes")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError(f"Invalid SHA-256 in columns manifest: {relative_path}")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise ValueError(f"Invalid byte size in columns manifest: {relative_path}")

    content = read_regular_file(path, f"Input artifact {relative_path}")
    if len(content) != expected_size or sha256_bytes(content) != expected_hash:
        raise ValueError(f"Checksum or size mismatch for input artifact: {path}")
    return content


def read_nonempty_lines(content, path):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"Input is not valid UTF-8: {path}") from error
    lines = text.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise ValueError(f"Input contains no rows or blank lines: {path}")
    return lines


def load_manifest(path):
    content = read_regular_file(path, "Columns run manifest")
    try:
        manifest = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid columns run manifest: {path}") from error
    if (not isinstance(manifest, dict)
            or isinstance(manifest.get("schema_version"), bool)
            or manifest.get("schema_version") != 1):
        raise ValueError(f"Unsupported columns run manifest schema: {path}")
    if not isinstance(manifest.get("counts"), dict):
        raise ValueError(f"Missing counts in columns run manifest: {path}")
    if not isinstance(manifest.get("groups"), list):
        raise ValueError(f"Missing groups in columns run manifest: {path}")
    if not isinstance(manifest.get("outputs"), dict):
        raise ValueError(f"Missing outputs in columns run manifest: {path}")
    return content, manifest


def parse_keyword_index(content, path):
    keyword_ids = []
    keywords = set()
    for line_number, line in enumerate(read_nonempty_lines(content, path), 1):
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"Unexpected keyword index format at {path}:{line_number}")
        keyword_id, lemma = fields
        expected_id = f"{line_number:06d}"
        if not KEYWORD_ID_RE.fullmatch(keyword_id) or keyword_id != expected_id:
            raise ValueError(f"Invalid or out-of-order keyword ID at {path}:{line_number}")
        if lemma in keywords:
            raise ValueError(f"Duplicate keyword lemma in {path}: {lemma}")
        keyword_ids.append(keyword_id)
        keywords.add(lemma)
    return keyword_ids


def parse_file_ids(content, path):
    document_ids = []
    groups = []
    for line_number, line in enumerate(read_nonempty_lines(content, path), 1):
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            raise ValueError(f"Unexpected file ID format at {path}:{line_number}")
        document_id, relative_path = fields
        if document_id != f"t{line_number:06d}" or not DOCUMENT_ID_RE.fullmatch(document_id):
            raise ValueError(f"Invalid or out-of-order document ID at {path}:{line_number}")
        if "\\" in relative_path:
            raise ValueError(f"Invalid document path at {path}:{line_number}")
        path_parts = PurePosixPath(relative_path).parts
        if (PurePosixPath(relative_path).is_absolute() or len(path_parts) < 2
                or any(part in ("", ".", "..") for part in path_parts)):
            raise ValueError(f"Unsafe document path at {path}:{line_number}")
        group = path_parts[0]
        if not GROUP_RE.fullmatch(group):
            raise ValueError(f"Invalid document group at {path}:{line_number}: {group}")
        document_ids.append(document_id)
        groups.append(group)
    return document_ids, groups


def validate_groups(manifest_groups, row_groups, path):
    actual_counts = Counter(row_groups)
    actual_order = list(dict.fromkeys(row_groups))
    expected = []
    seen = set()
    for record in manifest_groups:
        if not isinstance(record, dict):
            raise ValueError(f"Invalid group record in columns run manifest: {path}")
        group = record.get("group")
        count = record.get("documents")
        if not isinstance(group, str) or not GROUP_RE.fullmatch(group):
            raise ValueError(f"Invalid group in columns run manifest: {group!r}")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"Invalid document count for group in columns run manifest: {group}")
        if group in seen:
            raise ValueError(f"Duplicate group in columns run manifest: {group}")
        seen.add(group)
        expected.append((group, count))
    if actual_order != [group for group, _ in expected]:
        raise ValueError(f"Document group ordering does not match columns manifest: {path}")
    if actual_counts != Counter(dict(expected)):
        raise ValueError(f"Document group counts do not match columns manifest: {path}")


def read_full_column(path, document_ids, row_groups):
    content = read_regular_file(path, "Full keyword column")
    lines = read_nonempty_lines(content, path)
    if len(lines) != len(document_ids):
        raise ValueError(f"Row count mismatch in full column: {path}")
    flags = []
    for row_number, (line, expected_id, expected_group) in enumerate(
            zip(lines, document_ids, row_groups), 1):
        fields = line.split()
        if len(fields) != 3:
            raise ValueError(f"Unexpected full column format at {path}:{row_number}")
        document_id, group, flag = fields
        if document_id != expected_id or group != expected_group:
            raise ValueError(f"Document ID or group alignment mismatch at {path}:{row_number}")
        if flag not in {"0", "1"}:
            raise ValueError(f"Invalid binary flag in {path} at row {row_number}: {flag}")
        flags.append(flag)
    return content, flags


def read_clean_column(path, keyword_id, expected_flags):
    content = read_regular_file(path, "Clean keyword column")
    lines = read_nonempty_lines(content, path)
    if lines[0].strip() != keyword_id:
        raise ValueError(f"Keyword ID mismatch in {path}: expected {keyword_id}")
    flags = [line.strip() for line in lines[1:]]
    if len(flags) != len(expected_flags):
        raise ValueError(f"Row count mismatch in clean column: {path}")
    for row_number, flag in enumerate(flags, 1):
        if flag not in {"0", "1"}:
            raise ValueError(f"Invalid binary flag in {path} at data row {row_number}: {flag}")
    if flags != expected_flags:
        raise ValueError(f"Clean and full column values do not match: {path}")
    return content, flags


def validate_directory(directory, expected_names, description):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"{description} must be a regular, non-symlink directory: {directory}")
    actual_names = {entry.name for entry in directory.iterdir()}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise ValueError(f"Unexpected files in {directory}; missing={missing}, extra={extra}")


def build_matrix(phase_dir, columns_dir, clean_dir, file_ids_path,
                 keyword_index_path, manifest_path):
    manifest_content, manifest = load_manifest(manifest_path)
    manifest_outputs = manifest["outputs"]
    counts = manifest["counts"]
    document_count = counts.get("documents")
    keyword_count = counts.get("keywords")
    if (isinstance(document_count, bool) or not isinstance(document_count, int)
            or document_count <= 0 or isinstance(keyword_count, bool)
            or not isinstance(keyword_count, int) or keyword_count <= 0):
        raise ValueError(f"Invalid document or keyword counts in columns manifest: {manifest_path}")

    file_ids_content = verify_manifest_artifact(manifest_outputs, "file_ids.txt", file_ids_path)
    keyword_index_content = verify_manifest_artifact(
        manifest_outputs, "index_keywords.txt", keyword_index_path)
    document_ids, row_groups = parse_file_ids(file_ids_content, file_ids_path)
    keyword_ids = parse_keyword_index(keyword_index_content, keyword_index_path)
    if len(document_ids) != document_count:
        raise ValueError(f"Document count does not match columns manifest: {file_ids_path}")
    if len(keyword_ids) != keyword_count:
        raise ValueError(f"Keyword count does not match columns manifest: {keyword_index_path}")
    validate_groups(manifest["groups"], row_groups, manifest_path)

    expected_names = {f"{keyword_id}.txt" for keyword_id in keyword_ids}
    validate_directory(columns_dir, expected_names, "Full columns directory")
    validate_directory(clean_dir, expected_names, "Clean columns directory")
    expected_manifest_outputs = {
        "file_ids.txt", "index_keywords.txt",
        *(f"columns/{name}" for name in expected_names),
        *(f"columns_clean/{name}" for name in expected_names),
    }
    if set(manifest_outputs) != expected_manifest_outputs:
        raise ValueError("Columns manifest output set does not match the indexed keywords")

    rows = [[document_id, group] for document_id, group in zip(document_ids, row_groups)]
    column_records = []
    for keyword_id in keyword_ids:
        full_path = columns_dir / f"{keyword_id}.txt"
        full_relative = f"columns/{keyword_id}.txt"
        full_content = verify_manifest_artifact(manifest_outputs, full_relative, full_path)
        _, full_flags = read_full_column(full_path, document_ids, row_groups)

        clean_path = clean_dir / f"{keyword_id}.txt"
        clean_relative = f"columns_clean/{keyword_id}.txt"
        clean_content = verify_manifest_artifact(manifest_outputs, clean_relative, clean_path)
        _, clean_flags = read_clean_column(clean_path, keyword_id, full_flags)
        for row, flag in zip(rows, clean_flags):
            row.append(flag)
        column_records.extend([
            {"path": display_path(full_path, phase_dir), "sha256": sha256_bytes(full_content),
             "size_bytes": len(full_content)},
            {"path": display_path(clean_path, phase_dir), "sha256": sha256_bytes(clean_content),
             "size_bytes": len(clean_content)},
        ])

    input_records = {
        "columns_manifest": {
            "path": display_path(manifest_path, phase_dir),
            "sha256": sha256_bytes(manifest_content),
        },
        "file_ids": {
            "path": display_path(file_ids_path, phase_dir),
            "sha256": sha256_bytes(file_ids_content),
            "size_bytes": len(file_ids_content),
        },
        "keyword_index": {
            "path": display_path(keyword_index_path, phase_dir),
            "sha256": sha256_bytes(keyword_index_content),
            "size_bytes": len(keyword_index_content),
        },
        "columns": column_records,
    }
    matrix = "".join(" ".join(row) + "\n" for row in rows).encode("utf-8")
    return matrix, input_records, len(document_ids), len(keyword_ids)


def manifest_bytes(phase_dir, output_path, provenance_path, matrix,
                   input_records, document_count, keyword_count):
    provenance = {
        "schema_version": 1,
        "counts": {
            "documents": document_count,
            "keywords": keyword_count,
            "fields_per_row": keyword_count + 2,
        },
        "inputs": input_records,
        "outputs": {
            "matrix": {
                "path": display_path(output_path, phase_dir),
                "sha256": sha256_bytes(matrix),
                "size_bytes": len(matrix),
            },
            "provenance": display_path(provenance_path, phase_dir),
        },
    }
    return (json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_output_paths(output_path, provenance_path, input_paths, input_dirs):
    output_path = Path(os.path.abspath(output_path))
    provenance_path = Path(os.path.abspath(provenance_path))
    if output_path == provenance_path:
        raise ValueError("Matrix and provenance must use different paths")
    for path in (output_path, provenance_path):
        if path in input_paths:
            raise ValueError(f"Output path would overwrite an input: {path}")
        if any(path == directory or directory in path.parents for directory in input_dirs):
            raise ValueError(f"Output path must be outside the input column directories: {path}")
        parent = path.parent
        while parent != parent.parent:
            if parent.is_symlink():
                raise ValueError(f"Output parent must not be a symlink: {parent}")
            parent = parent.parent
    return output_path, provenance_path


def existing_outputs_match(output_path, provenance_path, matrix, provenance):
    output_exists = output_path.exists() or output_path.is_symlink()
    provenance_exists = provenance_path.exists() or provenance_path.is_symlink()
    if output_exists != provenance_exists:
        raise FileExistsError("Matrix/provenance output pair is incomplete; existing files were preserved")
    if not output_exists:
        return False
    for path, expected, description in (
            (output_path, matrix, "matrix"), (provenance_path, provenance, "provenance")):
        if path.is_symlink() or not path.is_file():
            raise FileExistsError(f"Existing {description} is not a regular file: {path}")
        if path.read_bytes() != expected:
            raise FileExistsError(f"Existing {description} conflicts with current inputs: {path}")
    return True


def publish_outputs(output_path, provenance_path, matrix, provenance):
    staged_paths = []
    published_path = None
    try:
        staged = []
        for destination, content in ((output_path, matrix), (provenance_path, provenance)):
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, staged_name = tempfile.mkstemp(
                prefix=f".{destination.name}.staging-", dir=destination.parent)
            staged_path = Path(staged_name)
            staged_paths.append(staged_path)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
            staged.append((staged_path, destination))

        for staged_path, destination in staged:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"Output appeared during publication: {destination}")
            os.link(staged_path, destination)
            published_path = destination
    except Exception:
        if published_path is not None:
            staged_for_published = next(
                staged for staged, destination in staged if destination == published_path)
            if published_path.exists() and os.path.samefile(published_path, staged_for_published):
                published_path.unlink()
        raise
    finally:
        for staged_path in staged_paths:
            staged_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Merge validated keyword columns into the SAS matrix.")
    parser.add_argument("--phase-dir", type=Path, default=PHASE_DIR,
                        help="Phase directory used to resolve relative paths.")
    parser.add_argument("--columns-dir", type=Path, default=COLUMNS_DIR)
    parser.add_argument("--clean-dir", type=Path, default=CLEAN_DIR)
    parser.add_argument("--file-ids", type=Path, default=FILE_IDS)
    parser.add_argument("--keyword-index", type=Path, default=KEYWORD_INDEX)
    parser.add_argument("--columns-manifest", type=Path, default=COLUMNS_MANIFEST)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE,
                        help="Headerless matrix output path.")
    parser.add_argument("--provenance", type=Path, default=PROVENANCE_FILE,
                        help="Merge provenance JSON output path.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and output safety without writing files.")
    args = parser.parse_args(argv)

    phase_dir = args.phase_dir.resolve()
    columns_dir = resolve_cli_path(args.columns_dir, phase_dir)
    clean_dir = resolve_cli_path(args.clean_dir, phase_dir)
    file_ids_path = resolve_cli_path(args.file_ids, phase_dir)
    keyword_index_path = resolve_cli_path(args.keyword_index, phase_dir)
    manifest_path = resolve_cli_path(args.columns_manifest, phase_dir)
    output_path, provenance_path = validate_output_paths(
        resolve_cli_path(args.output, phase_dir),
        resolve_cli_path(args.provenance, phase_dir),
        {file_ids_path, keyword_index_path, manifest_path},
        {columns_dir, clean_dir},
    )

    matrix, inputs, document_count, keyword_count = build_matrix(
        phase_dir, columns_dir, clean_dir, file_ids_path, keyword_index_path, manifest_path)
    provenance = manifest_bytes(
        phase_dir, output_path, provenance_path, matrix, inputs, document_count, keyword_count)
    existing = existing_outputs_match(output_path, provenance_path, matrix, provenance)
    if args.dry_run:
        action = "Identical outputs verified" if existing else "Validated; outputs can be published"
        print(f"{action}: {document_count} documents, {keyword_count} keyword columns.")
        return 0
    if existing:
        print(f"Identical outputs already exist; verified without changes: {output_path}")
        return 0

    publish_outputs(output_path, provenance_path, matrix, provenance)
    print(f"Merged data written to {output_path}")
    print(f"Rows written: {document_count}")
    print(f"Keyword columns merged: {keyword_count}")
    print(f"Provenance written to {provenance_path}")
    return 0


if __name__ == "__main__":
    main()