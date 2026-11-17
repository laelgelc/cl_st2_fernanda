#!/usr/bin/env python3
from pathlib import Path


# Paths
INDEX_FILE = Path("index_keywords.txt")
OUT_DIR = Path("sas")


def sas_escape(text: str) -> str:
    """Escape double quotes inside SAS quoted strings."""
    return text.replace('"', '""')


def load_keyword_index(index_file: Path) -> list[tuple[str, str]]:
    """
    Read index_keywords.txt.

    Expected format:
        000001 act
        000002 ai
        000003 air

    No header; space-separated; columns = keyword_id lemma.
    """
    if not index_file.exists():
        raise FileNotFoundError(f"Keyword index file not found: {index_file}")

    items = []

    with index_file.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            parts = line.split(maxsplit=1)

            if len(parts) != 2:
                raise ValueError(
                    f"Unexpected format in {index_file} at line {line_number}: "
                    "expected keyword_id and lemma"
                )

            keyword_id, lemma = parts

            if line_number == 1 and keyword_id.lower() in {"keyword_id", "id"}:
                raise ValueError(
                    f"{index_file} appears to contain a header. "
                    "Expected a headerless file."
                )

            if not keyword_id.isdigit():
                raise ValueError(
                    f"Invalid keyword ID in {index_file} at line {line_number}: "
                    f"{keyword_id}"
                )

            varname = f"v{keyword_id}"
            items.append((varname, sas_escape(lemma)))

    if not items:
        raise ValueError(f"No keyword entries found in {index_file}")

    return items


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    items = load_keyword_index(INDEX_FILE)

    # Full format with keyword and ID.
    with (OUT_DIR / "word_labels_full_format.sas").open("w", encoding="utf-8") as f:
        f.write("PROC FORMAT library=work ;\n")
        f.write("  VALUE  $lexlabelsfull\n")

        for varname, word in items:
            f.write(f'"{varname}" = "{word} ({varname})"\n')

        f.write(";\nrun;\nquit;\n")

    # Short format with just keyword.
    with (OUT_DIR / "word_labels_format.sas").open("w", encoding="utf-8") as f:
        f.write("PROC FORMAT library=work ;\n")
        f.write("  VALUE  $lexlabels\n")

        for varname, word in items:
            f.write(f'"{varname}" = "{word}"\n')

        f.write(";\nrun;\nquit;\n")

    print(f"SAS format files written to {OUT_DIR}")
    print(f"Keyword labels written: {len(items)}")


if __name__ == "__main__":
    main()