#!/usr/bin/env python3
"""Calculate corpus size for the tagged ENADE corpus."""

import argparse
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import columns


# --- Configuration ---
PHASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = Path("corpus_size/corpus_size.tsv")


def natural_sort_key(text):
    """Return a natural-sort key that treats digit runs as integers."""
    parts = re.split(r"(\d+)", str(text))
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def is_countable_token(word: str, tag: str) -> bool:
    """
    Return True if a tagged line should count as a word/token.

    Punctuation, symbols, and numeric-only tokens are excluded.
    Unicode alphabetic words, including accented Portuguese words, are included.
    """
    if not word:
        return False

    if not word[0].isalpha():
        return False

    if tag.startswith(("PUNCT", "SYM")):
        return False

    return True


def count_tokens_in_tagged_text(text: str) -> int:
    """
    Count token lines in a TreeTagger output file.

    Each valid tagged token line counts as one word/token.
    """
    words = 0

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in lines:
        line = line.strip()

        if not line:
            continue

        parts = line.split("\t")

        if len(parts) < 3:
            parts = line.split()

        if len(parts) < 3:
            continue

        word, tag, _lemma = parts[:3]

        if is_countable_token(word, tag):
            words += 1

    return words


def count_tokens_in_tagged_file(path: Path) -> int:
    """Count token lines in a UTF-8 TreeTagger output file."""
    return count_tokens_in_tagged_text(path.read_text(encoding="utf-8"))


def count_document(document, phase_dir):
    """Count one manifest-listed text, checking its recorded bytes before and after."""
    path = document["path"]
    expected_size = document["size_bytes"]
    expected_hash = document["sha256"]
    relative = f"corpus/05_enade_tagged/{document['relative_path']}"

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Tagged chapter is not a regular, non-symlink file: {path}")
    try:
        path.resolve(strict=True).relative_to(phase_dir)
    except (OSError, ValueError) as error:
        raise ValueError(f"Tagged chapter escapes the phase directory: {path}") from error

    data = path.read_bytes()
    if len(data) != expected_size or columns.sha256_bytes(data) != expected_hash:
        raise ValueError(f"Tagged chapter checksum or size mismatch: {relative}")

    words = count_tokens_in_tagged_text(data.decode("utf-8"))

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Tagged chapter changed while being counted: {path}")
    try:
        current_size = path.stat().st_size
        current_hash = columns.sha256_file(path)
    except OSError as error:
        raise ValueError(f"Tagged chapter changed while being counted: {path}") from error
    if current_size != expected_size or current_hash != expected_hash:
        raise ValueError(f"Tagged chapter changed while being counted: {path}")
    return words


def build_output(documents, phase_dir):
    text_counts = defaultdict(int)
    word_counts = defaultdict(int)
    total_texts = 0
    total_words = 0

    for document in documents:
        group = document["group"]
        words = count_document(document, phase_dir)
        text_counts[group] += 1
        word_counts[group] += words
        total_texts += 1
        total_words += words

    lines = ["Strata\tText Count\tWord Count\n"]
    for group in sorted(text_counts, key=natural_sort_key):
        lines.append(f"{group}\t{text_counts[group]}\t{word_counts[group]}\n")
    lines.extend(("\n", f"overall\t{total_texts}\t{total_words}\n"))
    return "".join(lines).encode("utf-8"), total_texts, total_words, len(text_counts)


def verify_existing_output(output_path, expected_bytes):
    """Return True for an identical existing output; reject unsafe/conflicting paths."""
    if output_path.parent.is_symlink():
        raise FileExistsError(f"Output directory must not be a symlink: {output_path.parent}")
    if output_path.parent.exists() and not output_path.parent.is_dir():
        raise FileExistsError(f"Output parent is not a directory: {output_path.parent}")
    if not output_path.exists() and not output_path.is_symlink():
        return False
    if output_path.is_symlink() or not output_path.is_file():
        raise FileExistsError(f"Output path is not a regular, non-symlink file: {output_path}")
    if output_path.read_bytes() != expected_bytes:
        raise FileExistsError(f"Existing output conflicts with current corpus: {output_path}")
    return True


def publish_output(output_path, content):
    """Atomically create the output without replacing any path that already exists."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.parent.is_symlink() or not output_path.parent.is_dir():
        raise FileExistsError(f"Output directory is not a regular directory: {output_path.parent}")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.staging-", dir=output_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, output_path)
        except FileExistsError:
            return verify_existing_output(output_path, content)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="Calculate corpus size for ENADE groups.")
    parser.add_argument("--phase-dir", type=Path, default=PHASE_DIR,
                        help="Phase directory used to resolve relative paths.")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE,
                        help="TSV output path (default: corpus_size/corpus_size.tsv).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate inputs and output safety without writing files.")
    args = parser.parse_args(argv)

    phase_dir = args.phase_dir.resolve()
    output_path = columns.resolve_cli_path(args.output, phase_dir)
    tagged_base = columns.resolve_cli_path(columns.TAGGED_BASE, phase_dir)
    tagged_manifest_path = columns.resolve_cli_path(columns.TAGGED_MANIFEST, phase_dir)
    target_manifest_path = columns.resolve_cli_path(columns.TARGET_MANIFEST, phase_dir)
    failures_manifest_path = columns.resolve_cli_path(columns.FAILURES_MANIFEST, phase_dir)

    documents = columns.load_corpus_documents(
        phase_dir, tagged_base, tagged_manifest_path, target_manifest_path,
        failures_manifest_path,
    )
    output_bytes, total_texts, total_words, group_count = build_output(documents, phase_dir)

    input_paths = {
        tagged_manifest_path,
        target_manifest_path,
        failures_manifest_path,
        *(document["path"] for document in documents),
        *(document["source_path"] for document in documents),
    }
    if output_path.resolve(strict=False) in {
            path.resolve(strict=False) for path in input_paths
    }:
        raise FileExistsError(f"Output path conflicts with a corpus input: {output_path}")

    existing = verify_existing_output(output_path, output_bytes)
    if args.dry_run:
        action = "Identical output verified" if existing else "Validated; output can be published"
        print(f"{action}: {total_texts} texts in {group_count} groups, {total_words} words.")
        return 0
    if existing:
        print(f"Identical output already exists; verified without changes: {output_path}")
        return 0

    if publish_output(output_path, output_bytes):
        print(f"Identical output appeared during publication; verified without changes: {output_path}")
        return 0
    print(f"Corpus sizes saved to {output_path}")
    print(f"Total texts: {total_texts}")
    print(f"Total words: {total_words}")
    return 0


if __name__ == "__main__":
    main()