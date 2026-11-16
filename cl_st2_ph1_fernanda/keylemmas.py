#!/usr/bin/env python3
"""
python keylemmas.py \
    --input corpus/07_tagged \
    --output corpus/08_keylemmas \
    --cutoff 3

cutoff = minimum percent presence requirement.
"""

import os
import math
import argparse
from collections import defaultdict

# POS tags to keep: nouns, main verbs, and adjectives.
#
VALID_TAG_PREFIXES = (
    "NOUN",
#    "PROPN",
    "VERB",
    "ADJ",
#    "ADV",
)

# stopwords (lowercase)
STOPWORDS = {
    "ii",
    "iii",
    "iv",
    "nº",
    "xvi",
    "xxi",
    "acima",
    "acre",
    "ademais",
    "adiante",
    "alagoas",
    "alemanha",
    "aliás",
    "amapá",
    "amazonas",
    "ana",
    "amplamente",
    "anderson",
    "aqui",
    "arnau",
    "art",
    "através",
    "autonomamente",
    "bahia",
    "bastante",
    "bloom",
    "bolivia",
    "bordieu",
    "brasil",
    "bruner",
    "catarina",
    "ceará",
    "chs",
    "chsa",
    "cnt",
    "colocá",
    "concomitantemente",
    "contudo",
    "dantas",
    "dayrell",
    "delizoicov",
    "dewey",
    "df",
    "es",
    "et",
    "fevereiro",
    "fochi",
    "freire",
    "frequentemente",
    "go",
    "goiás",
    "graciliano",
    "gramsci",
    "guiana",
    "hoje",
    "ibid",
    "implementá",
    "incentivá",
    "inglaterra",
    "janeiro",
    "josé",
    "joao",
    "julho",
    "logo",
    "lopes",
    "kishimoto",
    "krathwohl",
    "macedo",
    "maceió",
    "manoel",
    "manaus",
    "marajó",
    "maranhão",
    "milton",
    "moran",
    "morin",
    "ms",
    "muito",
    "neira",
    "normalmente",
    "notadamente",
    "novembro",
    "obrigatoriamente",
    "obstante",
    "obviamente",
    "of",
    "ora",
    "os",
    "outrora",
    "outrossim",
    "paraguai",
    "paraná",
    "paraíba",
    "pará",
    "paulo",
    "pedro",
    "pee",
    "pernambuco",
    "piauí",
    "porém",
    "progressivamente",
    "pv",
    "que",
    "ramos",
    "rca",
    "recentemente",
    "rj",
    "rs",
    "saviani",
    "sc",
    "santana",
    "sergipe",
    "sigla",
    "sucessivamente",
    "talvez",
    "teresina",
    "to",
    "tocantins",
    "um",
    "uma",
    "usá",
    "venezuela",
    "vigotski",
    "wallon",
    "zabala",
    "caput",
    "santo",
    "xi",
}


def ll(a, b, c, d):
    """Log-likelihood function."""
    if a == 0 or b == 0:
        return 0.0
    E1 = c * (a + b) / (c + d)
    E2 = d * (a + b) / (c + d)
    return 2 * ((a * math.log(a / E1)) + (b * math.log(b / E2)))


def is_corpus_folder(path):
    """Return True if path is a corpus group folder."""
    name = os.path.basename(path)
    return (
            os.path.isdir(path)
            and not name.startswith("_")
            and not name.startswith(".")
    )


def load_lemma_presence(base_dir, *, label_prefix=""):
    """
    Load lemma presence for one subcorpus folder.

    Return:
        lemma -> set(text labels)
        set(text labels)
    """
    presence = defaultdict(set)
    all_texts = set()

    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith("_") and not d.startswith(".")
        ]

        for filename in files:
            if not filename.endswith(".txt"):
                continue

            rel = os.path.relpath(os.path.join(root, filename), base_dir)
            text_label = os.path.join(label_prefix, rel) if label_prefix else rel
            all_texts.add(text_label)
            seen = set()

            with open(os.path.join(root, filename), "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) < 3:
                        continue

                    word, tag, lemma = parts[:3]

                    if not tag.startswith(VALID_TAG_PREFIXES):
                        continue

                    lemma = lemma.strip()
                    if lemma == "<unknown>" or not lemma:
                        lemma = word.strip()

                    lemma_lc = lemma.lower()

                    if sum(1 for ch in lemma_lc if ch.isalpha()) < 2:
                        continue

                    if lemma_lc in STOPWORDS:
                        continue

                    if lemma_lc not in seen:
                        presence[lemma_lc].add(text_label)
                        seen.add(lemma_lc)

    return presence, all_texts


def save_keywords(path, rows):
    header = (
        "lemma target_count comparison_count target_per_1k "
        "comparison_per_1k expected LL %DIFF status"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for r in rows:
            f.write(" ".join(map(str, r)) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Compute key lemmas.")
    parser.add_argument(
        "--input",
        default="corpus/07_tagged",
        help="Directory containing subcorpus folders",
    )
    parser.add_argument(
        "--output",
        default="corpus/08_keylemmas",
        help="Output directory for key lemma lists",
    )
    parser.add_argument(
        "--cutoff",
        default=3.0,
        type=float,
        help="Minimum % presence in target texts",
    )

    args = parser.parse_args()

    base_dir = args.input
    output_dir = args.output
    cutoff_percent = args.cutoff

    os.makedirs(output_dir, exist_ok=True)

    folders = sorted([
        d for d in os.listdir(base_dir)
        if is_corpus_folder(os.path.join(base_dir, d))
    ])

    if not folders:
        print(f"No corpus folders found under {base_dir}. Exiting.")
        return

    print("Corpus folders to process:")
    for folder in folders:
        print(f"  - {folder}")
    print()

    global_presence = defaultdict(set)
    global_texts = set()

    for folder in folders:
        subdir = os.path.join(base_dir, folder)
        p, t = load_lemma_presence(subdir, label_prefix=folder)

        for lemma, texts in p.items():
            global_presence[lemma] |= texts

        global_texts |= t

    pr = {"POSKW": 0, "NEGKW": 1, "NOTKW": 2}

    for folder in folders:
        print(f"Processing {folder}...")

        target_dir = os.path.join(base_dir, folder)

        target_presence, target_texts = load_lemma_presence(
            target_dir,
            label_prefix=folder,
        )
        comparison_texts = global_texts - target_texts

        comp_presence = defaultdict(set)
        for lemma, texts in global_presence.items():
            comp_presence[lemma] = texts & comparison_texts

        size_target = len(target_texts)
        size_comp = len(comparison_texts)
        total = size_target + size_comp
        cutoff_texts = size_target * cutoff_percent / 100

        all_lemmas = set(global_presence.keys())
        rows = []

        for lemma in all_lemmas:
            a = len(target_presence.get(lemma, []))
            b = len(comp_presence.get(lemma, []))

            if size_target == 0 or a < cutoff_texts:
                continue

            perA = (a / size_target) * 1000
            perB = (b / size_comp) * 1000 if size_comp else 0.0
            expected = (size_target * (a + b)) / total if total else 0.0
            LLv = ll(a, b, size_target, size_comp)

            if (perA + perB) == 0:
                diff = 0.0
            else:
                diff = 100 * (perA - perB) / ((perA + perB) / 2)

            status = (
                "POSKW" if LLv >= 3.84 and diff > 0 else
                "NEGKW" if LLv >= 3.84 else
                "NOTKW"
            )

            rows.append((
                lemma,
                a,
                b,
                round(perA, 2),
                round(perB, 2),
                round(expected, 2),
                round(LLv, 2),
                round(diff, 2),
                status,
            ))

        rows.sort(key=lambda r: (pr[r[8]], -r[6]))

        outpath = os.path.join(output_dir, f"{folder}.txt")
        save_keywords(outpath, rows)

        print(f"Saved {outpath} ({size_target} texts vs {size_comp} texts)")


if __name__ == "__main__":
    main()