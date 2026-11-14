import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

import llm_denoise_pages as denoise


class DenoisingFixture(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config = denoise.Config(
            base_dir=self.root,
            manifest=self.root / "manifest.ndjson",
            prompt=self.root / "prompt.md",
            output=self.root / "output",
            model="gpt-test",
            window_size=3,
            workers=2,
            max_retries=1,
            retry_backoff_seconds=0,
            temperature=None,
            max_output_tokens=100,
            env_file=self.root / ".env",
            limit=None,
            only_filename=None,
            resume=False,
            reprocess=False,
            dry_run=False,
        )
        self.template = "Process pages:\n" + denoise.PLACEHOLDER
        self.prompt_hash = denoise.sha256_text(self.template)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_pages(self, numbers, group=None):
        group = group or ("source.pdf", "report", "c4")
        pages = []
        for number in numbers:
            path = self.root / f"report_page_{number}.txt"
            text = f"page {number}"
            path.write_text(text, encoding="utf-8")
            row = {
                "chapter_of_interest": group[2],
                "filename_stem": group[1],
                "filepath_ori": group[0],
                "chapter_page_filepath_txt": str(path),
                "_manifest_line_number": number,
            }
            pages.append(denoise.Page(row, group, number, path, text, denoise.sha256_text(text),
                                      denoise.build_document_id(group[0], group[1]),
                                      denoise.result_path_for(self.config.output, group,
                                                              denoise.build_document_id(group[0], group[1]), number)))
        return pages


class PagePlanningTests(DenoisingFixture):
    def test_manifest_pages_sort_numerically_and_reject_duplicate_identity(self):
        rows = []
        for number in (100, 77):
            path = self.root / f"chapter_page_{number}.txt"
            path.write_text(str(number), encoding="utf-8")
            rows.append({
                "chapter_of_interest": "c4",
                "filename_stem": "report",
                "filepath_ori": "source.pdf",
                "chapter_page_filepath_txt": str(path),
            })
        pages = denoise.build_pages(rows, self.config)
        self.assertEqual([page.page_number for page in pages], [77, 100])
        with self.assertRaisesRegex(denoise.FatalSetupError, "Duplicate target identity"):
            denoise.build_pages(rows + [rows[1]], self.config)

    def test_bad_page_name_and_missing_manifest_fields_fail(self):
        with self.assertRaisesRegex(denoise.FatalSetupError, "_page_<number>"):
            denoise.parse_page_number("selected_page_last.txt")
        with self.assertRaisesRegex(denoise.FatalSetupError, "missing required string field"):
            denoise.build_pages([{"chapter_of_interest": "c4"}], self.config)

    def test_worker_and_retry_limits_are_enforced(self):
        with self.assertRaisesRegex(denoise.FatalSetupError, "between 1 and 64"):
            denoise.validate_config(replace(self.config, workers=65))
        with self.assertRaisesRegex(denoise.FatalSetupError, "between 0 and 10"):
            denoise.validate_config(replace(self.config, max_retries=11))

    def test_odd_window_sizes_and_page_gaps(self):
        pages = self.make_pages([77, 78, 79, 80, 81])
        target = pages[2]
        self.assertEqual([p.page_number for p in denoise.context_pages(target, pages, 1)], [79])
        self.assertEqual([p.page_number for p in denoise.context_pages(target, pages, 3)], [78, 79, 80])
        self.assertEqual([p.page_number for p in denoise.context_pages(target, pages, 5)], [77, 78, 79, 80, 81])
        gap_pages = [pages[0], pages[1], pages[3], pages[4]]
        self.assertEqual([p.page_number for p in denoise.context_pages(pages[1], gap_pages, 5)], [77, 78])
        self.assertEqual([p.page_number for p in denoise.context_pages(pages[3], gap_pages, 5)], [80, 81])
        with self.assertRaises(ValueError):
            denoise.context_pages(target, pages, 2)

    def test_grouped_context_does_not_cross_documents(self):
        first = self.make_pages([1, 2])
        second = self.make_pages([3], group=("other.pdf", "other", "c4"))
        self.assertEqual([page.page_number for page in denoise.context_pages(first[1], first + second, 3)], [1, 2])

    def test_prompt_labels_exactly_one_target_and_escapes_page_markup(self):
        pages = self.make_pages([1, 2, 3])
        pages[0] = replace(pages[0], source_text="<tag>context", source_hash=denoise.sha256_text("<tag>context"))
        target = pages[1]
        window = denoise.context_pages(target, pages, 3)
        rendered = denoise.build_prompt(self.template, window, target)
        self.assertEqual(rendered.count('role="target"'), 1)
        self.assertEqual(rendered.count('role="context"'), 2)
        self.assertIn("&lt;tag&gt;context", rendered)
        with self.assertRaises(denoise.FatalSetupError):
            denoise.build_prompt(denoise.PLACEHOLDER + denoise.PLACEHOLDER, window, target)


class PortablePathTests(DenoisingFixture):
    def make_relocated_inputs(self, base_dir):
        source_dir = base_dir / "corpus" / "selected"
        source_dir.mkdir(parents=True)
        source_document = base_dir / "corpus" / "source.pdf"
        source_document.parent.mkdir(parents=True, exist_ok=True)
        source_document.write_text("source", encoding="utf-8")
        rows = []
        for number in (1, 2, 3):
            path = source_dir / f"report_page_{number}.txt"
            path.write_text(f"page {number}", encoding="utf-8")
            rows.append({
                "chapter_of_interest": "c4",
                "filename_stem": "report",
                "filepath_ori": str(source_document),
                "chapter_page_filepath_txt": path.relative_to(base_dir).as_posix(),
                "_manifest_line_number": number,
            })
        config = replace(
            self.config,
            base_dir=base_dir,
            manifest=base_dir / "manifest.ndjson",
            prompt=base_dir / "prompt.md",
            output=base_dir / "output",
            env_file=base_dir / ".env",
        )
        return config, denoise.build_pages(rows, config)

    def test_relocated_inputs_keep_identity_and_fingerprint_and_resume_legacy_paths(self):
        first_root = self.root / "first"
        second_root = self.root / "second"
        first_root.mkdir()
        second_root.mkdir()
        first_config, first_pages = self.make_relocated_inputs(first_root)
        second_config, second_pages = self.make_relocated_inputs(second_root)
        first_target, second_target = first_pages[1], second_pages[1]
        first_window = denoise.context_pages(first_target, first_pages, 3)
        second_window = denoise.context_pages(second_target, second_pages, 3)
        first_fingerprint = denoise.request_fingerprint(first_target, first_window, self.prompt_hash, first_config)
        second_fingerprint = denoise.request_fingerprint(second_target, second_window, self.prompt_hash, second_config)

        self.assertEqual(first_target.identity, second_target.identity)
        self.assertEqual(first_fingerprint, second_fingerprint)
        self.assertEqual(first_target.group[0], "corpus/source.pdf")
        self.assertEqual(denoise.portable_path(self.root.parent / "outside" / "page.txt", self.root),
                         "../outside/page.txt")
        self.assertEqual(denoise.portable_source_identity("corpus/source.pdf", self.root), "corpus/source.pdf")

        legacy_record = denoise.base_page_record(
            first_target, self.prompt_hash, first_fingerprint, first_window, first_config)
        legacy_record.update({
            "status": "success",
            "text": "reusable prose",
            "text_sha256": denoise.sha256_text("reusable prose"),
            "empty_text": False,
            "review_notes": [],
        })
        legacy_record["input"]["source_path"] = str(first_target.source_path)
        legacy_record["context_pages"] = [
            {"page_number": context.page_number, "source_path": str(context.source_path),
             "source_sha256": context.source_hash}
            for context in first_window if context != first_target
        ]
        second_target.result_path.parent.mkdir(parents=True, exist_ok=True)
        second_target.result_path.write_text(json.dumps(legacy_record), encoding="utf-8")

        resumed = denoise.load_existing_success(
            second_target, second_fingerprint, second_window, second_config)

        self.assertIsNotNone(resumed)
        self.assertEqual(resumed["text"], "reusable prose")
        self.assertEqual(resumed["request_fingerprint"], first_fingerprint)
        self.assertEqual(resumed["input"]["source_path"], "corpus/selected/report_page_2.txt")
        self.assertEqual([item["source_path"] for item in resumed["context_pages"]], [
            "corpus/selected/report_page_1.txt", "corpus/selected/report_page_3.txt"])
        self.assertEqual(json.loads(second_target.result_path.read_text(encoding="utf-8")), resumed)

    def test_run_chapter_and_page_metadata_use_base_relative_paths(self):
        source = self.root / "corpus" / "selected" / "report_page_1.txt"
        source.parent.mkdir(parents=True)
        source.write_text("page 1", encoding="utf-8")
        source_document = self.root / "corpus" / "source.pdf"
        source_document.parent.mkdir(parents=True, exist_ok=True)
        source_document.write_text("source", encoding="utf-8")
        (self.root / "manifest.ndjson").write_text(json.dumps({
            "chapter_of_interest": "c4",
            "filename_stem": "report",
            "filepath_ori": str(source_document),
            "chapter_page_filepath_txt": "corpus/selected/report_page_1.txt",
        }) + "\n", encoding="utf-8")
        (self.root / "prompt.md").write_text("Prompt\n" + denoise.PLACEHOLDER, encoding="utf-8")
        args = SimpleNamespace(
            base_dir=self.root,
            manifest="manifest.ndjson",
            prompt="prompt.md",
            output="output",
            model="gpt-test",
            window_size=3,
            workers=1,
            max_retries=0,
            retry_backoff_seconds=0,
            temperature=None,
            max_output_tokens=100,
            env_file=".env",
            limit=None,
            only_filename=None,
            resume=False,
            reprocess=False,
            dry_run=False,
        )

        class FakeResponses:
            calls = 0

            def create(self, **kwargs):
                type(self).calls += 1
                return SimpleNamespace(output_text='{"text":"prose","review_notes":[]}')

        client = SimpleNamespace(responses=FakeResponses())
        with patch.object(denoise, "parse_args", return_value=args), \
                patch.object(denoise, "make_llm_client", return_value=client), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), redirect_stdout(StringIO()):
            self.assertEqual(denoise.main([]), 0)

        run_manifest_path = next((self.root / "output" / "runs").glob("*/run_manifest.json"))
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(run_manifest["manifest"], "manifest.ndjson")
        self.assertEqual(run_manifest["prompt"], "prompt.md")
        self.assertEqual(run_manifest["output"], "output")
        self.assertEqual(FakeResponses.calls, 1)
        status = json.loads((self.root / "output" / "chapter_status.ndjson").read_text(encoding="utf-8"))
        self.assertTrue(status["output_path"].startswith("output/chapters/"))
        self.assertFalse(Path(status["output_path"]).is_absolute())
        page_result = next((self.root / "output" / "pages").glob("c4/*/page_1.json"))
        page_record = json.loads(page_result.read_text(encoding="utf-8"))
        self.assertEqual(page_record["identity"]["filepath_ori"], "corpus/source.pdf")
        self.assertEqual(page_record["input"]["source_path"], "corpus/selected/report_page_1.txt")

        page_record["input"]["source_path"] = str(source)
        page_result.write_text(json.dumps(page_record), encoding="utf-8")
        existing_runs = set((self.root / "output" / "runs").iterdir())
        args.resume = True

        class ForbiddenResponses:
            def create(self, **kwargs):
                raise AssertionError("A validated cached page should not call the provider")

        with patch.object(denoise, "parse_args", return_value=args), \
                patch.object(denoise, "make_llm_client", return_value=SimpleNamespace(responses=ForbiddenResponses())), \
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}), redirect_stdout(StringIO()):
            self.assertEqual(denoise.main([]), 0)

        new_run = next(iter(set((self.root / "output" / "runs").iterdir()) - existing_runs))
        resumed_summary = json.loads((new_run / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(resumed_summary["counts"]["resumed_pages"], 1)
        refreshed_page_record = json.loads(page_result.read_text(encoding="utf-8"))
        self.assertEqual(refreshed_page_record["input"]["source_path"], "corpus/selected/report_page_1.txt")
        self.assertEqual(refreshed_page_record["text"], "prose")


class ResponseAndProcessingTests(DenoisingFixture):
    def test_response_schema_accepts_empty_text_and_rejects_bad_shapes(self):
        self.assertEqual(denoise.validate_response('{"text":"","review_notes":[]}'), ("", []))
        for response in (
            "",
            "not json",
            '{"text":"x","review_notes":[],"extra":true}',
            '{"text":1,"review_notes":[]}',
            '{"text":"x","review_notes":[1]}',
            '{"text":"x"}',
            '{"text":"x","text":"y","review_notes":[]}',
            '{"text":"I am sorry, but I cannot process this request.","review_notes":[]}',
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                denoise.validate_response(response)

    def test_process_target_persists_successful_empty_page(self):
        page = self.make_pages([5])[0]
        fingerprint = denoise.request_fingerprint(page, [page], self.prompt_hash, self.config)
        result = denoise.process_target(page, [page], self.template, self.prompt_hash, fingerprint,
                                        self.config, lambda _: ('{"text":"","review_notes":[]}', {}, 0),
                                        self.config.output / "invalid_responses")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["empty_text"])
        self.assertIn("rendered_prompt_sha256", result)
        self.assertEqual(json.loads(page.result_path.read_text(encoding="utf-8"))["text"], "")

    def test_invalid_response_is_separate_and_page_marked_invalid(self):
        page = self.make_pages([6])[0]
        fingerprint = denoise.request_fingerprint(page, [page], self.prompt_hash, self.config)
        result = denoise.process_target(page, [page], self.template, self.prompt_hash, fingerprint,
                                        self.config, lambda _: ("```json{}", {}, 0),
                                        self.config.output / "invalid_responses")
        self.assertEqual(result["status"], "invalid_response")
        invalid_path = self.config.base_dir / result["invalid_response_path"]
        self.assertFalse(Path(result["invalid_response_path"]).is_absolute())
        self.assertTrue(invalid_path.is_file())
        self.assertEqual(json.loads(page.result_path.read_text(encoding="utf-8"))["status"], "invalid_response")

    def test_resume_requires_matching_request_fingerprint(self):
        page = self.make_pages([7])[0]
        record = {"status": "success", "identity": page.identity, "request_fingerprint": "same", "text": "ok",
                  "text_sha256": denoise.sha256_text("ok"), "empty_text": False, "review_notes": []}
        page.result_path.parent.mkdir(parents=True, exist_ok=True)
        page.result_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(denoise.load_existing_success(page, "same"), record)
        self.assertIsNone(denoise.load_existing_success(page, "changed"))
        record["text_sha256"] = "invalid"
        page.result_path.write_text(json.dumps(record), encoding="utf-8")
        self.assertIsNone(denoise.load_existing_success(page, "same"))

    def test_fingerprint_changes_with_context_content(self):
        pages = self.make_pages([8, 9, 10])
        target = pages[1]
        before = denoise.request_fingerprint(target, pages, self.prompt_hash, self.config)
        changed_context = replace(pages[0], source_hash="changed")
        changed_pages = [changed_context, target, pages[2]]
        after = denoise.request_fingerprint(target, changed_pages, self.prompt_hash, self.config)
        self.assertNotEqual(before, after)

    def test_fingerprint_changes_when_temperature_is_explicit(self):
        page = self.make_pages([9])[0]
        default_fingerprint = denoise.request_fingerprint(page, [page], self.prompt_hash, self.config)
        explicit_fingerprint = denoise.request_fingerprint(
            page, [page], self.prompt_hash, replace(self.config, temperature=0.0))
        self.assertNotEqual(default_fingerprint, explicit_fingerprint)

    def test_transient_provider_error_retries_but_permanent_error_does_not(self):
        calls = []

        class RateLimitError(Exception):
            status_code = 429

        def eventually_succeeds(*args):
            calls.append(1)
            if len(calls) == 1:
                raise RateLimitError("rate limit")
            return "{}", {}

        with patch.object(denoise, "_provider_call", side_effect=eventually_succeeds), patch.object(denoise.time, "sleep"):
            response, _, retries = denoise.call_with_retries(object(), self.config, "prompt")
        self.assertEqual(response, "{}")
        self.assertEqual(retries, 1)
        self.assertEqual(len(calls), 2)

    def test_provider_requests_omit_temperature_unless_explicit(self):
        openai_calls = []

        class OpenAIResponses:
            def create(self, **kwargs):
                openai_calls.append(kwargs)
                return type("Response", (), {"output_text": "{}"})()

        openai_client = type("Client", (), {"responses": OpenAIResponses()})()
        denoise._provider_call(openai_client, self.config, "prompt")
        denoise._provider_call(openai_client, replace(self.config, temperature=0.25), "prompt")
        self.assertNotIn("temperature", openai_calls[0])
        self.assertEqual(openai_calls[1]["temperature"], 0.25)

        gemini_calls = []

        class GeminiModels:
            def generate_content(self, **kwargs):
                gemini_calls.append(kwargs)
                return type("Response", (), {"text": "{}"})()

        gemini_client = type("Client", (), {"models": GeminiModels()})()
        gemini_config = replace(self.config, model="gemini-test")
        denoise._provider_call(gemini_client, gemini_config, "prompt")
        denoise._provider_call(gemini_client, replace(gemini_config, temperature=0.5), "prompt")
        self.assertNotIn("temperature", gemini_calls[0]["config"])
        self.assertEqual(gemini_calls[1]["config"]["temperature"], 0.5)

    def test_provider_configuration_errors_are_fatal_but_unknown_bad_requests_are_not(self):
        class ProviderError(Exception):
            def __init__(self, status_code, message):
                super().__init__(message)
                self.status_code = status_code

        for error in (
            ProviderError(401, "invalid API key"),
            ProviderError(403, "permission denied"),
            ProviderError(404, "model not found"),
            ProviderError(400, "Unsupported parameter: temperature is not supported with this model"),
        ):
            with self.subTest(error=str(error)):
                self.assertTrue(denoise.is_fatal_provider_error(error))
        self.assertFalse(denoise.is_fatal_provider_error(ProviderError(400, "invalid page content")))
        self.assertTrue(denoise.is_recoverable_provider_error(ProviderError(429, "rate limit")))

    def test_fatal_provider_error_is_not_retried(self):
        calls = []

        class BadRequestError(Exception):
            status_code = 400

        def reject_temperature(*args):
            calls.append(1)
            raise BadRequestError("Unsupported parameter: temperature is not supported with this model")

        with patch.object(denoise, "_provider_call", side_effect=reject_temperature):
            with self.assertRaises(denoise.FatalProviderError):
                denoise.call_with_retries(object(), self.config, "prompt")
        self.assertEqual(len(calls), 1)

    def test_scheduler_stops_after_first_fatal_configuration_error(self):
        pages = self.make_pages([30, 31, 32])
        grouped = {pages[0].group: pages}
        work = []
        for page in pages:
            window = denoise.context_pages(page, pages, self.config.window_size)
            work.append((page, window, denoise.request_fingerprint(page, window, self.prompt_hash, self.config)))
        calls = []

        def fatal_provider(prompt):
            target_page = next(number for number in (30, 31, 32)
                               if f'role="target">page {number}</page>' in prompt)
            calls.append(target_page)
            raise denoise.FatalProviderError("unsupported temperature parameter")

        records = {pages[0].group: {}}
        fatal_error = denoise.process_work_queue(
            work, records, self.template, self.prompt_hash, self.config, fatal_provider,
            self.config.output / "invalid_responses")

        self.assertIn("unsupported temperature", fatal_error)
        self.assertEqual(calls, [30])
        self.assertEqual(records[pages[0].group][30]["status"], "failed")
        self.assertTrue(records[pages[0].group][30]["run_fatal_error"])
        self.assertEqual(records[pages[0].group][31]["status"], "not_attempted")
        self.assertEqual(records[pages[0].group][32]["status"], "not_attempted")
        status = denoise.consolidate_chapter(self.config, pages[0].group, pages, records[pages[0].group])
        self.assertFalse(status["complete"])
        self.assertEqual(status["unattempted_pages"], [31, 32])
        self.assertEqual(status["successful_page_count"], 0)

    def test_page_specific_failure_does_not_abort_unrelated_targets(self):
        pages = self.make_pages([35, 36])
        work = []
        for page in pages:
            window = denoise.context_pages(page, pages, self.config.window_size)
            work.append((page, window, denoise.request_fingerprint(page, window, self.prompt_hash, self.config)))
        calls = []

        def provider(prompt):
            target_page = next(number for number in (35, 36)
                               if f'role="target">page {number}</page>' in prompt)
            calls.append(target_page)
            if target_page == 35:
                raise RuntimeError("page-specific provider rejection")
            return json.dumps({"text": "unrelated prose", "review_notes": []}), {}, 0

        records = {pages[0].group: {}}
        fatal_error = denoise.process_work_queue(
            work, records, self.template, self.prompt_hash, self.config, provider,
            self.config.output / "invalid_responses")
        self.assertIsNone(fatal_error)
        self.assertCountEqual(calls, [35, 36])
        self.assertEqual(records[pages[0].group][35]["status"], "failed")
        self.assertEqual(records[pages[0].group][36]["status"], "success")

    def test_scheduler_does_not_queue_more_work_after_a_fatal_in_flight_error(self):
        import threading

        pages = self.make_pages([40, 41, 42, 43])
        work = []
        for page in pages:
            window = denoise.context_pages(page, pages, self.config.window_size)
            work.append((page, window, denoise.request_fingerprint(page, window, self.prompt_hash, self.config)))
        fatal_seen = threading.Event()
        release_second = threading.Event()
        calls = []

        def provider(prompt):
            target_page = next(number for number in (40, 41, 42, 43)
                               if f'role="target">page {number}</page>' in prompt)
            calls.append(target_page)
            if target_page == 41:
                fatal_seen.set()
                raise denoise.FatalProviderError("model is not available")
            if target_page == 42:
                self.assertTrue(fatal_seen.wait(1))
                self.assertTrue(release_second.wait(1))
            return json.dumps({"text": f"prose {target_page}", "review_notes": []}), {}, 0

        records = {pages[0].group: {}}
        release_thread = threading.Timer(0.1, release_second.set)
        release_thread.start()
        try:
            fatal_error = denoise.process_work_queue(
                work, records, self.template, self.prompt_hash, self.config, provider,
                self.config.output / "invalid_responses")
        finally:
            release_thread.cancel()
        self.assertIn("model is not available", fatal_error)
        self.assertCountEqual(calls, [40, 41, 42])
        self.assertEqual(records[pages[0].group][42]["status"], "success")
        self.assertEqual(records[pages[0].group][43]["status"], "not_attempted")

    def test_concurrent_pages_write_independent_results(self):
        from concurrent.futures import ThreadPoolExecutor

        pages = self.make_pages([20, 21])

        def fake_provider(prompt):
            target_page = next(number for number in (20, 21)
                               if f'role="target">page {number}</page>' in prompt)
            return json.dumps({"text": f"prose {target_page}", "review_notes": []}), {}, 0

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = []
            for page in pages:
                window = denoise.context_pages(page, pages, 3)
                fingerprint = denoise.request_fingerprint(page, window, self.prompt_hash, self.config)
                futures.append(executor.submit(denoise.process_target, page, window, self.template, self.prompt_hash,
                                               fingerprint, self.config, fake_provider,
                                               self.config.output / "invalid_responses"))
            results = [future.result() for future in futures]

        self.assertEqual([result["status"] for result in results], ["success", "success"])
        self.assertEqual([json.loads(page.result_path.read_text(encoding="utf-8"))["text"] for page in pages],
                         ["prose 20", "prose 21"])

    def test_chapter_consolidation_skips_empty_and_failure_blocks_publish(self):
        pages = self.make_pages([11, 12, 13])
        group = pages[0].group
        output_path = denoise.chapter_output_path(self.config, group, pages[0].document_id)
        records = {
            11: {"status": "success", "text": "First prose."},
            12: {"status": "success", "text": "", "review_notes": []},
            13: {"status": "success", "text": "Last prose."},
        }
        status = denoise.consolidate_chapter(self.config, group, pages, records)
        self.assertTrue(status["complete"])
        self.assertEqual(output_path.read_text(encoding="utf-8"), "First prose.\n\nLast prose.\n")
        output_path.write_text("previous complete output", encoding="utf-8")
        records[13] = {"status": "failed"}
        status = denoise.consolidate_chapter(self.config, group, pages, records)
        self.assertFalse(status["complete"])
        self.assertEqual(status["failed_or_missing_pages"], [13])
        self.assertEqual(output_path.read_text(encoding="utf-8"), "previous complete output")

    def test_limited_live_scope_is_never_complete(self):
        pages = self.make_pages([14])
        self.config = denoise.Config(**{**self.config.__dict__, "limit": 1})
        status = denoise.consolidate_chapter(self.config, pages[0].group, pages,
                                             {14: {"status": "success", "text": "Some text"}})
        self.assertFalse(status["complete"])
        self.assertTrue(status["scope_limited"])

    def test_secrets_are_redacted_from_error_text(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "secret-token"}):
            self.assertNotIn("secret-token", denoise.sanitize_error(RuntimeError("bad secret-token")))

    def test_usage_totals_normalize_openai_and_gemini_metadata(self):
        totals = denoise._usage_totals([
            {"api_metadata": {"usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}}},
            {"api_metadata": {"usage": {"prompt_token_count": 8, "candidates_token_count": 3,
                                         "total_token_count": 11}}},
        ])
        self.assertEqual(totals, {"input_tokens": 18, "output_tokens": 7, "total_tokens": 25})
        self.assertEqual(denoise._usage_totals([]), {"input_tokens": None, "output_tokens": None, "total_tokens": None})


if __name__ == "__main__":
    unittest.main()