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

import corpus_size


class TestCorpusSize(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="corpus_size_test_")
        self.root = Path(self.temp_dir.name)
        self.tagged_base = self.root / "corpus" / "05_enade_tagged"
        self.tagged_manifest = self.tagged_base / "enade_tagged_corpus.ndjson"
        self.failures_manifest = self.tagged_base / "tagging_failures.ndjson"
        self.target_manifest = self.root / "corpus" / "04_enade" / "enade_target_corpus.ndjson"
        self.documents = [
            ("2009", "c4", "doc10.txt", (
                "Árvore\tNOUN\tárvore\n"
                "-la\tNOUN\t-la\n"
                "curso6\tNOUN\tcurso6\n"
                "123\tNUM\t123\n"
                ".\tPUNCT\t.\n"
                "€\tSYM\t€\n"
                "sem-tab sem-tag lemma\n"
                "short\n\n"
            )),
            ("2009", "c4", "doc2.txt", "a\tNOUN\ta\n!!\tPUNCT\t!!\n"),
            ("2009", "c10", "doc1.txt", "x\tSYM\tx\nOlá\tVERB\tolá\n"),
            ("2010", "c4", "doc1.txt", "um\tNOUN\tum\ndois\tNOUN\tdois\n"),
        ]
        self.write_inputs()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def sha256(data):
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def write_ndjson(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def write_inputs(self, documents=None):
        target_rows = []
        tagged_rows = []
        for year, chapter, filename, content in documents or self.documents:
            group = f"{year}_{chapter}"
            source_relative = f"corpus/04_enade/{group}/{filename}"
            source_bytes = f"source {group}/{filename}\n".encode("utf-8")
            source_path = self.root / source_relative
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.write_bytes(source_bytes)

            tagged_relative = f"corpus/05_enade_tagged/{group}/{filename}"
            tagged_bytes = content.encode("utf-8")
            tagged_path = self.root / tagged_relative
            tagged_path.parent.mkdir(parents=True, exist_ok=True)
            tagged_path.write_bytes(tagged_bytes)

            target_rows.append({
                "year": year,
                "chapter": chapter,
                "target_subdirectory": group,
                "target_chapter_path": source_relative,
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
                "source_chapter_path": source_relative,
                "source_sha256": self.sha256(source_bytes),
                "source_size_bytes": len(source_bytes),
                "tagged_chapter_path": tagged_relative,
                "tagged_sha256": self.sha256(tagged_bytes),
                "tagged_size_bytes": len(tagged_bytes),
                "status": "success",
            })
        self.write_ndjson(self.target_manifest, target_rows)
        self.write_ndjson(self.tagged_manifest, tagged_rows)
        self.failures_manifest.parent.mkdir(parents=True, exist_ok=True)
        self.failures_manifest.write_text("", encoding="utf-8")

    def read_rows(self, path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def run_main(self, *arguments):
        args = ["--phase-dir", str(self.root), *arguments]
        with contextlib.redirect_stdout(io.StringIO()):
            return corpus_size.main(args)

    def test_writes_naturally_ordered_group_rows_and_overall_totals(self):
        self.run_main()

        output = self.root / "corpus_size" / "corpus_size.tsv"
        self.assertEqual(output.read_text(encoding="utf-8"), (
            "Strata\tText Count\tWord Count\n"
            "2009_c4\t2\t4\n"
            "2009_c10\t1\t1\n"
            "2010_c4\t1\t2\n"
            "\n"
            "overall\t4\t7\n"
        ))

    def test_dry_run_validates_without_creating_output(self):
        result = self.run_main("--output", "reports/custom.tsv", "--dry-run")

        self.assertEqual(result, 0)
        self.assertFalse((self.root / "reports").exists())
        self.assertFalse((self.root / "corpus_size").exists())

    def test_parser_keeps_unicode_line_separator_inside_tagged_line(self):
        self.assertEqual(
            corpus_size.count_tokens_in_tagged_text("word\tNO\u2028UN\tlemma\n"),
            1,
        )

    def test_output_option_resolves_relative_to_phase_directory(self):
        self.run_main("--output", "reports/custom.tsv")

        output = self.root / "reports" / "custom.tsv"
        self.assertTrue(output.is_file())
        self.assertIn("overall\t4\t7\n", output.read_text(encoding="utf-8"))

    def test_identical_rerun_is_reused_and_conflicting_output_is_preserved(self):
        self.run_main()
        output = self.root / "corpus_size" / "corpus_size.tsv"
        original = output.read_bytes()
        self.run_main()
        self.assertEqual(output.read_bytes(), original)

        output.write_text("existing result\n", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run_main()
        self.assertEqual(output.read_text(encoding="utf-8"), "existing result\n")

    def test_duplicate_tagged_manifest_record_is_rejected(self):
        rows = self.read_rows(self.tagged_manifest)
        rows.append(rows[0])
        self.write_ndjson(self.tagged_manifest, rows)

        with self.assertRaisesRegex(ValueError, "Duplicate tagged manifest document"):
            self.run_main()

    def test_missing_tagged_manifest_record_is_rejected(self):
        rows = self.read_rows(self.tagged_manifest)
        self.write_ndjson(self.tagged_manifest, rows[:-1])

        with self.assertRaisesRegex(ValueError, "Tagged manifest omits"):
            self.run_main()

    def test_inconsistent_group_metadata_is_rejected(self):
        rows = self.read_rows(self.tagged_manifest)
        rows[0]["target_subdirectory"] = "2009_c10"
        self.write_ndjson(self.tagged_manifest, rows)

        with self.assertRaisesRegex(ValueError, "Inconsistent ENADE group"):
            self.run_main()

    def test_tagged_checksum_mismatch_is_rejected(self):
        tagged_file = self.tagged_base / "2009_c4" / "doc10.txt"
        tagged_file.write_text("changed\tNOUN\tchanged\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "checksum or size mismatch"):
            self.run_main()

    def test_unlisted_tagged_file_is_rejected(self):
        extra_file = self.tagged_base / "2009_c4" / "unlisted.txt"
        extra_file.write_text("extra\tNOUN\textra\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "directory and manifest differ"):
            self.run_main()


if __name__ == "__main__":
    unittest.main()