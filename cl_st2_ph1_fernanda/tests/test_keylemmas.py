import csv
import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import keylemmas


class KeyLemmaFixture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="keylemma fixture ")
        self.phase = Path(self.temp_dir.name) / "phase with spaces é"
        self.tagged_root = self.phase / "corpus/05_enade_tagged"
        self.tagged_root.mkdir(parents=True)
        (self.phase / "keylemmas_pos.txt").write_text(
            "# selected categories\nNOUN\nVERB\nADJ\n", encoding="utf-8"
        )
        (self.phase / "keylemmas_stopwords.txt").write_text(
            "# intentionally empty\n", encoding="utf-8"
        )
        self.manifest = self.phase / "corpus/05_enade_tagged/enade_tagged_corpus.ndjson"
        self.records = []
        self.add_file(
            "2009", "c4", "same.txt",
            'Casa\tNOUN.Masc.Sing\tcasa\n'
            'CASA\tNOUN.Plur\tCASA\n'
            'maçã\tNOUN\tmac\u0327a\u0303\n'
            'surface\tVERB\t<unknown>\n'
            'a\tNOUN\ta\n'
            'prefix\tNOUNX\tprefix\n'
            'ignore\tADV\tignored\n'
            'dis"curso\tADJ\tdis"curso\n'
            'targetonly\tVERB\ttargetonly\n',
        )
        self.add_file("2009", "c4", "empty.txt", "")
        self.add_file(
            "2010", "c4", "same.txt",
            "Casa\tNOUN.Masc.Sing\tcasa\nbanana\tNOUN\tbanana\n",
        )
        self.write_manifest()

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_file(self, year, chapter, filename, content, *, path=None):
        relative = path or f"corpus/05_enade_tagged/{year}_{chapter}/{filename}"
        target = self.phase / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        target.write_bytes(data)
        self.records.append({
            "year": year,
            "chapter": chapter,
            "target_subdirectory": f"{year}_{chapter}",
            "filename": filename,
            "tagged_chapter_path": relative,
            "tagged_sha256": hashlib.sha256(data).hexdigest(),
            "tagged_size_bytes": len(data),
            "status": "success",
        })
        return target

    def write_manifest(self, records=None):
        values = self.records if records is None else records
        self.manifest.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values),
            encoding="utf-8",
        )

    def prepare(self, output="corpus/06_enade_keylemmas"):
        return keylemmas.prepare_run(
            self.manifest,
            self.phase / "keylemmas_pos.txt",
            self.phase / "keylemmas_stopwords.txt",
            self.phase,
            output,
        )

    def tsv_rows(self, outputs, name):
        return list(csv.DictReader(
            outputs[name].decode("utf-8").splitlines(), delimiter="\t"
        ))


class KeyLemmaTests(KeyLemmaFixture):
    def test_group_rest_counts_filters_normalization_and_fallback(self):
        outputs, summary = self.prepare()
        self.assertEqual(summary["groups"], 2)
        self.assertEqual(summary["files"], 3)
        rows = {row["lemma"]: row for row in self.tsv_rows(outputs, "2009_c4.tsv")}
        self.assertIn("banana", rows)
        self.assertEqual(rows["banana"]["target_present_files"], "0")
        self.assertEqual(rows["banana"]["comparison_present_files"], "1")
        self.assertEqual(rows["casa"]["target_present_files"], "1")
        self.assertEqual(rows["casa"]["target_total_files"], "2")
        self.assertEqual(rows["casa"]["comparison_total_files"], "1")
        self.assertIn("maçã", rows)
        self.assertIn("surface", rows)
        self.assertIn('dis"curso', rows)
        self.assertIn("targetonly", rows)
        self.assertNotIn("ignored", rows)
        self.assertNotIn("prefix", rows)
        self.assertNotIn("a", rows)
        self.assertEqual(summary["candidate_lemmas"], len(rows))
        self.assertIn(b'"dis""curso"', outputs["2009_c4.tsv"])

    def test_configurable_pos_and_normalized_stopwords(self):
        (self.phase / "keylemmas_pos.txt").write_text("VERB\n", encoding="utf-8")
        (self.phase / "keylemmas_stopwords.txt").write_text("# list\n  SURFACE  \n", encoding="utf-8")
        outputs, _ = self.prepare()
        rows = {row["lemma"] for row in self.tsv_rows(outputs, "2009_c4.tsv")}
        self.assertIn("targetonly", rows)
        self.assertNotIn("surface", rows)
        self.assertNotIn("casa", rows)

    def test_same_basename_in_different_groups_is_valid_and_distinct(self):
        outputs, _ = self.prepare()
        self.assertIn("2009_c4.tsv", outputs)
        self.assertIn("2010_c4.tsv", outputs)

    def test_g2_hand_calculation_zero_cells_and_equal_rates(self):
        self.assertAlmostEqual(keylemmas.g2_statistic(3, 4, 1, 6), 3.5548176768, places=9)
        self.assertGreater(keylemmas.g2_statistic(0, 3, 1, 4), 0)
        self.assertGreater(keylemmas.g2_statistic(2, 4, 0, 3), 0)
        self.assertEqual(keylemmas.g2_statistic(2, 4, 1, 2), 0.0)
        self.assertEqual(keylemmas.g2_statistic(4, 4, 2, 2), 0.0)

    def test_provenance_and_tsv_are_deterministic(self):
        outputs1, _ = self.prepare()
        outputs2, _ = self.prepare()
        self.assertEqual(outputs1, outputs2)
        provenance = json.loads(outputs1["keylemmas_run.json"])
        self.assertEqual(provenance["validated_file_count"], 3)
        self.assertEqual(provenance["groups"][0]["comparison_files"], 1)
        self.assertTrue(
            provenance["groups"][0]["tsv_path"].startswith("corpus/06_enade_keylemmas/")
        )
        self.assertIn("not applied", provenance["method"])

    def test_output_path_override_is_recorded(self):
        outputs, _ = self.prepare("corpus/custom output")
        provenance = json.loads(outputs["keylemmas_run.json"])
        self.assertEqual(provenance["groups"][0]["tsv_path"], "corpus/custom output/2009_c4.tsv")

    def test_manifest_order_does_not_change_group_or_tsv_order(self):
        first, _ = self.prepare()
        self.write_manifest(list(reversed(self.records)))
        second, _ = self.prepare()
        self.assertEqual(
            [name for name in first if name.endswith(".tsv")],
            [name for name in second if name.endswith(".tsv")],
        )
        for name in ("2009_c4.tsv", "2010_c4.tsv"):
            self.assertEqual(first[name], second[name])

    def test_manifest_duplicate_path_and_duplicate_output_identity_rejected(self):
        duplicate_path = self.records + [dict(self.records[0])]
        self.write_manifest(duplicate_path)
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "duplicate tagged path"):
            self.prepare()

        alternate = dict(self.records[0])
        alternate_path = self.tagged_root / "2009_c4/alternate.txt"
        alternate_path.write_text("new\tNOUN\tnew\n", encoding="utf-8")
        alternate["tagged_chapter_path"] = alternate_path.relative_to(self.phase).as_posix()
        alternate["tagged_sha256"] = hashlib.sha256(alternate_path.read_bytes()).hexdigest()
        alternate["tagged_size_bytes"] = alternate_path.stat().st_size
        self.write_manifest(self.records + [alternate])
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "duplicate output identity"):
            self.prepare()

    def test_bad_status_hash_size_and_missing_fields_rejected(self):
        for field, value, message in (
            ("status", "failed", "status must be 'success'"),
            ("tagged_sha256", "bad", "invalid tagged_sha256"),
            ("tagged_size_bytes", True, "non-negative integer"),
        ):
            records = [dict(row) for row in self.records]
            records[0][field] = value
            self.write_manifest(records)
            with self.subTest(field=field), self.assertRaisesRegex(keylemmas.KeyLemmaError, message):
                self.prepare()
        record = dict(self.records[0])
        del record["filename"]
        self.write_manifest([record, *self.records[1:]])
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "missing required fields"):
            self.prepare()

    def test_hash_mismatch_path_traversal_and_single_group_rejected(self):
        records = [dict(row) for row in self.records]
        records[0]["tagged_sha256"] = "0" * 64
        self.write_manifest(records)
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "does not match manifest"):
            self.prepare()

        records = [dict(row) for row in self.records]
        records[0]["tagged_chapter_path"] = "corpus/05_enade_tagged/../escaped.txt"
        self.write_manifest(records)
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "must not escape"):
            self.prepare()

        self.write_manifest(self.records[:2])
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "At least two distinct"):
            self.prepare()

    def test_symlink_escape_is_rejected(self):
        outside = self.phase / "outside.txt"
        outside.write_text("x\tNOUN\tx\n", encoding="utf-8")
        link = self.tagged_root / "2009_c4/linked.txt"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable")
        data = outside.read_bytes()
        record = dict(self.records[0])
        record.update({
            "filename": "linked.txt",
            "tagged_chapter_path": "corpus/05_enade_tagged/2009_c4/linked.txt",
            "tagged_sha256": hashlib.sha256(data).hexdigest(),
            "tagged_size_bytes": len(data),
        })
        self.write_manifest([record, *self.records[1:]])
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, "escapes"):
            self.prepare()

    def test_malformed_row_reports_path_and_line(self):
        path = self.phase / self.records[0]["tagged_chapter_path"]
        path.write_text("ok\tNOUN\tok\nmalformed\tNOUN\n", encoding="utf-8")
        data = path.read_bytes()
        records = [dict(row) for row in self.records]
        records[0]["tagged_sha256"] = hashlib.sha256(data).hexdigest()
        records[0]["tagged_size_bytes"] = len(data)
        self.write_manifest(records)
        with self.assertRaisesRegex(keylemmas.KeyLemmaError, r"2009_c4/same.txt:2"):
            self.prepare()

    def test_dry_run_creates_nothing_and_relative_paths_ignore_cwd(self):
        other = self.phase.parent / "elsewhere"
        other.mkdir()
        output = self.phase / "corpus/06_enade_keylemmas"
        stdout = StringIO()
        original_cwd = Path.cwd()
        try:
            os.chdir(other)
            with patch.object(keylemmas, "PHASE_DIR", self.phase), redirect_stdout(stdout):
                result = keylemmas.main(["--dry-run"])
        finally:
            os.chdir(original_cwd)
        self.assertEqual(result, 0)
        self.assertFalse(output.exists())
        self.assertIn("Dry run complete", stdout.getvalue())

    def test_publish_rerun_is_noop_and_conflicts_are_preserved(self):
        outputs, _ = self.prepare()
        destination = self.phase / "corpus/06_enade_keylemmas"
        self.assertIn("published", keylemmas.publish_outputs(destination, outputs))
        before = {path.name: path.read_bytes() for path in destination.iterdir()}
        self.assertIn("no changes", keylemmas.publish_outputs(destination, outputs))
        self.assertEqual(before, {path.name: path.read_bytes() for path in destination.iterdir()})

        (destination / "unexpected.txt").write_text("preserve", encoding="utf-8")
        with self.assertRaises(keylemmas.OutputConflict):
            keylemmas.publish_outputs(destination, outputs)
        self.assertEqual((destination / "unexpected.txt").read_text(encoding="utf-8"), "preserve")

    def test_failed_publication_keeps_existing_destination_and_staging(self):
        outputs, _ = self.prepare()
        destination = self.phase / "corpus/failure-output"
        def fail_after_destination_appears(staging, target):
            target.mkdir()
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            raise OSError("injected publication failure")

        with patch.object(
            keylemmas, "atomic_publish_no_replace", side_effect=fail_after_destination_appears
        ):
            with self.assertRaisesRegex(keylemmas.KeyLemmaError, "Staging directory retained"):
                keylemmas.publish_outputs(destination, outputs)
        marker = destination / "keep.txt"
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        staging = list(destination.parent.glob(f".{destination.name}.staging-*"))
        self.assertEqual(len(staging), 1)


if __name__ == "__main__":
    unittest.main()