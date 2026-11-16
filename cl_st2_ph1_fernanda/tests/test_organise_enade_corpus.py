import csv
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import organise_enade_corpus as organiser


class OrganiserFixture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="enade phase é ")
        self.root = Path(self.temp_dir.name) / "phase with spaces á"
        self.corpus = self.root / "corpus"
        self.source_pdf = self.corpus / "00_sources" / "report.pdf"
        self.chapter = self.corpus / "03_enade_selected_chapters_denoised" / "chapters" / "c4" / (
            "enade_2009_admin_b2a0b87461.txt"
        )
        self.selection = self.corpus / "selection.ndjson"
        self.metadata = self.corpus / "metadata.ndjson"
        self.status = self.corpus / "chapter_status.ndjson"
        self.output = self.corpus / "04_enade"
        self.source_pdf.parent.mkdir(parents=True)
        self.source_pdf.write_bytes(b"not a real PDF; provenance fixture")
        self.chapter.parent.mkdir(parents=True)
        self.chapter.write_bytes("ação — corpus text\n".encode("utf-8"))
        self.group = ("corpus/00_sources/report.pdf", "enade_2009_admin", "c4")
        self.write_inputs()

    def tearDown(self):
        self.temp_dir.cleanup()

    def metadata_row(self, source_path=None, year="2009", filename="ENADE_2009_ADMINISTRAÇÃO.pdf"):
        return {
            "year": year,
            "filename_ori": filename,
            "filepath_ori": source_path or self.group[0],
            "mnemonic": "admin",
            "discipline": "Administração",
        }

    def selection_rows(self, identity=None, pages=(100, 77)):
        source, stem, chapter = identity or self.group
        return [
            {
                "chapter_of_interest": chapter,
                "filename_stem": stem,
                "filepath_ori": source,
                "chapter_page_filepath_txt": f"corpus/02_selected/{stem}_page_{page}.txt",
            }
            for page in pages
        ]

    def status_row(self, identity=None, pages=(77, 100), output_path=None):
        source, stem, chapter = identity or self.group
        return {
            "group": {
                "filepath_ori": source,
                "filename_stem": stem,
                "chapter_of_interest": chapter,
            },
            "status": "complete",
            "complete": True,
            "scope_limited": False,
            "selected_pages": list(pages),
            "successful_page_count": len(pages),
            "failed_pages": [],
            "unattempted_pages": [],
            "failed_or_missing_pages": [],
            "empty_success_pages": [],
            "review_note_count": 2,
            "boundary_review_flags": [{"pages": [77, 78], "reason": "review"}],
            "output_path": output_path or "corpus/03_enade_selected_chapters_denoised/chapters/c4/"
            "enade_2009_admin_b2a0b87461.txt",
        }

    @staticmethod
    def write_ndjson(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def write_inputs(self, selections=None, metadata=None, statuses=None):
        self.write_ndjson(self.selection, selections if selections is not None else self.selection_rows())
        self.write_ndjson(self.metadata, metadata if metadata is not None else [self.metadata_row()])
        self.write_ndjson(self.status, statuses if statuses is not None else [self.status_row()])

    def build_plan(self):
        return organiser.build_plan(self.selection, self.metadata, self.status, self.output, self.root)

    def cli_args(self, *extra):
        return [
            "--input-manifest", str(self.selection),
            "--metadata-manifest", str(self.metadata),
            "--chapter-status", str(self.status),
            "--output-dir", str(self.output),
            *extra,
        ]

    def run_main(self, *extra):
        with patch.object(organiser, "PHASE_DIR", self.root):
            return organiser.main(self.cli_args(*extra))


class OrganiserPlanningTests(OrganiserFixture):
    def test_plan_sorts_pages_and_uses_metadata_year_and_status_output_name(self):
        plan = self.build_plan()
        row = plan.rows[0]
        self.assertEqual(row["selected_pages"], [77, 100])
        self.assertEqual(row["target_subdirectory"], "2009_c4")
        self.assertEqual(
            row["target_chapter_path"],
            "corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
        )
        self.assertEqual(row["source_pdf_path"], "corpus/00_sources/report.pdf")
        self.assertEqual(row["source_pdf_filename"], "ENADE_2009_ADMINISTRAÇÃO.pdf")
        self.assertEqual(row["corpus_status"], "accepted_subject_to_audit")
        self.assertEqual(row["boundary_review_flag_count"], 1)

    def test_duplicate_selected_page_identity_is_rejected(self):
        rows = self.selection_rows(pages=(77, 77))
        self.write_inputs(selections=rows)
        with self.assertRaisesRegex(organiser.OrganiserError, "duplicate selected page identity"):
            self.build_plan()

    def test_selection_status_page_mismatch_and_incomplete_status_are_rejected(self):
        self.write_inputs(statuses=[self.status_row(pages=(77, 101))])
        with self.assertRaisesRegex(organiser.OrganiserError, "selected pages differ"):
            self.build_plan()

        status = self.status_row()
        status["complete"] = False
        self.write_inputs(statuses=[status])
        with self.assertRaisesRegex(organiser.OrganiserError, "not marked complete"):
            self.build_plan()

    def test_missing_source_metadata_and_missing_pdf_are_rejected(self):
        self.write_inputs(metadata=[])
        with self.assertRaisesRegex(organiser.OrganiserError, "empty"):
            self.build_plan()

        self.write_inputs(metadata=[self.metadata_row(source_path="corpus/00_sources/other.pdf")])
        with self.assertRaisesRegex(organiser.OrganiserError, "No source metadata row matches"):
            self.build_plan()

        self.write_inputs(metadata=[self.metadata_row(), self.metadata_row()])
        with self.assertRaisesRegex(organiser.OrganiserError, "Duplicate source metadata path"):
            self.build_plan()

        self.write_inputs()
        self.source_pdf.unlink()
        with self.assertRaisesRegex(organiser.OrganiserError, "source PDF.*missing"):
            self.build_plan()

    def test_missing_and_duplicate_status_groups_are_rejected(self):
        other_identity = (self.group[0], "different_stem", "c4")
        with self.assertRaisesRegex(organiser.OrganiserError, "group sets differ"):
            self.write_inputs(statuses=[self.status_row(other_identity, pages=(3,))])
            self.build_plan()

        with self.assertRaisesRegex(organiser.OrganiserError, "duplicate chapter status identity"):
            self.write_inputs(statuses=[self.status_row(), self.status_row()])
            self.build_plan()

    def test_failed_or_unattempted_pages_and_output_symlink_are_rejected(self):
        failed = self.status_row()
        failed["failed_or_missing_pages"] = [77]
        with self.assertRaisesRegex(organiser.OrganiserError, "failed_or_missing_pages"):
            self.write_inputs(statuses=[failed])
            self.build_plan()

        unattempted = self.status_row()
        unattempted["unattempted_pages"] = [77]
        with self.assertRaisesRegex(organiser.OrganiserError, "unattempted_pages"):
            self.write_inputs(statuses=[unattempted])
            self.build_plan()

        try:
            self.output.symlink_to(self.corpus / "03_enade_selected_chapters_denoised", target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("This platform does not permit creating symlinks")
        with self.assertRaisesRegex(organiser.OrganiserError, "must not be a symlink"):
            self.build_plan()

    def test_unsafe_path_and_symlink_outside_phase_are_rejected(self):
        unsafe = self.group[0].replace("report.pdf", "../outside.pdf")
        identity = (unsafe, self.group[1], self.group[2])
        self.write_inputs(
            selections=self.selection_rows(identity),
            metadata=[self.metadata_row(source_path=unsafe)],
            statuses=[self.status_row(identity)],
        )
        with self.assertRaisesRegex(organiser.OrganiserError, "Unsafe relative"):
            self.build_plan()

        outside = self.root.parent / "outside.pdf"
        outside.write_bytes(b"outside")
        self.source_pdf.unlink()
        try:
            self.source_pdf.symlink_to(outside)
        except (NotImplementedError, OSError):
            self.skipTest("This platform does not permit creating symlinks")
        self.write_inputs()
        with self.assertRaisesRegex(organiser.OrganiserError, "resolves outside"):
            self.build_plan()

    def test_casefolded_target_collision_is_rejected(self):
        second_identity = (self.group[0], "different_stem", "c4")
        second_chapter = self.chapter.parent / "ENade_2009_admin_B2A0B87461.TXT"
        second_chapter.write_bytes(b"second chapter")
        self.write_inputs(
            selections=self.selection_rows() + self.selection_rows(second_identity, pages=(3,)),
            metadata=[self.metadata_row()],
            statuses=[
                self.status_row(),
                self.status_row(
                    second_identity,
                    pages=(3,),
                    output_path="corpus/03_enade_selected_chapters_denoised/chapters/c4/"
                    "ENade_2009_admin_B2A0B87461.TXT",
                ),
            ],
        )
        with self.assertRaisesRegex(organiser.OrganiserError, "Target path collision"):
            self.build_plan()

    def test_unicode_normalized_target_collision_is_rejected(self):
        second_identity = (self.group[0], "different_stem", "c4")
        composed_name = "café.txt"
        decomposed_name = "cafe\u0301.txt"
        (self.chapter.parent / composed_name).write_bytes(b"composed")
        (self.chapter.parent / decomposed_name).write_bytes(b"decomposed")
        self.write_inputs(
            selections=self.selection_rows() + self.selection_rows(second_identity, pages=(3,)),
            metadata=[self.metadata_row()],
            statuses=[
                self.status_row(
                    output_path="corpus/03_enade_selected_chapters_denoised/chapters/c4/" + composed_name
                ),
                self.status_row(
                    second_identity,
                    pages=(3,),
                    output_path="corpus/03_enade_selected_chapters_denoised/chapters/c4/" + decomposed_name,
                ),
            ],
        )
        with self.assertRaisesRegex(organiser.OrganiserError, "Target path collision"):
            self.build_plan()

    def test_empty_completed_chapter_is_valid_and_unicode_paths_are_preserved(self):
        self.chapter.write_bytes(b"")
        plan = self.build_plan()
        self.assertEqual(plan.rows[0]["chapter_size_bytes"], 0)
        self.assertIn("phase with spaces á", str(plan.base_dir))
        self.assertEqual(plan.rows[0]["discipline"], "Administração")

    def test_cli_relative_paths_are_resolved_from_phase_not_working_directory(self):
        self.assertEqual(
            organiser._resolve_cli_path("corpus/metadata.ndjson", self.root),
            self.metadata.resolve(),
        )


class OrganiserPublicationTests(OrganiserFixture):
    def test_dry_run_writes_nothing_and_full_run_publishes_verified_exports(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(self.run_main("--dry-run"), 0)
        self.assertIn("2 selected pages across 1 complete chapters", stdout.getvalue())
        self.assertFalse(self.output.exists())

        with redirect_stdout(StringIO()):
            self.assertEqual(self.run_main(), 0)
        destination = self.output / "2009_c4" / self.chapter.name
        self.assertEqual(destination.read_bytes(), self.chapter.read_bytes())
        row = json.loads((self.output / organiser.MANIFEST_NAMES[0]).read_text(encoding="utf-8"))
        self.assertEqual(row["chapter_sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual(row["chapter_size_bytes"], destination.stat().st_size)
        self.assertEqual(row["selected_pages"], [77, 100])

        with (self.output / organiser.MANIFEST_NAMES[1]).open(encoding="utf-8", newline="") as stream:
            tsv_reader = csv.DictReader(stream, delimiter="\t")
            tsv_row = next(tsv_reader)
        self.assertEqual(tsv_row["selected_pages"], "[77,100]")
        self.assertEqual(tsv_row["target_chapter_path"], row["target_chapter_path"])

        from openpyxl import load_workbook

        workbook = load_workbook(self.output / organiser.MANIFEST_NAMES[2], data_only=False)
        worksheet = workbook["chapters"]
        self.assertEqual(worksheet.freeze_panes, "A2")
        self.assertEqual(worksheet.cell(2, 9).value, "[77,100]")
        self.assertEqual(worksheet.cell(2, 12).value, row["target_chapter_path"])
        self.assertTrue(all(cell.data_type != "f" for line in worksheet.iter_rows() for cell in line))
        workbook.close()

    def test_identical_rerun_is_a_noop_and_edited_manifest_conflicts_without_overwrite(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(self.run_main(), 0)
            self.assertEqual(self.run_main(), 0)
        manifest = self.output / organiser.MANIFEST_NAMES[0]
        original = manifest.read_bytes()
        manifest.write_bytes(original + b"\n")
        edited = manifest.read_bytes()
        stderr = StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(self.run_main(), 2)
        self.assertIn("differs from the expected corpus", stderr.getvalue())
        self.assertEqual(manifest.read_bytes(), edited)

    def test_failed_staging_copy_keeps_target_absent_and_reports_staging_directory(self):
        stderr = StringIO()
        with patch.object(organiser, "copy_and_verify", side_effect=organiser.OrganiserError("fixture failure")):
            with redirect_stderr(stderr):
                self.assertEqual(self.run_main(), 2)
        self.assertFalse(self.output.exists())
        self.assertIn("Staging directory retained for diagnosis", stderr.getvalue())
        staging_path = Path(stderr.getvalue().split("Staging directory retained for diagnosis: ")[-1].strip())
        self.assertTrue(staging_path.is_dir())

    def test_extra_target_file_is_a_conflict_and_is_preserved(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(self.run_main(), 0)
        extra = self.output / "human-review.txt"
        extra.write_text("keep", encoding="utf-8")
        with redirect_stderr(StringIO()):
            self.assertEqual(self.run_main(), 2)
        self.assertEqual(extra.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()