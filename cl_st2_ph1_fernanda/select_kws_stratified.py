#!/usr/bin/env python3
"""
select_kws_stratified.py

Selects a balanced, stratum-based subset of positive keywords (POSKW)
from key-lemma tables produced by keylemmas.py.

In this project, the strata are usually Brazilian state codes, such as:

    ac
    al
    am
    ...
    sp
    to

What it does
------------
1) Reads every stratum key-lemma file in corpus/08_keylemmas/.
   Supported extensions: .txt and .tsv.

2) Extracts lemmas whose final column is POSKW, applying lexical filters:
   - keep alphabetic lemmas and valid hyphenated compounds;
   - allow Unicode alphabetic characters, including accented letters;
   - allow hyphens only internally, between alphabetic parts;
   - drop lemmas containing digits;
   - drop lemmas containing uppercase letters;
   - drop lemmas containing punctuation other than valid internal hyphens.

3) Applies the same quota to every stratum:
   - each stratum: at most --per-group lemmas.

4) Builds a consolidated list in deterministic stratum order.

5) Optionally truncates the consolidated list to --max-total before
   de-duplication.

6) Writes outputs to corpus/09_kw_selected/:
   - one file per stratum: <stratum>.txt
   - one consolidated, de-duplicated list: keywords.txt

Typical usage
-------------
python select_kws_stratified.py \
    --input corpus/08_keylemmas \
    --output corpus/09_kw_selected \
    --per-group 50 \
    --max-total 20000
"""

import argparse
import glob
import os
import re


INPUT_DIR = "corpus/08_keylemmas"
OUTPUT_DIR = "corpus/09_kw_selected"

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
    Return True if name looks like a corpus stratum.

    This accepts state-code files such as ac.txt, sp.txt, etc.,
    and also remains permissive enough for longer future strata.
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


def discover_keylemma_files(input_dir):
    """Return stratum-named key-lemma files from the input directory."""
    if not os.path.isdir(input_dir):
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    files = []

    for extension in SUPPORTED_EXTENSIONS:
        files.extend(glob.glob(os.path.join(input_dir, f"*{extension}")))

    stratum_files = {}

    for filepath in files:
        stem = os.path.splitext(os.path.basename(filepath))[0]

        if not is_valid_stratum_name(stem):
            continue

        existing = stratum_files.get(stem)

        # Prefer .tsv if both .tsv and .txt exist for the same stratum.
        if existing is None:
            stratum_files[stem] = filepath
        elif filepath.endswith(".tsv") and existing.endswith(".txt"):
            stratum_files[stem] = filepath

    if not stratum_files:
        raise FileNotFoundError(
            f"No stratum key-lemma files found in {input_dir}. "
            "Expected files such as ac.txt, es.txt, sp.txt, etc."
        )

    return [
        (stratum, stratum_files[stratum])
        for stratum in sorted(stratum_files, key=natural_sort_key)
    ]


def load_poskw(filepath):
    """
    Load POSKW lemmas from a key-lemma file.

    The file may be tab-separated or whitespace-separated.
    The first column is assumed to be the lemma.
    The final column is assumed to be the status.
    """
    lemmas = []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        return lemmas

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

        if status != "POSKW":
            continue

        if not is_clean_lemma(lemma):
            continue

        lemmas.append(lemma)

    return lemmas


def write_word_list(path, words):
    """Write one word per line."""
    with open(path, "w", encoding="utf-8") as fout:
        for word in words:
            fout.write(word + "\n")


# -----------------------------------------------------------
# Main
# -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Select balanced POSKW keyword lists across corpus strata."
    )
    parser.add_argument(
        "--input",
        "--input-dir",
        dest="input",
        default=INPUT_DIR,
        help="Input directory containing stratum key-lemma files.",
    )
    parser.add_argument(
        "--output",
        "--output-dir",
        dest="output",
        default=OUTPUT_DIR,
        help="Output directory for selected keyword lists.",
    )
    parser.add_argument(
        "--per-group",
        type=int,
        required=True,
        help="Maximum number of POSKW lemmas to select from each stratum.",
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

    args = parser.parse_args()

    if args.per_group <= 0:
        raise ValueError("--per-group must be greater than 0")

    if args.max_total < 0:
        raise ValueError("--max-total must be non-negative")

    os.makedirs(args.output, exist_ok=True)

    keylemma_files = discover_keylemma_files(args.input)

    strata = {}

    for stratum, filepath in keylemma_files:
        strata[stratum] = load_poskw(filepath)

    print("=== Stratum Keyword Quotas ===")
    for stratum in sorted(strata, key=natural_sort_key):
        print(f"{stratum:<22} → {args.per_group} keywords max")
    print("==============================\n")

    selected_by_stratum = {}

    for stratum in sorted(strata, key=natural_sort_key):
        lemmas = strata[stratum]
        chosen = lemmas[:args.per_group]
        selected_by_stratum[stratum] = chosen

        print(
            f"{stratum:<22} → selected {len(chosen)}/{args.per_group} "
            f"from {len(lemmas)} available POSKW lemmas"
        )

    consolidated = []

    for stratum in sorted(selected_by_stratum, key=natural_sort_key):
        consolidated.extend(selected_by_stratum[stratum])

    if args.max_total and len(consolidated) > args.max_total:
        consolidated = consolidated[:args.max_total]

    unique_lemmas = sorted(set(consolidated))

    total_count = len(consolidated)
    unique_count = len(unique_lemmas)

    print(f"\nTotal consolidated keywords before de-duplication: {total_count}")
    print(f"Unique keywords after de-duplication: {unique_count}")
    print(f"Duplicates removed: {total_count - unique_count}")

    for stratum, words in selected_by_stratum.items():
        outpath = os.path.join(args.output, f"{stratum}.txt")
        write_word_list(outpath, words)

    cons_path = os.path.join(args.output, "keywords.txt")
    write_word_list(cons_path, unique_lemmas)

    print(f"\nFinal unique keywords written to: {cons_path}")
    print(f"Final unique keyword count: {len(unique_lemmas)}")


if __name__ == "__main__":
    main()