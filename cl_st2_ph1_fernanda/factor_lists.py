#!/usr/bin/env python3
"""
Create readable factor-loading lists from SAS rotated.csv output.

The default project is cl_st2_ph1_fernanda. Relative paths resolve against
--phase-dir (defaulting to the directory containing this script).

Expected default inputs:
    sas/output_<Project Name>/rotated.csv
    index_keywords.txt

Expected index_keywords.txt format:
    No header
    Space-separated
    Columns:
        keyword_id lemma

Example:
    000001 act
    000002 air
    000003 camera

Outputs:
    factors/
        f1_pos.txt
        f1_neg.txt
        ...
        factor_lists_run.json

    factors/var_id/
        f1_pos_var_id.txt
        f1_neg_var_id.txt
        ...

    factors/primary_loadings/
        f1_pos.txt
        f1_neg.txt
        ...

The output files intentionally include a first summary line:
    variables loading on this pole = <count>

Typical usage from the project phase directory:
    python factor_lists.py --dry-run
    python factor_lists.py

Optional explicit usage:
    python factor_lists.py \\
        --project cl_st2_ph1_fernanda \\
        --sas-output-dir sas/output_cl_st2_ph1_fernanda \\
        --index-file index_keywords.txt \\
        --output-dir factors \\
        --cutoff 0.3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import pandas as pd


PHASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT = "cl_st2_ph1_fernanda"
DEFAULT_INDEX_FILE = Path("index_keywords.txt")
DEFAULT_OUTPUT_DIR = Path("factors")
DEFAULT_PROVENANCE_FILENAME = "factor_lists_run.json"
DEFAULT_CUTOFF = 0.3
KEYWORD_ID_RE = re.compile(r"^\d{6}$")


def sha256_bytes(data: bytes) -> str:
    """Compute SHA-256 hexadecimal digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def resolve_cli_path(value: str | Path, phase_dir: Path) -> Path:
    """Resolve a CLI path relative to phase_dir."""
    path = Path(value)
    if not path.is_absolute():
        path = phase_dir / path
    return Path(os.path.abspath(path))


def display_path(path: Path, phase_dir: Path) -> str:
    """Return path relative to phase_dir for display and provenance."""
    try:
        return path.relative_to(phase_dir).as_posix()
    except ValueError:
        return path.as_posix()


def read_regular_file(path: Path, description: str) -> bytes:
    """Read bytes from a regular, non-symlink file."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{description} must be a regular, non-symlink file: {path}")
    return path.read_bytes()


def fmt_loading(value: float) -> str:
    """Format a loading value with no leading zero, e.g. .45, -.62."""
    text = f"{value:.2f}"

    if text.startswith("0"):
        return text[1:]

    if text.startswith("-0"):
        return "-" + text[2:]

    return text


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create readable factor-loading lists from SAS rotated.csv output."
    )

    parser.add_argument(
        "--phase-dir",
        type=Path,
        default=PHASE_DIR,
        help="Phase directory used to resolve relative paths.",
    )
    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help="Project name. Default: cl_st2_ph1_fernanda.",
    )
    parser.add_argument(
        "--sas-output-dir",
        default=None,
        help=(
            "Directory containing rotated.csv. "
            "Default: sas/output_<project>."
        ),
    )
    parser.add_argument(
        "--index-file",
        default=str(DEFAULT_INDEX_FILE),
        help="Path to index_keywords.txt.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for factor lists.",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=DEFAULT_CUTOFF,
        help="Minimum absolute loading for secondary loadings. Default: 0.3.",
    )
    parser.add_argument(
        "--provenance",
        default=None,
        help="Path to write the run provenance file. Default: <output-dir>/factor_lists_run.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and factor loading logic without writing output files.",
    )

    return parser.parse_args(argv)


def resolve_sas_output_dir(
    project: str,
    sas_output_dir_arg: str | None,
    phase_dir: Path,
) -> Path:
    """Resolve the SAS output directory."""
    if sas_output_dir_arg is None:
        return resolve_cli_path(Path("sas") / f"output_{project}", phase_dir)

    return resolve_cli_path(sas_output_dir_arg, phase_dir)


def load_keyword_index(index_file: Path) -> tuple[dict[str, str], bytes, int]:
    """
    Load and validate keyword ID to lemma mapping.

    Expected format:
        000001 act
        000002 air

    Returns:
        Mapping (e.g. v000001 -> act), raw file bytes, and keyword count.
    """
    content = read_regular_file(index_file, "Keyword index file")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"Keyword index is not valid UTF-8: {index_file}") from error

    lines = text.splitlines()
    if not lines:
        raise ValueError(f"No keyword entries found in {index_file}")

    id_to_word: dict[str, str] = {}
    lemmas: set[str] = set()

    for line_number, line in enumerate(lines, start=1):
        line = line.strip()

        if not line:
            raise ValueError(
                f"Unexpected blank line in {index_file} at line {line_number}"
            )

        parts = line.split()

        if len(parts) != 2:
            raise ValueError(
                f"Unexpected format in {index_file} at line {line_number}: "
                "expected keyword_id and lemma."
            )

        keyword_id, word = parts

        if line_number == 1 and keyword_id.lower() in {"keyword_id", "id"}:
            raise ValueError(
                f"{index_file} appears to contain a header. "
                "Expected a headerless file."
            )

        expected_id = f"{line_number:06d}"
        if not KEYWORD_ID_RE.fullmatch(keyword_id) or keyword_id != expected_id:
            raise ValueError(
                f"Invalid or out-of-order keyword ID in {index_file} at line {line_number}: "
                f"{keyword_id}"
            )

        if word in lemmas:
            raise ValueError(f"Duplicate keyword lemma in {index_file}: {word}")

        id_to_word[f"v{keyword_id}"] = word
        lemmas.add(word)

    return id_to_word, content, len(id_to_word)


def load_rotated(rotated_path: Path) -> tuple[pd.DataFrame, list[str], bytes]:
    """Load and validate SAS rotated.csv output."""
    content = read_regular_file(rotated_path, "Rotated CSV file")

    try:
        rotated = pd.read_csv(rotated_path)
    except Exception as error:
        raise ValueError(f"Failed to parse CSV from {rotated_path}") from error

    required_columns = {"_NAME_", "loaded", "factor", "pole"}
    missing_columns = required_columns - set(rotated.columns)

    if missing_columns:
        raise ValueError(
            f"{rotated_path} is missing required columns: "
            f"{', '.join(sorted(missing_columns))}"
        )

    factor_columns = [
        column for column in rotated.columns
        if column.startswith("Factor")
    ]

    if not factor_columns:
        raise ValueError(f"No Factor columns found in {rotated_path}")

    # Natural sort factor columns e.g. Factor1, Factor2, ...
    def factor_sort_key(col: str) -> int:
        num = col.replace("Factor", "")
        return int(num) if num.isdigit() else 0

    factor_columns.sort(key=factor_sort_key)

    if rotated.empty:
        raise ValueError(f"Rotated CSV file is empty: {rotated_path}")

    return rotated, factor_columns, content


def extract_loading(entry: str) -> float:
    """Extract absolute loading value from a formatted entry for sorting."""
    parts = entry.replace("(", "").replace(")", "").split()

    if len(parts) >= 2:
        try:
            return abs(float(parts[-1]))
        except ValueError:
            return 0.0

    return 0.0


def build_word_to_var_id(id_to_word: dict[str, str]) -> dict[str, str]:
    """Build reverse lookup from lemma to variable ID."""
    return {
        word: var_id
        for var_id, word in id_to_word.items()
    }


def generate_factor_entries(
    rotated: pd.DataFrame,
    id_to_word: dict[str, str],
    factor_columns: list[str],
    cutoff: float,
) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    """
    Extract primary and secondary loadings from rotated DataFrame.

    Returns:
        Mapping of factor_pole key (e.g. 'f1_pos') to sorted loading entries,
        and summary count statistics.
    """
    results: dict[str, list[str]] = {}

    for _, row in rotated.iterrows():
        varname = str(row["_NAME_"])
        word = id_to_word.get(varname, varname)

        # Skip rows without primary loading.
        if (
            pd.isna(row["pole"])
            or pd.isna(row["factor"])
            or row["loaded"] != 1
        ):
            continue

        primary_factor = str(row["factor"]).strip()
        primary_pole = int(row["pole"])

        factor_id = primary_factor.replace("fac", "f")
        pole_label = "pos" if primary_pole == 1 else "neg"
        pole_key = f"{factor_id}_{pole_label}"

        results.setdefault(pole_key, [])

        # Mapping: fac1 -> Factor1
        factor_column = primary_factor.replace("fac", "Factor")
        primary_score = row.get(factor_column, None)

        if pd.isna(primary_score):
            continue

        formatted_score = fmt_loading(float(primary_score))
        entry = f"{word} ({formatted_score})"

        results[pole_key].append(entry)

        # Secondary loadings.
        for column in factor_columns:
            if column == factor_column:
                continue

            value = row[column]

            if pd.isna(value):
                continue

            float_val = float(value)
            if abs(float_val) >= cutoff:
                secondary_pole = 1 if float_val > 0 else -1
                secondary_factor_num = column.replace("Factor", "")
                secondary_pole_label = "pos" if secondary_pole == 1 else "neg"
                secondary_pole_key = f"f{secondary_factor_num}_{secondary_pole_label}"

                results.setdefault(secondary_pole_key, [])

                formatted_secondary = fmt_loading(float_val)
                secondary_entry = f"({word} ({formatted_secondary}))"

                results[secondary_pole_key].append(secondary_entry)

    if not results:
        raise ValueError(
            "No factor-loading entries were generated. "
            "Check rotated.csv, loaded column, factor column, and cutoff."
        )

    # Sort each pole's entries descending by absolute loading.
    sorted_results: dict[str, list[str]] = {}
    stats: dict[str, dict[str, int]] = {}

    for pole_key in sorted(results.keys()):
        entries = results[pole_key]
        sorted_list = sorted(entries, key=extract_loading, reverse=True)
        sorted_results[pole_key] = sorted_list

        primary_count = sum(1 for e in sorted_list if not e.startswith("("))
        total_count = len(sorted_list)
        stats[pole_key] = {
            "total": total_count,
            "primary": primary_count,
            "secondary": total_count - primary_count,
        }

    return sorted_results, stats


def render_all_outputs(
    results: dict[str, list[str]],
    id_to_word: dict[str, str],
    output_dir: Path,
    provenance_path: Path,
    phase_dir: Path,
    inputs_meta: dict[str, dict[str, str | int]],
    project: str,
    cutoff: float,
    keyword_count: int,
    rotated_rows_count: int,
    loaded_vars_count: int,
    factor_columns: list[str],
    stats: dict[str, dict[str, int]],
) -> tuple[dict[str, Path], dict[str, bytes]]:
    """Render all factor list files, var_id files, primary loading files, and provenance."""
    output_paths: dict[str, Path] = {}
    contents: dict[str, bytes] = {}

    var_id_dir = output_dir / "var_id"
    primary_dir = output_dir / "primary_loadings"
    word_to_var_id = build_word_to_var_id(id_to_word)

    for pole_key, sorted_entries in results.items():
        count = len(sorted_entries)

        # 1. Full word version: primary plus secondary loadings.
        full_path = output_dir / f"{pole_key}.txt"
        full_text = f"variables loading on this pole = {count}\n" + ", ".join(sorted_entries) + "\n"
        output_paths[f"full_{pole_key}"] = full_path
        contents[f"full_{pole_key}"] = full_text.encode("utf-8")

        # 2. Variable-ID version.
        var_id_entries = []
        for entry in sorted_entries:
            parts = entry.replace("(", "").replace(")", "").split()
            if not parts:
                continue

            word_part = parts[0]
            found_id = word_to_var_id.get(word_part, word_part)
            loading = parts[-1]

            if entry.startswith("("):
                new_entry = f"({found_id} ({loading}))"
            else:
                new_entry = f"{found_id} ({loading})"

            var_id_entries.append(new_entry)

        var_id_path = var_id_dir / f"{pole_key}_var_id.txt"
        var_id_text = f"variables loading on this pole = {count}\n" + ", ".join(var_id_entries) + "\n"
        output_paths[f"var_id_{pole_key}"] = var_id_path
        contents[f"var_id_{pole_key}"] = var_id_text.encode("utf-8")

        # 3. Primary-only word version.
        primary_only_entries = [
            entry for entry in sorted_entries
            if not entry.startswith("(")
        ]
        primary_only_count = len(primary_only_entries)
        primary_path = primary_dir / f"{pole_key}.txt"
        primary_text = f"variables loading on this pole = {primary_only_count}\n" + ", ".join(primary_only_entries) + "\n"
        output_paths[f"primary_{pole_key}"] = primary_path
        contents[f"primary_{pole_key}"] = primary_text.encode("utf-8")

    # 4. Provenance file.
    output_paths["provenance"] = provenance_path
    provenance_data = {
        "schema_version": 1,
        "project": project,
        "cutoff": cutoff,
        "counts": {
            "keywords_in_index": keyword_count,
            "rotated_rows": rotated_rows_count,
            "loaded_variables": loaded_vars_count,
            "unloaded_variables": rotated_rows_count - loaded_vars_count,
            "factors": len(factor_columns),
            "factor_poles": len(results),
            "pole_counts": stats,
        },
        "inputs": inputs_meta,
        "outputs": {
            key: {
                "path": display_path(output_paths[key], phase_dir),
                "sha256": sha256_bytes(contents[key]),
                "size_bytes": len(contents[key]),
            }
            for key in sorted(output_paths.keys())
            if key != "provenance"
        },
        "provenance": display_path(provenance_path, phase_dir),
    }
    contents["provenance"] = (
        json.dumps(provenance_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    return output_paths, contents


def validate_output_paths(
    output_paths: dict[str, Path],
    input_paths: set[Path],
) -> dict[str, Path]:
    """Validate that output paths do not collide with inputs or symlinks."""
    normalized = {key: Path(os.path.abspath(path)) for key, path in output_paths.items()}

    if len(set(normalized.values())) != len(normalized):
        raise ValueError("Factor list outputs and provenance must use distinct paths")

    for path in normalized.values():
        if path in input_paths:
            raise ValueError(f"Output path would overwrite an input: {path}")

        parent = path.parent
        while parent != parent.parent:
            if parent.is_symlink():
                raise ValueError(f"Output parent must not be a symlink: {parent}")
            parent = parent.parent

    return normalized


def existing_outputs_match(
    output_paths: dict[str, Path],
    contents: dict[str, bytes],
) -> bool:
    """Check if all existing outputs exist and match expected content exactly."""
    paths = [(output_paths[key], contents[key], key) for key in output_paths]
    exists = [path.exists() or path.is_symlink() for path, _, _ in paths]

    if any(exists) and not all(exists):
        raise FileExistsError(
            "Factor list output set is incomplete; existing files were preserved"
        )

    if not any(exists):
        return False

    for path, expected, key in paths:
        if path.is_symlink() or not path.is_file():
            raise FileExistsError(f"Existing output {key} is not a regular file: {path}")
        if path.read_bytes() != expected:
            raise FileExistsError(f"Existing output {key} conflicts with current inputs: {path}")

    return True


def publish_outputs(
    output_paths: dict[str, Path],
    contents: dict[str, bytes],
) -> None:
    """Safely publish output files atomically."""
    staged_paths: list[Path] = []
    staged: list[tuple[Path, Path]] = []
    published: list[tuple[Path, Path]] = []

    try:
        for key, destination in output_paths.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            parent = destination.parent

            while parent != parent.parent:
                if parent.is_symlink():
                    raise ValueError(f"Output parent must not be a symlink: {parent}")
                parent = parent.parent

            descriptor, staged_name = tempfile.mkstemp(
                prefix=f".{destination.name}.staging-",
                dir=destination.parent,
            )
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


def main(argv: list[str] | None = None) -> int:
    """Run factor-list generation."""
    args = parse_args(argv)

    phase_dir = args.phase_dir.resolve()
    project = args.project
    sas_output_dir = resolve_sas_output_dir(project, args.sas_output_dir, phase_dir)
    rotated_path = resolve_cli_path(sas_output_dir / "rotated.csv", phase_dir)
    index_file = resolve_cli_path(args.index_file, phase_dir)
    output_dir = resolve_cli_path(args.output_dir, phase_dir)
    provenance_path = resolve_cli_path(
        args.provenance if args.provenance is not None else output_dir / DEFAULT_PROVENANCE_FILENAME,
        phase_dir,
    )
    cutoff = args.cutoff

    if cutoff < 0:
        raise ValueError("--cutoff must be non-negative")

    id_to_word, index_bytes, keyword_count = load_keyword_index(index_file)
    rotated, factor_columns, rotated_bytes = load_rotated(rotated_path)

    inputs_meta = {
        "keyword_index": {
            "path": display_path(index_file, phase_dir),
            "sha256": sha256_bytes(index_bytes),
            "size_bytes": len(index_bytes),
        },
        "rotated_csv": {
            "path": display_path(rotated_path, phase_dir),
            "sha256": sha256_bytes(rotated_bytes),
            "size_bytes": len(rotated_bytes),
        },
    }

    results, stats = generate_factor_entries(
        rotated=rotated,
        id_to_word=id_to_word,
        factor_columns=factor_columns,
        cutoff=cutoff,
    )

    loaded_vars_count = int((rotated["loaded"] == 1).sum())
    rotated_rows_count = len(rotated)

    output_paths, contents = render_all_outputs(
        results=results,
        id_to_word=id_to_word,
        output_dir=output_dir,
        provenance_path=provenance_path,
        phase_dir=phase_dir,
        inputs_meta=inputs_meta,
        project=project,
        cutoff=cutoff,
        keyword_count=keyword_count,
        rotated_rows_count=rotated_rows_count,
        loaded_vars_count=loaded_vars_count,
        factor_columns=factor_columns,
        stats=stats,
    )

    protected_inputs = {index_file, rotated_path}
    output_paths = validate_output_paths(output_paths, protected_inputs)

    existing = existing_outputs_match(output_paths, contents)

    if args.dry_run:
        action = "Identical outputs verified" if existing else "Validated; outputs can be published"
        print(f"{action}: {len(results)} factor poles across {len(factor_columns)} factors.")
        print(f"Project: {project}")
        print(f"Rotated input: {display_path(rotated_path, phase_dir)}")
        print(f"Keyword index: {display_path(index_file, phase_dir)}")
        print(f"Loaded variables: {loaded_vars_count}/{rotated_rows_count}")
        print(f"Cutoff: {cutoff}")
        print(f"Output files to write: {len(output_paths)} (including provenance)")
        return 0

    if existing:
        print("Identical factor lists and provenance already exist; verified without changes.")
        return 0

    publish_outputs(output_paths, contents)

    print("Done.")
    print(f"Project: {project}")
    print(f"Rotated input: {display_path(rotated_path, phase_dir)}")
    print(f"Keyword index: {display_path(index_file, phase_dir)}")
    print(f"Output directory: {display_path(output_dir, phase_dir)}")
    print(f"Factor-list files written: {len(output_paths)}")
    print(f"Loaded variables: {loaded_vars_count}/{rotated_rows_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())