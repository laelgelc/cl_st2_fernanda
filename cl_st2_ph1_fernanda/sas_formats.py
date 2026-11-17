#!/usr/bin/env python3
"""Generate and safely publish SAS formats for the validated keyword index."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


PHASE_DIR = Path(__file__).resolve().parent
KEYWORD_INDEX = Path("index_keywords.txt")
COLUMNS_MANIFEST = Path("columns_run.json")
MATRIX_FILE = Path("sas/counts.txt")
MERGE_PROVENANCE = Path("sas/merge_columns_run.json")
OUTPUT_DIR = Path("sas")
SHORT_FORMAT = "word_labels_format.sas"
FULL_FORMAT = "word_labels_full_format.sas"
FORMAT_PROVENANCE = "sas_formats_run.json"
KEYWORD_ID_RE = re.compile(r"^\d{6}$")


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


def load_json(content, path, description):
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid {description}: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Invalid {description}: {path}")
    return value


def validate_artifact_record(record, content, description, require_size=True):
    if not isinstance(record, dict):
        raise ValueError(f"Missing artifact record: {description}")
    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError(f"Invalid SHA-256 in artifact record: {description}")
    if sha256_bytes(content) != expected_hash:
        raise ValueError(f"Checksum mismatch for {description}")
    if require_size:
        expected_size = record.get("size_bytes")
        if (isinstance(expected_size, bool) or not isinstance(expected_size, int)
                or expected_size < 0 or len(content) != expected_size):
            raise ValueError(f"Size mismatch for {description}")


def validate_record_shape(record, description):
    if not isinstance(record, dict):
        raise ValueError(f"Invalid artifact record: {description}")
    digest = record.get("sha256")
    size = record.get("size_bytes")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"Invalid SHA-256 in artifact record: {description}")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"Invalid size in artifact record: {description}")


def parse_keyword_index(content, path):
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"Keyword index is not valid UTF-8: {path}") from error

    entries = []
    lemmas = set()
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"No keyword entries found in {path}")
    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"Unexpected keyword index format at {path}:{line_number}")
        keyword_id, lemma = fields
        if not KEYWORD_ID_RE.fullmatch(keyword_id) or keyword_id != f"{line_number:06d}":
            raise ValueError(f"Invalid or out-of-order keyword ID at {path}:{line_number}")
        if lemma in lemmas:
            raise ValueError(f"Duplicate keyword lemma in {path}: {lemma}")
        entries.append((keyword_id, lemma))
        lemmas.add(lemma)
    return entries


def sas_escape(text: str) -> str:
    """Escape double quotes inside SAS quoted strings."""
    return text.replace('"', '""')


def load_keyword_index(index_file: Path) -> list[tuple[str, str]]:
    """Read the headerless ``keyword_id lemma`` index using the legacy mapping."""
    if not index_file.exists():
        raise FileNotFoundError(f"Keyword index file not found: {index_file}")

    items = []
    with index_file.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                raise ValueError(
                    f"Unexpected format in {index_file} at line {line_number}: "
                    "expected keyword_id and lemma")
            keyword_id, lemma = parts
            if line_number == 1 and keyword_id.lower() in {"keyword_id", "id"}:
                raise ValueError(
                    f"{index_file} appears to contain a header. Expected a headerless file.")
            if not keyword_id.isdigit():
                raise ValueError(
                    f"Invalid keyword ID in {index_file} at line {line_number}: {keyword_id}")
            items.append((f"v{keyword_id}", sas_escape(lemma)))

    if not items:
        raise ValueError(f"No keyword entries found in {index_file}")
    return items


def validate_inputs(phase_dir, keyword_index_path, columns_manifest_path,
                    matrix_path, merge_provenance_path):
    index_content = read_regular_file(keyword_index_path, "Keyword index")
    columns_content = read_regular_file(columns_manifest_path, "Columns run manifest")
    matrix_content = read_regular_file(matrix_path, "SAS counts matrix")
    merge_content = read_regular_file(merge_provenance_path, "Merge provenance")
    columns_manifest = load_json(columns_content, columns_manifest_path, "columns run manifest")
    merge_manifest = load_json(merge_content, merge_provenance_path, "merge provenance")

    if (isinstance(columns_manifest.get("schema_version"), bool)
            or columns_manifest.get("schema_version") != 1
            or not isinstance(columns_manifest.get("counts"), dict)
            or not isinstance(columns_manifest.get("outputs"), dict)):
        raise ValueError(f"Unsupported or incomplete columns run manifest: {columns_manifest_path}")
    counts = columns_manifest["counts"]
    keyword_count = counts.get("keywords")
    if isinstance(keyword_count, bool) or not isinstance(keyword_count, int) or keyword_count <= 0:
        raise ValueError(f"Invalid keyword count in columns run manifest: {columns_manifest_path}")

    entries = parse_keyword_index(index_content, keyword_index_path)
    keyword_ids = [keyword_id for keyword_id, _ in entries]
    if len(keyword_ids) != keyword_count:
        raise ValueError(f"Keyword count does not match columns run manifest: {keyword_index_path}")
    validate_artifact_record(
        columns_manifest["outputs"].get("index_keywords.txt"), index_content,
        f"keyword index in {columns_manifest_path}")
    expected_manifest_outputs = {
        "file_ids.txt", "index_keywords.txt",
        *(f"columns/{keyword_id}.txt" for keyword_id in keyword_ids),
        *(f"columns_clean/{keyword_id}.txt" for keyword_id in keyword_ids),
    }
    if set(columns_manifest["outputs"]) != expected_manifest_outputs:
        raise ValueError("Columns manifest output set does not match the ordered keyword index")
    for name, record in columns_manifest["outputs"].items():
        validate_record_shape(record, f"{name} in {columns_manifest_path}")

    if (isinstance(merge_manifest.get("schema_version"), bool)
            or merge_manifest.get("schema_version") != 1
            or not isinstance(merge_manifest.get("counts"), dict)
            or not isinstance(merge_manifest.get("inputs"), dict)
            or not isinstance(merge_manifest.get("outputs"), dict)):
        raise ValueError(f"Unsupported or incomplete merge provenance: {merge_provenance_path}")
    merge_counts = merge_manifest["counts"]
    merge_keyword_count = merge_counts.get("keywords")
    fields_per_row = merge_counts.get("fields_per_row")
    if (isinstance(merge_keyword_count, bool) or not isinstance(merge_keyword_count, int)
            or merge_keyword_count != keyword_count or isinstance(fields_per_row, bool)
            or not isinstance(fields_per_row, int) or fields_per_row != keyword_count + 2):
        raise ValueError(f"Keyword count does not match merge provenance: {merge_provenance_path}")

    merge_inputs = merge_manifest["inputs"]
    validate_artifact_record(
        merge_inputs.get("keyword_index"), index_content,
        f"keyword index in {merge_provenance_path}")
    validate_artifact_record(
        merge_inputs.get("columns_manifest"), columns_content,
        f"columns manifest in {merge_provenance_path}", require_size=False)
    column_records = merge_inputs.get("columns")
    if not isinstance(column_records, list) or len(column_records) != 2 * keyword_count:
        raise ValueError(f"Column record count does not match keyword index: {merge_provenance_path}")
    for index, keyword_id in enumerate(keyword_ids):
        pair = column_records[2 * index:2 * index + 2]
        for record in pair:
            validate_record_shape(record, f"column input in {merge_provenance_path}")
            path = record.get("path")
            if not isinstance(path, str) or Path(path).name != f"{keyword_id}.txt":
                raise ValueError(f"Column order does not match keyword index: {merge_provenance_path}")
        if pair[0]["path"] == pair[1]["path"]:
            raise ValueError(f"Full and clean column records must be distinct: {merge_provenance_path}")

    matrix_record = merge_manifest["outputs"].get("matrix")
    validate_artifact_record(matrix_record, matrix_content, f"matrix in {merge_provenance_path}")
    if not isinstance(matrix_record.get("path"), str):
        raise ValueError(f"Missing matrix path in merge provenance: {merge_provenance_path}")

    inputs = {
        "keyword_index": {
            "path": display_path(keyword_index_path, phase_dir),
            "sha256": sha256_bytes(index_content),
            "size_bytes": len(index_content),
        },
        "columns_manifest": {
            "path": display_path(columns_manifest_path, phase_dir),
            "sha256": sha256_bytes(columns_content),
            "size_bytes": len(columns_content),
        },
        "merge_provenance": {
            "path": display_path(merge_provenance_path, phase_dir),
            "sha256": sha256_bytes(merge_content),
            "size_bytes": len(merge_content),
        },
        "matrix": {
            "path": display_path(matrix_path, phase_dir),
            "sha256": sha256_bytes(matrix_content),
            "size_bytes": len(matrix_content),
        },
    }
    items = [(f"v{keyword_id}", sas_escape(lemma)) for keyword_id, lemma in entries]
    return items, inputs, keyword_count


def render_formats(items):
    full_lines = ["PROC FORMAT library=work ;\n", "  VALUE  $lexlabelsfull\n"]
    short_lines = ["PROC FORMAT library=work ;\n", "  VALUE  $lexlabels\n"]
    for varname, word in items:
        full_lines.append(f'"{varname}" = "{word} ({varname})"\n')
        short_lines.append(f'"{varname}" = "{word}"\n')
    full_lines.append(";\nrun;\nquit;\n")
    short_lines.append(";\nrun;\nquit;\n")
    return {
        "short_format": "".join(short_lines).encode("utf-8"),
        "full_format": "".join(full_lines).encode("utf-8"),
    }


def provenance_bytes(phase_dir, output_paths, contents, inputs, keyword_count):
    provenance = {
        "schema_version": 1,
        "counts": {"keywords": keyword_count},
        "inputs": inputs,
        "outputs": {
            key: {
                "path": display_path(output_paths[key], phase_dir),
                "sha256": sha256_bytes(contents[key]),
                "size_bytes": len(contents[key]),
            }
            for key in ("short_format", "full_format")
        },
        "provenance": display_path(output_paths["provenance"], phase_dir),
    }
    return (json.dumps(provenance, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def validate_output_paths(output_paths, input_paths, input_dirs):
    normalized = {key: Path(os.path.abspath(path)) for key, path in output_paths.items()}
    if len(set(normalized.values())) != len(normalized):
        raise ValueError("SAS format outputs and provenance must use different paths")
    for path in normalized.values():
        if path in input_paths:
            raise ValueError(f"Output path would overwrite an input: {path}")
        if any(path == directory or directory in path.parents for directory in input_dirs):
            raise ValueError(f"Output path must be outside input directories: {path}")
        parent = path.parent
        while parent != parent.parent:
            if parent.is_symlink():
                raise ValueError(f"Output parent must not be a symlink: {parent}")
            parent = parent.parent
    return normalized


def existing_outputs_match(output_paths, contents):
    paths = [(output_paths[key], contents[key]) for key in ("short_format", "full_format", "provenance")]
    exists = [path.exists() or path.is_symlink() for path, _ in paths]
    if any(exists) and not all(exists):
        raise FileExistsError("SAS formats/provenance output set is incomplete; existing files were preserved")
    if not any(exists):
        return False
    for (path, expected), description in zip(paths, ("short format", "full format", "provenance")):
        if path.is_symlink() or not path.is_file():
            raise FileExistsError(f"Existing {description} is not a regular file: {path}")
        if path.read_bytes() != expected:
            raise FileExistsError(f"Existing {description} conflicts with current inputs: {path}")
    return True


def publish_outputs(output_paths, contents):
    staged_paths = []
    staged = []
    published = []
    try:
        for key in ("short_format", "full_format", "provenance"):
            destination = output_paths[key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            parent = destination.parent
            while parent != parent.parent:
                if parent.is_symlink():
                    raise ValueError(f"Output parent must not be a symlink: {parent}")
                parent = parent.parent
            descriptor, staged_name = tempfile.mkstemp(
                prefix=f".{destination.name}.staging-", dir=destination.parent)
            staged_path = Path(staged_name)
            staged_paths.append(staged_path)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(contents[key])
            staged.append((staged_path, destination))

        for staged_path, destination in staged:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"Output appeared during publication: {destination}")
            os.link(staged_path, destination)
            published.append((staged_path, destination))
    except Exception:
        for staged_path, destination in reversed(published):
            if destination.exists() and os.path.samefile(destination, staged_path):
                destination.unlink()
        raise
    finally:
        for staged_path in staged_paths:
            staged_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate SAS formats for the validated keyword index.")
    parser.add_argument("--phase-dir", type=Path, default=PHASE_DIR,
                        help="Phase directory used to resolve relative paths.")
    parser.add_argument("--keyword-index", type=Path, default=KEYWORD_INDEX)
    parser.add_argument("--columns-manifest", type=Path, default=COLUMNS_MANIFEST)
    parser.add_argument("--matrix", type=Path, default=MATRIX_FILE,
                        help="Merged SAS counts matrix to verify.")
    parser.add_argument("--merge-provenance", type=Path, default=MERGE_PROVENANCE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR,
                        help="Directory for the two formats and their provenance.")
    parser.add_argument("--short-output", type=Path,
                        help="Override the short-format output path.")
    parser.add_argument("--full-output", type=Path,
                        help="Override the full-format output path.")
    parser.add_argument("--provenance", type=Path,
                        help="Override the format provenance output path.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and output safety without writing files.")
    args = parser.parse_args(argv)

    phase_dir = args.phase_dir.resolve()
    output_dir = resolve_cli_path(args.output_dir, phase_dir)
    output_paths = {
        "short_format": resolve_cli_path(
            args.short_output if args.short_output is not None else output_dir / SHORT_FORMAT,
            phase_dir),
        "full_format": resolve_cli_path(
            args.full_output if args.full_output is not None else output_dir / FULL_FORMAT,
            phase_dir),
        "provenance": resolve_cli_path(
            args.provenance if args.provenance is not None else output_dir / FORMAT_PROVENANCE,
            phase_dir),
    }
    keyword_index_path = resolve_cli_path(args.keyword_index, phase_dir)
    columns_manifest_path = resolve_cli_path(args.columns_manifest, phase_dir)
    matrix_path = resolve_cli_path(args.matrix, phase_dir)
    merge_provenance_path = resolve_cli_path(args.merge_provenance, phase_dir)
    protected_paths = {
        keyword_index_path, columns_manifest_path, matrix_path, merge_provenance_path,
        resolve_cli_path(MATRIX_FILE, phase_dir), resolve_cli_path(MERGE_PROVENANCE, phase_dir),
    }
    output_paths = validate_output_paths(output_paths, protected_paths, set())

    items, inputs, keyword_count = validate_inputs(
        phase_dir, keyword_index_path, columns_manifest_path, matrix_path, merge_provenance_path)
    contents = render_formats(items)
    contents["provenance"] = provenance_bytes(
        phase_dir, output_paths, contents, inputs, keyword_count)
    existing = existing_outputs_match(output_paths, contents)
    if args.dry_run:
        action = "Identical outputs verified" if existing else "Validated; outputs can be published"
        print(f"{action}: {keyword_count} keyword labels.")
        return 0
    if existing:
        print("Identical SAS formats and provenance already exist; verified without changes.")
        return 0

    publish_outputs(output_paths, contents)
    print(f"SAS format files written to {output_paths['short_format'].parent}")
    print(f"Keyword labels written: {keyword_count}")
    return 0


if __name__ == "__main__":
    main()