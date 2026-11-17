import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import columns


class TestColumns(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="columns_test_")
        self.root = Path(self.temp_dir.name)
        self.keyword_file = self.root / "corpus" / "07_enade_kw_selected" / "keywords.txt"
        self.tagged_dir = self.root / "corpus" / "05_enade_tagged"
        self.tagged_dir.mkdir(parents=True)
        self.tagged_manifest = self.tagged_dir / "enade_tagged_corpus.ndjson"
        self.failures_manifest = self.tagged_dir / "tagging_failures.ndjson"
        self.target_manifest = self.root / "corpus" / "04_enade" / "enade_target_corpus.ndjson"
        self.output_root = self.root / "outputs"
        self.documents = [
            ("2009", "c4", "doc10.txt", "N	NOUN	beta\nX	NOUN	<unknown>\n"),
            ("2010", "c4", "doc2.txt", "A	VERB	árvore\nB	ADJ	ÁRVORE\n"),
            ("2009", "c4", "doc2.txt", "A	VERB	ÁRVORE\nB	NOUN	beta\nC	NOUN	beta\n"),
        ]
        self.write_inputs()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def sha256(data):
        return hashlib.sha256(data).hexdigest()

    def write_inputs(self, documents=None, keywords="ÁRVORE\nbeta\nárvore\n"):
        self.keyword_file.parent.mkdir(parents=True, exist_ok=True)
        self.keyword_file.write_text(keywords, encoding="utf-8")
        target_rows = []
        tagged_rows = []
        for year, chapter, filename, content in documents or self.documents:
            group = f"{year}_{chapter}"
            source_rel = f"corpus/04_enade/{group}/{filename}"
            source_path = self.root / source_rel
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_bytes = f"source {group}/{filename}\n".encode("utf-8")
            source_path.write_bytes(source_bytes)
            tagged_rel = f"corpus/05_enade_tagged/{group}/{filename}"
            tagged_path = self.root / tagged_rel
            tagged_path.parent.mkdir(parents=True, exist_ok=True)
            tagged_bytes = content.encode("utf-8")
            tagged_path.write_bytes(tagged_bytes)
            target_rows.append({
                "year": year,
                "chapter": chapter,
                "target_subdirectory": group,
                "target_chapter_path": source_rel,
                "chapter_sha256": self.sha256(source_bytes),
                "chapter_size_bytes": len(source_bytes),
                "denoise_status": "complete",
                "corpus_status": "accepted_subject_to_audit",
            })
            tagged_rows.append({
                "year": year,
                "chapter": chapter,
                "target_subdirectory": group,
                "filename": filename,
                "source_chapter_path": source_rel,
                "source_sha256": self.sha256(source_bytes),
                "source_size_bytes": len(source_bytes),
                "tagged_chapter_path": tagged_rel,
                "tagged_sha256": self.sha256(tagged_bytes),
                "tagged_size_bytes": len(tagged_bytes),
                "status": "success",
            })
        self.write_ndjson(self.target_manifest, target_rows)
        self.write_ndjson(self.tagged_manifest, tagged_rows)
        self.failures_manifest.write_text("", encoding="utf-8")

    @staticmethod
    def write_ndjson(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def run_columns(self, *arguments):
        args = [
            "--phase-dir", str(self.root),
            "--keyword-file", str(self.keyword_file),
            "--tagged-dir", str(self.tagged_dir),
            "--tagged-manifest", str(self.tagged_manifest),
            "--target-manifest", str(self.target_manifest),
            "--failures-manifest", str(self.failures_manifest),
            "--output-root", str(self.output_root),
            *arguments,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            return columns.main(args)

    def test_matrix_order_group_labels_presence_semantics_and_alignment(self):
        self.run_columns()

        file_ids = (self.output_root / "file_ids.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(file_ids, [
            "t000001 2009_c4/doc2.txt",
            "t000002 2009_c4/doc10.txt",
            "t000003 2010_c4/doc2.txt",
        ])
        index_lines = (self.output_root / "index_keywords.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(index_lines, ["000001 beta", "000002 árvore"])
        beta_full = (self.output_root / "columns" / "000001.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(beta_full, [
            "t000001 2009_c4 1",
            "t000002 2009_c4 1",
            "t000003 2010_c4 0",
        ])
        tree_full = (self.output_root / "columns" / "000002.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(tree_full, [
            "t000001 2009_c4 1",
            "t000002 2009_c4 0",
            "t000003 2010_c4 1",
        ])
        for keyword_id, expected in (("000001", ["1", "1", "0"]), ("000002", ["1", "0", "1"])):
            clean = (self.output_root / "columns_clean" / f"{keyword_id}.txt").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(clean, [keyword_id, *expected])

    def test_skipped_manifest_rows_are_accepted(self):
        rows = [json.loads(line) for line in self.tagged_manifest.read_text(encoding="utf-8").splitlines()]
        rows[0]["status"] = "skipped"
        self.write_ndjson(self.tagged_manifest, rows)

        self.run_columns("--dry-run")

    def test_dry_run_writes_nothing(self):
        self.run_columns("--dry-run")

        self.assertFalse(self.output_root.exists())

    def test_identical_rerun_is_safe_and_has_provenance(self):
        self.run_columns()
        first_manifest = (self.output_root / "columns_run.json").read_bytes()

        self.run_columns()

        run = json.loads(first_manifest)
        self.assertEqual(run["counts"], {"documents": 3, "keywords": 2})
        self.assertEqual(run["outputs"]["columns/000001.txt"]["sha256"], self.sha256(
            (self.output_root / "columns" / "000001.txt").read_bytes()
        ))
        self.assertEqual((self.output_root / "columns_run.json").read_bytes(), first_manifest)

    def test_conflicting_existing_output_is_preserved(self):
        self.run_columns()
        conflict = self.output_root / "columns" / "000001.txt"
        conflict.write_text("leave this untouched\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            self.run_columns()

        self.assertEqual(conflict.read_text(encoding="utf-8"), "leave this untouched\n")

    def test_partial_existing_output_is_rejected(self):
        columns_dir = self.output_root / "columns"
        columns_dir.mkdir(parents=True)
        sentinel = columns_dir / "000001.txt"
        sentinel.write_text("partial\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            self.run_columns()

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "partial\n")

    def test_duplicate_tag_manifest_identity_is_rejected(self):
        rows = [json.loads(line) for line in self.tagged_manifest.read_text(encoding="utf-8").splitlines()]
        rows.append(rows[0])
        self.write_ndjson(self.tagged_manifest, rows)

        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

    def test_missing_tag_manifest_document_is_rejected(self):
        rows = [json.loads(line) for line in self.tagged_manifest.read_text(encoding="utf-8").splitlines()]
        self.write_ndjson(self.tagged_manifest, rows[:-1])

        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

    def test_failure_manifest_entries_are_rejected(self):
        self.write_ndjson(self.failures_manifest, [{"filename": "failed.txt", "error_type": "TagError"}])

        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

    def test_unsafe_manifest_paths_are_rejected(self):
        rows = [json.loads(line) for line in self.tagged_manifest.read_text(encoding="utf-8").splitlines()]
        rows[0]["tagged_chapter_path"] = "corpus/05_enade_tagged/../outside.txt"
        self.write_ndjson(self.tagged_manifest, rows)

        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

    def test_tagged_checksum_and_size_are_validated(self):
        tagged_path = self.tagged_dir / "2009_c4" / "doc2.txt"
        tagged_path.write_text("different\tNOUN\tcontent\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

    def test_target_source_metadata_must_match_tag_manifest(self):
        rows = [json.loads(line) for line in self.target_manifest.read_text(encoding="utf-8").splitlines()]
        rows[0]["chapter_sha256"] = "0" * 64
        self.write_ndjson(self.target_manifest, rows)

        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

    def test_empty_keywords_and_missing_input_are_rejected(self):
        self.keyword_file.write_text("\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

        self.keyword_file.unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_columns("--dry-run")

    def test_manifest_empty_and_malformed_rows_are_rejected(self):
        self.tagged_manifest.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")

        self.tagged_manifest.write_text("not-json\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_columns("--dry-run")


if __name__ == "__main__":
    unittest.main()