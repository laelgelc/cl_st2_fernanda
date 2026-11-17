#!/usr/bin/env python3
"""Create deterministic binary keyword-presence columns for the ENADE corpus."""

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath


PHASE_DIR = Path(__file__).resolve().parent
KEYWORD_FILE = Path("corpus/07_enade_kw_selected/keywords.txt")
TAGGED_BASE = Path("corpus/05_enade_tagged")
TAGGED_MANIFEST = TAGGED_BASE / "enade_tagged_corpus.ndjson"
FAILURES_MANIFEST = TAGGED_BASE / "tagging_failures.ndjson"
TARGET_MANIFEST = Path("corpus/04_enade/enade_target_corpus.ndjson")
OUTPUT_ROOT = Path(".")
RUN_MANIFEST = "columns_run.json"
GROUP_RE = re.compile(r"^(\d{4})_(c\d+)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def natural_sort_key(text):
    """Return a natural-sort key that treats digit runs as integers."""
    parts = re.split(r"(\d+)", str(text))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def normalise_lemma(lemma):
    """Normalise lemmas consistently with the keyword-selection stage."""
    return lemma.strip().lower()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def load_ndjson(path, description, required=True):
    if path.is_symlink():
        raise ValueError(f"{description} must not be a symlink: {path}")
    if not path.exists():
        if required:
            raise FileNotFoundError(f"{description} does not exist: {path}")
        return []
    if not path.is_file():
        raise ValueError(f"{description} must be a regular, non-symlink file: {path}")

    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid {description} JSON on line {line_number}: {path}"
                ) from error
            if not isinstance(row, dict):
                raise ValueError(
                    f"{description} line {line_number} must be a JSON object: {path}"
                )
            rows.append(row)
    if required and not rows:
        raise ValueError(f"{description} is empty: {path}")
    return rows


def safe_relative_path(value, description):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"Invalid {description} path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"Unsafe {description} path: {value!r}")
    return path


def safe_phase_file(phase_dir, relative, description):
    relative = safe_relative_path(relative, description)
    path = phase_dir.joinpath(*relative.parts)
    if path.is_symlink():
        raise ValueError(f"{description} must not be a symlink: {path}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(phase_dir)
    except (OSError, ValueError) as error:
        raise ValueError(f"{description} escapes the phase directory or is missing: {path}") from error
    if not resolved.is_file():
        raise ValueError(f"{description} is not a regular file: {path}")
    return resolved


def validate_sha256(value, description):
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ValueError(f"Invalid SHA-256 value for {description}: {value!r}")
    return value


def validate_size(value, description):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid byte size for {description}: {value!r}")
    return value


def load_keywords(path):
    """Load the consolidated keyword list."""
    if path.is_symlink():
        raise ValueError(f"Keyword path must not be a symlink: {path}")
    if not path.exists():
        raise FileNotFoundError(f"Keyword file does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Keyword path must be a regular, non-symlink file: {path}")

    lemmas = [
        normalise_lemma(keyword)
        for keyword in path.read_text(encoding="utf-8").splitlines()
        if keyword.strip()
    ]

    return sorted(set(lemmas), key=natural_sort_key)


def validate_group_fields(row, description):
    year = row.get("year")
    chapter = row.get("chapter")
    group = row.get("target_subdirectory")
    if not isinstance(year, str) or not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"Invalid year in {description}: {year!r}")
    if not isinstance(chapter, str) or not re.fullmatch(r"c\d+", chapter):
        raise ValueError(f"Invalid chapter in {description}: {chapter!r}")
    expected_group = f"{year}_{chapter}"
    if group != expected_group or not GROUP_RE.fullmatch(group):
        raise ValueError(f"Inconsistent ENADE group in {description}: {group!r}")
    return expected_group


def validate_filename(value, description):
    if (not isinstance(value, str) or not value.endswith(".txt")
            or Path(value).name != value or value in (".", "..")):
        raise ValueError(f"Invalid filename in {description}: {value!r}")
    return value


def scan_tagged_texts(tagged_base):
    if tagged_base.is_symlink():
        raise ValueError(f"Tagged corpus directory must not be a symlink: {tagged_base}")
    if not tagged_base.exists():
        raise FileNotFoundError(f"Tagged corpus directory does not exist: {tagged_base}")
    if not tagged_base.is_dir():
        raise NotADirectoryError(f"Tagged corpus path must be a real directory: {tagged_base}")

    found = set()
    for current, directories, filenames in os.walk(tagged_base, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            if (current_path / directory).is_symlink():
                raise ValueError(f"Symlink directory in tagged corpus: {current_path / directory}")
        for filename in filenames:
            path = current_path / filename
            if path.suffix != ".txt":
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Tagged text must be a regular, non-symlink file: {path}")
            found.add(path.relative_to(tagged_base).as_posix())
    return found


def load_corpus_documents(phase_dir, tagged_base, tagged_manifest_path,
                          target_manifest_path, failures_manifest_path):
    """Reconcile tagged outputs with the full stage-4 target corpus."""
    target_rows = load_ndjson(target_manifest_path, "Target corpus manifest")
    tagged_rows = load_ndjson(tagged_manifest_path, "Tagged corpus manifest")
    failure_rows = load_ndjson(
        failures_manifest_path, "Tagging failures manifest", required=False
    )
    if failure_rows:
        raise ValueError(
            f"Tagging failures manifest contains {len(failure_rows)} records: "
            f"{failures_manifest_path}"
        )

    targets = {}
    source_details = {}
    for row_number, row in enumerate(target_rows, 1):
        group = validate_group_fields(row, f"target manifest row {row_number}")
        source_relative = row.get("target_chapter_path")
        source_path_parts = safe_relative_path(
            source_relative, f"target manifest row {row_number}"
        ).parts
        if len(source_path_parts) != 4:
            raise ValueError(f"Invalid target chapter path on row {row_number}: {source_relative!r}")
        filename = validate_filename(source_path_parts[-1], f"target manifest row {row_number}")
        expected_relative = f"corpus/04_enade/{group}/{filename}"
        if source_relative != expected_relative:
            raise ValueError(
                f"Target path does not match group and filename on row {row_number}: "
                f"{source_relative!r}"
            )
        if row.get("filename") is not None and row["filename"] != filename:
            raise ValueError(f"Target filename does not match target chapter path: {source_relative}")
        if source_relative in targets:
            raise ValueError(f"Duplicate target manifest document: {source_relative}")

        expected_hash = validate_sha256(row.get("chapter_sha256"), source_relative)
        expected_size = validate_size(row.get("chapter_size_bytes"), source_relative)
        source_path = safe_phase_file(phase_dir, source_relative, "Target chapter")
        if source_path.stat().st_size != expected_size or sha256_file(source_path) != expected_hash:
            raise ValueError(f"Target chapter checksum or size mismatch: {source_relative}")

        targets[source_relative] = {
            "group": group,
            "filename": filename,
            "sha256": expected_hash,
            "size_bytes": expected_size,
        }
        source_details[source_relative] = source_path

    documents = {}
    tagged_paths = set()
    for row_number, row in enumerate(tagged_rows, 1):
        group = validate_group_fields(row, f"tagged manifest row {row_number}")
        filename = validate_filename(row.get("filename"), f"tagged manifest row {row_number}")
        status = row.get("status")
        if status not in ("success", "skipped"):
            raise ValueError(f"Unusable tagging status on row {row_number}: {status!r}")

        source_relative = row.get("source_chapter_path")
        target = targets.get(source_relative)
        if target is None:
            raise ValueError(f"Tagged manifest document is absent from target manifest: {source_relative!r}")
        if source_relative in documents:
            raise ValueError(f"Duplicate tagged manifest document: {source_relative}")
        if (target["group"] != group or target["filename"] != filename
                or row.get("source_sha256") != target["sha256"]
                or row.get("source_size_bytes") != target["size_bytes"]):
            raise ValueError(f"Tagged source metadata does not match target manifest: {source_relative}")

        tagged_relative = f"corpus/05_enade_tagged/{group}/{filename}"
        if row.get("tagged_chapter_path") != tagged_relative:
            raise ValueError(
                f"Tagged path does not match group and filename on row {row_number}: "
                f"{row.get('tagged_chapter_path')!r}"
            )
        safe_relative_path(row.get("tagged_chapter_path"), "Tagged corpus")
        tagged_path = safe_phase_file(phase_dir, tagged_relative, "Tagged chapter")
        expected_tagged_path = (tagged_base / group / filename).resolve()
        if tagged_path != expected_tagged_path:
            raise ValueError(f"Tagged path is outside the configured tagged directory: {tagged_relative}")

        expected_hash = validate_sha256(row.get("tagged_sha256"), tagged_relative)
        expected_size = validate_size(row.get("tagged_size_bytes"), tagged_relative)
        if tagged_path.stat().st_size != expected_size or sha256_file(tagged_path) != expected_hash:
            raise ValueError(f"Tagged chapter checksum or size mismatch: {tagged_relative}")

        relative_to_tagged = f"{group}/{filename}"
        if relative_to_tagged in tagged_paths:
            raise ValueError(f"Duplicate tagged output path: {relative_to_tagged}")
        tagged_paths.add(relative_to_tagged)
        documents[source_relative] = {
            "path": tagged_path,
            "relative_path": relative_to_tagged,
            "group": group,
            "status": status,
            "sha256": expected_hash,
            "size_bytes": expected_size,
            "source_sha256": target["sha256"],
            "source_size_bytes": target["size_bytes"],
        }

    missing = sorted(set(targets) - set(documents), key=natural_sort_key)
    if missing:
        raise ValueError(
            f"Tagged manifest omits {len(missing)} target documents; first missing: {missing[0]}"
        )
    if set(targets) != set(documents):
        raise ValueError("Tagged and target manifests do not identify the same documents")

    actual_tagged = scan_tagged_texts(tagged_base)
    if actual_tagged != tagged_paths:
        missing_files = sorted(tagged_paths - actual_tagged, key=natural_sort_key)
        unmanifested = sorted(actual_tagged - tagged_paths, key=natural_sort_key)
        raise ValueError(
            "Tagged directory and manifest differ; "
            f"missing files={missing_files[:3]}, unmanifested files={unmanifested[:3]}"
        )

    result = []
    for source_relative, document in documents.items():
        result.append({
            **document,
            "source_relative_path": source_relative,
            "source_path": source_details[source_relative],
        })
    result.sort(key=lambda document: (
        natural_sort_key(document["group"]),
        natural_sort_key(document["relative_path"]),
    ))
    return result


def read_present_lemmas(text_file):
    """Read lemmas from the third column of a TreeTagger output file."""
    return read_present_lemmas_text(text_file.read_text(encoding="utf-8"))


def read_present_lemmas_text(text):
    present = set()

    for line in text.splitlines(keepends=True):
        parts = line.rstrip("\n").split("\t")

        if len(parts) < 3:
            parts = line.strip().split()

        if len(parts) >= 3:
            lemma = normalise_lemma(parts[2])
            if lemma and lemma != "<unknown>":
                present.add(lemma)

    return present


def build_outputs(lemmas, documents):
    lemma_index = {lemma: f"{index + 1:06d}" for index, lemma in enumerate(lemmas)}
    text_infos = []
    for index, document in enumerate(documents, 1):
        tagged_bytes = document["path"].read_bytes()
        if (len(tagged_bytes) != document["size_bytes"]
                or sha256_bytes(tagged_bytes) != document["sha256"]):
            raise ValueError(
                f"Tagged chapter changed after validation: {document['relative_path']}"
            )
        text_infos.append({
            "id": f"t{index:06d}",
            "relative_path": document["relative_path"],
            "group": document["group"],
            "lemmas": read_present_lemmas_text(tagged_bytes.decode("utf-8")),
        })

    outputs = {}
    outputs["file_ids.txt"] = "".join(
        f"{info['id']} {info['relative_path']}\n" for info in text_infos
    ).encode("utf-8")
    outputs["index_keywords.txt"] = "".join(
        f"{lemma_index[lemma]} {lemma}\n" for lemma in lemmas
    ).encode("utf-8")

    for lemma in lemmas:
        lemma_id = lemma_index[lemma]
        full_lines = []
        clean_lines = [f"{lemma_id}\n"]
        for info in text_infos:
            has_keyword = 1 if lemma in info["lemmas"] else 0
            full_lines.append(f"{info['id']} {info['group']} {has_keyword}\n")
            clean_lines.append(f"{has_keyword}\n")
        outputs[f"columns/{lemma_id}.txt"] = "".join(full_lines).encode("utf-8")
        outputs[f"columns_clean/{lemma_id}.txt"] = "".join(clean_lines).encode("utf-8")
    return outputs, text_infos, lemma_index


def make_run_manifest(phase_dir, keyword_path, tagged_manifest_path,
                      target_manifest_path, failures_manifest_path,
                      lemmas, documents, outputs):
    inputs = {
        "keywords": {
            "path": display_path(keyword_path, phase_dir),
            "sha256": sha256_file(keyword_path),
        },
        "tagged_manifest": {
            "path": display_path(tagged_manifest_path, phase_dir),
            "sha256": sha256_file(tagged_manifest_path),
        },
        "target_manifest": {
            "path": display_path(target_manifest_path, phase_dir),
            "sha256": sha256_file(target_manifest_path),
        },
        "tagging_failures_manifest": {
            "path": display_path(failures_manifest_path, phase_dir),
            "sha256": sha256_file(failures_manifest_path) if failures_manifest_path.is_file() else None,
        },
        "documents": [
            {
                "tagged_path": document["relative_path"],
                "tagged_sha256": document["sha256"],
                "tagged_size_bytes": document["size_bytes"],
                "source_path": document["source_relative_path"],
                "source_sha256": document["source_sha256"],
                "source_size_bytes": document["source_size_bytes"],
                "status": document["status"],
                "group": document["group"],
            }
            for document in documents
        ],
    }
    group_counts = {}
    for document in documents:
        group_counts[document["group"]] = group_counts.get(document["group"], 0) + 1
    return {
        "schema_version": 1,
        "logic": {
            "presence": "normalized third-column lemma occurs at least once",
            "normalization": "strip and lowercase",
            "unknown_lemma": "ignored",
            "part_of_speech_filter": None,
        },
        "counts": {"documents": len(documents), "keywords": len(lemmas)},
        "groups": [
            {"group": group, "documents": group_counts[group]}
            for group in sorted(group_counts, key=natural_sort_key)
        ],
        "inputs": inputs,
        "outputs": {
            name: {"sha256": sha256_bytes(content), "size_bytes": len(content)}
            for name, content in sorted(outputs.items())
        },
    }


def run_manifest_bytes(manifest):
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def verify_existing_outputs(output_root, outputs, manifest):
    expected_columns = {Path(name).name for name in outputs if name.startswith("columns/")}
    expected_clean = {Path(name).name for name in outputs if name.startswith("columns_clean/")}
    expected_root_files = {"file_ids.txt", "index_keywords.txt", RUN_MANIFEST}

    if output_root.is_symlink():
        raise FileExistsError(f"Output root must not be a symlink: {output_root}")
    if not output_root.exists():
        return False
    if not output_root.is_dir():
        raise FileExistsError(f"Output root is not a directory: {output_root}")

    output_paths = [output_root / name for name in ("columns", "columns_clean", *expected_root_files)]
    present = [path.exists() or path.is_symlink() for path in output_paths]
    if not any(present):
        return False
    if not all(present):
        raise FileExistsError(f"Existing output is incomplete: {output_root}")

    for dirname, expected_names in (("columns", expected_columns), ("columns_clean", expected_clean)):
        directory = output_root / dirname
        if directory.is_symlink() or not directory.is_dir():
            raise FileExistsError(f"Existing output path is not a directory: {directory}")
        actual_names = {entry.name for entry in directory.iterdir()}
        if actual_names != expected_names:
            raise FileExistsError(f"Existing output has missing or unexpected files: {directory}")

    expected_bytes = {**outputs, RUN_MANIFEST: run_manifest_bytes(manifest)}
    for name, content in expected_bytes.items():
        path = output_root / name
        if path.is_symlink() or not path.is_file():
            raise FileExistsError(f"Existing output is not a regular file: {path}")
        if path.read_bytes() != content:
            raise FileExistsError(f"Existing output conflicts with current inputs: {path}")
    return True


def publish_outputs(output_root, outputs, manifest):
    """Stage all files, then create destinations without replacing existing paths."""
    if output_root.exists() and output_root.is_symlink():
        raise FileExistsError(f"Output root must not be a symlink: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent))
    try:
        for name, content in outputs.items():
            staged = staging_dir / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
        (staging_dir / RUN_MANIFEST).write_bytes(run_manifest_bytes(manifest))

        if not output_root.exists():
            output_root.mkdir()
        if output_root.is_symlink() or not output_root.is_dir():
            raise FileExistsError(f"Output root changed during publication: {output_root}")

        for dirname in ("columns", "columns_clean"):
            destination = output_root / dirname
            if not destination.exists():
                destination.mkdir()
            elif destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
                raise FileExistsError(f"Output directory appeared during publication: {destination}")

        for name in sorted([*outputs, RUN_MANIFEST], key=natural_sort_key):
            source = staging_dir / name
            destination = output_root / name
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"Output appeared during publication: {destination}")
            os.link(source, destination)
    finally:
        shutil.rmtree(staging_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create binary keyword-presence columns for ENADE.")
    parser.add_argument("--phase-dir", type=Path, default=PHASE_DIR,
                        help="Phase directory used to resolve relative paths.")
    parser.add_argument("--keyword-file", type=Path, default=KEYWORD_FILE)
    parser.add_argument("--tagged-dir", type=Path, default=TAGGED_BASE)
    parser.add_argument("--tagged-manifest", type=Path, default=TAGGED_MANIFEST)
    parser.add_argument("--target-manifest", type=Path, default=TARGET_MANIFEST)
    parser.add_argument("--failures-manifest", type=Path, default=FAILURES_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT,
                        help="Directory for columns/, columns_clean/, indexes, and provenance.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and output safety without writing files.")
    args = parser.parse_args(argv)

    phase_dir = args.phase_dir.resolve()
    keyword_path = resolve_cli_path(args.keyword_file, phase_dir)
    tagged_base = resolve_cli_path(args.tagged_dir, phase_dir)
    tagged_manifest_path = resolve_cli_path(args.tagged_manifest, phase_dir)
    target_manifest_path = resolve_cli_path(args.target_manifest, phase_dir)
    failures_manifest_path = resolve_cli_path(args.failures_manifest, phase_dir)
    output_root = resolve_cli_path(args.output_root, phase_dir)

    lemmas = load_keywords(keyword_path)
    if not lemmas:
        raise ValueError(f"No keywords found in {keyword_path}")
    documents = load_corpus_documents(
        phase_dir, tagged_base, tagged_manifest_path, target_manifest_path,
        failures_manifest_path,
    )
    outputs, _, _ = build_outputs(lemmas, documents)
    manifest = make_run_manifest(
        phase_dir, keyword_path, tagged_manifest_path, target_manifest_path,
        failures_manifest_path, lemmas, documents, outputs,
    )

    existing = verify_existing_outputs(output_root, outputs, manifest)
    if args.dry_run:
        action = "Identical outputs verified" if existing else "Validated; outputs can be published"
        print(f"{action}: {len(documents)} documents, {len(lemmas)} keywords, "
              f"{len(manifest['groups'])} groups.")
        return 0
    if existing:
        print(f"Identical outputs already exist; verified without changes: {output_root}")
        return 0

    publish_outputs(output_root, outputs, manifest)
    print(f"Processing complete: {len(lemmas)} keywords and {len(documents)} tagged texts.")
    print(f"Columns: {output_root / 'columns'}")
    print(f"Clean binary columns: {output_root / 'columns_clean'}")
    print(f"File IDs: {output_root / 'file_ids.txt'}")
    print(f"Keyword index: {output_root / 'index_keywords.txt'}")
    print(f"Provenance: {output_root / RUN_MANIFEST}")
    return 0


if __name__ == "__main__":
    main()