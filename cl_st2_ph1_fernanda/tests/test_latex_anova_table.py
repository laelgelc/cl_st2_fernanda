import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "latex_anova_table.py"
SAS_SOURCE_DIR = PROJECT_DIR / "sas" / "output_cl_st2_ph1_fernanda"
PROJECT_NAME = "cl_st2_ph1_fernanda"
sys.path.insert(0, str(PROJECT_DIR))

import latex_anova_table


class TestLatexAnovaTable(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="latex_anova_table_test_")
        self.root = Path(self.temp_dir.name)
        self.phase_dir = self.root / PROJECT_NAME
        self.phase_dir.mkdir()
        self.script = self.phase_dir / "latex_anova_table.py"
        shutil.copy2(SCRIPT_PATH, self.script)
        self.input_dir = self.phase_dir / "sas" / f"output_{PROJECT_NAME}"
        self.input_dir.mkdir(parents=True)
        self.working_dir = self.root / "elsewhere"
        self.working_dir.mkdir()
        self.copy_inputs(self.input_dir, PROJECT_NAME)

    def tearDown(self):
        self.temp_dir.cleanup()

    def copy_inputs(self, destination, project):
        shutil.copy2(
            SAS_SOURCE_DIR / "cl_st2_ph1_fernanda_scores_only.tsv",
            destination / f"{project}_scores_only.tsv",
        )
        for dim in range(1, 5):
            for prefix in ("anova", "params"):
                filename = f"{prefix}_year_chapter_f{dim}.tsv"
                shutil.copy2(SAS_SOURCE_DIR / filename, destination / filename)

    def run_script(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_defaults_use_phase_paths_and_generate_four_factor_table(self):
        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        output_path = self.phase_dir / "latex_tables" / "anova_year_chapter.tex"
        table = output_path.read_text(encoding="utf-8")
        self.assertIn(r"\caption{ANOVA Results by Year Chapter}", table)
        self.assertIn(r"\label{tab:anova_year_chapter}", table)
        for row in (
            "1 & 1115.32 & < .0001 & .97881 & 97.88",
            "2 & 1164.71 & < .0001 & .97969 & 97.97",
            "3 & 823.63 & < .0001 & .97152 & 97.15",
            "4 & 688.87 & < .0001 & .96613 & 96.61",
        ):
            self.assertIn(row, table)

    def test_relative_path_and_metadata_overrides_resolve_from_phase(self):
        custom_input = self.phase_dir / "custom-input"
        custom_input.mkdir()
        self.copy_inputs(custom_input, "demo")

        result = self.run_script(
            "--project", "demo",
            "--effect", "year_chapter",
            "--input-dir", "custom-input",
            "--output-dir", "custom-output",
            "--caption", "Custom caption",
            "--label", "tab:custom-anova",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output_path = self.phase_dir / "custom-output" / "anova_year_chapter.tex"
        table = output_path.read_text(encoding="utf-8")
        self.assertIn(r"\caption{Custom caption}", table)
        self.assertIn(r"\label{tab:custom-anova}", table)

    def test_absolute_path_overrides_are_preserved(self):
        output_dir = self.root / "absolute-output"
        result = self.run_script(
            "--input-dir", str(self.input_dir),
            "--output-dir", str(output_dir),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output_dir / "anova_year_chapter.tex").is_file())

    def test_missing_scores_file_is_reported(self):
        (self.input_dir / f"{PROJECT_NAME}_scores_only.tsv").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Scores-only file not found", result.stderr)

    def test_missing_anova_file_is_reported(self):
        (self.input_dir / "anova_year_chapter_f1.tsv").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANOVA file not found", result.stderr)

    def test_missing_parameter_file_is_reported(self):
        (self.input_dir / "params_year_chapter_f1.tsv").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("R-square parameter file not found", result.stderr)

    def test_anova_rows_select_requested_type_i_and_keep_fallback(self):
        anova_file = self.root / "selection.tsv"
        anova_file.write_text(
            "HypothesisType\tSource\tFValue\tProbF\n"
            "3\tyear_chapter\t900\t0.5\n"
            "1\tother\t100\t0.2\n"
            "1\tyear_chapter\t200\t0.1\n",
            encoding="utf-8",
        )

        selected = latex_anova_table.read_anova_row(anova_file, "year_chapter")
        fallback = latex_anova_table.read_anova_row(anova_file, "missing_effect")

        self.assertEqual(selected["FValue"], 200)
        self.assertEqual(selected["HypothesisType"], 1)
        self.assertEqual(fallback["FValue"], 100)
        self.assertEqual(fallback["HypothesisType"], 1)


if __name__ == "__main__":
    unittest.main()