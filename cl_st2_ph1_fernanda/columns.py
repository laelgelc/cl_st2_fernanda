#!/usr/bin/env python3
"""
Create binary keyword-presence columns for the tagged corpus.

Input:
    corpus/09_kw_selected/keywords.txt
    corpus/07_tagged/<state>/<text_id>.txt

Expected state folder format:
    ac
    al
    am
    ...
    sp
    to

Outputs:
    columns/<Keyword ID>.txt
        Full column files with file ID, state, and binary keyword presence.

    columns_clean/<Keyword ID>.txt
        Clean binary columns for downstream analysis.

    file_ids.txt
        Mapping from generated text IDs to tagged corpus files.

    index_keywords.txt
        Mapping from keyword IDs to lemmas.
"""

import re
from pathlib import Path


# === Configuration ===
KEYWORD_FILE = Path("corpus/09_kw_selected/keywords.txt")
TAGGED_BASE = Path("corpus/07_tagged")
OUTPUT_DIR = Path("columns")
CLEAN_DIR = Path("columns_clean")
INDEX_FILE = Path("index_keywords.txt")
FILE_IDS = Path("file_ids.txt")

STATE_RE = re.compile(r"^[a-z]{2}$")


def natural_sort_key(text):
    """Return a natural-sort key that treats digit runs as integers."""
    parts = re.split(r"(\d+)", str(text))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def normalise_lemma(lemma):
    """Normalise lemmas consistently with the keyword-selection stage."""
    return lemma.strip().lower()


def is_corpus_state_folder(path):
    """Return True if path is a valid state-level corpus folder."""
    return (
            path.is_dir()
            and STATE_RE.match(path.name)
            and not path.name.startswith("_")
            and not path.name.startswith(".")
    )


def load_keywords(path):
    """Load the consolidated keyword list."""
    if not path.exists():
        raise FileNotFoundError(f"Keyword file does not exist: {path}")

    lemmas = [
        normalise_lemma(keyword)
        for keyword in path.read_text(encoding="utf-8").splitlines()
        if keyword.strip()
    ]

    return sorted(set(lemmas), key=natural_sort_key)


def collect_tagged_texts(tagged_base):
    """Collect tagged text files from state folders."""
    if not tagged_base.exists():
        raise FileNotFoundError(f"Tagged corpus directory does not exist: {tagged_base}")

    if not tagged_base.is_dir():
        raise NotADirectoryError(f"Tagged corpus path is not a directory: {tagged_base}")

    text_paths = []

    state_folders = sorted(
        [
            folder for folder in tagged_base.iterdir()
            if is_corpus_state_folder(folder)
        ],
        key=lambda path: natural_sort_key(path.name),
    )

    if not state_folders:
        raise FileNotFoundError(
            f"No state folders found under {tagged_base}. "
            "Expected folders such as ac, es, mg, sp, etc."
        )

    for folder in state_folders:
        for text_file in sorted(
                folder.rglob("*.txt"),
                key=lambda path: natural_sort_key(path.as_posix()),
        ):
            text_paths.append(text_file)

    if not text_paths:
        raise FileNotFoundError(f"No tagged .txt files found under {tagged_base}")

    return text_paths


def read_present_lemmas(text_file):
    """Read lemmas from the third column of a TreeTagger output file."""
    present = set()

    with text_file.open("r", encoding="utf-8") as tf:
        for line in tf:
            parts = line.rstrip("\n").split("\t")

            if len(parts) < 3:
                parts = line.strip().split()

            if len(parts) >= 3:
                lemma = normalise_lemma(parts[2])
                if lemma and lemma != "<unknown>":
                    present.add(lemma)

    return present


def main():
    # === Step 1: Load consolidated keywords ===
    lemmas = load_keywords(KEYWORD_FILE)

    if not lemmas:
        raise ValueError(f"No keywords found in {KEYWORD_FILE}")

    # === Step 2: Create index map for unique lemmas ===
    lemma_index = {
        lemma: f"{i + 1:06d}"
        for i, lemma in enumerate(lemmas)
    }

    # === Step 3: Collect all tagged text files ===
    text_paths = collect_tagged_texts(TAGGED_BASE)

    # === Step 4: Assign file IDs ===
    file_id_map = {}

    with FILE_IDS.open("w", encoding="utf-8") as fidx:
        for i, text_file in enumerate(text_paths, 1):
            file_id = f"t{i:06d}"
            file_id_map[text_file] = file_id

            rel = text_file.relative_to(TAGGED_BASE).as_posix()

            fidx.write(f"{file_id} {rel}\n")

    # === Step 5: Read each text and record lemma presence ===
    text_infos = []

    for text_file in text_paths:
        file_id = file_id_map[text_file]
        rel_parts = text_file.relative_to(TAGGED_BASE).parts
        state = rel_parts[0]

        present = read_present_lemmas(text_file)

        text_infos.append(
            {
                "id": file_id,
                "state": state,
                "lemmas": present,
            }
        )

    # === Step 6: Write one column file per lemma ===
    OUTPUT_DIR.mkdir(exist_ok=True)

    for lemma in lemmas:
        lemma_id = lemma_index[lemma]
        outpath = OUTPUT_DIR / f"{lemma_id}.txt"

        with outpath.open("w", encoding="utf-8") as outf:
            for info in text_infos:
                has_keyword = 1 if lemma in info["lemmas"] else 0
                outf.write(
                    f"{info['id']} "
                    f"{info['state']} "
                    f"{has_keyword}\n"
                )

    # === Step 7: Save lemma index ===
    with INDEX_FILE.open("w", encoding="utf-8") as idxf:
        for lemma in lemmas:
            idxf.write(f"{lemma_index[lemma]} {lemma}\n")

    # === Step 8: Produce clean binary column files ===
    CLEAN_DIR.mkdir(exist_ok=True)

    for lemma in lemmas:
        lemma_id = lemma_index[lemma]
        src = OUTPUT_DIR / f"{lemma_id}.txt"
        dst = CLEAN_DIR / f"{lemma_id}.txt"

        lines = src.read_text(encoding="utf-8").splitlines()

        with dst.open("w", encoding="utf-8") as fout:
            fout.write(f"{lemma_id}\n")

            for line in lines:
                parts = line.split()
                if parts:
                    fout.write(f"{parts[-1]}\n")

    print("Processing complete.")
    print(f"→ Keywords loaded: {len(lemmas)}")
    print(f"→ Tagged texts processed: {len(text_infos)}")
    print("→ Columns in 'columns/'")
    print("→ Clean binary columns in 'columns_clean/'")
    print("→ File IDs saved to 'file_ids.txt'")
    print("→ Keyword index saved to 'index_keywords.txt'")


if __name__ == "__main__":
    main()