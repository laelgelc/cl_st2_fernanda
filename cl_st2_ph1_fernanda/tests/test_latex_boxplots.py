import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import latex_boxplots.latex_boxplots as latex_boxplots


class TestLatexBoxplots(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="latex_boxplots_test_")
        self.root = Path(self.temp_dir.name)
        self.sas_dir = self.root / "sas"
        self.sas_dir.mkdir()
        self.output_dir = self.root / "output"
        self.scores_file = self.sas_dir / "demo_scores_only.tsv"
        self.write_scores()
        self.write_params("year_chapter", 1, 0.978809)
        self.write_params("year_chapter", 2, 0.5)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_scores(self, rows=None):
        rows = rows if rows is not None else [
            ("2009_c10", "2009_c10", 7, 0.7),
            ("2009_c10", "2009_c10", "", 0.6),
            ("2009_c2", "2009_c2", 1, 0.1),
            ("2009_c2", "2009_c2", 2, 0.2),
            ("2009_c2", "2009_c2", 3, 0.3),
            ("2009_c2", "2009_c2", 4, 0.4),
            ("2009_c2", "2009_c2", 100, 0.5),
        ]
        content = ["year_chapter\tgroup\tfac1\tfac2"]
        content.extend("\t".join(map(str, row)) for row in rows)
        self.scores_file.write_text("\n".join(content) + "\n", encoding="utf-8")

    def write_params(self, model_group, dim, rsquare, dependent=None):
        path = self.sas_dir / f"params_{model_group}_f{dim}.tsv"
        headers = ["Dependent", "RSquare"] if dependent is not False else ["RSquare"]
        values = [dependent or f"fac{dim}", rsquare] if dependent is not False else [rsquare]
        path.write_text(
            "\t".join(headers) + "\n" + "\t".join(map(str, values)) + "\n",
            encoding="utf-8",
        )
        return path

    def run_plotter(self, *arguments):
        args = [
            "--project", "demo",
            "--sas-output-dir", str(self.sas_dir),
            "--output-dir", str(self.output_dir),
            *arguments,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            return latex_boxplots.main(args)

    def run_phase_plotter(self, *arguments):
        args = ["--phase-dir", str(self.root), "--project", "demo", *arguments]
        with contextlib.redirect_stdout(io.StringIO()):
            return latex_boxplots.main(args)

    def test_default_maps_year_chapter_models_and_preserves_plot_statistics(self):
        self.run_plotter()

        factor_plot = (self.output_dir / "boxplot_f1_by_group.tex").read_text(encoding="utf-8")
        self.assertIn(r"R² = 97.88\%", factor_plot)
        self.assertLess(factor_plot.index(r"2009\_c2"), factor_plot.index(r"2009\_c10"))
        self.assertIn("lower whisker=1.0", factor_plot)
        self.assertIn("lower quartile=2.0", factor_plot)
        self.assertIn("median=3.0", factor_plot)
        self.assertIn("upper quartile=4.0", factor_plot)
        self.assertIn("upper whisker=7.0", factor_plot)
        self.assertIn("coordinates {(1,100.0)}", factor_plot)
        self.assertIn("coordinates {(1,22.0)}", factor_plot)
        mosaic = (self.output_dir / "mosaic_by_group.tex").read_text(encoding="utf-8")
        self.assertEqual(mosaic.count(r"\begin{tikzpicture}"), 2)

    def test_group_alias_can_use_explicit_matching_model_group(self):
        self.run_plotter("--group-column", "group", "--params-group", "year_chapter")

        factor_plot = (self.output_dir / "boxplot_f1_by_group.tex").read_text(encoding="utf-8")
        self.assertIn(r"R² = 97.88\%", factor_plot)

    def test_parameter_rsquare_and_dependent_metadata_are_validated(self):
        path = self.write_params("year_chapter", 1, "not-a-number")
        with self.assertRaisesRegex(ValueError, "RSquare"):
            latex_boxplots.read_rsquare(path, 1)

        path = self.write_params("year_chapter", 1, 0.9, dependent="fac2")
        with self.assertRaisesRegex(ValueError, "Dependent"):
            latex_boxplots.read_rsquare(path, 1)

        path = self.write_params("year_chapter", 1, "nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            latex_boxplots.read_rsquare(path, 1)

        path = self.write_params("year_chapter", 1, 0.9, dependent=False)
        self.assertEqual(latex_boxplots.read_rsquare(path, 1), 90.0)

    def test_missing_parameter_file_is_not_treated_as_zero(self):
        with self.assertRaises(FileNotFoundError):
            latex_boxplots.read_rsquare(self.sas_dir / "missing.tsv", 1)

    def test_missing_scores_file_is_rejected(self):
        self.scores_file.unlink()

        with self.assertRaises(FileNotFoundError):
            self.run_plotter()

    def test_nonnumeric_factor_values_are_rejected(self):
        self.write_scores([
            ("2009_c2", "2009_c2", "not-numeric", 0.2),
            ("2009_c2", "2009_c2", 2, 0.3),
        ])

        with self.assertRaisesRegex(ValueError, "numeric"):
            self.run_plotter()

    def test_group_without_usable_factor_values_is_rejected(self):
        self.write_scores([
            ("2009_c2", "2009_c2", "", 0.2),
            ("2009_c2", "2009_c2", "", 0.3),
        ])

        with self.assertRaisesRegex(ValueError, "2009_c2"):
            self.run_plotter()

    def test_blank_group_labels_are_rejected(self):
        self.write_scores([
            ("", "2009_c2", 1, 0.2),
        ])

        with self.assertRaisesRegex(ValueError, "group"):
            self.run_plotter()

    def test_relative_overrides_resolve_from_phase_directory(self):
        self.run_phase_plotter("--sas-output-dir", "sas", "--output-dir", "relative-plots")

        self.assertTrue((self.root / "relative-plots" / "mosaic_by_group.tex").is_file())

    def test_default_paths_resolve_from_phase_directory(self):
        phase = self.root / "phase"
        sas_dir = phase / "sas" / "output_demo"
        sas_dir.mkdir(parents=True)
        (sas_dir / "demo_scores_only.tsv").write_bytes(self.scores_file.read_bytes())
        for dim in (1, 2):
            source = self.sas_dir / f"params_year_chapter_f{dim}.tsv"
            target = sas_dir / source.name
            target.write_bytes(source.read_bytes())

        with contextlib.redirect_stdout(io.StringIO()):
            latex_boxplots.main(["--phase-dir", str(phase), "--project", "demo"])

        self.assertTrue((phase / "latex_boxplots" / "slides" / "mosaic_by_group.tex").is_file())

    def test_dry_run_writes_no_output(self):
        self.run_phase_plotter(
            "--sas-output-dir", "sas", "--output-dir", "dry-run-plots", "--dry-run"
        )

        self.assertFalse((self.root / "dry-run-plots").exists())

    def test_identical_rerun_reuses_complete_output_set(self):
        self.run_plotter()
        before = {
            path.name: path.read_bytes()
            for path in self.output_dir.iterdir()
        }

        self.run_plotter()

        self.assertEqual(
            {path.name: path.read_bytes() for path in self.output_dir.iterdir()},
            before,
        )

    def test_partial_output_is_rejected_and_preserved(self):
        self.output_dir.mkdir()
        existing = self.output_dir / "boxplot_f1_by_group.tex"
        existing.write_text("partial result\n", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "incomplete"):
            self.run_plotter()

        self.assertEqual(existing.read_text(encoding="utf-8"), "partial result\n")
        self.assertEqual({path.name for path in self.output_dir.iterdir()}, {existing.name})

    def test_conflicting_complete_output_set_is_rejected_and_preserved(self):
        self.run_plotter()
        factor_plot = self.output_dir / "boxplot_f1_by_group.tex"
        factor_plot.write_text("conflicting result\n", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "conflicts"):
            self.run_plotter()

        self.assertEqual(factor_plot.read_text(encoding="utf-8"), "conflicting result\n")

    def test_outputs_cannot_collide_with_inputs(self):
        with self.assertRaisesRegex(ValueError, "overwrite an input"):
            latex_boxplots.validate_output_paths(
                {"collision": self.scores_file}, {self.scores_file}
            )


if __name__ == "__main__":
    unittest.main()