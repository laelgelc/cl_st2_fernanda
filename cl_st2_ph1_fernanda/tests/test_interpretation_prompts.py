import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "interpretation_prompts.py"


class TestInterpretationPrompts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="interpretation_prompts_test_")
        self.root = Path(self.temp_dir.name)
        self.phase_dir = self.root / "demo_phase"
        self.phase_dir.mkdir()
        self.script = self.phase_dir / "interpretation_prompts.py"
        shutil.copy2(SCRIPT_PATH, self.script)
        self.working_dir = self.root / "elsewhere"
        self.working_dir.mkdir()
        self.write_inputs(self.phase_dir, "demo_phase", "year_chapter", "default")

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def write_inputs(base, project, group, marker, sas_output_dir=None):
        factors_dir = base / "factors"
        examples_dir = base / "examples_txt" / "f1_pos"
        sas_dir = base / (sas_output_dir or f"sas/output_{project}")
        details_file = base / "examples" / "score_details.txt"
        factors_dir.mkdir(parents=True, exist_ok=True)
        examples_dir.mkdir(parents=True, exist_ok=True)
        sas_dir.mkdir(parents=True, exist_ok=True)
        details_file.parent.mkdir(parents=True, exist_ok=True)
        (factors_dir / "f1_pos.txt").write_text(
            f"loading_{marker} (.90)\n",
            encoding="utf-8",
        )
        (examples_dir / "f1_pos_001.txt").write_text(
            "Example metadata\n"
            "Text ID: t000001\n"
            "Corpo com uma evidência textual.\n",
            encoding="utf-8",
        )
        (sas_dir / f"means_{group}_f1.tsv").write_text(
            f"means for {marker}\n",
            encoding="utf-8",
        )
        details_file.write_text(
            "text ID: t000001\n"
            "f1 score: 2\n"
            "f1 pos words (N=2): ação, evidência\n",
            encoding="utf-8",
        )

    def run_script(self, *arguments):
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def write_score_details(path, records):
        lines = []
        for text_id, factor_details in records:
            lines.append(f"text ID: {text_id}")
            lines.extend(factor_details)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_defaults_are_phase_relative_from_an_external_working_directory(self):
        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Project: {self.phase_dir.name}", result.stdout)
        self.assertIn("Group: year_chapter", result.stdout)
        self.assertIn(
            f"SAS output directory: {self.phase_dir / 'sas' / 'output_demo_phase'}",
            result.stdout,
        )
        prompt = (self.phase_dir / "interpretation" / "input" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertIn("means for default", prompt)
        self.assertIn("ENADE course reports", prompt)
        self.assertIn("c4 (perception of the exam)", prompt)
        self.assertIn("c5 (distribution of concepts)", prompt)
        self.assertIn("c6 (technical analysis of the exam)", prompt)
        self.assertIn("do not necessarily correspond to literal chapter numbers", prompt)
        self.assertIn("year/chapter", prompt)
        self.assertIn("document-level", prompt)
        self.assertNotIn("Regional or group-level", prompt)

    def test_relative_path_overrides_resolve_from_the_phase_directory(self):
        self.write_inputs(
            self.phase_dir / "custom",
            "ignored",
            "custom_group",
            "relative",
            sas_output_dir="custom_sas",
        )

        result = self.run_script(
            "--project", "custom_project",
            "--group", "custom_group",
            "--sas-output-dir", "custom/custom_sas",
            "--factors-dir", "custom/factors",
            "--examples-dir", "custom/examples_txt",
            "--details-file", "custom/examples/score_details.txt",
            "--output-dir", "custom/output",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.phase_dir / "custom" / "output" / "f1_pos.txt").exists())
        prompt = (self.phase_dir / "custom" / "output" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertIn("means for relative", prompt)

    def test_project_and_group_overrides_select_default_means_directory(self):
        sas_dir = self.phase_dir / "sas" / "output_custom_project"
        sas_dir.mkdir(parents=True)
        (sas_dir / "means_custom_group_f1.tsv").write_text(
            "means for custom project and group\n",
            encoding="utf-8",
        )

        result = self.run_script(
            "--project", "custom_project",
            "--group", "custom_group",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"SAS output directory: {sas_dir}", result.stdout)
        prompt = (self.phase_dir / "interpretation" / "input" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertIn("means for custom project and group", prompt)

    def test_absolute_path_overrides_are_preserved(self):
        external = self.root / "absolute_inputs"
        self.write_inputs(external, "ignored", "year_chapter", "absolute")
        output_dir = self.root / "absolute_output"

        result = self.run_script(
            "--group", "year_chapter",
            "--sas-output-dir", str(external / "sas" / "output_ignored"),
            "--factors-dir", str(external / "factors"),
            "--examples-dir", str(external / "examples_txt"),
            "--details-file", str(external / "examples" / "score_details.txt"),
            "--output-dir", str(output_dir),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output_dir / "f1_pos.txt").exists())
        prompt = (output_dir / "f1_pos.txt").read_text(encoding="utf-8")
        self.assertIn("means for absolute", prompt)

    def test_multiple_factors_and_poles_keep_prompt_sections_and_document_words(self):
        factors_dir = self.phase_dir / "factors"
        (factors_dir / "f1_neg.txt").write_text("negative_loading (.88)\n", encoding="utf-8")
        (factors_dir / "f2_pos.txt").write_text("second_factor_loading (.77)\n", encoding="utf-8")
        (self.phase_dir / "sas" / "output_demo_phase" / "means_year_chapter_f2.tsv").write_text(
            "means for factor two\n",
            encoding="utf-8",
        )
        for factor_name, text_id, body in (
            ("f1_neg", "t000002", "Texto negativo."),
            ("f2_pos", "t000003", "Texto do segundo fator."),
        ):
            example_dir = self.phase_dir / "examples_txt" / factor_name
            example_dir.mkdir(parents=True)
            (example_dir / f"{factor_name}_001.txt").write_text(
                f"Text ID: {text_id}\n{body}\n",
                encoding="utf-8",
            )
        self.write_score_details(
            self.phase_dir / "examples" / "score_details.txt",
            [
                ("t000001", [
                    "f1 score: 2",
                    "f1 pos words (N=2): ação, evidência",
                    "f1 neg words (N=1): inversão",
                    "f2 score: 1",
                    "f2 pos words (N=1): segundo",
                ]),
                ("t000002", [
                    "f1 score: -2",
                    "f1 neg words (N=1): oposição",
                ]),
                ("t000003", [
                    "f2 score: 3",
                    "f2 pos words (N=1): análise",
                ]),
            ],
        )

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        prompts_dir = self.phase_dir / "interpretation" / "input"
        self.assertEqual(
            {path.name for path in prompts_dir.glob("*.txt")},
            {"f1_neg.txt", "f1_pos.txt", "f2_pos.txt"},
        )
        pos_prompt = (prompts_dir / "f1_pos.txt").read_text(encoding="utf-8")
        expected_sections = (
            "Interpret Factor f1 (pos) as a discourse dimension.",
            "=== MEAN YEAR_CHAPTER SCORES ===\nmeans for default",
            "=== FACTOR LOADINGS (f1_pos) ===\nloading_default (.90)",
            "===== EXCERPT: f1_pos_001.txt (text ID t000001) =====",
            "Loading words for this example (pos): ação, evidência",
        )
        positions = [pos_prompt.index(section) for section in expected_sections]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("equal weight to the loadings and the examples", pos_prompt)
        neg_prompt = (prompts_dir / "f1_neg.txt").read_text(encoding="utf-8")
        self.assertIn("Interpret Factor f1 (neg)", neg_prompt)
        self.assertIn("lowest means", neg_prompt)
        self.assertIn("Loading words for this example (neg): oposição", neg_prompt)
        second_factor_prompt = (prompts_dir / "f2_pos.txt").read_text(encoding="utf-8")
        self.assertIn("means for factor two", second_factor_prompt)
        self.assertIn("Loading words for this example (pos): análise", second_factor_prompt)
        written_names = [
            Path(line.removeprefix("Wrote: ")).name
            for line in result.stdout.splitlines()
            if line.startswith("Wrote:")
        ]
        self.assertEqual(written_names, ["f1_neg.txt", "f1_pos.txt", "f2_pos.txt"])

    def test_default_and_custom_excerpt_limits_and_full_file_id_detection(self):
        examples_dir = self.phase_dir / "examples_txt" / "f1_pos"
        for path in examples_dir.glob("*.txt"):
            path.unlink()
        detail_records = []
        for number in range(1, 13):
            text_id = f"t{number:06d}"
            lines = [f"example {number} line {line_number:02d}" for line_number in range(1, 36)]
            lines.extend((f"Text ID: {text_id}", "document body beyond excerpt"))
            (examples_dir / f"example_{number}.txt").write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )
            words = "document_word_acción" if number == 1 else f"document_word_{number}"
            detail_records.append((text_id, [
                "f1 score: 1",
                f"f1 pos words (N=1): {words}",
            ]))
        self.write_score_details(
            self.phase_dir / "examples" / "score_details.txt",
            detail_records,
        )

        default_result = self.run_script()

        self.assertEqual(default_result.returncode, 0, default_result.stderr)
        default_prompt = (self.phase_dir / "interpretation" / "input" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertEqual(default_prompt.count("===== EXCERPT:"), 10)
        self.assertIn("EXCERPT: example_10.txt (text ID t000010)", default_prompt)
        self.assertNotIn("EXCERPT: example_11.txt", default_prompt)
        self.assertIn("example 1 line 30", default_prompt)
        self.assertNotIn("example 1 line 31", default_prompt)
        self.assertIn("EXCERPT: example_1.txt (text ID t000001)", default_prompt)
        self.assertIn("Loading words for this example (pos): document_word_acción", default_prompt)
        example_excerpt = default_prompt.split("EXCERPT: example_1.txt", 1)[1].split(
            "--- Loading words", 1,
        )[0]
        self.assertNotIn("document_word_acción", example_excerpt)
        self.assertLess(
            default_prompt.index("EXCERPT: example_2.txt"),
            default_prompt.index("EXCERPT: example_10.txt"),
        )

        custom_result = self.run_script(
            "--excerpt-count", "2",
            "--excerpt-lines", "3",
            "--output-dir", "custom_output",
        )

        self.assertEqual(custom_result.returncode, 0, custom_result.stderr)
        custom_prompt = (self.phase_dir / "custom_output" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertEqual(custom_prompt.count("===== EXCERPT:"), 2)
        self.assertIn("example 1 line 03", custom_prompt)
        self.assertNotIn("example 1 line 04", custom_prompt)
        self.assertNotIn("EXCERPT: example_10.txt", custom_prompt)

    def test_missing_means_and_example_folder_use_warning_fallbacks(self):
        (self.phase_dir / "sas" / "output_demo_phase" / "means_year_chapter_f1.tsv").unlink()
        shutil.rmtree(self.phase_dir / "examples_txt" / "f1_pos")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Warning: missing means file", result.stdout)
        self.assertIn("Warning: missing example folder", result.stdout)
        prompt = (self.phase_dir / "interpretation" / "input" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertIn("(No means file found)", prompt)
        self.assertTrue(prompt.endswith("=== EXAMPLE EXCERPTS ===\n"))

    def test_missing_example_id_warns_and_skips_that_excerpt(self):
        example_file = self.phase_dir / "examples_txt" / "f1_pos" / "f1_pos_001.txt"
        example_file.write_text("No text identifier is present.\n", encoding="utf-8")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"Warning: no text ID found in {example_file}", result.stdout)
        prompt = (self.phase_dir / "interpretation" / "input" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertTrue(prompt.endswith("=== EXAMPLE EXCERPTS ===\n"))

    def test_missing_or_empty_document_word_lists_use_none_fallback(self):
        examples_dir = self.phase_dir / "examples_txt" / "f1_pos"
        (examples_dir / "f1_pos_002.txt").write_text(
            "Text ID: t000002\nSecond example.\n",
            encoding="utf-8",
        )
        self.write_score_details(
            self.phase_dir / "examples" / "score_details.txt",
            [("t000001", ["f1 score: 1", "f1 pos words (N=0):"])],
        )

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = (self.phase_dir / "interpretation" / "input" / "f1_pos.txt").read_text(
            encoding="utf-8",
        )
        self.assertEqual(prompt.count("Loading words for this example (pos): (none)"), 2)

    def test_missing_required_inputs_remain_fatal(self):
        cases = (
            (("--factors-dir", "missing_factors"), "Factors directory not found"),
            (("--examples-dir", "missing_examples"), "Examples directory not found"),
            (("--sas-output-dir", "missing_sas"), "SAS output directory not found"),
            (("--details-file", "missing_details.txt"), "Score details file not found"),
        )
        for arguments, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                result = self.run_script(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)


if __name__ == "__main__":
    unittest.main()