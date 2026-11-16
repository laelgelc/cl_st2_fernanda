import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import tag


class TestTag(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="tag_test_")
        self.root = Path(self.temp_dir.name)
        self.input_dir = self.root / "corpus" / "04_enade"
        self.output_dir = self.root / "corpus" / "05_enade_tagged"

        # Create sample input structure
        self.chapter_dir_1 = self.input_dir / "2009_c4"
        self.chapter_dir_2 = self.input_dir / "2011_c6"
        self.chapter_dir_1.mkdir(parents=True, exist_ok=True)
        self.chapter_dir_2.mkdir(parents=True, exist_ok=True)

        self.file1 = self.chapter_dir_1 / "enade_2009_admin_b2a0b87461.txt"
        self.file2 = self.chapter_dir_2 / "enade_2011_biomed_e473b1892f.txt"

        self.file1.write_text("O ENADE avalia cursos com p < 0.05 e <div>.\n", encoding="utf-8")
        self.file2.write_text("Relatório síntese de avaliação 2011.\n", encoding="utf-8")

        self.manifest_path = self.input_dir / "enade_target_corpus.ndjson"
        manifest_rows = [
            {
                "year": "2009",
                "chapter": "c4",
                "target_subdirectory": "2009_c4",
                "target_chapter_path": "corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
                "filename_stem": "enade_2009_admin_b2a0b87461",
            },
            {
                "year": "2011",
                "chapter": "c6",
                "target_subdirectory": "2011_c6",
                "target_chapter_path": "corpus/04_enade/2011_c6/enade_2011_biomed_e473b1892f.txt",
                "filename_stem": "enade_2011_biomed_e473b1892f",
            },
        ]
        self.manifest_path.write_text(
            "".join(json.dumps(row) + "\n" for row in manifest_rows),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_escape_xml_tags(self):
        text = "p < 0.05 and x > 10 with <html> markup"
        escaped = tag.escape_xml_tags(text)
        self.assertEqual(escaped, "p &lt; 0.05 and x &gt; 10 with &lt;html&gt; markup")

    def test_sanitize_text(self):
        text = "Line 1\r\nLine 2\rLine 3\x00 with <tags>"
        sanitized = tag.sanitize_text(text)
        self.assertEqual(sanitized, "Line 1\nLine 2\nLine 3 with &lt;tags&gt;")

    def test_count_tokens(self):
        output = "O\tART\to\nENADE\tNP\tENADE\n\navalia\tVPI\tavaliar\n"
        self.assertEqual(tag.count_tokens(output), 3)

    def test_resolve_tagger_command(self):
        cmd = tag.resolve_tagger_command("custom-tagger --flag")
        self.assertEqual(cmd, ["custom-tagger", "--flag"])

        with patch.dict(os.environ, {"TREETAGGER_CMD": "env-tagger -opt"}):
            self.assertEqual(tag.resolve_tagger_command(None), ["env-tagger", "-opt"])

    def test_preflight_tagger_check(self):
        # Successful probe
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["mock-tagger"],
                returncode=0,
                stdout="O\tART\to\n",
                stderr="",
            )
            ok, err = tag.preflight_tagger_check(["mock-tagger"])
            self.assertTrue(ok)
            self.assertEqual(err, "")

        # Failed probe (non-zero return code)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["mock-tagger"],
                returncode=1,
                stdout="",
                stderr="Tagger error",
            )
            ok, err = tag.preflight_tagger_check(["mock-tagger"])
            self.assertFalse(ok)
            self.assertIn("exit code 1", err)

    def test_discover_tasks_from_manifest(self):
        tasks = tag.discover_tasks(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            input_manifest=self.manifest_path,
            base_dir=self.root,
        )
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].year, "2009")
        self.assertEqual(tasks[0].chapter, "c4")
        self.assertEqual(tasks[0].filename, "enade_2009_admin_b2a0b87461.txt")
        self.assertEqual(tasks[1].year, "2011")
        self.assertEqual(tasks[1].chapter, "c6")

    def test_discover_tasks_from_directory(self):
        tasks = tag.discover_tasks(
            input_dir=self.input_dir,
            output_dir=self.output_dir,
            input_manifest=None,
            base_dir=self.root,
        )
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0].year, "2009")
        self.assertEqual(tasks[0].chapter, "c4")
        self.assertEqual(tasks[1].year, "2011")
        self.assertEqual(tasks[1].chapter, "c6")

    def test_tag_document_success(self):
        task = tag.TagTask(
            year="2009",
            chapter="c4",
            target_subdirectory="2009_c4",
            filename="enade_2009_admin_b2a0b87461.txt",
            source_file=self.file1,
            source_rel_path="corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
            target_file=self.output_dir / "2009_c4" / "enade_2009_admin_b2a0b87461.txt",
            target_rel_path="corpus/05_enade_tagged/2009_c4/enade_2009_admin_b2a0b87461.txt",
        )

        mock_tagged_output = "O\tART\to\nENADE\tNP\tENADE\navalia\tVPI\tavaliar\n"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["tree-tagger-portuguese2"],
                returncode=0,
                stdout=mock_tagged_output,
                stderr="",
            )
            res = tag.tag_document(task, ["tree-tagger-portuguese2"])

            self.assertTrue(res.success)
            self.assertEqual(res.status, "success")
            self.assertEqual(res.token_count, 3)
            self.assertTrue(task.target_file.exists())
            self.assertEqual(task.target_file.read_text(encoding="utf-8"), mock_tagged_output)

    def test_tag_document_resume(self):
        target_file = self.output_dir / "2009_c4" / "enade_2009_admin_b2a0b87461.txt"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("O\tART\to\nENADE\tNP\tENADE\n", encoding="utf-8")

        task = tag.TagTask(
            year="2009",
            chapter="c4",
            target_subdirectory="2009_c4",
            filename="enade_2009_admin_b2a0b87461.txt",
            source_file=self.file1,
            source_rel_path="corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
            target_file=target_file,
            target_rel_path="corpus/05_enade_tagged/2009_c4/enade_2009_admin_b2a0b87461.txt",
        )

        # In resume mode, subprocess.run should not be called
        with patch("subprocess.run") as mock_run:
            res = tag.tag_document(task, ["tree-tagger-portuguese2"], resume=True)
            self.assertTrue(res.success)
            self.assertEqual(res.status, "skipped")
            self.assertEqual(res.token_count, 2)
            mock_run.assert_not_called()

    def test_tag_document_error_isolation(self):
        task = tag.TagTask(
            year="2009",
            chapter="c4",
            target_subdirectory="2009_c4",
            filename="enade_2009_admin_b2a0b87461.txt",
            source_file=self.file1,
            source_rel_path="corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
            target_file=self.output_dir / "2009_c4" / "enade_2009_admin_b2a0b87461.txt",
            target_rel_path="corpus/05_enade_tagged/2009_c4/enade_2009_admin_b2a0b87461.txt",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["tree-tagger-portuguese2"],
                returncode=1,
                stdout="",
                stderr="Tagger internal error",
            )
            res = tag.tag_document(task, ["tree-tagger-portuguese2"])
            self.assertFalse(res.success)
            self.assertEqual(res.status, "failure")
            self.assertEqual(res.error_type, "TreeTaggerSubprocessError")
            self.assertIn("Tagger internal error", res.error_message)

    def test_write_manifests(self):
        task1 = tag.TagTask(
            year="2009",
            chapter="c4",
            target_subdirectory="2009_c4",
            filename="enade_2009_admin_b2a0b87461.txt",
            source_file=self.file1,
            source_rel_path="corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
            target_file=self.output_dir / "2009_c4" / "enade_2009_admin_b2a0b87461.txt",
            target_rel_path="corpus/05_enade_tagged/2009_c4/enade_2009_admin_b2a0b87461.txt",
        )
        task2 = tag.TagTask(
            year="2011",
            chapter="c6",
            target_subdirectory="2011_c6",
            filename="enade_2011_biomed_e473b1892f.txt",
            source_file=self.file2,
            source_rel_path="corpus/04_enade/2011_c6/enade_2011_biomed_e473b1892f.txt",
            target_file=self.output_dir / "2011_c6" / "enade_2011_biomed_e473b1892f.txt",
            target_rel_path="corpus/05_enade_tagged/2011_c6/enade_2011_biomed_e473b1892f.txt",
        )

        res1 = tag.TaskResult(
            task=task1,
            success=True,
            source_sha256="aaa",
            source_size_bytes=100,
            tagged_sha256="bbb",
            tagged_size_bytes=200,
            token_count=10,
            tagger_command="tree-tagger-portuguese2",
            status="success",
            elapsed_seconds=0.15,
            timestamp="2026-11-16T15:00:00Z",
        )
        res2 = tag.TaskResult(
            task=task2,
            success=False,
            status="failure",
            tagger_command="tree-tagger-portuguese2",
            timestamp="2026-11-16T15:00:01Z",
            error_type="SubprocessError",
            error_message="Exit 1",
        )

        tag.write_manifests([res1, res2], self.output_dir)

        # Check NDJSON
        ndjson_file = self.output_dir / "enade_tagged_corpus.ndjson"
        self.assertTrue(ndjson_file.exists())
        lines = ndjson_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["year"], "2009")
        self.assertEqual(rec["token_count"], 10)

        # Check TSV
        tsv_file = self.output_dir / "enade_tagged_corpus.tsv"
        self.assertTrue(tsv_file.exists())
        tsv_lines = tsv_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(tsv_lines), 2)  # Header + 1 row
        self.assertIn("token_count", tsv_lines[0])

        # Check XLSX
        xlsx_file = self.output_dir / "enade_tagged_corpus.xlsx"
        self.assertTrue(xlsx_file.exists())

        # Check Failure NDJSON
        fail_file = self.output_dir / "tagging_failures.ndjson"
        self.assertTrue(fail_file.exists())
        fail_lines = fail_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(fail_lines), 1)
        fail_rec = json.loads(fail_lines[0])
        self.assertEqual(fail_rec["filename"], "enade_2011_biomed_e473b1892f.txt")
        self.assertEqual(fail_rec["error_type"], "SubprocessError")

    def test_main_dry_run(self):
        cli_args = [
            "--input-dir", str(self.input_dir),
            "--output-dir", str(self.output_dir),
            "--input-manifest", str(self.manifest_path),
            "--dry-run",
        ]
        with patch.object(tag, "PHASE_DIR", self.root), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["tree-tagger-portuguese2"],
                returncode=0,
                stdout="O\tART\to\n",
                stderr="",
            )
            exit_code = tag.main(cli_args)
            self.assertEqual(exit_code, 0)
            # Output directory should not have been created / written to
            self.assertFalse((self.output_dir / "enade_tagged_corpus.ndjson").exists())

    def test_main_full_run(self):
        cli_args = [
            "--input-dir", str(self.input_dir),
            "--output-dir", str(self.output_dir),
            "--input-manifest", str(self.manifest_path),
            "--workers", "1",
        ]
        mock_output = "O\tART\to\nENADE\tNP\tENADE\n"
        with patch.object(tag, "PHASE_DIR", self.root), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["tree-tagger-portuguese2"],
                returncode=0,
                stdout=mock_output,
                stderr="",
            )
            exit_code = tag.main(cli_args)
            self.assertEqual(exit_code, 0)
            self.assertTrue((self.output_dir / "enade_tagged_corpus.ndjson").exists())
            self.assertTrue((self.output_dir / "2009_c4" / "enade_2009_admin_b2a0b87461.txt").exists())


if __name__ == "__main__":
    unittest.main()
