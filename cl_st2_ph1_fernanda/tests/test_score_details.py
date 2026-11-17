import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "score_details.py"
SAS_SOURCE_DIR = PROJECT_DIR / "sas" / "output_cl_st2_ph1_fernanda"
FACTORS_VARID_SOURCE_DIR = PROJECT_DIR / "factors" / "var_id"
FILE_IDS_SOURCE_PATH = PROJECT_DIR / "file_ids.txt"
PROJECT_NAME = "cl_st2_ph1_fernanda"
sys.path.insert(0, str(PROJECT_DIR))

import score_details


class TestScoreDetails(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="score_details_test_")
        self.root = Path(self.temp_dir.name)
        self.phase_dir = self.root / PROJECT_NAME
        self.phase_dir.mkdir()
        self.script = self.phase_dir / "score_details.py"
        shutil.copy2(SCRIPT_PATH, self.script)
        self.input_dir = self.phase_dir / "sas" / f"output_{PROJECT_NAME}"
        self.input_dir.mkdir(parents=True)
        self.varid_dir = self.phase_dir / "factors" / "var_id"
        self.varid_dir.mkdir(parents=True)
        self.working_dir = self.root / "elsewhere"
        self.working_dir.mkdir()
        self.copy_inputs(self.input_dir, self.varid_dir, self.phase_dir, PROJECT_NAME)

    def tearDown(self):
        self.temp_dir.cleanup()

    def copy_inputs(self, sas_dest, varid_dest, phase_dest, project):
        shutil.copy2(
            SAS_SOURCE_DIR / f"{PROJECT_NAME}_scores.tsv",
            sas_dest / f"{project}_scores.tsv",
        )
        shutil.copy2(
            SAS_SOURCE_DIR / "word_labels_format.sas",
            sas_dest / "word_labels_format.sas",
        )
        for dim in range(1, 5):
            for pole in ("pos", "neg"):
                filename = f"f{dim}_{pole}_var_id.txt"
                shutil.copy2(FACTORS_VARID_SOURCE_DIR / filename, varid_dest / filename)
        shutil.copy2(FILE_IDS_SOURCE_PATH, phase_dest / "file_ids.txt")

    def run_script(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_defaults_use_phase_paths_and_generate_score_details(self):
        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        output_path = self.phase_dir / "examples" / "score_details.txt"
        self.assertTrue(output_path.is_file())

        content = output_path.read_text(encoding="utf-8")
        self.assertIn("text ID: t000001", content)
        self.assertIn("filename: 2009_c4/enade_2009_admin_b2a0b87461.txt", content)
        self.assertIn("f1 score: -7", content)
        self.assertIn("f1 pos words (N=1): segunda", content)
        self.assertIn("f1 neg words (N=8): estar, torno, perguntar, localização, ordem, esquema, cobertura, cada", content)
        self.assertIn("f2 score: 1", content)
        self.assertIn("f3 score: 1", content)
        self.assertIn("f4 score: -6", content)
        self.assertIn("=============================================", content)

    def test_relative_path_and_metadata_overrides_resolve_from_phase(self):
        custom_sas = self.phase_dir / "custom-sas"
        custom_sas.mkdir()
        custom_varid = self.phase_dir / "custom-varid"
        custom_varid.mkdir()
        self.copy_inputs(custom_sas, custom_varid, self.phase_dir, "demo")

        result = self.run_script(
            "--project", "demo",
            "--sas-output-dir", "custom-sas",
            "--varid-dir", "custom-varid",
            "--file-ids", "file_ids.txt",
            "--output", "custom-output/details.txt",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output_path = self.phase_dir / "custom-output" / "details.txt"
        self.assertTrue(output_path.is_file())
        content = output_path.read_text(encoding="utf-8")
        self.assertIn("text ID: t000001", content)

    def test_absolute_path_overrides_are_preserved(self):
        output_file = self.root / "absolute-output" / "details.txt"
        result = self.run_script(
            "--sas-output-dir", str(self.input_dir),
            "--varid-dir", str(self.varid_dir),
            "--file-ids", str(self.phase_dir / "file_ids.txt"),
            "--output", str(output_file),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output_file.is_file())

    def test_phase_dir_override(self):
        other_phase = self.root / "other_phase"
        other_phase.mkdir()
        other_sas = other_phase / "sas" / "output_other_phase"
        other_sas.mkdir(parents=True)
        other_varid = other_phase / "factors" / "var_id"
        other_varid.mkdir(parents=True)
        self.copy_inputs(other_sas, other_varid, other_phase, "other_phase")

        result = self.run_script(
            "--phase-dir", str(other_phase),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output_path = other_phase / "examples" / "score_details.txt"
        self.assertTrue(output_path.is_file())

    def test_fallback_to_phase_sas_for_word_labels(self):
        # Move word_labels_format.sas from output_dir to sas/
        labels_src = self.input_dir / "word_labels_format.sas"
        labels_dst = self.phase_dir / "sas" / "word_labels_format.sas"
        shutil.move(labels_src, labels_dst)

        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        output_path = self.phase_dir / "examples" / "score_details.txt"
        self.assertTrue(output_path.is_file())

    def test_missing_scores_file_is_reported(self):
        (self.input_dir / f"{PROJECT_NAME}_scores.tsv").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Scores file not found", result.stderr)

    def test_empty_scores_file_is_reported(self):
        (self.input_dir / f"{PROJECT_NAME}_scores.tsv").write_text("", encoding="utf-8")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)

    def test_missing_filename_column_is_reported(self):
        (self.input_dir / f"{PROJECT_NAME}_scores.tsv").write_text(
            "doc_id\tfac1\tv000001\n1\t2\t1\n", encoding="utf-8"
        )

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Column 'filename' not found", result.stderr)

    def test_missing_factor_columns_is_reported(self):
        (self.input_dir / f"{PROJECT_NAME}_scores.tsv").write_text(
            "filename\tscore1\tv000001\nt000001\t2\t1\n", encoding="utf-8"
        )

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No fac<n> columns found in scores file", result.stderr)

    def test_missing_word_labels_file_is_reported(self):
        (self.input_dir / "word_labels_format.sas").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Word-labels file not found", result.stderr)

    def test_missing_factor_varid_file_is_reported(self):
        (self.varid_dir / "f1_pos_var_id.txt").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Factor var-id file not found", result.stderr)

    def test_missing_file_ids_is_reported(self):
        (self.phase_dir / "file_ids.txt").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("File ID map not found", result.stderr)

    def test_header_in_file_ids_is_reported(self):
        (self.phase_dir / "file_ids.txt").write_text(
            "file_id filename\nt000001 2009_c4/text.txt\n", encoding="utf-8"
        )

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("appears to contain a header", result.stderr)

    def test_load_var_ids_ignores_parentheses_and_deduplicates(self):
        test_file = self.root / "var_ids.txt"
        test_file.write_text(
            "v000001 v000002 (v000003 v000004) v000005 v000001\n",
            encoding="utf-8",
        )
        loaded = score_details.load_var_ids(test_file)
        self.assertEqual(loaded, ["v000001", "v000002", "v000005"])

    def test_load_word_labels_parsing(self):
        test_file = self.root / "labels.sas"
        test_file.write_text(
            'value word_labels\n"v000001" = "alpha"\n"v000002" = "beta";\n',
            encoding="utf-8",
        )
        labels = score_details.load_word_labels(test_file)
        self.assertEqual(labels, {"v000001": "alpha", "v000002": "beta"})


if __name__ == "__main__":
    unittest.main()
