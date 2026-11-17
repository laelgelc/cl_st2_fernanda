#!/usr/bin/env python3
"""
generate_interpretation_gpt.py

Reads files from interpretation/input, sends each full file text as a single
user prompt to GPT, and saves the response to interpretation/output with the
same filename.

Default project usage:
    python generate_interpretation_gpt.py

Example explicit usage:
    python generate_interpretation_gpt.py \
        --input interpretation/input \
        --output interpretation/output \
        --model gpt-6.2-sol \
        --workers 4 \
        --max-output-tokens 9000 \
        --skip-existing \
        --retries 5 \
        --retry-base-sleep 2.0 \
        --limit 3

The script loads OPENAI_API_KEY from either:
    1. the system environment; or
    2. env/.env in this script's phase directory.

Expected input:
    interpretation/input/f<n>_<pole>.txt

Output:
    interpretation/output/f<n>_<pole>.txt

Additional run artefacts:
    interpretation/output/generate_interpretation_gpt.log
    interpretation/output/failed_prompts.txt, if any prompts fail
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv


# ------------------------------------------------------------
# Project defaults
# ------------------------------------------------------------

PHASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT = PHASE_DIR.name
DEFAULT_INPUT_DIR = Path("interpretation/input")
DEFAULT_OUTPUT_DIR = Path("interpretation/output")
DEFAULT_MODEL = "gpt-6.2-sol"
DEFAULT_WORKERS = 4
DEFAULT_MAX_OUTPUT_TOKENS = 9000
DEFAULT_RETRIES = 5
DEFAULT_RETRY_BASE_SLEEP = 2.0
DEFAULT_LOG_FILE_NAME = "generate_interpretation_gpt.log"
DEFAULT_FAILED_FILE_NAME = "failed_prompts.txt"


# ------------------------------------------------------------
# Environment loading
# ------------------------------------------------------------

load_dotenv(dotenv_path=PHASE_DIR / "env/.env", override=False)


# ------------------------------------------------------------
# API
# ------------------------------------------------------------

try:
    from openai import OpenAI
except ImportError:
    print(
        "Error: the `openai` package is not available in the active environment.\n"
        "Activate the correct project environment and ensure the OpenAI SDK is installed there."
    )
    sys.exit(1)


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Send LMDA interpretation prompts to GPT."
    )

    parser.add_argument(
        "--input",
        "-i",
        default=str(DEFAULT_INPUT_DIR),
        help=(
            "Directory containing prompt files. "
            f"Default: {PHASE_DIR / DEFAULT_INPUT_DIR}; relative paths resolve from the phase directory."
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Directory for GPT responses. "
            f"Default: {PHASE_DIR / DEFAULT_OUTPUT_DIR}; relative paths resolve from the phase directory."
        ),
    )
    parser.add_argument(
        "--model",
        "-m",
        default=DEFAULT_MODEL,
        help=f"Model to use. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--max-output-tokens",
        "-t",
        type=int,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        help=f"Maximum output tokens. Default: {DEFAULT_MAX_OUTPUT_TOKENS}.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers. Default: {DEFAULT_WORKERS}.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip prompts whose output file already exists. Default: enabled.",
    )
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="Reprocess prompts even if output files already exist.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Number of retries for transient API/network failures. Default: {DEFAULT_RETRIES}.",
    )
    parser.add_argument(
        "--retry-base-sleep",
        type=float,
        default=DEFAULT_RETRY_BASE_SLEEP,
        help=f"Base sleep in seconds for exponential backoff. Default: {DEFAULT_RETRY_BASE_SLEEP}.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional maximum number of prompt files to process. Use 0 for no limit.",
    )
    parser.add_argument(
        "--log-file",
        default="",
        help=(
            "Optional log-file path. "
            f"Default: <output>/{DEFAULT_LOG_FILE_NAME}; relative overrides resolve from the phase directory."
        ),
    )
    parser.add_argument(
        "--failed-file",
        default="",
        help=(
            "Optional failed-prompts file path. "
            f"Default: <output>/{DEFAULT_FAILED_FILE_NAME}; relative overrides resolve from the phase directory."
        ),
    )

    return parser.parse_args()


# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------

def setup_logging(log_file: Path) -> None:
    """Configure console and file logging."""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def resolve_phase_path(path: str | Path) -> Path:
    """Resolve a path relative to the phase directory, preserving absolute paths."""
    path = Path(path)
    return path if path.is_absolute() else PHASE_DIR / path


def read_text(path: Path) -> str:
    """Read a UTF-8 text file."""
    return path.read_text(encoding="utf-8", errors="ignore")


def write_text(path: Path, content: str) -> None:
    """Write a UTF-8 text file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_failed_prompts(path: Path, failed: list[str]) -> None:
    """Write failed prompt filenames, one per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{name}\n" for name in failed),
        encoding="utf-8",
    )


def model_supports_temperature(model: str) -> bool:
    """
    Return whether the selected model should receive the temperature parameter.

    Newer GPT reasoning/solution models may reject the Responses API
    temperature parameter. For safety, omit temperature for GPT-5 and later
    families, including names such as:

        gpt-5
        gpt-5.6-sol
        gpt-6.2-sol

    Older GPT-4-family models are still treated as supporting temperature.
    """
    normalized = model.strip().lower()

    no_temperature_prefixes = (
        "gpt-5",
        "gpt-6",
        "o1",
        "o3",
        "o4",
    )

    return not normalized.startswith(no_temperature_prefixes)


def is_transient_error(exc: Exception) -> bool:
    """Return True if the exception looks like a transient API/network error."""
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()

    transient_markers = [
        "rate",
        "timeout",
        "temporar",
        "connection",
        "server",
        "service unavailable",
        "gateway",
        "empty output",
        "429",
        "500",
        "502",
        "503",
        "504",
    ]

    return any(marker in name or marker in message for marker in transient_markers)


def call_api(
        *,
        client: OpenAI,
        model: str,
        full_prompt: str,
        max_output_tokens: int,
) -> str:
    """Send the full prompt file as a single user message."""
    kwargs = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": full_prompt,
            }
        ],
        "max_output_tokens": max_output_tokens,
    }

    if model_supports_temperature(model):
        kwargs["temperature"] = 0.0

    response = client.responses.create(**kwargs)

    output_text = getattr(response, "output_text", None)

    if not isinstance(output_text, str) or not output_text.strip():
        raise RuntimeError("API returned empty output.")

    return output_text.strip()


def call_api_with_retries(
        *,
        model: str,
        full_prompt: str,
        max_output_tokens: int,
        retries: int,
        base_sleep: float,
) -> str:
    """
    Retry wrapper with exponential backoff and jitter for transient failures.

    Creates a fresh client per prompt to avoid thread-safety assumptions.
    """
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            return call_api(
                client=client,
                model=model,
                full_prompt=full_prompt,
                max_output_tokens=max_output_tokens,
            )

        except Exception as exc:
            last_error = exc

            if attempt >= retries or not is_transient_error(exc):
                break

            sleep_seconds = base_sleep * (2 ** attempt)
            sleep_seconds = sleep_seconds * (0.8 + 0.4 * random.random())

            logging.warning(
                "Attempt %s/%s failed: %s — retrying in %.1fs",
                attempt + 1,
                retries + 1,
                exc,
                sleep_seconds,
                )

            time.sleep(sleep_seconds)

    raise RuntimeError(
        f"API call failed after {retries + 1} attempts: {last_error}"
    ) from last_error


# ------------------------------------------------------------
# Worker
# ------------------------------------------------------------

def process_prompt(
        *,
        path: Path,
        outpath: Path,
        model: str,
        max_tokens: int,
        retries: int,
        base_sleep: float,
) -> bool:
    """Process one prompt file."""
    try:
        logging.info("[WORKER] Reading %s", path.name)

        full_prompt = read_text(path).strip()

        if not full_prompt:
            raise ValueError("Prompt file is empty after stripping.")

        logging.info("[WORKER] Sending to GPT: %s", path.name)

        result = call_api_with_retries(
            model=model,
            full_prompt=full_prompt,
            max_output_tokens=max_tokens,
            retries=retries,
            base_sleep=base_sleep,
        )

        write_text(outpath, result)

        logging.info("[WORKER] Saved → %s", outpath)

        return True

    except Exception as exc:
        logging.error("[ERROR] %s: %s", path.name, exc)
        return False


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    args = parse_args()

    input_dir = resolve_phase_path(args.input)
    output_dir = resolve_phase_path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_file = (
        resolve_phase_path(args.log_file)
        if args.log_file
        else output_dir / DEFAULT_LOG_FILE_NAME
    )
    failed_file = (
        resolve_phase_path(args.failed_file)
        if args.failed_file
        else output_dir / DEFAULT_FAILED_FILE_NAME
    )

    setup_logging(log_file)

    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(
            f"ERROR: input directory does not exist or is not a directory: {input_dir}"
        )

    if args.workers <= 0:
        raise SystemExit("ERROR: --workers must be greater than 0.")

    if args.max_output_tokens <= 0:
        raise SystemExit("ERROR: --max-output-tokens must be greater than 0.")

    if args.retries < 0:
        raise SystemExit("ERROR: --retries must be non-negative.")

    if args.retry_base_sleep < 0:
        raise SystemExit("ERROR: --retry-base-sleep must be non-negative.")

    if args.limit < 0:
        raise SystemExit("ERROR: --limit must be non-negative.")

    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        raise SystemExit(
            "ERROR: OPENAI_API_KEY is not set in the environment or env/.env."
        )

    files = sorted(input_dir.glob("*.txt"))

    if args.limit:
        files = files[: args.limit]

    if not files:
        logging.info("No prompt files found.")
        sys.exit(0)

    tasks: list[tuple[Path, Path]] = []

    for prompt_file in files:
        outpath = output_dir / prompt_file.name

        if args.skip_existing and outpath.exists():
            continue

        tasks.append((prompt_file, outpath))

    if not tasks:
        logging.info("Nothing to do: all outputs already exist.")
        sys.exit(0)

    if failed_file.exists():
        failed_file.unlink()

    logging.info("Project: %s", DEFAULT_PROJECT)
    logging.info("Input directory: %s", input_dir)
    logging.info("Output directory: %s", output_dir)
    logging.info("Log file: %s", log_file)
    logging.info("Failed-prompts file: %s", failed_file)
    logging.info("Model: %s", args.model)
    logging.info("Temperature sent: %s", model_supports_temperature(args.model))
    logging.info("Max output tokens: %s", args.max_output_tokens)
    logging.info("Retries: %s", args.retries)
    logging.info("Retry base sleep: %s", args.retry_base_sleep)
    logging.info("Skip existing: %s", args.skip_existing)

    if args.limit:
        logging.info("Limit: %s prompt files", args.limit)

    logging.info("Submitting %s prompts using %s workers…", len(tasks), args.workers)

    succeeded = 0
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {
            pool.submit(
                process_prompt,
                path=input_path,
                outpath=output_path,
                model=args.model,
                max_tokens=args.max_output_tokens,
                retries=args.retries,
                base_sleep=args.retry_base_sleep,
            ): input_path
            for input_path, output_path in tasks
        }

        for future in as_completed(future_map):
            prompt_path = future_map[future]

            try:
                ok = future.result()
            except Exception as exc:
                logging.error("[ERROR] Unhandled worker failure for %s: %s", prompt_path.name, exc)
                ok = False

            if ok:
                succeeded += 1
            else:
                failed.append(prompt_path.name)

    logging.info("")
    logging.info("Done. Succeeded: %s/%s", succeeded, len(tasks))

    if failed:
        failed = sorted(failed)
        write_failed_prompts(failed_file, failed)

        logging.error("Failed prompts:")
        for name in failed:
            logging.error("  - %s", name)

        logging.error("Failed-prompts list written to: %s", failed_file)

        raise SystemExit("ERROR: some prompts failed. See log above.")

    logging.info("All prompts completed successfully.")


if __name__ == "__main__":
    main()