import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import sas_formats


class TestSasFormats(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="sas_formats_test_")
        self.root = Path(self.temp_dir.name)
        self.sas_dir = self.root / "sas"
        self.sas_dir.mkdir()
        self.index_path = self.root / "index_keywords.txt"
        self.columns_manifest_path = self.root / "columns_run.json"
        self.matrix_path = self.sas_dir / "counts.txt"
        self.merge_provenance_path = self.sas_dir / "merge_columns_run.json"
        self.index_content = "000001 café\n000002 mot\"clé\n".encode("utf-8")
        self.matrix_content = b"t000001 2009_c4 1 0\nt000002 2009_c4 0 1\n"
        self.write_fixture()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def record(data):
        return {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}

    def write_fixture(self):
        self.index_path.write_bytes(self.index_content)
        self.matrix_path.write_bytes(self.matrix_content)
        columns_outputs = {
            "file_ids.txt": self.record(b"t000001 2009_c4/a.txt\nt000002 2009_c4/b.txt\n"),
            "index_keywords.txt": self.record(self.index_content),
        }
        for keyword_id in ("000001", "000002"):
            columns_outputs[f"columns/{keyword_id}.txt"] = self.record(b"full column\n")
            columns_outputs[f"columns_clean/{keyword_id}.txt"] = self.record(b"clean column\n")
        columns_manifest = {
            "schema_version": 1,
            "counts": {"documents": 2, "keywords": 2},
            "groups": [{"group": "2009_c4", "documents": 2}],
            "outputs": columns_outputs,
        }
        self.columns_manifest_content = (
            json.dumps(columns_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.columns_manifest_path.write_bytes(self.columns_manifest_content)

        column_inputs = []
        for keyword_id in ("000001", "000002"):
            column_inputs.extend([
                {"path": f"columns/{keyword_id}.txt", **self.record(b"full column\n")},
                {"path": f"columns_clean/{keyword_id}.txt", **self.record(b"clean column\n")},
            ])
        merge_manifest = {
            "schema_version": 1,
            "counts": {"documents": 2, "keywords": 2, "fields_per_row": 4},
            "inputs": {
                "columns_manifest": {
                    "path": "columns_run.json",
                    "sha256": hashlib.sha256(self.columns_manifest_content).hexdigest(),
                },
                "keyword_index": {
                    "path": "index_keywords.txt",
                    **self.record(self.index_content),
                },
                "columns": column_inputs,
            },
            "outputs": {
                "matrix": {"path": "sas/counts.txt", **self.record(self.matrix_content)},
                "provenance": "sas/merge_columns_run.json",
            },
        }
        self.merge_provenance_content = (
            json.dumps(merge_manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self.merge_provenance_path.write_bytes(self.merge_provenance_content)

    def run_formats(self, *arguments):
        args = ["--phase-dir", str(self.root), *arguments]
        with contextlib.redirect_stdout(io.StringIO()):
            return sas_formats.main(args)

    @property
    def short_output(self):
        return self.sas_dir / sas_formats.SHORT_FORMAT

    @property
    def full_output(self):
        return self.sas_dir / sas_formats.FULL_FORMAT

    @property
    def provenance_output(self):
        return self.sas_dir / sas_formats.FORMAT_PROVENANCE

    def test_exact_legacy_format_contents_and_provenance(self):
        counts_before = self.matrix_path.read_bytes()
        merge_before = self.merge_provenance_path.read_bytes()

        self.run_formats()

        self.assertEqual(self.short_output.read_bytes(), (
            'PROC FORMAT library=work ;\n'
            '  VALUE  $lexlabels\n'
            '"v000001" = "café"\n'
            '"v000002" = "mot""clé"\n'
            ';\nrun;\nquit;\n'
        ).encode("utf-8"))
        self.assertEqual(self.full_output.read_bytes(), (
            'PROC FORMAT library=work ;\n'
            '  VALUE  $lexlabelsfull\n'
            '"v000001" = "café (v000001)"\n'
            '"v000002" = "mot""clé (v000002)"\n'
            ';\nrun;\nquit;\n'
        ).encode("utf-8"))
        provenance = json.loads(self.provenance_output.read_text(encoding="utf-8"))
        self.assertEqual(provenance["counts"], {"keywords": 2})
        self.assertEqual(
            provenance["outputs"]["short_format"]["sha256"],
            hashlib.sha256(self.short_output.read_bytes()).hexdigest())
        self.assertEqual(self.matrix_path.read_bytes(), counts_before)
        self.assertEqual(self.merge_provenance_path.read_bytes(), merge_before)

    def test_dry_run_validates_without_publishing(self):
        self.run_formats("--dry-run")

        self.assertFalse(self.short_output.exists())
        self.assertFalse(self.full_output.exists())
        self.assertFalse(self.provenance_output.exists())

    def test_identical_rerun_verifies_without_rewriting(self):
        self.run_formats()
        files = (self.short_output, self.full_output, self.provenance_output)
        original = [(path.read_bytes(), path.stat().st_mtime_ns) for path in files]

        self.run_formats()

        self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in files], original)

    def test_output_directory_override_and_explicit_input_paths(self):
        self.run_formats(
            "--keyword-index", "index_keywords.txt",
            "--columns-manifest", "columns_run.json",
            "--matrix", "sas/counts.txt",
            "--merge-provenance", "sas/merge_columns_run.json",
            "--output-dir", "exports",
        )

        self.assertTrue((self.root / "exports" / sas_formats.SHORT_FORMAT).is_file())
        self.assertTrue((self.root / "exports" / sas_formats.FULL_FORMAT).is_file())
        self.assertTrue((self.root / "exports" / sas_formats.FORMAT_PROVENANCE).is_file())

    def test_index_checksum_mismatch_is_rejected(self):
        self.index_path.write_bytes("000001 changed\n000002 mot\"clé\n".encode("utf-8"))

        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.run_formats()
        self.assertFalse(self.short_output.exists())

    def test_invalid_or_out_of_order_index_is_rejected(self):
        self.index_path.write_bytes("000002 café\n000001 mot\"clé\n".encode("utf-8"))

        with self.assertRaisesRegex(ValueError, "out-of-order"):
            self.run_formats()

    def test_columns_manifest_keyword_count_mismatch_is_rejected(self):
        columns_manifest = json.loads(self.columns_manifest_path.read_text(encoding="utf-8"))
        columns_manifest["counts"]["keywords"] = 3
        self.columns_manifest_path.write_text(
            json.dumps(columns_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Keyword count"):
            self.run_formats()

    def test_merge_index_checksum_mismatch_is_rejected(self):
        merge_manifest = json.loads(self.merge_provenance_path.read_text(encoding="utf-8"))
        merge_manifest["inputs"]["keyword_index"]["sha256"] = "0" * 64
        self.merge_provenance_path.write_text(
            json.dumps(merge_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "keyword index in"):
            self.run_formats()

    def test_columns_manifest_checksum_mismatch_is_rejected(self):
        self.columns_manifest_path.write_bytes(self.columns_manifest_content + b"\n")

        with self.assertRaisesRegex(ValueError, "columns manifest in"):
            self.run_formats()

    def test_merge_column_order_mismatch_is_rejected(self):
        merge_manifest = json.loads(self.merge_provenance_path.read_text(encoding="utf-8"))
        merge_manifest["inputs"]["columns"][0:2], merge_manifest["inputs"]["columns"][2:4] = (
            merge_manifest["inputs"]["columns"][2:4], merge_manifest["inputs"]["columns"][0:2])
        self.merge_provenance_path.write_text(
            json.dumps(merge_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Column order"):
            self.run_formats()

    def test_matrix_checksum_mismatch_is_rejected(self):
        self.matrix_path.write_bytes(self.matrix_content + b"tampered\n")

        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.run_formats()

    def test_partial_outputs_are_preserved_and_rejected(self):
        self.short_output.write_bytes(b"pre-existing partial output")

        with self.assertRaisesRegex(FileExistsError, "incomplete"):
            self.run_formats()
        self.assertEqual(self.short_output.read_bytes(), b"pre-existing partial output")
        self.assertFalse(self.full_output.exists())

    def test_conflicting_outputs_are_preserved_and_rejected(self):
        self.run_formats()
        self.short_output.write_bytes(b"conflict")

        with self.assertRaisesRegex(FileExistsError, "conflicts"):
            self.run_formats()
        self.assertEqual(self.short_output.read_bytes(), b"conflict")

    def test_publication_failure_rolls_back_only_new_outputs(self):
        original_link = sas_formats.os.link
        calls = 0

        def fail_second_link(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated publication failure")
            return original_link(source, destination)

        with mock.patch.object(sas_formats.os, "link", side_effect=fail_second_link):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.run_formats()

        self.assertFalse(self.short_output.exists())
        self.assertFalse(self.full_output.exists())
        self.assertFalse(self.provenance_output.exists())

    def test_outputs_cannot_overwrite_matrix_or_use_symlink_parent(self):
        with self.assertRaisesRegex(ValueError, "overwrite an input"):
            self.run_formats("--short-output", "sas/counts.txt")

        link = self.root / "sas-link"
        link.symlink_to(self.sas_dir, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.run_formats("--output-dir", "sas-link")


if __name__ == "__main__":
    unittest.main()