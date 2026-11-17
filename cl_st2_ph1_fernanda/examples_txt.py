#!/usr/bin/env python3
"""
Generate plaintext example files for each factor pole.

Aligned with examples.py selection logic:
    - reads the same scores table (<project>_scores_only.tsv)
    - uses a configurable grouping variable, defaulting to state
    - ranks groups using means_<group>_f<n>.tsv
    - selects: top group -> 20 examples, other groups -> 10 each
    - skips rows where the factor score is 0
    - uses tagged corpus existence checks to keep selection stable with examples.py

The project name is inferred from the current working directory unless supplied
explicitly with --project.

Default expected inputs:
    sas/output_<project>/<project>_scores_only.tsv
    sas/output_<project>/means_state_f<n>.tsv
    file_ids.txt
    examples/score_details.txt
    corpus/07_tagged/<state>/<filename>.txt
    corpus/02_extracted/<state>/<filename>.md
        or
    corpus/02_extracted/<state>/<filename>.txt

Expected file_ids.txt format:
    No header
    Space-separated
    Columns:
        file_id path

Example:
    t000001 al/al_inf_15.txt

Outputs:
    examples_txt/f<n>_<pole>/f<n>_<pole>_001.txt
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_PROJECT = Path.cwd().name
DEFAULT_GROUP = "state"
DEFAULT_TAGGED_BASE = Path("corpus/07_tagged")
DEFAULT_FULLTEXT_ROOT = Path("corpus/02_extracted")
DEFAULT_FILE_IDS_PATH = Path("file_ids.txt")
DEFAULT_SCORE_DETAILS = Path("examples/score_details.txt")
DEFAULT_OUT_ROOT = Path("examples_txt")


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate plaintext examples for factor poles by group."
    )

    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=(
            "Project name, e.g. cl_st1_ph2_anna. "
            "Default: current directory name."
        ),
    )
    parser.add_argument(
        "--group",
        default=DEFAULT_GROUP,
        help=(
            "Grouping column and means-file suffix, e.g. state or decade. "
            "Default: state."
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
        "--tagged-base",
        default=str(DEFAULT_TAGGED_BASE),
        help="Tagged corpus root. Default: corpus/07_tagged.",
    )
    parser.add_argument(
        "--fulltext-root",
        default=str(DEFAULT_FULLTEXT_ROOT),
        help="Full-text corpus root. Default: corpus/02_extracted.",
    )
    parser.add_argument(
        "--file-ids",
        default=str(DEFAULT_FILE_IDS_PATH),
        help="Path to file_ids.txt.",
    )
    parser.add_argument(
        "--score-details",
        default=str(DEFAULT_SCORE_DETAILS),
        help="Path to examples/score_details.txt.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUT_ROOT),
        help="Output directory. Default: examples_txt.",
    )
    parser.add_argument(
        "--top-group-examples",
        type=int,
        default=20,
        help="Number of examples for the top-ranked group.",
    )
    parser.add_argument(
        "--other-group-examples",
        type=int,
        default=10,
        help="Number of examples for each other group.",
    )

    # Backwards-compatible aliases.
    parser.add_argument(
        "--top-decade-examples",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--other-decade-examples",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    if args.top_decade_examples is not None:
        args.top_group_examples = args.top_decade_examples

    if args.other_decade_examples is not None:
        args.other_group_examples = args.other_decade_examples

    return args


def normalize_group(group: str) -> str:
    """Normalize group name for filenames and column lookup."""
    normalized = str(group).strip().lower()

    if not normalized:
        raise ValueError("--group must not be empty")

    if not re.fullmatch(r"[a-zA-Z0-9_]+", normalized):
        raise ValueError(
            "--group may contain only letters, numbers, and underscores"
        )

    return normalized


def resolve_sas_output_dir(project: str, sas_output_dir_arg: str | None) -> Path:
    """Resolve SAS output directory."""
    if sas_output_dir_arg is None:
        return Path("sas") / f"output_{project}"

    return Path(sas_output_dir_arg)


# ============================================================
# HELPERS
# ============================================================

def natural_sort_key(text: str) -> list[int | str]:
    """Return a natural-sort key that treats digit runs as integers."""
    parts = re.split(r"(\d+)", str(text))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def load_id_map(path: Path) -> dict[str, str]:
    """
    Load file-id to relative path map.

    Expected format:
        t000001 al/al_inf_15.txt
    """
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")

    output: dict[str, str] = {}

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            parts = line.split(maxsplit=1)

            if len(parts) != 2:
                raise ValueError(
                    f"Unexpected format in {path} at line {line_number}: "
                    "expected file_id and path."
                )

            file_id, relative_path = parts

            if line_number == 1 and file_id.lower() in {"file_id", "filename"}:
                raise ValueError(
                    f"{path} appears to contain a header. "
                    "Expected a headerless file."
                )

            output[file_id] = relative_path

    if not output:
        raise ValueError(f"No file IDs found in {path}")

    return output


def detect_factor_columns(scores_df: pd.DataFrame) -> list[str]:
    """Detect factor-score columns named fac1, fac2, etc."""
    factor_columns = [
        column for column in scores_df.columns
        if re.fullmatch(r"fac\d+", str(column))
    ]

    if not factor_columns:
        raise RuntimeError("No factor columns 'fac<n>' found in scores file.")

    return sorted(factor_columns, key=natural_sort_key)


def parse_score_details(path: Path, *, num_factors: int) -> dict[str, dict[str, list[str]]]:
    """
    Parse examples/score_details.txt.

    Returns:
        loading_words[text_id]["f<n>_pos" or "f<n>_neg"] -> list[str]
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Required file missing: {path}\n"
            "Run `python score_details.py` to generate it "
            "(expected output: examples/score_details.txt)."
        )

    output: dict[str, dict[str, list[str]]] = {}
    text = path.read_text(encoding="utf-8")
    blocks = text.split("=============================================")

    for block in blocks:
        match = re.search(r"^text ID:[ \t]*(.+?)[ \t]*$", block, flags=re.MULTILINE)

        if not match:
            continue

        text_id = match.group(1).strip()
        output[text_id] = {}

        for factor_number in range(1, num_factors + 1):
            match_pos = re.search(
                rf"^f{factor_number} pos words \(N=\d+\):[ \t]*(.*)$",
                block,
                flags=re.MULTILINE,
            )
            match_neg = re.search(
                rf"^f{factor_number} neg words \(N=\d+\):[ \t]*(.*)$",
                block,
                flags=re.MULTILINE,
            )

            pos_words = match_pos.group(1).split(",") if match_pos else []
            neg_words = match_neg.group(1).split(",") if match_neg else []

            output[text_id][f"f{factor_number}_pos"] = [
                word.strip()
                for word in pos_words
                if word.strip()
            ]
            output[text_id][f"f{factor_number}_neg"] = [
                word.strip()
                for word in neg_words
                if word.strip()
            ]

    return output


def path_candidates_from_relative(root: Path, relative_path: str) -> list[Path]:
    """Build direct and extension-swapped path candidates from a relative path."""
    relative = Path(relative_path)
    direct = root / relative

    candidates = [direct]

    if relative.suffix:
        candidates.append(root / relative.with_suffix(".txt"))
        candidates.append(root / relative.with_suffix(".md"))
    else:
        candidates.append(root / relative.with_suffix(".txt"))
        candidates.append(root / relative.with_suffix(".md"))

    # De-duplicate while preserving order.
    unique_candidates = []
    seen = set()

    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)

    return unique_candidates


def path_candidates_from_row(
        *,
        row: pd.Series,
        id_map: dict[str, str],
        root: Path,
        group: str,
) -> list[Path]:
    """Return possible paths for a row under a given root."""
    text_id = str(row["filename"]).strip()
    group_value = str(row[group]).strip()

    candidates: list[Path] = []

    mapped_relative = id_map.get(text_id)
    if mapped_relative:
        candidates.extend(path_candidates_from_relative(root, mapped_relative))

    filename_path = Path(text_id)

    candidates.append(root / group_value / text_id)

    if filename_path.suffix:
        candidates.append(root / group_value / filename_path.with_suffix(".txt").name)
        candidates.append(root / group_value / filename_path.with_suffix(".md").name)
    else:
        candidates.append(root / group_value / f"{text_id}.txt")
        candidates.append(root / group_value / f"{text_id}.md")

    unique_candidates = []
    seen = set()

    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)

    return unique_candidates


def locate_existing_path(
        *,
        row: pd.Series,
        id_map: dict[str, str],
        root: Path,
        group: str,
) -> Path | None:
    """Locate an existing file for a row under a given root."""
    for path in path_candidates_from_row(
            row=row,
            id_map=id_map,
            root=root,
            group=group,
    ):
        if path.exists():
            return path

    return None


def read_group_means(
        means_file: Path,
        factor_number: int,
        group: str,
) -> dict[str, float]:
    """Read group means for one factor."""
    if not means_file.exists():
        raise FileNotFoundError(f"Required means file missing: {means_file}")

    means_df = pd.read_csv(means_file, sep="\t")
    mean_column = f"Mean fac{factor_number}"

    if group not in means_df.columns:
        raise ValueError(f"Column '{group}' missing in {means_file}")

    if mean_column not in means_df.columns:
        raise ValueError(f"Column '{mean_column}' missing in {means_file}")

    return dict(zip(
        means_df[group].astype(str).str.strip(),
        means_df[mean_column],
    ))


def write_plaintext_example(
        *,
        outfile: Path,
        text_id: str,
        group: str,
        group_value: str,
        fulltext_path: Path,
        label: str,
        score_value,
        loading_words: list[str],
) -> None:
    """Write one plaintext example file."""
    header = [
        f"Text ID: {text_id}",
        f"{group}: {group_value}",
        f"File:   {fulltext_path}",
        "",
        f"Score ({label}): {score_value}",
        f"Loading words ({label}), N={len(loading_words)}: {', '.join(loading_words)}",
        "",
    ]

    body = fulltext_path.read_text(encoding="utf-8", errors="ignore")
    outfile.write_text("\n".join(header) + body, encoding="utf-8")


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """Run plaintext example generation."""
    args = parse_args()

    project = args.project
    group = normalize_group(args.group)

    sas_output_dir = resolve_sas_output_dir(project, args.sas_output_dir)
    tagged_base = Path(args.tagged_base)
    fulltext_root = Path(args.fulltext_root)
    file_ids_path = Path(args.file_ids)
    score_details_path = Path(args.score_details)
    output_root = Path(args.output_dir)

    scores_file = sas_output_dir / f"{project}_scores_only.tsv"

    if not scores_file.exists():
        raise FileNotFoundError(f"Required file missing: {scores_file}")

    if not tagged_base.exists():
        raise FileNotFoundError(f"Tagged corpus root not found: {tagged_base}")

    if not fulltext_root.exists():
        raise FileNotFoundError(f"Full-text corpus root not found: {fulltext_root}")

    output_root.mkdir(exist_ok=True, parents=True)

    id_map = load_id_map(file_ids_path)
    scores_df = pd.read_csv(scores_file, sep="\t")

    required_columns = {"filename", group}
    missing_columns = required_columns - set(scores_df.columns)

    if missing_columns:
        raise ValueError(
            f"{scores_file} is missing required columns: "
            f"{', '.join(sorted(missing_columns))}"
        )

    scores_df["filename"] = scores_df["filename"].astype(str).str.strip()
    scores_df[group] = scores_df[group].astype(str).str.strip()

    factor_columns = detect_factor_columns(scores_df)
    num_factors = len(factor_columns)

    print(f"Project: {project}")
    print(f"Group: {group}")
    print(f"Scores file: {scores_file}")
    print(f"Tagged corpus: {tagged_base}")
    print(f"Full-text corpus: {fulltext_root}")
    print(f"Detected {num_factors} factors.\n")

    loading_words = parse_score_details(
        score_details_path,
        num_factors=num_factors,
    )

    missing_files: set[str] = set()
    missing_loading_words: set[tuple[str, str]] = set()

    for factor_number in range(1, num_factors + 1):
        factor_column = f"fac{factor_number}"

        if factor_column not in scores_df.columns:
            raise ValueError(
                f"Expected factor score column '{factor_column}' missing in {scores_file}"
            )

        means_file = sas_output_dir / f"means_{group}_f{factor_number}.tsv"
        group_means = read_group_means(means_file, factor_number, group)

        for pole, ascending in (("pos", False), ("neg", True)):
            label = f"f{factor_number}_{pole}"

            print(
                f"→ {label}: selecting by {group} means "
                f"(column={factor_column}, ascending={ascending})"
            )

            ranked_groups = sorted(
                group_means.keys(),
                key=lambda group_value: group_means[group_value],
                reverse=not ascending,
            )

            if not ranked_groups:
                raise ValueError(f"No {group} values found in {means_file}")

            top_group = ranked_groups[0]
            other_groups = ranked_groups[1:]

            sorted_df = scores_df.sort_values(by=factor_column, ascending=ascending)

            output_dir = output_root / label
            output_dir.mkdir(parents=True, exist_ok=True)

            example_id = 1

            # Top group: more examples.
            top_group_df = sorted_df[sorted_df[group] == top_group]

            for _, row in top_group_df.iterrows():
                if row[factor_column] == 0:
                    continue

                if example_id > args.top_group_examples:
                    break

                tagged_path = locate_existing_path(
                    row=row,
                    id_map=id_map,
                    root=tagged_base,
                    group=group,
                )

                if not tagged_path:
                    missing_files.add(str(row["filename"]))
                    continue

                fulltext_path = locate_existing_path(
                    row=row,
                    id_map=id_map,
                    root=fulltext_root,
                    group=group,
                )

                if not fulltext_path:
                    missing_files.add(str(row["filename"]))
                    continue

                text_id = str(row["filename"]).strip()
                group_value = str(row[group]).strip()
                label_words = loading_words.get(text_id, {}).get(label)

                if label_words is None:
                    missing_loading_words.add((text_id, label))
                    label_words = []

                outfile = output_dir / f"{label}_{example_id:03d}.txt"

                write_plaintext_example(
                    outfile=outfile,
                    text_id=text_id,
                    group=group,
                    group_value=group_value,
                    fulltext_path=fulltext_path,
                    label=label,
                    score_value=row[factor_column],
                    loading_words=label_words,
                )

                example_id += 1

            # Other groups: fewer examples each.
            for current_group in other_groups:
                group_df = sorted_df[sorted_df[group] == current_group]

                count = 0

                for _, row in group_df.iterrows():
                    if row[factor_column] == 0:
                        continue

                    if count >= args.other_group_examples:
                        break

                    tagged_path = locate_existing_path(
                        row=row,
                        id_map=id_map,
                        root=tagged_base,
                        group=group,
                    )

                    if not tagged_path:
                        missing_files.add(str(row["filename"]))
                        continue

                    fulltext_path = locate_existing_path(
                        row=row,
                        id_map=id_map,
                        root=fulltext_root,
                        group=group,
                    )

                    if not fulltext_path:
                        missing_files.add(str(row["filename"]))
                        continue

                    text_id = str(row["filename"]).strip()
                    group_value = str(row[group]).strip()
                    label_words = loading_words.get(text_id, {}).get(label)

                    if label_words is None:
                        missing_loading_words.add((text_id, label))
                        label_words = []

                    outfile = output_dir / f"{label}_{example_id:03d}.txt"

                    write_plaintext_example(
                        outfile=outfile,
                        text_id=text_id,
                        group=group,
                        group_value=group_value,
                        fulltext_path=fulltext_path,
                        label=label,
                        score_value=row[factor_column],
                        loading_words=label_words,
                    )

                    count += 1
                    example_id += 1

            print(f"  ✓ Wrote {example_id - 1} examples for {label}\n")

    if missing_files:
        missing_path = Path("missing_files.txt")
        missing_path.write_text(
            "\n".join(sorted(missing_files)),
            encoding="utf-8",
        )
        print(f"⚠ Missing files written to {missing_path}")

    if missing_loading_words:
        report_path = Path("missing_loading_words.txt")
        report_path.write_text(
            "\n".join(
                f"{text_id}\t{label}"
                for text_id, label in sorted(missing_loading_words)
            ),
            encoding="utf-8",
        )
        print(f"⚠ Missing loading words written to {report_path}")

    print(f"\n✓ Done! All plaintext examples written to {output_root}/")


if __name__ == "__main__":
    main()