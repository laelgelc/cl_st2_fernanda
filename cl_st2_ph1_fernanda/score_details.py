#!/usr/bin/env python3
"""
Generate score-details file showing, for each text and factor, which loading
words are present.

The project name is inferred from the current working directory unless supplied
explicitly with --project.

Expected inputs:
    sas/output_<project>/<project>_scores.tsv
    sas/output_<project>/word_labels_format.sas
    factors/var_id/f<n>_pos_var_id.txt
    factors/var_id/f<n>_neg_var_id.txt
    file_ids.txt

Expected file_ids.txt format:
    No header
    Space-separated
    Columns:
        file_id path

Example:
    t000001 ac/ac_ef_1.txt

Output:
    examples/score_details.txt
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


# ------------------------------------------------------------
# Defaults
# ------------------------------------------------------------

DEFAULT_PROJECT = Path.cwd().name
DEFAULT_VARID_DIR = Path("factors/var_id")
DEFAULT_FILE_IDS = Path("file_ids.txt")
DEFAULT_OUTFILE = Path("examples/score_details.txt")


# ------------------------------------------------------------
# Arguments
# ------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate per-text factor score details."
    )

    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=(
            "Project name, e.g. cl_st1_ph2_anna or cl_st1_ph3_anna. "
            "Default: current directory name."
        ),
    )
    parser.add_argument(
        "--sas-output-dir",
        default=None,
        help=(
            "Directory containing SAS outputs. "
            "Default: sas/output_<project>."
        ),
    )
    parser.add_argument(
        "--varid-dir",
        default=str(DEFAULT_VARID_DIR),
        help="Directory containing factor var-id files. Default: factors/var_id.",
    )
    parser.add_argument(
        "--file-ids",
        default=str(DEFAULT_FILE_IDS),
        help="Path to file_ids.txt. Default: file_ids.txt.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTFILE),
        help="Output file. Default: examples/score_details.txt.",
    )

    return parser.parse_args()


def resolve_sas_output_dir(project: str, sas_output_dir_arg: str | None) -> Path:
    """Resolve SAS output directory."""
    if sas_output_dir_arg is None:
        return Path("sas") / f"output_{project}"

    return Path(sas_output_dir_arg)


# ------------------------------------------------------------
# Loaders
# ------------------------------------------------------------

def load_scores(scores_file: Path) -> pd.DataFrame:
    """Load SAS factor scores."""
    if not scores_file.exists():
        raise FileNotFoundError(f"Scores file not found: {scores_file}")

    scores = pd.read_csv(scores_file, sep="\t")

    if "filename" not in scores.columns:
        raise ValueError(f"Column 'filename' not found in {scores_file}")

    return scores


def detect_factor_columns(scores: pd.DataFrame) -> list[str]:
    """Detect factor columns named fac1, fac2, etc."""
    factor_columns = sorted(
        [
            column for column in scores.columns
            if re.fullmatch(r"fac\d+", str(column))
        ],
        key=lambda column: int(str(column)[3:]),
    )

    if not factor_columns:
        raise RuntimeError("No fac<n> columns found in scores file.")

    return factor_columns


def load_word_labels(word_labels_file: Path) -> dict[str, str]:
    """
    Load SAS variable labels.

    Expected lines in word_labels_format.sas:
        "v000001" = "word";
    """
    if not word_labels_file.exists():
        raise FileNotFoundError(f"Word-labels file not found: {word_labels_file}")

    label_text = word_labels_file.read_text(encoding="utf-8")

    lexicon = {}

    for var_id, word in re.findall(r'"(v\d{6})"\s*=\s*"([^"]+)"', label_text):
        lexicon[var_id] = word

    if not lexicon:
        raise ValueError(f"No variable labels found in {word_labels_file}")

    return lexicon


def load_var_ids(path: Path) -> list[str]:
    """
    Extract primary variable IDs from a factor var-id file.

    IDs inside parentheses are treated as secondary loadings and ignored.
    """
    if not path.exists():
        raise FileNotFoundError(f"Factor var-id file not found: {path}")

    text = path.read_text(encoding="utf-8")

    all_ids = re.findall(r"v\d{6}", text)

    inside = set()
    for block in re.findall(r"\([^)]*\)", text):
        inside.update(re.findall(r"v\d{6}", block))

    outside = [
        var_id for var_id in all_ids
        if var_id not in inside
    ]

    # Preserve order and remove duplicates.
    seen = set()
    final = []

    for var_id in outside:
        if var_id not in seen:
            seen.add(var_id)
            final.append(var_id)

    return final


def load_factor_var_lists(
        varid_dir: Path,
        num_factors: int,
) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """Load positive and negative primary variable IDs for all factors."""
    if not varid_dir.exists():
        raise FileNotFoundError(f"Factor var-id directory not found: {varid_dir}")

    varlist_pos = {}
    varlist_neg = {}

    for factor_number in range(1, num_factors + 1):
        pos_file = varid_dir / f"f{factor_number}_pos_var_id.txt"
        neg_file = varid_dir / f"f{factor_number}_neg_var_id.txt"

        varlist_pos[factor_number] = load_var_ids(pos_file)
        varlist_neg[factor_number] = load_var_ids(neg_file)

    return varlist_pos, varlist_neg


def load_file_id_map(file_ids_path: Path) -> dict[str, str]:
    """
    Load file_ids.txt mapping.

    Expected format:
        t000001 1950/tv_com_1950_1.txt
    """
    if not file_ids_path.exists():
        raise FileNotFoundError(f"File ID map not found: {file_ids_path}")

    id_map = {}

    with file_ids_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            parts = line.split(maxsplit=1)

            if len(parts) != 2:
                raise ValueError(
                    f"Unexpected format in {file_ids_path} at line {line_number}: "
                    "expected file_id and path."
                )

            file_id, file_path = parts

            if line_number == 1 and file_id.lower() in {"file_id", "filename"}:
                raise ValueError(
                    f"{file_ids_path} appears to contain a header. "
                    "Expected a headerless file."
                )

            id_map[file_id] = file_path

    if not id_map:
        raise ValueError(f"No file IDs found in {file_ids_path}")

    return id_map


# ------------------------------------------------------------
# Output
# ------------------------------------------------------------

def write_score_details(
        *,
        scores: pd.DataFrame,
        factor_columns: list[str],
        varlist_pos: dict[int, list[str]],
        varlist_neg: dict[int, list[str]],
        lexicon: dict[str, str],
        id_map: dict[str, str],
        outfile: Path,
) -> None:
    """Write examples/score_details.txt."""
    outfile.parent.mkdir(exist_ok=True, parents=True)

    num_factors = len(factor_columns)

    with outfile.open("w", encoding="utf-8") as out:
        for _, row in scores.iterrows():
            file_id = row["filename"]
            file_name = id_map.get(file_id, "UNKNOWN")

            out.write(f"text ID: {file_id}\n")
            out.write(f"filename: {file_name}\n\n")

            for factor_number in range(1, num_factors + 1):
                factor_column = f"fac{factor_number}"

                score = row[factor_column]
                out.write(f"f{factor_number} score: {score}\n")

                # Positive pole.
                pos_ids = varlist_pos[factor_number]
                pos_used_ids = [
                    var_id for var_id in pos_ids
                    if row.get(var_id, 0) != 0
                ]
                pos_words = [
                    lexicon.get(var_id, var_id)
                    for var_id in pos_used_ids
                ]

                out.write(
                    f"f{factor_number} pos words (N={len(pos_used_ids)}): "
                    f"{', '.join(pos_words)}\n"
                )

                # Negative pole.
                neg_ids = varlist_neg[factor_number]
                neg_used_ids = [
                    var_id for var_id in neg_ids
                    if row.get(var_id, 0) != 0
                ]
                neg_words = [
                    lexicon.get(var_id, var_id)
                    for var_id in neg_used_ids
                ]

                out.write(
                    f"f{factor_number} neg words (N={len(neg_used_ids)}): "
                    f"{', '.join(neg_words)}\n\n"
                )

            out.write("=============================================\n\n")


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main() -> None:
    """Run score-details generation."""
    args = parse_args()

    project = args.project
    sas_output_dir = resolve_sas_output_dir(project, args.sas_output_dir)
    varid_dir = Path(args.varid_dir)
    file_ids_path = Path(args.file_ids)
    outfile = Path(args.output)

    scores_file = sas_output_dir / f"{project}_scores.tsv"
    word_labels_file = sas_output_dir / "word_labels_format.sas"

    scores = load_scores(scores_file)
    factor_columns = detect_factor_columns(scores)
    num_factors = len(factor_columns)

    lexicon = load_word_labels(word_labels_file)
    varlist_pos, varlist_neg = load_factor_var_lists(varid_dir, num_factors)
    id_map = load_file_id_map(file_ids_path)

    write_score_details(
        scores=scores,
        factor_columns=factor_columns,
        varlist_pos=varlist_pos,
        varlist_neg=varlist_neg,
        lexicon=lexicon,
        id_map=id_map,
        outfile=outfile,
    )

    print("\n✓ Finished.")
    print(f"Project: {project}")
    print(f"Scores file: {scores_file}")
    print(f"Word labels file: {word_labels_file}")
    print(f"Factor var-id directory: {varid_dir}")
    print(f"Output written to: {outfile}\n")


if __name__ == "__main__":
    main()