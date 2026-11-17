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

import merge_columns


class TestMergeColumns(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="merge_columns_test_")
        self.root = Path(self.temp_dir.name)
        self.columns_dir = self.root / "columns"
        self.clean_dir = self.root / "columns_clean"
        self.columns_dir.mkdir()
        self.clean_dir.mkdir()
        self.file_ids = self.root / "file_ids.txt"
        self.keyword_index = self.root / "index_keywords.txt"
        self.columns_manifest = self.root / "columns_run.json"
        self.output = self.root / "sas" / "counts.txt"
        self.provenance = self.root / "sas" / "merge_columns_run.json"
        self.write_fixture()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def artifact_record(data):
        return {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}

    def write_fixture(self):
        file_ids = (
            "t000001 2009_c4/a.txt\n"
            "t000002 2009_c4/b.txt\n"
            "t000003 2010_c4/c.txt\n"
        ).encode("utf-8")
        keyword_index = "000001 alfa\n000002 beta\n".encode("utf-8")
        full_columns = {
            "000001": "t000001 2009_c4 1\nt000002 2009_c4 0\nt000003 2010_c4 1\n",
            "000002": "t000001 2009_c4 0\nt000002 2009_c4 1\nt000003 2010_c4 1\n",
        }
        clean_columns = {
            "000001": "000001\n1\n0\n1\n",
            "000002": "000002\n0\n1\n1\n",
        }
        self.file_ids.write_bytes(file_ids)
        self.keyword_index.write_bytes(keyword_index)
        outputs = {
            "file_ids.txt": self.artifact_record(file_ids),
            "index_keywords.txt": self.artifact_record(keyword_index),
        }
        for keyword_id, text in full_columns.items():
            content = text.encode("utf-8")
            (self.columns_dir / f"{keyword_id}.txt").write_bytes(content)
            outputs[f"columns/{keyword_id}.txt"] = self.artifact_record(content)
        for keyword_id, text in clean_columns.items():
            content = text.encode("utf-8")
            (self.clean_dir / f"{keyword_id}.txt").write_bytes(content)
            outputs[f"columns_clean/{keyword_id}.txt"] = self.artifact_record(content)
        self.write_manifest(outputs)

    def write_manifest(self, outputs):
        manifest = {
            "schema_version": 1,
            "counts": {"documents": 3, "keywords": 2},
            "groups": [
                {"group": "2009_c4", "documents": 2},
                {"group": "2010_c4", "documents": 1},
            ],
            "outputs": outputs,
        }
        self.columns_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def refresh_artifact_record(self, relative_path, path):
        manifest = json.loads(self.columns_manifest.read_text(encoding="utf-8"))
        manifest["outputs"][relative_path] = self.artifact_record(path.read_bytes())
        self.write_manifest(manifest["outputs"])

    def run_merge(self, *arguments):
        args = [
            "--phase-dir", str(self.root),
            "--output", "sas/counts.txt",
            "--provenance", "sas/merge_columns_run.json",
            *arguments,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            return merge_columns.main(args)

    def test_exact_matrix_values_and_keyword_order(self):
        self.run_merge()

        self.assertEqual(self.output.read_text(encoding="utf-8"), (
            "t000001 2009_c4 1 0\n"
            "t000002 2009_c4 0 1\n"
            "t000003 2010_c4 1 1\n"
        ))
        provenance = json.loads(self.provenance.read_text(encoding="utf-8"))
        self.assertEqual(provenance["counts"], {
            "documents": 3, "keywords": 2, "fields_per_row": 4,
        })
        self.assertEqual(
            provenance["outputs"]["matrix"]["sha256"],
            hashlib.sha256(self.output.read_bytes()).hexdigest())

    def test_dry_run_validates_without_creating_outputs(self):
        self.run_merge("--dry-run")

        self.assertFalse(self.output.exists())
        self.assertFalse(self.provenance.exists())
        self.assertFalse(self.output.parent.exists())

    def test_identical_rerun_is_safe_and_conflicts_are_refused(self):
        self.run_merge()
        original_output = self.output.read_bytes()
        original_provenance = self.provenance.read_bytes()

        self.run_merge()
        self.assertEqual(self.output.read_bytes(), original_output)
        self.assertEqual(self.provenance.read_bytes(), original_provenance)

        self.output.write_bytes(b"conflict\n")
        with self.assertRaisesRegex(FileExistsError, "conflicts"):
            self.run_merge()
        self.assertEqual(self.output.read_bytes(), b"conflict\n")

    def test_partial_output_pair_is_refused(self):
        self.output.parent.mkdir()
        self.output.write_text("existing\n", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "incomplete"):
            self.run_merge()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "existing\n")

    def test_output_cannot_be_placed_in_an_input_column_directory(self):
        with self.assertRaisesRegex(ValueError, "outside the input column directories"):
            self.run_merge("--output", "columns/merged.txt")

    def test_missing_and_extra_keyword_columns_are_refused(self):
        (self.clean_dir / "000002.txt").unlink()
        with self.assertRaisesRegex(ValueError, "missing=.*000002.txt"):
            self.run_merge()

        (self.clean_dir / "000002.txt").write_text("000002\n0\n1\n1\n", encoding="utf-8")
        (self.clean_dir / "000003.txt").write_text("extra\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "extra=.*000003.txt"):
            self.run_merge()

    def test_checksum_failure_is_detected(self):
        with (self.clean_dir / "000001.txt").open("a", encoding="utf-8") as stream:
            stream.write("0\n")

        with self.assertRaisesRegex(ValueError, "Checksum or size mismatch"):
            self.run_merge()

    def test_invalid_flags_are_detected_after_checksum_validation(self):
        clean_path = self.clean_dir / "000001.txt"
        clean_path.write_text("000001\n1\nX\n1\n", encoding="utf-8")
        self.refresh_artifact_record("columns_clean/000001.txt", clean_path)

        with self.assertRaisesRegex(ValueError, "Invalid binary flag"):
            self.run_merge()

    def test_clean_row_count_mismatch_is_detected(self):
        clean_path = self.clean_dir / "000001.txt"
        clean_path.write_text("000001\n1\n0\n", encoding="utf-8")
        self.refresh_artifact_record("columns_clean/000001.txt", clean_path)

        with self.assertRaisesRegex(ValueError, "Row count mismatch"):
            self.run_merge()

    def test_full_and_clean_values_must_align(self):
        clean_path = self.clean_dir / "000001.txt"
        clean_path.write_text("000001\n0\n0\n1\n", encoding="utf-8")
        self.refresh_artifact_record("columns_clean/000001.txt", clean_path)

        with self.assertRaisesRegex(ValueError, "do not match"):
            self.run_merge()

    def test_full_column_document_order_must_match_file_ids(self):
        full_path = self.columns_dir / "000001.txt"
        full_path.write_text(
            "t000002 2009_c4 0\nt000001 2009_c4 1\nt000003 2010_c4 1\n",
            encoding="utf-8")
        self.refresh_artifact_record("columns/000001.txt", full_path)

        with self.assertRaisesRegex(ValueError, "alignment mismatch"):
            self.run_merge()

    def test_invalid_full_flag_is_detected(self):
        full_path = self.columns_dir / "000001.txt"
        full_path.write_text(
            "t000001 2009_c4 2\nt000002 2009_c4 0\nt000003 2010_c4 1\n",
            encoding="utf-8")
        self.refresh_artifact_record("columns/000001.txt", full_path)

        with self.assertRaisesRegex(ValueError, "Invalid binary flag"):
            self.run_merge()


if __name__ == "__main__":
    unittest.main()