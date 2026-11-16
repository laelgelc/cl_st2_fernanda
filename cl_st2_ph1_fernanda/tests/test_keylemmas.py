import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import keylemmas


class TestKeylemmas(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="keylemmas_test_")
        self.root = Path(self.temp_dir.name)
        self.input_dir = self.root / "corpus" / "05_enade_tagged"
        self.output_dir = self.root / "corpus" / "06_enade_keylemmas"

        self.group1_dir = self.input_dir / "2009_c4"
        self.group2_dir = self.input_dir / "2011_c6"
        self.group1_dir.mkdir(parents=True, exist_ok=True)
        self.group2_dir.mkdir(parents=True, exist_ok=True)

        # Sample tagged files
        # File 1 in 2009_c4: administration, pedagogy, assess
        (self.group1_dir / "doc1.txt").write_text(
            "A\tART\to\n"
            "administração\tNC\tadministração\n"
            "pedagógica\tADJ\tpedagógico\n"
            "avalia\tVPI\tavaliar\n"
            "x\tNC\tx\n"  # < 2 alpha chars -> filtered
            "brasil\tNP\tbrasil\n"  # stopword -> filtered
            "unidade\tNC\t<unknown>\n",  # unknown lemma -> fallback to word
            encoding="utf-8",
        )
        (self.group1_dir / "doc2.txt").write_text(
            "administração\tNC\tadministração\n"
            "currículo\tNC\tcurrículo\n",
            encoding="utf-8",
        )

        # File 1 & 2 in 2011_c6
        (self.group2_dir / "doc3.txt").write_text(
            "avalia\tVPI\tavaliar\n"
            "currículo\tNC\tcurrículo\n",
            encoding="utf-8",
        )
        (self.group2_dir / "doc4.txt").write_text(
            "currículo\tNC\tcurrículo\n"
            "avaliação\tNC\tavaliação\n",
            encoding="utf-8",
        )

        # Pos config
        self.pos_config_path = self.root / "keylemmas_pos.txt"
        self.pos_config_path.write_text(
            "# Content words\nNC\nVPI\nADJ\n",
            encoding="utf-8",
        )

        # Stopwords config
        self.stopwords_path = self.root / "keylemmas_stopwords.txt"
        self.stopwords_path.write_text(
            "# Stopwords\nbrasil\n",
            encoding="utf-8",
        )

        # Manifest
        self.manifest_path = self.input_dir / "enade_tagged_corpus.ndjson"
        manifest_rows = [
            {
                "year": "2009",
                "chapter": "c4",
                "target_subdirectory": "2009_c4",
                "tagged_chapter_path": str(self.group1_dir / "doc1.txt"),
                "status": "TAGGED",
            },
            {
                "year": "2009",
                "chapter": "c4",
                "target_subdirectory": "2009_c4",
                "tagged_chapter_path": str(self.group1_dir / "doc2.txt"),
                "status": "TAGGED",
            },
            {
                "year": "2011",
                "chapter": "c6",
                "target_subdirectory": "2011_c6",
                "tagged_chapter_path": str(self.group2_dir / "doc3.txt"),
                "status": "TAGGED",
            },
            {
                "year": "2011",
                "chapter": "c6",
                "target_subdirectory": "2011_c6",
                "tagged_chapter_path": str(self.group2_dir / "doc4.txt"),
                "status": "TAGGED",
            },
        ]
        self.manifest_path.write_text(
            "".join(json.dumps(r) + "\n" for r in manifest_rows),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_statistical_ll_and_diff(self):
        # Invariance of ll calculation
        val = keylemmas.ll(42, 180, 50, 982)
        self.assertAlmostEqual(val, 56.81, places=1)

        # Zero count edge cases
        self.assertEqual(keylemmas.ll(0, 10, 50, 100), 0.0)
        self.assertEqual(keylemmas.ll(10, 0, 50, 100), 0.0)
        self.assertEqual(keylemmas.ll(0, 0, 50, 100), 0.0)
        self.assertEqual(keylemmas.ll(10, 10, 0, 0), 0.0)

        # Percent diff
        self.assertEqual(keylemmas.calculate_diff_percent(0.0, 0.0), 0.0)
        self.assertAlmostEqual(keylemmas.calculate_diff_percent(840.0, 185.57), 127.62, places=1)
        self.assertAlmostEqual(keylemmas.calculate_diff_percent(100.0, 350.52), -111.21, places=1)

        # Classification
        self.assertEqual(keylemmas.classify_status(10.0, 50.0), "POSKW")
        self.assertEqual(keylemmas.classify_status(10.0, -50.0), "NEGKW")
        self.assertEqual(keylemmas.classify_status(2.0, 50.0), "NOTKW")
        self.assertEqual(keylemmas.classify_status(2.0, -50.0), "NOTKW")

    def test_load_configs(self):
        prefixes, sha_pos = keylemmas.load_pos_config(self.pos_config_path)
        self.assertEqual(prefixes, ("NC", "VPI", "ADJ"))
        self.assertTrue(len(sha_pos) == 64)

        stopwords, sha_stop = keylemmas.load_stopwords_config(self.stopwords_path)
        self.assertEqual(stopwords, {"brasil"})
        self.assertTrue(len(sha_stop) == 64)

        # Missing config handling
        with self.assertRaises(keylemmas.KeylemmasError):
            keylemmas.load_pos_config(self.root / "nonexistent.txt")

    def test_parse_document_lemmas(self):
        prefixes = ("NC", "VPI", "ADJ")
        stopwords = {"brasil"}
        doc1 = self.group1_dir / "doc1.txt"

        lemmas = keylemmas.parse_document_lemmas(doc1, prefixes, stopwords)
        self.assertIn("administração", lemmas)
        self.assertIn("pedagógico", lemmas)
        self.assertIn("avaliar", lemmas)
        self.assertIn("unidade", lemmas)  # from <unknown> fallback
        self.assertNotIn("brasil", lemmas)  # stopword
        self.assertNotIn("x", lemmas)  # length < 2
        self.assertNotIn("o", lemmas)  # ART prefix not in NC/VPI/ADJ

    def test_discover_documents_manifest_and_fallback(self):
        # From manifest
        groups_manifest = keylemmas.discover_documents(self.input_dir, self.manifest_path)
        self.assertEqual(list(groups_manifest.keys()), ["2009_c4", "2011_c6"])
        self.assertEqual(len(groups_manifest["2009_c4"]), 2)
        self.assertEqual(len(groups_manifest["2011_c6"]), 2)

        # Fallback (without manifest)
        groups_fallback = keylemmas.discover_documents(self.input_dir, None)
        self.assertEqual(list(groups_fallback.keys()), ["2009_c4", "2011_c6"])
        self.assertEqual(len(groups_fallback["2009_c4"]), 2)
        self.assertEqual(len(groups_fallback["2011_c6"]), 2)

    def test_dry_run(self):
        code = keylemmas.run_pipeline(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            input_manifest=self.manifest_path,
            pos_config_path=self.pos_config_path,
            stopwords_path=self.stopwords_path,
            cutoff_percent=0.0,
            dry_run=True,
        )
        self.assertEqual(code, 0)
        self.assertFalse(self.output_dir.exists())

    def test_full_pipeline_run(self):
        code = keylemmas.run_pipeline(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            input_manifest=self.manifest_path,
            pos_config_path=self.pos_config_path,
            stopwords_path=self.stopwords_path,
            cutoff_percent=0.0,
            dry_run=False,
        )
        self.assertEqual(code, 0)
        self.assertTrue((self.output_dir / "2009_c4.tsv").is_file())
        self.assertTrue((self.output_dir / "2011_c6.tsv").is_file())
        self.assertTrue((self.output_dir / "keylemmas_run.json").is_file())

        # Inspect TSV
        tsv_text = (self.output_dir / "2009_c4.tsv").read_text(encoding="utf-8")
        lines = tsv_text.strip().split("\n")
        self.assertEqual(
            lines[0],
            "lemma\ttarget_count\tcomparison_count\ttarget_per_1k\tcomparison_per_1k\texpected\tLL\tdiff_percent\tstatus",
        )
        # Verify content lines
        data_rows = [line.split("\t") for line in lines[1:]]
        lemmas_in_output = [r[0] for r in data_rows]
        self.assertIn("administração", lemmas_in_output)

        # Inspect Manifest
        manifest = json.loads((self.output_dir / "keylemmas_run.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["total_documents"], 4)
        self.assertEqual(manifest["total_groups"], 2)
        self.assertIn("2009_c4", manifest["groups"])
        self.assertIn("2011_c6", manifest["groups"])
        self.assertEqual(manifest["groups"]["2009_c4"]["target_documents"], 2)
        self.assertEqual(manifest["groups"]["2009_c4"]["comparison_documents"], 2)

    def test_cutoff_filtering(self):
        # 2 documents in target. Cutoff 60% requires >= 1.2 texts -> must appear in 2 documents.
        # "administração" is in 2 docs, "pedagógico" is in 1 doc.
        code = keylemmas.run_pipeline(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            input_manifest=self.manifest_path,
            pos_config_path=self.pos_config_path,
            stopwords_path=self.stopwords_path,
            cutoff_percent=60.0,
            dry_run=False,
        )
        self.assertEqual(code, 0)
        tsv_text = (self.output_dir / "2009_c4.tsv").read_text(encoding="utf-8")
        lines = tsv_text.strip().split("\n")
        data_rows = [line.split("\t") for line in lines[1:]]
        lemmas_in_output = [r[0] for r in data_rows]
        self.assertIn("administração", lemmas_in_output)
        self.assertNotIn("pedagógico", lemmas_in_output)


if __name__ == "__main__":
    unittest.main()
