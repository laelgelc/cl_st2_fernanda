#!/usr/bin/env python3
"""Deterministic key lemma extraction pipeline for ENADE subcorpora.

Evaluates binary document-presence prevalence and computes log-likelihood (G^2),
effect sizes (%DIFF), and keyword classifications (POSKW, NEGKW, NOTKW) across
corpus groups.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

PHASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = Path("corpus/05_enade_tagged")
DEFAULT_OUTPUT_DIR = Path("corpus/06_enade_keylemmas")
DEFAULT_INPUT_MANIFEST = Path("corpus/05_enade_tagged/enade_tagged_corpus.ndjson")
DEFAULT_POS_CONFIG = Path("keylemmas_pos.txt")
DEFAULT_STOPWORDS = Path("keylemmas_stopwords.txt")
DEFAULT_CUTOFF = 0.0
MANIFEST_RUN_JSON = "keylemmas_run.json"

TSV_HEADER = (
    "lemma\ttarget_count\tcomparison_count\ttarget_per_1k\t"
    "comparison_per_1k\texpected\tLL\tdiff_percent\tstatus\n"
)

logger = logging.getLogger("keylemmas")


class KeylemmasError(Exception):
    """An invalid configuration, input file, or processing error."""


@dataclass(frozen=True)
class GroupMetrics:
    target_documents: int
    comparison_documents: int
    total_lemmas_evaluated: int
    poskw_count: int
    negkw_count: int
    notkw_count: int
    output_file: str
    output_sha256: str
    output_size_bytes: int


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel_posix(path: Path, base: Path = PHASE_DIR) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_path(path: Path | str, base: Path = PHASE_DIR) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return (base / p).resolve()


def load_pos_config(path: Path) -> tuple[tuple[str, ...], str]:
    if not path.is_file():
        raise KeylemmasError(f"POS configuration file not found: {path}")

    prefixes: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            prefixes.append(cleaned)

    if not prefixes:
        raise KeylemmasError(f"No valid POS tag prefixes found in: {path}")

    sha256_hash, _ = _sha256_file(path)
    return tuple(prefixes), sha256_hash


def load_stopwords_config(path: Path) -> tuple[set[str], str]:
    if not path.is_file():
        raise KeylemmasError(f"Stopwords configuration file not found: {path}")

    stopwords: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            stopwords.add(cleaned.lower())

    sha256_hash, _ = _sha256_file(path)
    return stopwords, sha256_hash


def ll(a: int, b: int, c: int, d: int) -> float:
    """Log-likelihood contingency test statistic (G^2)."""
    if a == 0 or b == 0 or (c + d) == 0:
        return 0.0
    total = c + d
    E1 = c * (a + b) / total
    E2 = d * (a + b) / total
    if E1 <= 0 or E2 <= 0:
        return 0.0
    val = 2.0 * ((a * math.log(a / E1)) + (b * math.log(b / E2)))
    return max(0.0, val)


def calculate_diff_percent(per_a: float, per_b: float) -> float:
    """Symmetrical percentage difference in prevalence rates."""
    if (per_a + per_b) == 0.0:
        return 0.0
    return 100.0 * (per_a - per_b) / ((per_a + per_b) / 2.0)


def classify_status(ll_val: float, diff_val: float) -> str:
    """Classify keyword status based on LL >= 3.84 and effect direction."""
    if ll_val >= 3.84 and diff_val > 0.0:
        return "POSKW"
    if ll_val >= 3.84:
        return "NEGKW"
    return "NOTKW"


def is_corpus_folder(path: Path) -> bool:
    """Return True if path is a corpus group folder."""
    name = path.name
    return path.is_dir() and not name.startswith(("_", "."))


def discover_documents(
    input_dir: Path,
    manifest_path: Path | None = None,
) -> dict[str, list[Path]]:
    """Discover tagged .txt files grouped by subcorpus folder/manifest entry.

    Returns a mapping of group_name -> sorted list of file paths.
    """
    groups: dict[str, list[Path]] = defaultdict(list)

    if manifest_path is not None and manifest_path.is_file():
        logger.info("Discovering documents from manifest: %s", manifest_path)
        with manifest_path.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    record = json.loads(line_str)
                except json.JSONDecodeError as err:
                    logger.warning("Skipping invalid JSON line in manifest: %s (%s)", line_str, err)
                    continue

                if record.get("status") and record.get("status") != "TAGGED":
                    continue

                group_key = record.get("target_subdirectory")
                if not group_key:
                    year = record.get("year")
                    chapter = record.get("chapter")
                    if year and chapter:
                        group_key = f"{year}_{chapter}"

                if not group_key:
                    continue

                tagged_path_str = record.get("tagged_chapter_path")
                if tagged_path_str:
                    doc_path = resolve_path(tagged_path_str)
                    if not doc_path.is_file():
                        # Try relative to input_dir
                        candidate = input_dir / group_key / Path(tagged_path_str).name
                        if candidate.is_file():
                            doc_path = candidate
                    if doc_path.is_file() and doc_path.suffix == ".txt":
                        groups[group_key].append(doc_path)

    if not groups:
        if not input_dir.is_dir():
            raise KeylemmasError(f"Input directory does not exist: {input_dir}")

        logger.info("Discovering documents by directory traversal in: %s", input_dir)
        subdirs = sorted([d for d in input_dir.iterdir() if is_corpus_folder(d)])
        for subdir in subdirs:
            group_key = subdir.name
            txt_files = sorted([f for f in subdir.glob("*.txt") if f.is_file() and not f.name.startswith(("_", "."))])
            if txt_files:
                groups[group_key].extend(txt_files)

    # Sort files within each group deterministically
    return {k: sorted(v) for k, v in sorted(groups.items())}


def parse_document_lemmas(
    file_path: Path,
    valid_prefixes: tuple[str, ...],
    stopwords: set[str],
) -> set[str]:
    """Parse a 3-column tagged file and return set of unique eligible lemmas."""
    lemmas: set[str] = set()
    with file_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 3:
                continue

            word, tag, lemma = parts[:3]

            if not tag.startswith(valid_prefixes):
                continue

            lemma_clean = lemma.strip()
            if not lemma_clean or lemma_clean == "<unknown>":
                lemma_clean = word.strip()

            lemma_lc = lemma_clean.lower()

            if sum(1 for ch in lemma_lc if ch.isalpha()) < 2:
                continue

            if lemma_lc in stopwords:
                continue

            lemmas.add(lemma_lc)

    return lemmas


def evaluate_group_keylemmas(
    group_name: str,
    target_texts: set[str],
    global_texts: set[str],
    group_presence: dict[str, set[str]],
    global_presence: dict[str, set[str]],
    cutoff_percent: float,
) -> tuple[list[tuple[str, int, int, float, float, float, float, float, str]], int, int, int]:
    """Calculate key lemma statistics for a target group against the comparison corpus."""
    comparison_texts = global_texts - target_texts
    size_target = len(target_texts)
    size_comp = len(comparison_texts)
    total = size_target + size_comp
    cutoff_texts = size_target * cutoff_percent / 100.0

    pr = {"POSKW": 0, "NEGKW": 1, "NOTKW": 2}
    rows: list[tuple[str, int, int, float, float, float, float, float, str]] = []
    poskw_count = 0
    negkw_count = 0
    notkw_count = 0

    all_lemmas = sorted(global_presence.keys())

    for lemma in all_lemmas:
        target_seen = group_presence.get(lemma, set())
        a = len(target_seen)
        b = len(global_presence[lemma] & comparison_texts)

        if size_target == 0 or a < cutoff_texts:
            continue

        per_a = (a / size_target) * 1000.0 if size_target else 0.0
        per_b = (b / size_comp) * 1000.0 if size_comp else 0.0
        expected = (size_target * (a + b)) / total if total else 0.0
        ll_val = ll(a, b, size_target, size_comp)
        diff = calculate_diff_percent(per_a, per_b)
        status = classify_status(ll_val, diff)

        if status == "POSKW":
            poskw_count += 1
        elif status == "NEGKW":
            negkw_count += 1
        else:
            notkw_count += 1

        rows.append((
            lemma,
            a,
            b,
            round(per_a, 2),
            round(per_b, 2),
            round(expected, 2),
            round(ll_val, 2),
            round(diff, 2),
            status,
        ))

    # Sort deterministically: status priority, then -LL, then alphabetical lemma
    rows.sort(key=lambda r: (pr[r[8]], -r[6], r[0]))
    return rows, poskw_count, negkw_count, notkw_count


def format_tsv_content(rows: Sequence[tuple[str, int, int, float, float, float, float, float, str]]) -> str:
    """Format rows into standard UTF-8 TSV content."""
    lines = [TSV_HEADER]
    for r in rows:
        lines.append(
            f"{r[0]}\t{r[1]}\t{r[2]}\t{r[3]:.2f}\t{r[4]:.2f}\t"
            f"{r[5]:.2f}\t{r[6]:.2f}\t{r[7]:.2f}\t{r[8]}\n"
        )
    return "".join(lines)


def configure_logging(log_file: Path | None = None) -> None:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


def run_pipeline(
    input_dir: Path,
    output_dir: Path,
    input_manifest: Path | None,
    pos_config_path: Path,
    stopwords_path: Path,
    cutoff_percent: float,
    dry_run: bool = False,
) -> int:
    start_time = time.time()
    timestamp_str = _utc_timestamp()

    valid_prefixes, pos_sha256 = load_pos_config(pos_config_path)
    stopwords, stopwords_sha256 = load_stopwords_config(stopwords_path)

    logger.info("Loaded %d valid POS tag prefixes: %s", len(valid_prefixes), ", ".join(valid_prefixes))
    logger.info("Loaded %d stopwords from %s", len(stopwords), stopwords_path)

    groups = discover_documents(input_dir, input_manifest)
    if not groups:
        raise KeylemmasError(f"No corpus groups or documents found under {input_dir}.")

    total_documents = sum(len(docs) for docs in groups.values())
    logger.info("Found %d groups and %d total documents.", len(groups), total_documents)

    if dry_run:
        logger.info("DRY-RUN MODE ENABLED. Validating execution plan without writing files.")
        print("\n=== DRY RUN EXECUTION PLAN ===")
        print(f"Input Directory:     {_rel_posix(input_dir)}")
        print(f"Output Directory:    {_rel_posix(output_dir)}")
        print(f"POS Configuration:   {_rel_posix(pos_config_path)} (SHA-256: {pos_sha256[:16]}...)")
        print(f"Stopwords:           {_rel_posix(stopwords_path)} ({len(stopwords)} words, SHA-256: {stopwords_sha256[:16]}...)")
        print(f"Cutoff Percentage:   {cutoff_percent}%")
        print(f"Total Groups:        {len(groups)}")
        print(f"Total Documents:     {total_documents}")
        print("\nDiscovered Groups:")
        for group_name, docs in groups.items():
            print(f"  - {group_name}: {len(docs)} documents")
        print("\nDry run completed successfully. No changes made.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    # Ingest document presence
    global_presence: dict[str, set[str]] = defaultdict(set)
    global_texts: set[str] = set()
    group_presence_map: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    group_texts_map: dict[str, set[str]] = defaultdict(set)

    for group_name, doc_paths in groups.items():
        for doc_path in doc_paths:
            doc_id = f"{group_name}/{doc_path.name}"
            lemmas = parse_document_lemmas(doc_path, valid_prefixes, stopwords)

            global_texts.add(doc_id)
            group_texts_map[group_name].add(doc_id)

            for lemma in lemmas:
                global_presence[lemma].add(doc_id)
                group_presence_map[group_name][lemma].add(doc_id)

    # Evaluate each group
    group_manifest_data: dict[str, Any] = {}

    for group_name, doc_paths in groups.items():
        target_texts = group_texts_map[group_name]
        size_target = len(target_texts)
        size_comp = len(global_texts) - size_target

        rows, poskw, negkw, notkw = evaluate_group_keylemmas(
            group_name=group_name,
            target_texts=target_texts,
            global_texts=global_texts,
            group_presence=group_presence_map[group_name],
            global_presence=global_presence,
            cutoff_percent=cutoff_percent,
        )

        tsv_content = format_tsv_content(rows)
        tsv_bytes = tsv_content.encode("utf-8")
        tsv_sha256 = _sha256_bytes(tsv_bytes)
        tsv_size = len(tsv_bytes)

        out_file = output_dir / f"{group_name}.tsv"
        out_file.write_bytes(tsv_bytes)
        logger.info(
            "Saved %s (%d target vs %d comp texts | %d POSKW, %d NEGKW, %d NOTKW)",
            _rel_posix(out_file),
            size_target,
            size_comp,
            poskw,
            negkw,
            notkw,
        )

        group_manifest_data[group_name] = {
            "target_documents": size_target,
            "comparison_documents": size_comp,
            "total_lemmas_evaluated": len(rows),
            "poskw_count": poskw,
            "negkw_count": negkw,
            "notkw_count": notkw,
            "output_file": _rel_posix(out_file),
            "output_sha256": tsv_sha256,
            "output_size_bytes": tsv_size,
        }

    elapsed = round(time.time() - start_time, 2)
    run_manifest = {
        "timestamp": timestamp_str,
        "elapsed_seconds": elapsed,
        "input_dir": _rel_posix(input_dir),
        "output_dir": _rel_posix(output_dir),
        "cutoff_percent": cutoff_percent,
        "pos_config": {
            "path": _rel_posix(pos_config_path),
            "sha256": pos_sha256,
            "active_prefixes": list(valid_prefixes),
        },
        "stopwords_config": {
            "path": _rel_posix(stopwords_path),
            "sha256": stopwords_sha256,
            "stopword_count": len(stopwords),
        },
        "total_documents": total_documents,
        "total_groups": len(groups),
        "groups": group_manifest_data,
    }

    manifest_file = output_dir / MANIFEST_RUN_JSON
    manifest_bytes = (json.dumps(run_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_file.write_bytes(manifest_bytes)
    logger.info("Saved run manifest: %s in %.2fs", _rel_posix(manifest_file), elapsed)

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic Key Lemma extraction for ENADE subcorpora.",
    )
    parser.add_argument(
        "--input-dir",
        "--input",
        dest="input_dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing tagged <year>_<chapter> subdirectories (default: {DEFAULT_INPUT_DIR}).",
    )
    parser.add_argument(
        "--output-dir",
        "--output",
        dest="output_dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Destination directory for TSV key lemma tables and run manifest (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--input-manifest",
        dest="input_manifest",
        type=Path,
        default=DEFAULT_INPUT_MANIFEST,
        help=f"Path to upstream tagged corpus manifest (default: {DEFAULT_INPUT_MANIFEST}).",
    )
    parser.add_argument(
        "--pos-config",
        dest="pos_config",
        type=Path,
        default=DEFAULT_POS_CONFIG,
        help=f"Path to POS tag prefix configuration file (default: {DEFAULT_POS_CONFIG}).",
    )
    parser.add_argument(
        "--stopwords",
        dest="stopwords",
        type=Path,
        default=DEFAULT_STOPWORDS,
        help=f"Path to stopword exclusion file (default: {DEFAULT_STOPWORDS}).",
    )
    parser.add_argument(
        "--cutoff",
        dest="cutoff",
        type=float,
        default=DEFAULT_CUTOFF,
        help=f"Minimum target group document presence percentage (default: {DEFAULT_CUTOFF}).",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Validate inputs and display execution plan without writing files.",
    )
    parser.add_argument(
        "--log-file",
        dest="log_file",
        type=Path,
        default=None,
        help="Optional path to write detailed execution logs.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    log_file = resolve_path(args.log_file) if args.log_file else None
    configure_logging(log_file)

    input_dir = resolve_path(args.input_dir)
    output_dir = resolve_path(args.output_dir)
    input_manifest = resolve_path(args.input_manifest) if args.input_manifest else None
    pos_config = resolve_path(args.pos_config)
    stopwords = resolve_path(args.stopwords)

    try:
        return run_pipeline(
            input_dir=input_dir,
            output_dir=output_dir,
            input_manifest=input_manifest,
            pos_config_path=pos_config,
            stopwords_path=stopwords,
            cutoff_percent=args.cutoff,
            dry_run=args.dry_run,
        )
    except KeylemmasError as err:
        logger.error("Keylemmas execution error: %s", err)
        return 1
    except Exception as err:
        logger.exception("Unexpected error during key lemma extraction: %s", err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
