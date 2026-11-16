import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import select_kws_stratified


HEADER = (
    "lemma\ttarget_count\tcomparison_count\ttarget_per_1k\t"
    "comparison_per_1k\texpected\tLL\tdiff_percent\tstatus\n"
)


def tsv_row(lemma, status="POSKW"):
    return f"{lemma}\t1\t2\t3\t4\t5\t6\t7\t{status}\n"


class TestSelectKwsStratified(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="select_kws_test_")
        self.root = Path(self.temp_dir.name)
        self.input_dir = self.root / "corpus" / "06_enade_keylemmas"
        self.output_dir = self.root / "corpus" / "07_enade_kw_selected"
        self.input_dir.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_tsv(self, group, rows):
        path = self.input_dir / f"{group}.tsv"
        path.write_text(HEADER + "".join(tsv_row(*row) for row in rows), encoding="utf-8")
        return path

    def run_selector(self, *arguments):
        args = [
            "--input", str(self.input_dir),
            "--output", str(self.output_dir),
            *arguments,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            return select_kws_stratified.main(args)

    def test_tsv_schema_filters_statuses_and_preserves_source_order(self):
        self.write_tsv("2009_c4", [
            ("administração", "POSKW"),
            ("vis-à-vis", "POSKW"),
            ("negative", "NEGKW"),
            ("notkeyword", "NOTKW"),
            ("Uppercase", "POSKW"),
            ("term2", "POSKW"),
            ("one!", "POSKW"),
            ("-hyphen", "POSKW"),
            ("hyphen-", "POSKW"),
            ("double--hyphen", "POSKW"),
            ("x", "POSKW"),
        ])

        self.run_selector("--per-group", "20")

        self.assertEqual(
            (self.output_dir / "2009_c4.txt").read_text(encoding="utf-8").splitlines(),
            ["administração", "vis-à-vis"],
        )
        self.assertEqual(
            (self.output_dir / "keywords.txt").read_text(encoding="utf-8").splitlines(),
            sorted(["administração", "vis-à-vis"]),
        )
        manifest = json.loads(
            (self.output_dir / "select_kws_stratified_run.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["groups"][0]["eligible_poskw"], 2)
        self.assertEqual(manifest["groups"][0]["selected"], 2)
        self.assertEqual(manifest["outputs"]["keywords.txt"]["line_count"], 2)
        self.assertEqual(len(manifest["groups"][0]["input_sha256"]), 64)

    def test_legacy_text_is_supported_and_tsv_takes_precedence(self):
        (self.input_dir / "2009_c4.txt").write_text(
            "lemma status\nlegacy POSKW\n", encoding="utf-8"
        )
        tsv_path = self.write_tsv("2009_c4", [("tabular", "POSKW")])

        discovered = select_kws_stratified.discover_keylemma_files(self.input_dir)
        self.assertEqual(discovered, [("2009_c4", tsv_path)])
        (self.input_dir / "2010_c1.txt").write_text(
            "lemma status\nlegacy POSKW\n", encoding="utf-8"
        )

        self.run_selector("--per-group", "5")

        self.assertEqual(
            (self.output_dir / "2009_c4.txt").read_text(encoding="utf-8"),
            "tabular\n",
        )
        self.assertEqual(
            (self.output_dir / "2010_c1.txt").read_text(encoding="utf-8"),
            "legacy\n",
        )

    def test_natural_order_quota_and_cap_before_deduplication(self):
        self.write_tsv("2010_c1", [("shared", "POSKW"), ("other", "POSKW")])
        self.write_tsv("2009_c10", [("shared", "POSKW"), ("zeta", "POSKW")])
        self.write_tsv("2009_c2", [("alpha", "POSKW"), ("shared", "POSKW")])

        self.run_selector("--per-group", "2", "--max-total", "3")

        self.assertEqual(
            (self.output_dir / "keywords.txt").read_text(encoding="utf-8").splitlines(),
            ["alpha", "shared"],
        )
        self.assertEqual(
            (self.output_dir / "2010_c1.txt").read_text(encoding="utf-8").splitlines(),
            ["shared", "other"],
        )
        manifest = json.loads(
            (self.output_dir / "select_kws_stratified_run.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [item["group"] for item in manifest["groups"]],
            ["2009_c2", "2009_c10", "2010_c1"],
        )
        self.assertEqual(manifest["counts"]["selected_occurrences_before_cap"], 6)
        self.assertEqual(manifest["counts"]["selected_occurrences_after_cap"], 3)
        self.assertEqual(manifest["counts"]["unique_keywords"], 2)

    def test_zero_cap_is_uncapped_and_forty_two_groups_select_at_most_210(self):
        for index in range(42):
            rows = [(f"lemma{suffix}", "POSKW") for suffix in "abcde"]
            self.write_tsv(f"{2000 + index}_c1", rows)

        self.run_selector("--per-group", "5", "--max-total", "0")

        manifest = json.loads(
            (self.output_dir / "select_kws_stratified_run.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["counts"]["group_count"], 42)
        self.assertEqual(manifest["counts"]["selected_occurrences_before_cap"], 210)
        self.assertEqual(manifest["counts"]["selected_occurrences_after_cap"], 210)
        self.assertEqual(manifest["counts"]["unique_keywords"], 5)

    def test_dry_run_does_not_create_output_or_its_parent(self):
        self.write_tsv("2009_c4", [("lemma", "POSKW")])
        absent_output = self.root / "not-created" / "selection"
        args = [
            "--input", str(self.input_dir),
            "--output", str(absent_output),
            "--per-group", "5",
            "--max-total", "220",
            "--dry-run",
        ]

        with contextlib.redirect_stdout(io.StringIO()):
            select_kws_stratified.main(args)

        self.assertFalse(absent_output.exists())
        self.assertFalse(absent_output.parent.exists())

    def test_missing_and_unusable_inputs_fail(self):
        missing = self.root / "missing"
        args = ["--input", str(missing), "--output", str(self.output_dir), "--per-group", "5"]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                select_kws_stratified.main(args)

        (self.input_dir / "keylemmas_run.json").write_text("{}", encoding="utf-8")
        args = ["--input", str(self.input_dir), "--output", str(self.output_dir), "--per-group", "5"]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                select_kws_stratified.main(args)
        self.assertFalse(self.output_dir.exists())

    def test_invalid_values_and_overlapping_paths_fail_before_writing(self):
        self.write_tsv("2009_c4", [("lemma", "POSKW")])
        base_args = ["--input", str(self.input_dir), "--output", str(self.output_dir)]
        for numeric_args in (["--per-group", "0"], ["--per-group", "1", "--max-total", "-1"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    select_kws_stratified.main(base_args + list(numeric_args))

        overlap_args = [
            "--input", str(self.input_dir),
            "--output", str(self.input_dir / "nested"),
            "--per-group", "1",
            "--dry-run",
        ]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                select_kws_stratified.main(overlap_args)
        self.assertFalse(self.output_dir.exists())
        self.assertFalse((self.input_dir / "nested").exists())

    def test_identical_rerun_is_a_noop_and_changed_input_is_preserved(self):
        source = self.write_tsv("2009_c4", [("lemma", "POSKW")])
        args = ["--per-group", "1"]
        self.run_selector(*args)
        original_files = {
            path.name: path.read_bytes() for path in self.output_dir.iterdir()
        }

        self.run_selector(*args)

        self.assertEqual(
            {path.name: path.read_bytes() for path in self.output_dir.iterdir()},
            original_files,
        )
        source.write_text(HEADER + tsv_row("changed", "POSKW"), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_selector(*args)
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.output_dir.iterdir()},
            original_files,
        )

    def test_unexpected_or_corrupted_existing_outputs_are_not_overwritten(self):
        self.write_tsv("2009_c4", [("lemma", "POSKW")])
        self.run_selector("--per-group", "1")
        unexpected = self.output_dir / "unexpected.txt"
        unexpected.write_text("keep", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_selector("--per-group", "1")
        self.assertEqual(unexpected.read_text(encoding="utf-8"), "keep")
        unexpected.unlink()

        output_file = self.output_dir / "keywords.txt"
        output_file.write_text("corrupted\n", encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_selector("--per-group", "1")
        self.assertEqual(output_file.read_text(encoding="utf-8"), "corrupted\n")


if __name__ == "__main__":
    unittest.main()