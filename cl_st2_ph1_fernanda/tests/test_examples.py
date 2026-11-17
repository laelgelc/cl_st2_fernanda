import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "examples.py"
TOP_HEADER_PATH = PROJECT_DIR / "examples" / "top_header"
sys.path.insert(0, str(PROJECT_DIR))

import examples


class TestExamples(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="examples_test_")
        self.root = Path(self.temp_dir.name)
        self.phase_dir = self.root / "demo_project"
        self.phase_dir.mkdir()
        self.script = self.phase_dir / "examples.py"
        shutil.copy2(SCRIPT_PATH, self.script)
        self.working_dir = self.root / "elsewhere"
        self.working_dir.mkdir()
        self.write_inputs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_inputs(self, base=None):
        base = base or self.phase_dir
        project = base.name if base == self.phase_dir else "demo_project"
        sas_dir = base / "sas" / f"output_{project}"
        tagged_dir = base / "corpus" / "05_enade_tagged"
        factors_dir = base / "factors"
        examples_dir = base / "examples"
        sas_dir.mkdir(parents=True, exist_ok=True)
        factors_dir.mkdir(parents=True, exist_ok=True)
        for group in ("2020_c4", "2021_c5"):
            (tagged_dir / group).mkdir(parents=True, exist_ok=True)
            (tagged_dir / group / "same.txt").write_text(
                "Curso NOUN curso\n"
                "secundário ADJ secundário\n"
                "avaliação NOUN avaliação\n"
                ". PUNCT .\n",
                encoding="utf-8",
            )

        (sas_dir / f"{project}_scores_only.tsv").write_text(
            "filename\tyear_chapter\tfac1\n"
            "t000001\t2020_c4\t1\n"
            "t000002\t2020_c4\t0\n"
            "t000003\t2021_c5\t-1\n"
            "t000004\t2021_c5\t2\n",
            encoding="utf-8",
        )
        (sas_dir / "means_year_chapter_f1.tsv").write_text(
            "Effect\tyear_chapter\tN\tMean fac1\tSD fac1\n"
            "year_chapter\t2020_c4\t2\t1.5\t0.5\n"
            "year_chapter\t2021_c5\t2\t-1.5\t0.5\n",
            encoding="utf-8",
        )
        (factors_dir / "f1_pos.txt").write_text(
            "variables loading on this pole = 1\n"
            "curso (.90), (avaliação (.80))\n",
            encoding="utf-8",
        )
        (factors_dir / "f1_neg.txt").write_text(
            "variables loading on this pole = 1\n"
            "curso (.90), (avaliação (.80))\n",
            encoding="utf-8",
        )
        (base / "file_ids.txt").write_text(
            "t000001 2020_c4/same.txt\n"
            "t000002 2020_c4/same.txt\n"
            "t000003 2021_c5/same.txt\n"
            "t000004 2021_c5/same.txt\n",
            encoding="utf-8",
        )
        examples_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TOP_HEADER_PATH, examples_dir / "top_header")

    def run_script(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_defaults_use_phase_paths_and_generate_ranked_poles(self):
        result = self.run_script(
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        examples_dir = self.phase_dir / "examples"
        pos = sorted((examples_dir / "f1_pos").glob("*.tex"))
        neg = sorted((examples_dir / "f1_neg").glob("*.tex"))
        self.assertEqual(len(pos), 2)
        self.assertEqual(len(neg), 2)

        pos_top = pos[0].read_text(encoding="utf-8")
        pos_other = pos[1].read_text(encoding="utf-8")
        neg_top = neg[0].read_text(encoding="utf-8")
        neg_other = neg[1].read_text(encoding="utf-8")
        self.assertIn("2020\\_c4", pos_top)
        self.assertIn("2021\\_c5", pos_other)
        self.assertIn("2021\\_c5", neg_top)
        self.assertIn("2020\\_c4", neg_other)
        self.assertIn("Score 1.00", pos_top)
        self.assertIn("Score 2.00", pos_other)
        self.assertIn("Score -1.00", neg_top)
        self.assertIn("Score 1.00", neg_other)
        self.assertIn(r"\textbf{Curso}", pos_top)
        self.assertIn("avaliação", pos_top)
        self.assertNotIn(r"\textbf{avaliação}", pos_top)
        self.assertTrue((examples_dir / "examples.tex").is_file())
        self.assertFalse((self.phase_dir / "missing_files.txt").exists())

    def test_relative_path_overrides_resolve_from_phase(self):
        custom = self.phase_dir / "custom"
        self.write_inputs(custom)
        result = self.run_script(
            "--project", "demo_project",
            "--sas-output-dir", "custom/sas/output_demo_project",
            "--tagged-base", "custom/corpus/05_enade_tagged",
            "--factor-folder", "custom/factors",
            "--examples-dir", "custom/examples",
            "--file-ids", "custom/file_ids.txt",
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            len(list((custom / "examples" / "f1_pos").glob("*.tex"))), 2
        )

    def test_absolute_path_overrides_are_preserved(self):
        output_dir = self.root / "absolute-output"
        result = self.run_script(
            "--sas-output-dir", str(self.phase_dir / "sas" / "output_demo_project"),
            "--tagged-base", str(self.phase_dir / "corpus" / "05_enade_tagged"),
            "--factor-folder", str(self.phase_dir / "factors"),
            "--examples-dir", str(output_dir),
            "--file-ids", str(self.phase_dir / "file_ids.txt"),
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list((output_dir / "f1_neg").glob("*.tex"))), 2)

    def test_missing_means_file_is_reported(self):
        (self.phase_dir / "sas" / "output_demo_project" / "means_year_chapter_f1.tsv").unlink()

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Means file not found", result.stderr)

    def test_missing_tagged_file_report_is_written_in_phase_directory(self):
        missing_path = (
            self.phase_dir / "corpus" / "05_enade_tagged" / "2020_c4" / "same.txt"
        )
        missing_path.unlink()

        result = self.run_script(
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.phase_dir / "missing_files.txt").read_text(encoding="utf-8"),
            "t000001",
        )
        self.assertFalse((self.working_dir / "missing_files.txt").exists())

    def test_id_map_resolves_group_path_with_duplicate_basenames(self):
        id_map = examples.load_file_id_map(self.phase_dir / "file_ids.txt")
        row = examples.pd.Series({
            "filename": "t000003",
            "year_chapter": "2021_c5",
        })

        located = examples.locate_text(
            row,
            id_map,
            self.phase_dir / "corpus" / "05_enade_tagged",
            "year_chapter",
        )

        self.assertEqual(
            located,
            self.phase_dir / "corpus" / "05_enade_tagged" / "2021_c5" / "same.txt",
        )

    def test_primary_lemma_highlighting_preserves_portuguese_text(self):
        pole_file = self.phase_dir / "factors" / "f1_pos.txt"
        primary_lemmas = examples.load_primary_lemmas(pole_file)
        text_path = (
            self.phase_dir / "corpus" / "05_enade_tagged" / "2020_c4" / "same.txt"
        )

        paragraphs, matched = examples.annotate_text(text_path, primary_lemmas)

        self.assertEqual(primary_lemmas, {"curso"})
        self.assertEqual(matched, {"curso"})
        self.assertIn(r"\textbf{Curso}", " ".join(paragraphs))
        self.assertIn("avaliação", " ".join(paragraphs))
        self.assertNotIn(r"\textbf{avaliação}", " ".join(paragraphs))


if __name__ == "__main__":
    unittest.main()