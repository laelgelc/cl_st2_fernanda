#!/usr/bin/env python3
"""
Generate TikZ boxplots in LaTeX for factor dimensions by group.

This script is expected to be located in:

    latex_boxplots/latex_boxplots.py

Default input, resolved relative to --phase-dir:

    sas/output_<project>/<project>_scores_only.tsv
    sas/output_<project>/params_<model-group>_f<n>.tsv

The model group defaults to the selected grouping column (year_chapter by
default). Relative path overrides resolve from --phase-dir, not the current
working directory.

where <project> is inferred from the parent directory name, for example:

    cl_st2_ph1_fernanda

Default output:

    latex_boxplots/slides/boxplot_f<dim>_by_group.tex
    latex_boxplots/slides/mosaic_by_group.tex

Typical usage from inside latex_boxplots/:

    python latex_boxplots.py --dry-run
    python latex_boxplots.py

Typical usage from the project root:

    python latex_boxplots/latex_boxplots.py

Optional explicit usage:

    python latex_boxplots.py \
        --phase-dir .. \
        --project cl_st2_ph1_fernanda \
        --sas-output-dir sas/output_cl_st2_ph1_fernanda \
        --output-dir latex_boxplots/slides \
        --params-group year_chapter
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
import tempfile
from pathlib import Path

import pandas as pd
from tqdm import tqdm


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_PROJECT = PROJECT_DIR.name
DEFAULT_OUTPUT_DIR = Path("latex_boxplots") / "slides"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate LaTeX/TikZ factor-score boxplots by group."
    )

    parser.add_argument(
        "--phase-dir",
        type=Path,
        default=PROJECT_DIR,
        help="Phase directory used to resolve relative input and output paths.",
    )
    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=(
            "Project name. Default: inferred from the phase directory containing this script."
        ),
    )
    parser.add_argument(
        "--sas-output-dir",
        default=None,
        help=(
            "Directory containing SAS outputs. "
            "Default: sas/output_<project>, resolved relative to --phase-dir."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory where LaTeX boxplot files will be written. "
            "Default: latex_boxplots/slides, resolved relative to --phase-dir."
        ),
    )
    parser.add_argument(
        "--group-column",
        default="year_chapter",
        help=(
            "Column in the scores-only TSV used for grouping. "
            "Default: year_chapter."
        ),
    )

    parser.add_argument(
        "--params-group",
        default=None,
        help=(
            "Group name used in params_<group>_f<n>.tsv. "
            "Default: the selected --group-column; choose a model corresponding "
            "to the plotted grouping (for example, group aliases year_chapter)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render all outputs without writing files.",
    )

    return parser.parse_args(argv)


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve input and output directories."""
    phase_dir = Path(args.phase_dir).resolve()
    if args.sas_output_dir is None:
        sas_output_dir = phase_dir / "sas" / f"output_{args.project}"
    else:
        sas_output_dir = Path(args.sas_output_dir)

        if not sas_output_dir.is_absolute():
            sas_output_dir = phase_dir / sas_output_dir

    if args.output_dir is None:
        output_dir = phase_dir / DEFAULT_OUTPUT_DIR
    else:
        output_dir = Path(args.output_dir)

        if not output_dir.is_absolute():
            output_dir = phase_dir / output_dir

    return Path(os.path.abspath(sas_output_dir)), Path(os.path.abspath(output_dir))


def read_rsquare(param_file: Path, dim: int) -> float:
    """
    Return R² (%) from a params TSV file containing a column named RSquare.

    Validate the parameter row and its optional dependent-factor metadata.
    """
    with param_file.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = reader.fieldnames
        if not fieldnames or "RSquare" not in fieldnames:
            raise ValueError(f"Parameter file has no RSquare column: {param_file}")
        rows = list(reader)

    if len(rows) != 1:
        raise ValueError(
            f"Expected exactly one parameter row for fac{dim} in {param_file}; "
            f"found {len(rows)}"
        )

    row = rows[0]
    if "Dependent" in fieldnames and (row.get("Dependent") or "").strip() != f"fac{dim}":
        raise ValueError(f"Parameter file Dependent must be fac{dim}: {param_file}")

    try:
        rsquare = float(row["RSquare"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(f"Invalid RSquare value in parameter file: {param_file}") from exc

    if not math.isfinite(rsquare):
        raise ValueError(f"RSquare must be finite in parameter file: {param_file}")

    return rsquare * 100.0


def read_scores(input_file: Path, group_column: str) -> tuple[pd.DataFrame, list[int]]:
    """Read and validate grouping labels and numeric factor scores."""
    try:
        df = pd.read_csv(input_file, sep="\t")
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ValueError(f"Could not read scores-only TSV: {input_file}") from exc

    if df.empty:
        raise ValueError(f"Scores-only TSV contains no rows: {input_file}")
    if group_column not in df.columns:
        raise ValueError(f"Column '{group_column}' not found in {input_file}")
    if df[group_column].isna().any():
        raise ValueError(f"Scores-only TSV contains a missing group label in '{group_column}'")

    df[group_column] = df[group_column].astype(str).str.strip()
    if df[group_column].eq("").any():
        raise ValueError(f"Scores-only TSV contains a blank group label in '{group_column}'")

    dims = detect_dims(df, input_file)
    for dim in dims:
        column = f"fac{dim}"
        original = df[column]
        numeric = pd.to_numeric(original, errors="coerce")
        nonblank = original.notna() & original.astype(str).str.strip().ne("")
        invalid = nonblank & numeric.isna()
        if invalid.any():
            invalid_value = original[invalid].iloc[0]
            raise ValueError(
                f"Non-numeric value in factor column '{column}' in {input_file}: "
                f"{invalid_value!r}"
            )

        nonfinite = numeric.notna() & ~numeric.map(lambda value: math.isfinite(float(value)))
        if nonfinite.any():
            raise ValueError(f"Non-finite value in factor column '{column}' in {input_file}")

        df[column] = numeric
        has_values = df.groupby(group_column)[column].apply(lambda values: values.notna().any())
        empty_groups = has_values.index[~has_values]
        if len(empty_groups):
            raise ValueError(
                f"Group {empty_groups[0]!r} has no usable values in factor column '{column}'"
            )

    return df, dims


def latex_escape(text: str) -> str:
    """Escape characters that have special meaning in LaTeX."""
    replacements = {
        "\\": r"\textbackslash{}",
        "_": r"\_",
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
        "{": r"\{",
        "}": r"\}",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }

    for original, escaped in replacements.items():
        text = text.replace(original, escaped)

    return text


def natural_sort_key(text: str) -> list[int | str]:
    """Return a natural-sort key that treats digit runs as integers."""
    parts = re.split(r"(\d+)", str(text))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def compute_boxplot_stats(series: pd.Series) -> tuple[float, float, float, float, float]:
    """Compute lower whisker, Q1, median, Q3, and upper whisker."""
    q1, median, q3 = series.quantile([0.25, 0.5, 0.75])
    iqr = q3 - q1

    return (
        max(series.min(), q1 - 1.5 * iqr),
        q1,
        median,
        q3,
        min(series.max(), q3 + 1.5 * iqr),
    )


def detect_dims(df: pd.DataFrame, input_file: Path) -> list[int]:
    """Detect available factor dimensions from columns named fac1, fac2, etc."""
    factor_columns = [
        column for column in df.columns
        if re.fullmatch(r"fac\d+", str(column))
    ]

    dims = sorted({int(str(column)[3:]) for column in factor_columns})

    if not dims:
        raise RuntimeError(f"No fac<n> columns found in {input_file}")

    return dims


def sort_group_values(values: list[str]) -> list[str]:
    """Sort group labels naturally."""
    return sorted(values, key=natural_sort_key)


def generate_boxplot(
        df: pd.DataFrame,
        dim: int,
        group_var: str,
        suffix: str,
        caption: str,
) -> str:
    """Render one TikZ boxplot for one factor dimension."""
    column = f"fac{dim}"

    if column not in df.columns:
        raise ValueError(f"Column not found in dataframe: {column}")

    means = df.groupby(group_var)[column].mean()
    groups = sort_group_values([str(group) for group in means.index.tolist()])
    labels = [latex_escape(str(group)) for group in groups]
    total = len(groups)

    tex = [
        r"\begin{figure}[H]",
        r"\centering",
        r"\hspace*{-.25in}",
        r"\begin{tikzpicture}",
        r"\begin{axis}[",
        r"  boxplot/draw direction=y,",
        r"  enlarge x limits=0.01,",
        r"  every boxplot/.style={draw=black, fill=blue!25},",
        f"  ylabel={{Mean Dim. {dim} Score}},",
        r"  ylabel style={font=\scriptsize},",
        r"  height=0.45\textheight, width=\textwidth,",
        r"  yticklabel style={font=\footnotesize},",
        r"  x tick label style={rotate=60, anchor=east, font=\scriptsize},",
        r"  x=7.5,",
        f"  xtick={{1,...,{total}}},",
        r"  xticklabels={",
        ",\n  ".join(labels),
        r"},",
        r"]",
        f"\\addplot[red, densely dashed] coordinates {{(0.5,0) ({total + 0.5},0)}};",
    ]

    for index, group in enumerate(groups, start=1):
        values = df[df[group_var].astype(str) == str(group)][column].dropna()

        if values.empty:
            continue

        lower_whisker, q1, median, q3, upper_whisker = compute_boxplot_stats(values)

        iqr = q3 - q1
        outliers = values[
            (values < q1 - 1.5 * iqr)
            | (values > q3 + 1.5 * iqr)
        ]

        if not outliers.empty:
            coords = " ".join(f"({index},{value})" for value in sorted(outliers))
            tex.append(
                rf"\addplot+[only marks, mark=*, mark options={{fill=black, mark size=.8pt}}] coordinates {{{coords}}};"
            )

        tex += [
            r"\addplot+[solid, draw=black, fill=blue!25, boxplot prepared={",
            f"  lower whisker={lower_whisker},",
            f"  lower quartile={q1},",
            f"  median={median},",
            f"  upper quartile={q3},",
            f"  upper whisker={upper_whisker}",
            r"}] coordinates {};",
        ]

        tex.append(
            f"\\addplot[only marks, mark=*, draw=red, fill=red, mark size=1.2pt] coordinates {{({index},{values.mean()})}};"
        )

    tex += [
        r"\end{axis}",
        r"\end{tikzpicture}",
        f"\\caption{{{caption}}}",
        f"\\label{{fig:means_f{dim}_{suffix}}}",
        r"\end{figure}",
    ]

    return "\n".join(tex)


def generate_mosaic(
        suffix: str,
        caption: str,
        dims: list[int],
        plots: dict[int, str],
        max_plots: int = 4,
) -> str:
    """
    Build a simple one-row mosaic by reusing rendered boxplot snippets.

    By default, the mosaic includes up to the first four dimensions.
    """
    blocks = []

    for dim in dims[:max_plots]:
        if dim not in plots:
            raise FileNotFoundError(f"Boxplot content not found for mosaic: fac{dim}")

        lines = plots[dim].splitlines()

        start = next(
            index for index, line in enumerate(lines)
            if line.strip().startswith(r"\hspace*")
        )
        end = next(
            index for index, line in enumerate(lines)
            if line.strip() == r"\end{tikzpicture}"
        )

        blocks.append("\n".join(lines[start:end + 1]))

    mosaic = [
        r"\begin{figure}[ht]",
        r"\centering",
    ]

    for block in blocks:
        mosaic += [
            r"\begin{minipage}[t]{0.24\textwidth}",
            r"\centering",
            block,
            r"\end{minipage}\hfill",
        ]

    mosaic += [
        f"\\caption{{{caption}}}",
        rf"\label{{fig:mosaic_{suffix}}}",
        r"\end{figure}",
    ]

    return "\n".join(mosaic)


def validate_output_paths(
        output_paths: dict[str, Path],
        input_paths: set[Path],
) -> dict[str, Path]:
    """Validate distinct output paths and prevent output/input collisions."""
    normalized = {name: Path(os.path.abspath(path)) for name, path in output_paths.items()}
    normalized_inputs = {Path(os.path.abspath(path)) for path in input_paths}

    if len(set(normalized.values())) != len(normalized):
        raise ValueError("Boxplot outputs must use distinct paths")

    for path in normalized.values():
        if path in normalized_inputs:
            raise ValueError(f"Output path would overwrite an input: {path}")

        parent = path.parent
        if parent.exists() and not parent.is_dir():
            raise FileExistsError(f"Output parent is not a directory: {parent}")
        while parent != parent.parent:
            if parent.is_symlink():
                raise ValueError(f"Output parent must not be a symlink: {parent}")
            parent = parent.parent

    return normalized


def existing_outputs_match(
        output_paths: dict[str, Path],
        contents: dict[str, bytes],
) -> bool:
    """Return true for an identical complete output set; reject partial/conflicting files."""
    paths = [(output_paths[name], contents[name], name) for name in output_paths]
    exists = [path.exists() or path.is_symlink() for path, _, _ in paths]

    if any(exists) and not all(exists):
        raise FileExistsError("Boxplot output set is incomplete; existing files were preserved")
    if not any(exists):
        return False

    for path, expected, name in paths:
        if path.is_symlink() or not path.is_file():
            raise FileExistsError(f"Existing output {name} is not a regular file: {path}")
        if path.read_bytes() != expected:
            raise FileExistsError(f"Existing output {name} conflicts with current inputs: {path}")

    return True


def publish_outputs(output_paths: dict[str, Path], contents: dict[str, bytes]) -> None:
    """Stage all output bytes, then publish without replacing existing paths."""
    staged: list[tuple[Path, Path]] = []
    published: list[tuple[Path, Path]] = []

    try:
        for name, destination in output_paths.items():
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
            staged.append((staged_path, destination))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(contents[name])

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
        for staged_path, _ in staged:
            staged_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Generate all group boxplots and the group mosaic."""
    args = parse_args(argv)

    project = args.project
    group_column = args.group_column
    sas_output_dir, output_dir = resolve_paths(args)

    input_file = sas_output_dir / f"{project}_scores_only.tsv"

    if not input_file.exists():
        raise FileNotFoundError(f"Scores-only file not found: {input_file}")

    df, dims = read_scores(input_file, group_column)
    params_group = args.params_group or group_column
    param_files = {
        dim: sas_output_dir / f"params_{params_group}_f{dim}.tsv"
        for dim in dims
    }
    rsquares = {
        dim: read_rsquare(param_files[dim], dim) for dim in dims
    }

    plots: dict[int, str] = {}
    for dim in tqdm(dims, desc="By group"):
        rsquare = rsquares[dim]
        caption = f"Mean Dim. {dim} Scores by Group (R² = {rsquare:.2f}\\%)"

        plots[dim] = generate_boxplot(
            df=df,
            dim=dim,
            group_var=group_column,
            suffix="by_group",
            caption=caption,
        )

    mosaic = generate_mosaic(
        suffix="by_group",
        caption="Mean Dim. Scores by Group",
        dims=dims,
        plots=plots,
    )

    contents = {
        f"boxplot_f{dim}_by_group.tex": plots[dim].encode("utf-8")
        for dim in dims
    }
    contents["mosaic_by_group.tex"] = mosaic.encode("utf-8")
    output_paths = {
        name: output_dir / name for name in contents
    }
    input_paths = {input_file, *param_files.values()}
    output_paths = validate_output_paths(output_paths, input_paths)
    existing = existing_outputs_match(output_paths, contents)

    if args.dry_run:
        action = "Identical outputs verified" if existing else "Validated; outputs can be published"
        print(f"{action}: {len(dims)} factor plots and one mosaic.")
        print(f"Project: {project}")
        print(f"Input file: {input_file}")
        print(f"Parameter directory: {sas_output_dir}")
        print(f"Output directory: {output_dir}")
        return 0

    if existing:
        print(f"Identical plots and mosaic already exist; verified without changes: {output_dir}")
        return 0

    publish_outputs(output_paths, contents)

    print(f"Project: {project}")
    print(f"Input file: {input_file}")
    print(f"Parameter directory: {sas_output_dir}")
    print(f"Output directory: {output_dir}")
    print("All boxplots and mosaics generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())