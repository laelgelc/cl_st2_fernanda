#!/usr/bin/env python3
"""
select_kws_stratified.py

Selects a balanced, stratum-based subset of positive keywords (POSKW)
from ENADE group profiles produced by keylemmas.py.

What it does
------------
1) Reads every group key-lemma file in corpus/06_enade_keylemmas/.
   Supported extensions: .txt and .tsv.

2) Extracts lemmas whose final column is POSKW, applying lexical filters:
   - keep alphabetic lemmas and valid hyphenated compounds;
   - allow Unicode alphabetic characters, including accented letters;
   - allow hyphens only internally, between alphabetic parts;
   - drop lemmas containing digits;
   - drop lemmas containing uppercase letters;
   - drop lemmas containing punctuation other than valid internal hyphens.

3) Applies the same quota to every group:
   - each group: at most --per-group lemmas.

4) Builds a consolidated list in deterministic natural group order.

5) Optionally truncates the consolidated list to --max-total before
   de-duplication.

6) Writes outputs to corpus/07_enade_kw_selected/:
   - one file per group: <year>_<chapter>.txt
   - one consolidated, de-duplicated list: keywords.txt
   - a run manifest containing input and output checksums

Typical usage
-------------
python select_kws_stratified.py \
    --input corpus/06_enade_keylemmas \
    --output corpus/07_enade_kw_selected \
    --per-group 5 \
    --max-total 220 \
    --dry-run
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


PHASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = "corpus/06_enade_keylemmas"
OUTPUT_DIR = "corpus/07_enade_kw_selected"
RUN_MANIFEST = "select_kws_stratified_run.json"

SUPPORTED_EXTENSIONS = (".txt", ".tsv")


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------

def natural_sort_key(text):
    """Return a natural-sort key that treats digit runs as integers."""
    parts = re.split(r"(\d+)", text)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def is_valid_stratum_name(name):
    """
    Return True if name is a usable group profile stem.

    Hidden files, metadata files, and consolidated keyword files are skipped.
    """
    return (
            name
            and name != "keywords"
            and not name.startswith("_")
            and not name.startswith(".")
    )


def is_valid_lemma_shape(lemma):
    """
    Return True if a lemma has valid lexical shape.

    Valid lemmas must:

    1. contain at least two alphabetic characters overall;
    2. consist of one or more alphabetic parts;
    3. use hyphens only internally, between alphabetic parts.

    Unicode alphabetic characters, including accented letters, are allowed.
    """
    parts = lemma.split("-")

    if any(not part for part in parts):
        return False

    if any(not all(ch.isalpha() for ch in part) for part in parts):
        return False

    return sum(1 for ch in lemma if ch.isalpha()) >= 2


def is_clean_lemma(lemma):
    """Return True if lemma passes lexical filtering rules."""
    if any(ch.isupper() for ch in lemma):
        return False

    return is_valid_lemma_shape(lemma)


def resolve_path(path):
    """Resolve relative paths from this phase directory."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PHASE_DIR / candidate
    return candidate.resolve()


def validate_path_separation(input_dir, output_dir):
    """Reject output locations that overlap the source directory."""
    common = Path(os.path.commonpath((str(input_dir), str(output_dir))))
    if common == input_dir or common == output_dir:
        raise ValueError(
            f"Input and output directories must not overlap: "
            f"{input_dir} and {output_dir}"
        )


def discover_keylemma_files(input_dir):
    """Return group-named key-lemma files in natural group order."""
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    group_files = {}

    for extension in SUPPORTED_EXTENSIONS:
        for filepath in input_dir.glob(f"*{extension}"):
            if not filepath.is_file():
                continue

            stem = filepath.stem
            if not is_valid_stratum_name(stem):
                continue

            existing = group_files.get(stem)
            # Prefer .tsv if both .tsv and .txt exist for the same group.
            if existing is None or (
                filepath.suffix == ".tsv" and existing.suffix == ".txt"
            ):
                group_files[stem] = filepath

    if not group_files:
        raise FileNotFoundError(
            f"No group key-lemma files found in {input_dir}. "
            "Expected files such as 2009_c4.tsv."
        )

    return [
        (group, group_files[group])
        for group in sorted(group_files, key=natural_sort_key)
    ]


def sha256_bytes(content):
    """Return a SHA-256 checksum for bytes."""
    return hashlib.sha256(content).hexdigest()


def load_poskw_details(filepath):
    """Load filtered POSKW lemmas and checksum the exact source bytes."""
    content = filepath.read_bytes()
    lines = content.decode("utf-8").splitlines()
    lemmas = []

    # The first line is the header for TSV and legacy text files.
    for line in lines[1:]:
        line = line.strip()

        if not line:
            continue

        if "\t" in line:
            parts = line.split("\t")
        else:
            parts = line.split()

        if len(parts) < 2:
            continue

        lemma = parts[0].strip()
        status = parts[-1].strip()

        if status == "POSKW" and is_clean_lemma(lemma):
            lemmas.append(lemma)

    return lemmas, sha256_bytes(content)


def load_poskw(filepath):
    """Load eligible POSKW lemmas from a key-lemma file."""
    return load_poskw_details(Path(filepath))[0]


def plan_selection(keylemma_files, per_group, max_total):
    """Build group and consolidated selections without writing files."""
    selected_by_group = {}
    group_details = []

    for group, filepath in keylemma_files:
        eligible, input_checksum = load_poskw_details(filepath)
        chosen = eligible[:per_group]
        selected_by_group[group] = chosen
        group_details.append({
            "group": group,
            "input_file": filepath.name,
            "input_sha256": input_checksum,
            "eligible_poskw": len(eligible),
            "selected": len(chosen),
        })

    consolidated = []
    for group in selected_by_group:
        consolidated.extend(selected_by_group[group])

    before_cap = len(consolidated)
    if max_total and len(consolidated) > max_total:
        consolidated = consolidated[:max_total]

    unique_lemmas = sorted(set(consolidated))
    return {
        "selected_by_group": selected_by_group,
        "groups": group_details,
        "before_cap": before_cap,
        "after_cap": len(consolidated),
        "unique_lemmas": unique_lemmas,
        "duplicates_removed": len(consolidated) - len(unique_lemmas),
    }


def output_bytes(words):
    """Encode a one-lemma-per-line output file."""
    return "".join(word + "\n" for word in words).encode("utf-8")


def build_run_manifest(input_dir, output_dir, per_group, max_total, selection,
                       outputs):
    """Build provenance metadata for the planned output files."""
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_directory": str(input_dir),
        "output_directory": str(output_dir),
        "parameters": {
            "per_group": per_group,
            "max_total": max_total,
        },
        "groups": selection["groups"],
        "counts": {
            "group_count": len(selection["groups"]),
            "selected_occurrences_before_cap": selection["before_cap"],
            "selected_occurrences_after_cap": selection["after_cap"],
            "unique_keywords": len(selection["unique_lemmas"]),
            "duplicates_removed": selection["duplicates_removed"],
        },
        "outputs": {
            name: {
                "sha256": sha256_bytes(content),
                "line_count": content.count(b"\n"),
            }
            for name, content in outputs.items()
        },
    }


def manifest_bytes(manifest):
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")


def verify_existing_output(output_dir, expected_manifest):
    """Accept only a complete, checksum-valid, identical prior run."""
    expected_names = set(expected_manifest["outputs"]) | {RUN_MANIFEST}
    entries = list(output_dir.iterdir())
    if ({entry.name for entry in entries} != expected_names
            or any(entry.is_symlink() or not entry.is_file() for entry in entries)):
        raise FileExistsError(
            f"Existing output has missing or unexpected files: {output_dir}"
        )

    try:
        existing_manifest = json.loads(
            (output_dir / RUN_MANIFEST).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        raise FileExistsError(
            f"Existing output manifest is unreadable: {output_dir / RUN_MANIFEST}"
        ) from error

    identity_fields = (
        "schema_version", "input_directory", "output_directory", "parameters",
        "groups", "counts", "outputs",
    )
    if not isinstance(existing_manifest, dict):
        raise FileExistsError(
            f"Existing output manifest is not a JSON object: {output_dir / RUN_MANIFEST}"
        )

    if any(existing_manifest.get(field) != expected_manifest[field]
           for field in identity_fields):
        raise FileExistsError(
            f"Existing output conflicts with current inputs or parameters: {output_dir}"
        )

    for name, details in expected_manifest["outputs"].items():
        if sha256_bytes((output_dir / name).read_bytes()) != details["sha256"]:
            raise FileExistsError(
                f"Existing output checksum does not match: {output_dir / name}"
            )


def publish_outputs(output_dir, outputs, manifest):
    """Publish a complete output directory from a sibling staging directory."""
    if output_dir.exists():
        if not output_dir.is_dir():
            raise FileExistsError(f"Output path exists and is not a directory: {output_dir}")
        verify_existing_output(output_dir, manifest)
        print(f"Identical output already exists; verified without changes: {output_dir}")
        return False

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(
        prefix=f".{output_dir.name}.staging-", dir=output_dir.parent
    ))
    try:
        for name, content in outputs.items():
            (staging_dir / name).write_bytes(content)
        (staging_dir / RUN_MANIFEST).write_bytes(manifest_bytes(manifest))

        if output_dir.exists():
            raise FileExistsError(f"Output path appeared during publication: {output_dir}")
        os.rename(staging_dir, output_dir)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

    print(f"Published outputs: {output_dir}")
    return True


# -----------------------------------------------------------
# Main
# -----------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Select a stratified ENADE POSKW keyword set."
    )
    parser.add_argument(
        "--input",
        "--input-dir",
        dest="input",
        default=INPUT_DIR,
        help=f"Input group profiles (default: {INPUT_DIR}).",
    )
    parser.add_argument(
        "--output",
        "--output-dir",
        dest="output",
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--per-group",
        type=int,
        required=True,
        help="Maximum number of POSKW lemmas to select from each group.",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=0,
        help=(
            "Optional maximum consolidated keyword count before de-duplication. "
            "Use 0 for no maximum."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report the selection without writing any files.",
    )

    args = parser.parse_args(argv)

    if args.per_group <= 0:
        parser.error("--per-group must be greater than 0")

    if args.max_total < 0:
        parser.error("--max-total must be non-negative")

    try:
        input_dir = resolve_path(args.input)
        output_dir = resolve_path(args.output)
        validate_path_separation(input_dir, output_dir)
        keylemma_files = discover_keylemma_files(input_dir)
        selection = plan_selection(keylemma_files, args.per_group, args.max_total)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    output_files = {
        f"{group}.txt": output_bytes(words)
        for group, words in selection["selected_by_group"].items()
    }
    output_files["keywords.txt"] = output_bytes(selection["unique_lemmas"])
    manifest = build_run_manifest(
        input_dir,
        output_dir,
        args.per_group,
        args.max_total,
        selection,
        output_files,
    )

    print("=== ENADE Keyword Selection ===")
    for group in selection["selected_by_group"]:
        detail = next(item for item in selection["groups"] if item["group"] == group)
        print(
            f"{group:<22} → selected {detail['selected']}/{args.per_group} "
            f"from {detail['eligible_poskw']} eligible POSKW lemmas"
        )

    print(f"\nGroup count: {len(selection['groups'])}")
    print(f"Selected occurrences before cap: {selection['before_cap']}")
    print(f"Occurrences after cap: {selection['after_cap']}")
    print(f"Unique keywords: {len(selection['unique_lemmas'])}")
    print(f"Duplicates removed: {selection['duplicates_removed']}")

    if args.dry_run:
        if output_dir.exists():
            try:
                verify_existing_output(output_dir, manifest)
            except (OSError, ValueError) as error:
                parser.error(str(error))
            print(f"Existing output verified; no changes made: {output_dir}")
        else:
            print(f"Dry run: no files written; planned output: {output_dir}")
        return 0

    try:
        publish_outputs(output_dir, output_files, manifest)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    main()