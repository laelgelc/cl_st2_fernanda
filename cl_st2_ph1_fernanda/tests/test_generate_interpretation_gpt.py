import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from argparse import Namespace
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_DIR / "generate_interpretation_gpt.py"
sys.path.insert(0, str(PROJECT_DIR))

import generate_interpretation_gpt as generator


class TestGenerateInterpretationGPT(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="generate_interpretation_gpt_test_")
        self.root = Path(self.temp_dir.name)
        self.phase_dir = self.root / "demo_phase"
        self.phase_dir.mkdir()
        self.working_dir = self.root / "elsewhere"
        self.working_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_args(self, **overrides):
        values = {
            "input": "interpretation/input",
            "output": "interpretation/output",
            "model": "gpt-6.2-sol",
            "max_output_tokens": 9000,
            "workers": 2,
            "skip_existing": True,
            "retries": 1,
            "retry_base_sleep": 0,
            "limit": 0,
            "log_file": "",
            "failed_file": "",
        }
        values.update(overrides)
        return Namespace(**values)

    def write_prompt(self, directory, name="f1_pos.txt", content="A complete prompt."):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def patched_main(self, args, worker):
        stack = ExitStack()
        stack.enter_context(patch.object(generator, "PHASE_DIR", self.phase_dir))
        stack.enter_context(patch.object(generator, "DEFAULT_PROJECT", self.phase_dir.name))
        stack.enter_context(patch.object(generator, "parse_args", return_value=args))
        stack.enter_context(patch.dict(generator.os.environ, {"OPENAI_API_KEY": "test-key"}))
        setup_logging = stack.enter_context(patch.object(generator, "setup_logging"))
        process_prompt = stack.enter_context(patch.object(
            generator, "process_prompt", side_effect=worker
        ))
        for method in ("info", "warning", "error"):
            stack.enter_context(patch.object(generator.logging, method))
        return stack, setup_logging, process_prompt

    def test_defaults_are_phase_relative_from_another_working_directory(self):
        input_path = self.write_prompt(self.phase_dir / "interpretation" / "input")
        args = self.make_args()
        original_cwd = Path.cwd()
        stack, setup_logging, process_prompt = self.patched_main(args, lambda **kwargs: True)
        try:
            os.chdir(self.working_dir)
            with stack:
                generator.main()
        finally:
            os.chdir(original_cwd)

        process_prompt.assert_called_once()
        self.assertEqual(process_prompt.call_args.kwargs["path"], input_path)
        self.assertEqual(
            process_prompt.call_args.kwargs["outpath"],
            self.phase_dir / "interpretation" / "output" / input_path.name,
        )
        setup_logging.assert_called_once_with(
            self.phase_dir / "interpretation" / "output" / generator.DEFAULT_LOG_FILE_NAME
        )
        self.assertEqual(generator.DEFAULT_PROJECT, generator.PHASE_DIR.name)

    def test_relative_path_overrides_include_log_and_failure_paths(self):
        input_path = self.write_prompt(self.phase_dir / "custom" / "prompts")
        args = self.make_args(
            input="custom/prompts",
            output="custom/results",
            log_file="custom/logs/run.log",
            failed_file="custom/failures.txt",
        )
        stack, setup_logging, process_prompt = self.patched_main(args, lambda **kwargs: False)
        with stack:
            with self.assertRaisesRegex(SystemExit, "some prompts failed"):
                generator.main()

        process_prompt.assert_called_once()
        self.assertEqual(process_prompt.call_args.kwargs["path"], input_path)
        self.assertEqual(
            process_prompt.call_args.kwargs["outpath"],
            self.phase_dir / "custom" / "results" / input_path.name,
        )
        setup_logging.assert_called_once_with(self.phase_dir / "custom/logs/run.log")
        self.assertEqual(
            (self.phase_dir / "custom/failures.txt").read_text(encoding="utf-8"),
            f"{input_path.name}\n",
        )

    def test_absolute_path_overrides_are_preserved(self):
        absolute_input = self.root / "absolute-input"
        absolute_output = self.root / "absolute-output"
        input_path = self.write_prompt(absolute_input)
        absolute_log = self.root / "logs" / "run.log"
        absolute_failures = self.root / "failures.txt"
        args = self.make_args(
            input=str(absolute_input),
            output=str(absolute_output),
            log_file=str(absolute_log),
            failed_file=str(absolute_failures),
        )
        stack, setup_logging, process_prompt = self.patched_main(args, lambda **kwargs: False)
        with stack:
            with self.assertRaisesRegex(SystemExit, "some prompts failed"):
                generator.main()

        self.assertEqual(process_prompt.call_args.kwargs["path"], input_path)
        self.assertEqual(process_prompt.call_args.kwargs["outpath"], absolute_output / input_path.name)
        setup_logging.assert_called_once_with(absolute_log)
        self.assertEqual(absolute_failures.read_text(encoding="utf-8"), f"{input_path.name}\n")

    def test_phase_dotenv_is_loaded_and_system_environment_wins(self):
        script_copy = self.phase_dir / "generate_interpretation_gpt.py"
        shutil.copy2(SCRIPT_PATH, script_copy)
        env_dir = self.phase_dir / "env"
        env_dir.mkdir()
        (env_dir / ".env").write_text("OPENAI_API_KEY=phase-file-key\n", encoding="utf-8")
        import_code = (
            "import importlib.util, os, sys; "
            "spec = importlib.util.spec_from_file_location('generator_copy', sys.argv[1]); "
            "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
            "print(module.DEFAULT_PROJECT + '|' + os.environ['OPENAI_API_KEY'])"
        )

        for system_key, expected_key in ((None, "phase-file-key"), ("system-key", "system-key")):
            with self.subTest(system_key=system_key):
                environment = os.environ.copy()
                environment.pop("OPENAI_API_KEY", None)
                if system_key:
                    environment["OPENAI_API_KEY"] = system_key
                result = subprocess.run(
                    [sys.executable, "-c", import_code, str(script_copy)],
                    cwd=self.working_dir,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), f"{self.phase_dir.name}|{expected_key}")

    def test_call_api_sends_the_full_prompt_and_model_appropriate_temperature(self):
        create = Mock(return_value=SimpleNamespace(output_text="  interpretation  "))
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        prompt = "Complete prompt with all sections."

        result = generator.call_api(
            client=client,
            model="gpt-4o",
            full_prompt=prompt,
            max_output_tokens=123,
        )

        self.assertEqual(result, "interpretation")
        create.assert_called_once_with(
            model="gpt-4o",
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=123,
            temperature=0.0,
        )

        create.reset_mock()
        generator.call_api(
            client=client,
            model="gpt-6.2-sol",
            full_prompt=prompt,
            max_output_tokens=123,
        )
        self.assertNotIn("temperature", create.call_args.kwargs)

    def test_transient_api_error_is_retried_before_success(self):
        create = Mock(side_effect=[RuntimeError("503 service unavailable"),
                                   SimpleNamespace(output_text="done")])
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        with (
            patch.object(generator, "OpenAI", return_value=client) as openai,
            patch.object(generator.time, "sleep") as sleep,
            patch.object(generator.random, "random", return_value=0.5),
            patch.dict(generator.os.environ, {"OPENAI_API_KEY": "test-key"}),
        ):
            result = generator.call_api_with_retries(
                model="gpt-6.2-sol",
                full_prompt="prompt",
                max_output_tokens=50,
                retries=1,
                base_sleep=2.0,
            )

        self.assertEqual(result, "done")
        self.assertEqual(create.call_count, 2)
        openai.assert_called_once_with(api_key="test-key")
        sleep.assert_called_once_with(2.0)

    def test_permanent_api_error_is_not_retried(self):
        create = Mock(side_effect=RuntimeError("401 invalid API key"))
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        with (
            patch.object(generator, "OpenAI", return_value=client),
            patch.object(generator.time, "sleep") as sleep,
            patch.dict(generator.os.environ, {"OPENAI_API_KEY": "test-key"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "API call failed"):
                generator.call_api_with_retries(
                    model="gpt-6.2-sol",
                    full_prompt="prompt",
                    max_output_tokens=50,
                    retries=5,
                    base_sleep=1.0,
                )

        create.assert_called_once()
        sleep.assert_not_called()

    def test_process_prompt_writes_response_to_matching_filename(self):
        prompt = self.write_prompt(self.root / "input", content="  full prompt  \n")
        output = self.root / "output" / prompt.name
        with patch.object(generator, "call_api_with_retries", return_value="response") as call:
            result = generator.process_prompt(
                path=prompt,
                outpath=output,
                model="gpt-6.2-sol",
                max_tokens=50,
                retries=0,
                base_sleep=0,
            )

        self.assertTrue(result)
        self.assertEqual(output.read_text(encoding="utf-8"), "response")
        self.assertEqual(call.call_args.kwargs["full_prompt"], "full prompt")

    def test_limit_is_applied_before_existing_outputs_are_skipped(self):
        input_dir = self.phase_dir / "interpretation" / "input"
        output_dir = self.phase_dir / "interpretation" / "output"
        self.write_prompt(input_dir, "a.txt")
        self.write_prompt(input_dir, "b.txt")
        output_dir.mkdir(parents=True)
        (output_dir / "a.txt").write_text("existing", encoding="utf-8")

        args = self.make_args(limit=1)
        stack, _, process_prompt = self.patched_main(args, lambda **kwargs: True)
        with stack:
            with self.assertRaises(SystemExit) as stopped:
                generator.main()
        self.assertEqual(stopped.exception.code, 0)
        process_prompt.assert_not_called()

        args.limit = 2
        stack, _, process_prompt = self.patched_main(args, lambda **kwargs: True)
        with stack:
            generator.main()
        process_prompt.assert_called_once()
        self.assertEqual(process_prompt.call_args.kwargs["path"].name, "b.txt")

    def test_no_skip_existing_reprocesses_an_existing_output(self):
        input_dir = self.phase_dir / "interpretation" / "input"
        output_dir = self.phase_dir / "interpretation" / "output"
        self.write_prompt(input_dir)
        output_dir.mkdir(parents=True)
        (output_dir / "f1_pos.txt").write_text("old", encoding="utf-8")

        args = self.make_args(skip_existing=False)
        stack, _, process_prompt = self.patched_main(args, lambda **kwargs: True)
        with stack:
            generator.main()
        process_prompt.assert_called_once()

    def test_workers_process_prompts_concurrently(self):
        input_dir = self.phase_dir / "interpretation" / "input"
        self.write_prompt(input_dir, "a.txt")
        self.write_prompt(input_dir, "b.txt")
        barrier = threading.Barrier(2)

        def wait_for_other_worker(**kwargs):
            barrier.wait(timeout=2)
            return True

        stack, _, process_prompt = self.patched_main(self.make_args(workers=2), wait_for_other_worker)
        with stack:
            generator.main()
        self.assertEqual(process_prompt.call_count, 2)


if __name__ == "__main__":
    unittest.main()