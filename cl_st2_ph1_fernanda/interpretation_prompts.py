#!/usr/bin/env python3
"""
Generate interpretation prompt files for factor poles.

For each pole, this script assembles a complete prompt containing:
    1. System prompt
    2. User prompt
    3. Mean group scores
    4. Factor loadings
    5. Example excerpts, with their loading words appended

The project name is inferred from the current working directory unless supplied
explicitly with --project.

Default expected inputs:
    factors/f<n>_<pole>.txt
    examples_txt/f<n>_<pole>/*.txt
    examples/score_details.txt
    sas/output_<project>/means_state_f<n>.tsv

Output:
    interpretation/input/f<n>_<pole>.txt
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_PROJECT = Path.cwd().name
DEFAULT_GROUP = "state"
DEFAULT_FACTORS_DIR = Path("factors")
DEFAULT_EXAMPLES_DIR = Path("examples_txt")
DEFAULT_DETAILS_FILE = Path("examples/score_details.txt")
DEFAULT_OUTPUT_DIR = Path("interpretation/input")
DEFAULT_EXCERPT_COUNT = 10
DEFAULT_EXCERPT_LINES = 30


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate LLM interpretation prompts for factor poles."
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
        "--factors-dir",
        default=str(DEFAULT_FACTORS_DIR),
        help="Directory containing factor loading files. Default: factors.",
    )
    parser.add_argument(
        "--examples-dir",
        default=str(DEFAULT_EXAMPLES_DIR),
        help="Directory containing plaintext example files. Default: examples_txt.",
    )
    parser.add_argument(
        "--details-file",
        default=str(DEFAULT_DETAILS_FILE),
        help="Path to score_details.txt. Default: examples/score_details.txt.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for interpretation prompts. Default: interpretation/input.",
    )
    parser.add_argument(
        "--excerpt-count",
        type=int,
        default=DEFAULT_EXCERPT_COUNT,
        help="Maximum number of examples to include per pole.",
    )
    parser.add_argument(
        "--excerpt-lines",
        type=int,
        default=DEFAULT_EXCERPT_LINES,
        help="Maximum number of lines to include from each example file.",
    )

    return parser.parse_args()


def normalize_group(group: str) -> str:
    """Normalize group name for filenames, headings, and table lookup."""
    normalized = str(group).strip().lower()

    if not normalized:
        raise ValueError("--group must not be empty")

    if not re.fullmatch(r"[a-zA-Z0-9_]+", normalized):
        raise ValueError(
            "--group may contain only letters, numbers, and underscores"
        )

    return normalized


def resolve_sas_output_dir(project: str, sas_output_dir_arg: str | None) -> Path:
    """Resolve the SAS output directory."""
    if sas_output_dir_arg is None:
        return Path("sas") / f"output_{project}"

    return Path(sas_output_dir_arg)


# ============================================================
# PROMPT TEXT
# ============================================================

def group_description(group: str) -> str:
    """Return a readable group description."""
    if group == "state":
        return "Brazilian state"

    return group.replace("_", " ")


def phase_description(project: str, group: str) -> str:
    """Return a project-specific corpus description."""
    group_label = group_description(group)

    return (
        "This phase analyses a corpus of Brazilian educational curriculum and "
        "guideline excerpts. The texts have been denoised, tagged, transformed "
        "into lexical variables, and analysed with Lexical Multi-Dimensional "
        f"Analysis. The corpus is organised by {group_label} strata."
    )


def build_system_prompt(project: str, group: str) -> str:
    """Build the system prompt."""
    group_label = group_description(group)

    return f"""You are a corpus linguist specialising in Lexical Multi-Dimensional Analysis (LMDA).
Your task is to interpret a single factor pole as a discourse dimension.

{phase_description(project, group)}

The analysis is applied to {group_label}-based strata. The mean-score table shows
how strongly each {group_label} scores on the relevant factor.

Your interpretation must identify the discourses encoded at this pole, taking into account:
• lexical loadings, which represent the full analysed corpus;
• example excerpts, which illustrate high-scoring texts at this pole;
• the {group_label}s that score most strongly at this pole;
• the loading words that appear in the examples.

Do not interpret isolated examples as if they represented the entire corpus.
Use the examples to illustrate and qualify the broader pattern shown by the loadings
and by the group mean scores.
"""


USER_PROMPT = """Interpret Factor {factor} ({polarity}) as a discourse dimension.
Propose possible labels for this pole only and justify them.

Base your interpretation on:
• Mean {group_label} scores. For positive poles, consider the highest-scoring {group_label}s in the table. For negative poles, consider the lowest-scoring {group_label}s; these may be the lowest positive scores or the most negative scores if there are any.
• Factor loadings.
• Example excerpts from high-scoring texts.
• The loading words that appear in these examples.
• Which {group_label}s appear to drive this pole.
• Regional or group-level tendencies suggested by the mean scores.

Do not offer a "versus" interpretation of the opposite pole.
Focus on this single pole only.

Give equal weight to the loadings and the examples. Remember that loadings represent
the full analysed corpus, whereas the excerpts are only a limited set of high-scoring
samples.

When proposing labels, prefer concise discourse-functional labels rather than merely
listing frequent words.
"""


# ============================================================
# LOAD SCORE DETAILS
# ============================================================

def load_score_details(details_path: Path) -> dict[str, dict[str, dict[str, list[str]]]]:
    """
    Parse score_details.txt into:
        score_details[text_id][factor]["pos" or "neg"] = list_of_words
    """
    if not details_path.exists():
        raise FileNotFoundError(f"Score details file not found: {details_path}")

    score_details: dict[str, dict[str, dict[str, list[str]]]] = {}
    current_id = None
    current_factor = None

    with details_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            match_id = re.match(r"text ID:\s*(.+)", line)
            if match_id:
                current_id = match_id.group(1).strip()
                score_details[current_id] = {}
                current_factor = None
                continue

            match_factor = re.match(r"(f\d+)\s+score:", line)
            if match_factor and current_id:
                current_factor = match_factor.group(1)
                score_details[current_id][current_factor] = {
                    "pos": [],
                    "neg": [],
                }
                continue

            match_words = re.match(r"f\d+\s+(pos|neg)\s+words.*:\s*(.*)", line)
            if match_words and current_id and current_factor:
                pole = match_words.group(1)
                words_string = match_words.group(2).strip()
                words = [
                    word.strip()
                    for word in words_string.split(",")
                    if word.strip()
                ]
                score_details[current_id][current_factor][pole] = words

    return score_details


# ============================================================
# EXCERPT EXTRACTOR
# ============================================================

def extract_excerpt(file_path: Path, n_lines: int) -> str:
    """Extract the first n_lines from an example text file."""
    lines = []

    with file_path.open("r", encoding="utf-8") as f:
        for _ in range(n_lines):
            line = f.readline()

            if not line:
                break

            lines.append(line.rstrip("\n"))

    return "\n".join(lines)


def detect_text_id(text: str) -> str | None:
    """Detect the text ID from an example file."""
    match = re.search(r"^Text ID:\s*(.+?)\s*$", text, flags=re.MULTILINE)

    if match:
        return match.group(1).strip()

    legacy_match = re.search(r"(t\d{6})", text)

    if legacy_match:
        return legacy_match.group(1)

    return None


def natural_sort_key(path: Path) -> list[int | str]:
    """Return a natural-sort key for paths."""
    parts = re.split(r"(\d+)", path.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def factor_sort_key(path: Path) -> list[int | str]:
    """Return a natural-sort key for factor pole files."""
    parts = re.split(r"(\d+)", path.stem)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """Build all interpretation prompt files."""
    args = parse_args()

    project = args.project
    group = normalize_group(args.group)
    group_label = group_description(group)

    sas_output_dir = resolve_sas_output_dir(project, args.sas_output_dir)
    factors_dir = Path(args.factors_dir)
    examples_dir = Path(args.examples_dir)
    details_file = Path(args.details_file)
    output_dir = Path(args.output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    if not factors_dir.exists():
        raise FileNotFoundError(f"Factors directory not found: {factors_dir}")

    if not examples_dir.exists():
        raise FileNotFoundError(f"Examples directory not found: {examples_dir}")

    if not sas_output_dir.exists():
        raise FileNotFoundError(f"SAS output directory not found: {sas_output_dir}")

    score_details = load_score_details(details_file)

    factor_files = sorted(
        factors_dir.glob("f*_*.txt"),
        key=factor_sort_key,
    )

    factor_files = [
        path for path in factor_files
        if re.fullmatch(r"f\d+_(pos|neg)", path.stem)
    ]

    if not factor_files:
        raise FileNotFoundError(f"No factor pole files found in {factors_dir}")

    system_prompt = build_system_prompt(project, group)

    for factor_file in factor_files:
        factor_name = factor_file.stem

        parts = factor_name.split("_")
        if len(parts) != 2:
            print(f"Warning: skipping unexpected factor filename: {factor_file}")
            continue

        factor = parts[0]
        polarity = parts[1]

        if polarity not in {"pos", "neg"}:
            print(f"Warning: skipping unexpected polarity in: {factor_file}")
            continue

        factor_number = factor.replace("f", "")

        loadings_text = factor_file.read_text(encoding="utf-8").strip()

        means_file = sas_output_dir / f"means_{group}_f{factor_number}.tsv"

        if not means_file.exists():
            print(f"Warning: missing means file {means_file}")
            means_text = "(No means file found)"
        else:
            means_text = means_file.read_text(encoding="utf-8").strip()

        example_folder = examples_dir / factor_name

        if not example_folder.exists():
            print(f"Warning: missing example folder {example_folder}")
            example_files = []
        else:
            example_files = sorted(
                example_folder.glob("*.txt"),
                key=natural_sort_key,
            )[:args.excerpt_count]

        excerpts_block = []

        for example_path in example_files:
            excerpt = extract_excerpt(example_path, args.excerpt_lines)
            file_text = example_path.read_text(encoding="utf-8")

            text_id = detect_text_id(file_text)

            if not text_id:
                print(f"Warning: no text ID found in {example_path}")
                continue

            loading_words = (
                score_details
                .get(text_id, {})
                .get(factor, {})
                .get(polarity, [])
            )

            loading_words_string = (
                ", ".join(loading_words)
                if loading_words
                else "(none)"
            )

            excerpt_block = (
                f"\n===== EXCERPT: {example_path.name} "
                f"(text ID {text_id}) =====\n"
                f"{excerpt}\n"
                f"\n--- Loading words for this example ({polarity}): "
                f"{loading_words_string}\n"
            )

            excerpts_block.append(excerpt_block)

        user_prompt = USER_PROMPT.format(
            factor=factor,
            polarity=polarity,
            group_label=group_label,
        )

        mean_section = (
            f"\n=== MEAN {group.upper()} SCORES ===\n"
            f"{means_text}\n"
        )
        loadings_section = (
            f"\n=== FACTOR LOADINGS ({factor_name}) ===\n"
            f"{loadings_text}\n"
        )

        final_prompt = (
                system_prompt
                + "\n\n"
                + user_prompt
                + "\n"
                + mean_section
                + loadings_section
                + "\n=== EXAMPLE EXCERPTS ===\n"
                + "\n".join(excerpts_block)
        )

        output_path = output_dir / f"{factor_name}.txt"
        output_path.write_text(final_prompt, encoding="utf-8")

        print("Wrote:", output_path)

    print(f"\nProject: {project}")
    print(f"Group: {group}")
    print(f"SAS output directory: {sas_output_dir}")
    print(f"Interpretation prompts written to: {output_dir}")


if __name__ == "__main__":
    main()