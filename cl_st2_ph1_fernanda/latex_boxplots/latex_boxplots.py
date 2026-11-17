#!/usr/bin/env python3
"""
Generate TikZ boxplots in LaTeX for factor dimensions by group.

This script is expected to be located in:

    latex_boxplots/latex_boxplots.py

Default input, resolved relative to the project directory:

    ../sas/output_<project>/<project>_scores_only.tsv
    ../sas/output_<project>/params_group_f<n>.tsv

where <project> is inferred from the parent directory name, for example:

    cl_st1_ph2_anna
    cl_st1_ph3_anna

Default output:

    latex_boxplots/slides/boxplot_f<dim>_by_group.tex
    latex_boxplots/slides/mosaic_by_group.tex

Typical usage from inside latex_boxplots/:

    python latex_boxplots.py

Typical usage from the project root:

    python latex_boxplots/latex_boxplots.py

Optional explicit usage:

    python latex_boxplots.py \
        --project cl_st1_ph3_anna \
        --sas-output-dir ../sas/output_cl_st1_ph3_anna \
        --output-dir slides
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_PROJECT = PROJECT_DIR.name
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "slides"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate LaTeX/TikZ factor-score boxplots by group."
    )

    parser.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=(
            "Project name, e.g. cl_st1_ph2_anna or cl_st1_ph3_anna. "
            "Default: inferred from the parent directory name."
        ),
    )
    parser.add_argument(
        "--sas-output-dir",
        default=None,
        help=(
            "Directory containing SAS outputs. "
            "Default: ../sas/output_<project>, resolved relative to this script."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory where LaTeX boxplot files will be written. "
            "Default: latex_boxplots/slides."
        ),
    )
    parser.add_argument(
        "--group-column",
        default="state",
        help=(
            "Column in the scores-only TSV used for grouping. "
            "Default: state."
        ),
    )

    return parser.parse_args()


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    """Resolve input and output directories."""
    if args.sas_output_dir is None:
        sas_output_dir = PROJECT_DIR / "sas" / f"output_{args.project}"
    else:
        sas_output_dir = Path(args.sas_output_dir)

        if not sas_output_dir.is_absolute():
            sas_output_dir = (Path.cwd() / sas_output_dir).resolve()

    if args.output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR
    else:
        output_dir = Path(args.output_dir)

        if not output_dir.is_absolute():
            output_dir = (Path.cwd() / output_dir).resolve()

    return sas_output_dir, output_dir


def read_rsquare(param_file: Path) -> float:
    """
    Return R² (%) from a params TSV file containing a column named RSquare.

    If the file is missing, empty, or unreadable, return 0.0.
    """
    try:
        with param_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        return float(rows[0]["RSquare"]) * 100.0 if rows else 0.0

    except FileNotFoundError:
        return 0.0
    except Exception:
        return 0.0


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
        output_dir: Path,
) -> None:
    """Generate one TikZ boxplot file for one factor dimension."""
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

    output_path = output_dir / f"boxplot_f{dim}_{suffix}.tex"
    output_path.write_text("\n".join(tex), encoding="utf-8")


def generate_mosaic(
        suffix: str,
        caption: str,
        dims: list[int],
        output_dir: Path,
        max_plots: int = 4,
) -> None:
    """
    Build a simple one-row mosaic by reusing already-written boxplot tex files.

    By default, the mosaic includes up to the first four dimensions.
    """
    blocks = []

    for dim in dims[:max_plots]:
        path = output_dir / f"boxplot_f{dim}_{suffix}.tex"

        if not path.exists():
            raise FileNotFoundError(f"Boxplot file not found for mosaic: {path}")

        lines = path.read_text(encoding="utf-8").splitlines()

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

    output_path = output_dir / f"mosaic_{suffix}.tex"
    output_path.write_text("\n".join(mosaic), encoding="utf-8")


def main() -> None:
    """Generate all group boxplots and the group mosaic."""
    args = parse_args()

    project = args.project
    group_column = args.group_column
    sas_output_dir, output_dir = resolve_paths(args)
    output_dir.mkdir(exist_ok=True, parents=True)

    input_file = sas_output_dir / f"{project}_scores_only.tsv"

    if not input_file.exists():
        raise FileNotFoundError(f"Scores-only file not found: {input_file}")

    df = pd.read_csv(input_file, sep="\t")

    if group_column not in df.columns:
        raise ValueError(f"Column '{group_column}' not found in {input_file}")

    df[group_column] = df[group_column].astype(str).str.strip()

    dims = detect_dims(df, input_file)

    for dim in tqdm(dims, desc="By group"):
        rsquare = read_rsquare(sas_output_dir / f"params_group_f{dim}.tsv")
        caption = f"Mean Dim. {dim} Scores by Group (R² = {rsquare:.2f}\\%)"

        generate_boxplot(
            df=df,
            dim=dim,
            group_var=group_column,
            suffix="by_group",
            caption=caption,
            output_dir=output_dir,
        )

    generate_mosaic(
        suffix="by_group",
        caption="Mean Dim. Scores by Group",
        dims=dims,
        output_dir=output_dir,
    )

    print(f"Project: {project}")
    print(f"Input file: {input_file}")
    print(f"Parameter directory: {sas_output_dir}")
    print(f"Output directory: {output_dir.resolve()}")
    print("All boxplots and mosaics generated.")


if __name__ == "__main__":
    main()