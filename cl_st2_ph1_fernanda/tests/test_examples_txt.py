import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "examples_txt.py"
LATEX_SCRIPT_PATH = PROJECT_DIR / "examples.py"
sys.path.insert(0, str(PROJECT_DIR))

import examples_txt


class TestExamplesTxt(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="examples_txt_test_")
        self.root = Path(self.temp_dir.name)
        self.phase_dir = self.root / "demo_project"
        self.phase_dir.mkdir()
        self.script = self.phase_dir / "examples_txt.py"
        shutil.copy2(SCRIPT_PATH, self.script)
        self.latex_script = self.phase_dir / "examples.py"
        shutil.copy2(LATEX_SCRIPT_PATH, self.latex_script)
        self.working_dir = self.root / "elsewhere"
        self.working_dir.mkdir()
        self.write_inputs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_inputs(self, base=None):
        base = base or self.phase_dir
        project = "demo_project"
        sas_dir = base / "sas" / f"output_{project}"
        tagged_dir = base / "corpus" / "05_enade_tagged"
        fulltext_dir = base / "corpus" / "04_enade"
        factors_dir = base / "factors"
        examples_dir = base / "examples"
        sas_dir.mkdir(parents=True, exist_ok=True)
        factors_dir.mkdir(parents=True, exist_ok=True)
        rows = [
            ("t000001", "2020_c4", 3),
            ("t000002", "2020_c4", 0),
            ("t000003", "2021_c5", -2),
            ("t000004", "2021_c5", 2),
        ]
        for text_id, group, _ in rows:
            for corpus_root in (tagged_dir, fulltext_dir):
                group_dir = corpus_root / group
                group_dir.mkdir(parents=True, exist_ok=True)
                (group_dir / "same.txt").write_text(
                    f"Chapter {group} text {text_id}\n",
                    encoding="utf-8",
                )

        scores = ["filename\tyear_chapter\tfac1"]
        scores.extend(f"{text_id}\t{group}\t{score}" for text_id, group, score in rows)
        (sas_dir / f"{project}_scores_only.tsv").write_text(
            "\n".join(scores) + "\n",
            encoding="utf-8",
        )
        (sas_dir / "means_year_chapter_f1.tsv").write_text(
            "Effect\tyear_chapter\tN\tMean fac1\tSD fac1\n"
            "year_chapter\t2020_c4\t2\t1.5\t0.5\n"
            "year_chapter\t2021_c5\t2\t-1.5\t0.5\n",
            encoding="utf-8",
        )
        (base / "file_ids.txt").write_text(
            "".join(f"{text_id} {group}/same.txt\n" for text_id, group, _ in rows),
            encoding="utf-8",
        )
        examples_dir.mkdir(parents=True, exist_ok=True)
        score_details = []
        for text_id, _, _ in rows:
            score_details.extend([
                "=============================================",
                f"text ID: {text_id}",
                "f1 pos words (N=1): alpha",
                "f1 neg words (N=1): beta",
            ])
        (examples_dir / "score_details.txt").write_text(
            "\n".join(score_details) + "\n",
            encoding="utf-8",
        )
        (factors_dir / "f1_pos.txt").write_text(
            "alpha (.90)\n",
            encoding="utf-8",
        )
        (factors_dir / "f1_neg.txt").write_text(
            "beta (.90)\n",
            encoding="utf-8",
        )

    def run_script(self, *arguments, script=None):
        return subprocess.run(
            [sys.executable, str(script or self.script), *arguments],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def plaintext_signature(output_dir, label):
        signature = []
        for path in sorted((output_dir / label).glob("*.txt")):
            text = path.read_text(encoding="utf-8")
            group = re.search(r"^year_chapter: (.+)$", text, re.MULTILINE).group(1)
            score = re.search(r"^Score \([^)]*\): (.+)$", text, re.MULTILINE).group(1)
            signature.append((group, float(score)))
        return signature

    @staticmethod
    def latex_signature(output_dir, label):
        signature = []
        for path in sorted((output_dir / label).glob("*.tex")):
            text = path.read_text(encoding="utf-8")
            match = re.search(r"Dim 1 – (.+?) – Score ([+-]?\d+\.\d+)", text)
            if match:
                signature.append((match.group(1).replace(r"\_", "_"), float(match.group(2))))
        return signature

    def test_defaults_match_latex_selection_for_both_poles_and_mapped_paths(self):
        text_result = self.run_script(
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )
        self.assertEqual(text_result.returncode, 0, text_result.stderr)

        latex_result = self.run_script(
            "--top-group-examples", "1",
            "--other-group-examples", "1",
            script=self.latex_script,
        )
        self.assertEqual(latex_result.returncode, 0, latex_result.stderr)

        for label in ("f1_pos", "f1_neg"):
            self.assertEqual(
                self.plaintext_signature(self.phase_dir / "examples_txt", label),
                self.latex_signature(self.phase_dir / "examples", label),
            )

        pos = sorted((self.phase_dir / "examples_txt" / "f1_pos").glob("*.txt"))
        neg = sorted((self.phase_dir / "examples_txt" / "f1_neg").glob("*.txt"))
        self.assertEqual(len(pos), 2)
        self.assertEqual(len(neg), 2)
        self.assertIn("Text ID: t000001", pos[0].read_text(encoding="utf-8"))
        self.assertIn("Text ID: t000004", pos[1].read_text(encoding="utf-8"))
        self.assertIn("Text ID: t000003", neg[0].read_text(encoding="utf-8"))
        self.assertIn("Score (f1_neg): 3", neg[1].read_text(encoding="utf-8"))
        self.assertIn("2021_c5/same.txt", pos[1].read_text(encoding="utf-8"))

    def test_default_quotas_keep_rank_order_and_exclude_zero_scores(self):
        sas_dir = self.phase_dir / "sas" / "output_demo_project"
        tagged_dir = self.phase_dir / "corpus" / "05_enade_tagged"
        fulltext_dir = self.phase_dir / "corpus" / "04_enade"
        groups = (("2022_c4", 3), ("2021_c5", 0), ("2020_c6", -3))
        rows = []
        for group, _ in groups:
            for score in range(-12, 13):
                text_id = f"t{len(rows) + 1:06d}"
                rows.append((text_id, group, score))
                for corpus_root in (tagged_dir, fulltext_dir):
                    group_dir = corpus_root / group
                    group_dir.mkdir(parents=True, exist_ok=True)
                    (group_dir / f"{text_id}.txt").write_text(
                        f"Text {text_id}\n",
                        encoding="utf-8",
                    )

        (sas_dir / "demo_project_scores_only.tsv").write_text(
            "filename\tyear_chapter\tfac1\n"
            + "".join(f"{text_id}\t{group}\t{score}\n" for text_id, group, score in rows),
            encoding="utf-8",
        )
        (sas_dir / "means_year_chapter_f1.tsv").write_text(
            "Effect\tyear_chapter\tN\tMean fac1\tSD fac1\n"
            "year_chapter\t2022_c4\t25\t3\t1\n"
            "year_chapter\t2021_c5\t25\t0\t1\n"
            "year_chapter\t2020_c6\t25\t-3\t1\n",
            encoding="utf-8",
        )
        (self.phase_dir / "file_ids.txt").write_text(
            "".join(f"{text_id} {group}/{text_id}.txt\n" for text_id, group, _ in rows),
            encoding="utf-8",
        )
        details = []
        for text_id, _, _ in rows:
            details.extend([
                "=============================================",
                f"text ID: {text_id}",
                "f1 pos words (N=1): alpha",
                "f1 neg words (N=1): beta",
            ])
        (self.phase_dir / "examples" / "score_details.txt").write_text(
            "\n".join(details) + "\n",
            encoding="utf-8",
        )

        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)

        expected_groups = {
            "f1_pos": {"2022_c4": 20, "2021_c5": 10, "2020_c6": 10},
            "f1_neg": {"2020_c6": 20, "2021_c5": 10, "2022_c4": 10},
        }
        for label, group_counts in expected_groups.items():
            paths = sorted((self.phase_dir / "examples_txt" / label).glob("*.txt"))
            self.assertEqual(len(paths), 40)
            selected_groups = []
            selected_scores = []
            for path in paths:
                text = path.read_text(encoding="utf-8")
                selected_groups.append(
                    re.search(r"^year_chapter: (.+)$", text, re.MULTILINE).group(1)
                )
                selected_scores.append(float(
                    re.search(r"^Score \([^)]*\): (.+)$", text, re.MULTILINE).group(1)
                ))
            self.assertEqual(
                {group: selected_groups.count(group) for group in group_counts},
                group_counts,
            )
            self.assertNotIn(0, selected_scores)
            top_group = "2022_c4" if label == "f1_pos" else "2020_c6"
            top_scores = [
                score for group, score in zip(selected_groups, selected_scores)
                if group == top_group
            ]
            self.assertEqual(top_scores, sorted(top_scores, reverse=label == "f1_pos"))
            if label == "f1_pos":
                self.assertTrue(any(score < 0 for score in top_scores))
            else:
                self.assertTrue(any(score > 0 for score in top_scores))

    def test_relative_path_overrides_resolve_from_phase_directory(self):
        custom = self.phase_dir / "custom"
        self.write_inputs(custom)
        result = self.run_script(
            "--project", "demo_project",
            "--sas-output-dir", "custom/sas/output_demo_project",
            "--tagged-base", "custom/corpus/05_enade_tagged",
            "--fulltext-root", "custom/corpus/04_enade",
            "--file-ids", "custom/file_ids.txt",
            "--score-details", "custom/examples/score_details.txt",
            "--output-dir", "custom/examples_txt",
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            len(list((custom / "examples_txt" / "f1_pos").glob("*.txt"))),
            2,
        )

    def test_absolute_path_overrides_are_preserved(self):
        output_dir = self.root / "absolute-output"
        result = self.run_script(
            "--sas-output-dir", str(self.phase_dir / "sas" / "output_demo_project"),
            "--tagged-base", str(self.phase_dir / "corpus" / "05_enade_tagged"),
            "--fulltext-root", str(self.phase_dir / "corpus" / "04_enade"),
            "--file-ids", str(self.phase_dir / "file_ids.txt"),
            "--score-details", str(self.phase_dir / "examples" / "score_details.txt"),
            "--output-dir", str(output_dir),
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list((output_dir / "f1_neg").glob("*.txt"))), 2)

    def test_missing_corpus_files_are_reported_in_phase_directory(self):
        (self.phase_dir / "corpus" / "05_enade_tagged" / "2020_c4" / "same.txt").unlink()
        (self.phase_dir / "corpus" / "04_enade" / "2021_c5" / "same.txt").unlink()

        result = self.run_script(
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (self.phase_dir / "missing_files.txt").read_text(encoding="utf-8"),
            "t000001\nt000003\nt000004",
        )
        self.assertFalse((self.working_dir / "missing_files.txt").exists())

    def test_missing_loading_words_report_and_empty_word_list_parsing(self):
        details_path = self.phase_dir / "examples" / "score_details.txt"
        details_path.write_text(
            "=============================================\n"
            "text ID: t000001\n"
            "f1 pos words (N=0):\n"
            "f1 neg words (N=1): alpha\n"
            "=============================================\n"
            "text ID: t000004\n"
            "f1 pos words (N=1): beta\n"
            "f1 neg words (N=1): gamma\n",
            encoding="utf-8",
        )
        parsed = examples_txt.parse_score_details(details_path, num_factors=1)
        self.assertEqual(parsed["t000001"]["f1_pos"], [])
        self.assertEqual(parsed["t000001"]["f1_neg"], ["alpha"])

        result = self.run_script(
            "--top-group-examples", "1",
            "--other-group-examples", "1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = (self.phase_dir / "missing_loading_words.txt").read_text(encoding="utf-8")
        self.assertIn("t000003\tf1_neg", report)
        self.assertFalse((self.working_dir / "missing_loading_words.txt").exists())


if __name__ == "__main__":
    unittest.main()