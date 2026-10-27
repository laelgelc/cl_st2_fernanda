#!/usr/bin/env python3
"""
Denoise Brazilian educational guideline excerpts with OpenAI or Gemini APIs.

The program is manifest-driven, resumable, concurrent, and writes:
- one Markdown file per successful excerpt;
- one metadata JSON file per processed excerpt;
- failures/invalid-response NDJSON files;
- a consolidated denoised NDJSON dataset;
- run manifest, timestamped manifest, summary, and log files.

Model routing:
- Models whose names start with "gemini-" use the Gemini API.
- Other models use the OpenAI API.

Environment:
- OPENAI_API_KEY is required for OpenAI models.
- GEMINI_API_KEY is required for Gemini models.
- By default, environment variables are also loaded from env/.env when present.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLACEHOLDER = "<<<GUIDELINE_EXCERPT_TEXT>>>"
PROGRAMME = "llm_denoise.py"

OPENAI_MODEL_PREFIXES = ("gpt-", "o")
GEMINI_MODEL_PREFIXES = ("gemini-",)


class FatalSetupError(RuntimeError):
    """Raised for fatal setup errors before processing starts."""


@dataclass(frozen=True)
class Config:
    base_dir: Path
    manifest: Path
    output: Path
    prompt: Path
    model: str
    limit: int | None
    only_filename: str | None
    resume: bool
    reprocess: bool
    dry_run: bool
    workers: int
    max_retries: int
    retry_backoff_seconds: float
    temperature: float
    max_output_tokens: int
    env_file: Path
    log_file: Path
    manifest_file: Path
    filename_field: str
    filepath_field: str
    state_field: str
    output_extension: str
    metadata_dir: Path
    denoised_ndjson: Path
    failures_ndjson: Path
    invalid_responses_ndjson: Path
    summary_json: Path


@dataclass(frozen=True)
class PlanItem:
    index: int
    row: dict[str, Any]
    valid: bool
    error_type: str | None
    error: str | None
    filename: str
    state: str
    filepath_raw: str
    excerpt_id: str
    source_path: Path
    markdown_path: Path
    metadata_path: Path


class TemperatureSupportCache:
    """Thread-safe cache for models that reject temperature."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._unsupported_models: set[str] = set()

    def supports_temperature(self, model: str) -> bool:
        with self._lock:
            return model not in self._unsupported_models

    def mark_unsupported(self, model: str) -> None:
        with self._lock:
            self._unsupported_models.add(model)


def model_family(model: str) -> str:
    model_lower = model.strip().lower()
    if model_lower.startswith(GEMINI_MODEL_PREFIXES):
        return "gemini"
    if model_lower.startswith(OPENAI_MODEL_PREFIXES):
        return "openai"
    return "openai"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def resolve_path(path: str | Path, base_dir: Path) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (base_dir / p).resolve()


def relpath(path: str | Path, base_dir: Path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(base_dir.resolve()))
    except Exception:
        return str(p)


def safe_path_part(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    if not text:
        text = default
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or default


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Denoise guideline excerpts with OpenAI or Gemini.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", required=True)

    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--only-filename",
        help="Process only manifest row(s) whose filename field exactly matches this value.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-output-tokens", type=int, default=1000)
    parser.add_argument("--env-file", default="env/.env")
    parser.add_argument("--log-file")
    parser.add_argument("--manifest-file")
    parser.add_argument("--filename-field", default="filename")
    parser.add_argument("--filepath-field", default="filepath")
    parser.add_argument("--state-field", default="state")
    parser.add_argument("--output-extension", default=".md")

    return parser.parse_args(argv)


def make_config(args: argparse.Namespace) -> Config:
    base_dir = Path(__file__).resolve().parent

    manifest = resolve_path(args.manifest, base_dir)
    output = resolve_path(args.output, base_dir)
    prompt = resolve_path(args.prompt, base_dir)
    env_file = resolve_path(args.env_file, base_dir)

    log_file = resolve_path(args.log_file, base_dir) if args.log_file else output / "llm_denoise.log"
    manifest_file = (
        resolve_path(args.manifest_file, base_dir)
        if args.manifest_file
        else output / "llm_denoise_manifest.json"
    )

    return Config(
        base_dir=base_dir,
        manifest=manifest,
        output=output,
        prompt=prompt,
        model=args.model,
        limit=args.limit,
        only_filename=args.only_filename.strip() if args.only_filename and args.only_filename.strip() else None,
        resume=args.resume,
        reprocess=args.reprocess,
        dry_run=args.dry_run,
        workers=args.workers,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        env_file=env_file,
        log_file=log_file,
        manifest_file=manifest_file,
        filename_field=args.filename_field,
        filepath_field=args.filepath_field,
        state_field=args.state_field,
        output_extension=args.output_extension,
        metadata_dir=output / "_llm_denoise_metadata",
        denoised_ndjson=output / "llm_denoised_guidelines.ndjson",
        failures_ndjson=output / "llm_denoise_failures.ndjson",
        invalid_responses_ndjson=output / "llm_denoise_invalid_responses.ndjson",
        summary_json=output / "llm_denoise_summary.json",
    )


def validate_basic_options(config: Config) -> None:
    if not config.model.strip():
        raise FatalSetupError("--model must not be empty")
    if config.limit is not None and config.limit <= 0:
        raise FatalSetupError("--limit must be greater than 0")
    if config.only_filename is not None and not config.only_filename.strip():
        raise FatalSetupError("--only-filename must not be empty")
    if config.workers <= 0:
        raise FatalSetupError("--workers must be greater than 0")
    if config.max_retries < 0:
        raise FatalSetupError("--max-retries must not be negative")
    if config.retry_backoff_seconds < 0:
        raise FatalSetupError("--retry-backoff-seconds must not be negative")
    if config.temperature < 0:
        raise FatalSetupError("--temperature must not be negative")
    if config.max_output_tokens <= 0:
        raise FatalSetupError("--max-output-tokens must be greater than 0")
    if not config.output_extension.startswith("."):
        raise FatalSetupError("--output-extension must start with '.'")
    if config.resume and config.reprocess:
        logging.warning("--reprocess supplied with --resume; reprocess takes precedence")

    if not config.manifest.exists():
        raise FatalSetupError(f"Manifest does not exist: {config.manifest}")
    if not config.manifest.is_file():
        raise FatalSetupError(f"Manifest is not a file: {config.manifest}")
    if not config.prompt.exists():
        raise FatalSetupError(f"Prompt does not exist: {config.prompt}")
    if not config.prompt.is_file():
        raise FatalSetupError(f"Prompt is not a file: {config.prompt}")

    try:
        config.output.mkdir(parents=True, exist_ok=True)
        config.metadata_dir.mkdir(parents=True, exist_ok=True)
        config.log_file.parent.mkdir(parents=True, exist_ok=True)
        config.manifest_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise FatalSetupError(f"Output directory cannot be created: {exc}") from exc


def setup_logging(config: Config) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")

    file_handler = logging.FileHandler(config.log_file, encoding="utf-8")
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)


def load_dotenv_file(path: Path) -> dict[str, Any]:
    found = path.exists() and path.is_file()
    loaded_keys: list[str] = []

    if found:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("export "):
                    stripped = stripped[len("export "):].strip()
                if "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
                    loaded_keys.append(key)

    return {
        "env_file_found": found,
        "loaded_keys": loaded_keys,
        "openai_api_key_available": bool(os.environ.get("OPENAI_API_KEY")),
        "gemini_api_key_available": bool(os.environ.get("GEMINI_API_KEY")),
        "openai_api_key_source": "env_file_or_process_environment" if os.environ.get("OPENAI_API_KEY") else None,
        "gemini_api_key_source": "env_file_or_process_environment" if os.environ.get("GEMINI_API_KEY") else None,
        "api_keys_logged": False,
    }


def validate_api_key_available(config: Config, env_metadata: dict[str, Any]) -> None:
    family = model_family(config.model)
    if family == "gemini":
        if not env_metadata["gemini_api_key_available"]:
            raise FatalSetupError("GEMINI_API_KEY is unavailable")
    else:
        if not env_metadata["openai_api_key_available"]:
            raise FatalSetupError("OPENAI_API_KEY is unavailable")


def load_prompt(config: Config) -> str:
    text = config.prompt.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise FatalSetupError("Prompt file is empty")
    if PLACEHOLDER not in text:
        raise FatalSetupError(f"Prompt file must contain placeholder {PLACEHOLDER}")
    return text


def load_manifest_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                rows.append(
                    {
                        "_manifest_parse_error": str(exc),
                        "_manifest_line_number": line_number,
                    }
                )
                continue

            if not isinstance(obj, dict):
                rows.append(
                    {
                        "_manifest_parse_error": "Manifest line is not a JSON object",
                        "_manifest_line_number": line_number,
                        "_manifest_value": obj,
                    }
                )
                continue

            obj["_manifest_line_number"] = line_number
            rows.append(obj)

    return rows


def filter_rows_by_filename(rows: list[dict[str, Any]], config: Config) -> list[dict[str, Any]]:
    if config.only_filename is None:
        return rows

    filtered = [
        row
        for row in rows
        if str(row.get(config.filename_field, "")).strip() == config.only_filename
    ]

    if not filtered:
        raise FatalSetupError(
            f"No manifest row matched --only-filename {config.only_filename!r} "
            f"using filename field {config.filename_field!r}"
        )

    if len(filtered) > 1:
        logging.warning(
            "--only-filename matched multiple rows filename=%s matches=%s",
            config.only_filename,
            len(filtered),
        )

    return filtered


def get_excerpt_id(filename: str) -> str:
    return safe_path_part(Path(filename).stem, default=f"excerpt_{uuid.uuid4().hex[:8]}")


def validate_manifest_row(row: dict[str, Any], config: Config) -> tuple[bool, str | None, str | None]:
    if "_manifest_parse_error" in row:
        return False, "invalid_manifest_json", row["_manifest_parse_error"]

    missing = [
        field
        for field in (config.filename_field, config.state_field, config.filepath_field)
        if field not in row or str(row.get(field, "")).strip() == ""
    ]
    if missing:
        return False, "missing_required_manifest_fields", f"Missing required field(s): {', '.join(missing)}"

    return True, None, None


def expected_markdown_output_path(config: Config, state: str, filename: str) -> Path:
    stem = safe_path_part(Path(filename).stem, default="excerpt")
    return config.output / safe_path_part(state, "unknown_state") / f"{stem}{config.output_extension}"


def expected_metadata_output_path(config: Config, state: str, filename: str) -> Path:
    stem = safe_path_part(Path(filename).stem, default="excerpt")
    return config.metadata_dir / safe_path_part(state, "unknown_state") / f"{stem}.json"


def build_plan(config: Config, rows: list[dict[str, Any]]) -> list[PlanItem]:
    planned_rows = rows[: config.limit] if config.limit is not None else rows
    plan: list[PlanItem] = []

    for index, row in enumerate(planned_rows):
        valid, error_type, error = validate_manifest_row(row, config)

        filename = str(row.get(config.filename_field, f"invalid_row_{index + 1}.txt"))
        state = safe_path_part(row.get(config.state_field, "unknown_state"), "unknown_state")
        filepath_raw = str(row.get(config.filepath_field, ""))
        excerpt_id = get_excerpt_id(filename)

        source_path = resolve_path(filepath_raw, config.base_dir) if filepath_raw else config.base_dir / "__missing__"
        markdown_path = expected_markdown_output_path(config, state, filename)
        metadata_path = expected_metadata_output_path(config, state, filename)

        plan.append(
            PlanItem(
                index=index,
                row=row,
                valid=valid,
                error_type=error_type,
                error=error,
                filename=filename,
                state=state,
                filepath_raw=filepath_raw,
                excerpt_id=excerpt_id,
                source_path=source_path,
                markdown_path=markdown_path,
                metadata_path=metadata_path,
            )
        )

    return plan


def existing_success(item: PlanItem) -> bool:
    if not item.markdown_path.exists() or not item.metadata_path.exists():
        return False
    try:
        metadata = json.loads(item.metadata_path.read_text(encoding="utf-8"))
        return metadata.get("status") == "success"
    except Exception:
        return False


def read_source_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def build_denoising_prompt(prompt_template: str, source_text: str) -> str:
    return prompt_template.replace(PLACEHOLDER, source_text)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
    ) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _obj_to_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, "to_json_dict"):
        try:
            return obj.to_json_dict()
        except Exception:
            pass
    return {}


def make_json_safe(value: Any) -> Any:
    """
    Recursively convert provider SDK objects and unusual Python values into
    JSON-serializable structures.

    This protects all metadata, manifest, summary, failure, invalid-response,
    and consolidated NDJSON writes from SDK-specific objects such as bytes.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "__type__": "bytes",
                "sha256": hashlib.sha256(value).hexdigest(),
                "size": len(value),
            }

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, dict):
        return {str(key): make_json_safe(nested) for key, nested in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [make_json_safe(item) for item in value]

    converted = _obj_to_dict(value)
    if converted:
        return make_json_safe(converted)

    return str(value)


def write_json_file(path: Path, obj: dict[str, Any]) -> None:
    safe_obj = make_json_safe(obj)
    write_text_atomic(path, json.dumps(safe_obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_ndjson_file(path: Path, rows: list[dict[str, Any]]) -> None:
    safe_rows = [make_json_safe(row) for row in rows]
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in safe_rows]
    write_text_atomic(path, "\n".join(lines) + ("\n" if lines else ""))


def make_openai_client() -> Any:
    try:
        from openai import OpenAI
    except Exception as exc:
        raise FatalSetupError("OpenAI Python SDK is unavailable") from exc
    return OpenAI()


def make_gemini_client() -> Any:
    try:
        from google import genai
    except Exception as exc:
        raise FatalSetupError("Google GenAI Python SDK is unavailable; install google-genai") from exc
    return genai.Client(vertexai=False)


def make_llm_client(config: Config) -> Any:
    if model_family(config.model) == "gemini":
        return make_gemini_client()
    return make_openai_client()


def _api_error_suggests_temperature_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return "temperature" in text and (
            "unsupported" in text
            or "not support" in text
            or "not supported" in text
            or "unknown parameter" in text
            or "invalid parameter" in text
    )


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    data = _obj_to_dict(response)
    texts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") in {"output_text", "text"} and isinstance(value.get("text"), str):
                texts.append(value["text"])
            elif isinstance(value.get("text"), str) and "annotations" in value:
                texts.append(value["text"])
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data.get("output", data))
    return "\n".join(t for t in texts if t.strip()).strip()


def extract_api_metadata(response: Any) -> dict[str, Any]:
    data = _obj_to_dict(response)
    usage = data.get("usage") or getattr(response, "usage", None)
    usage_dict = _obj_to_dict(usage)

    return {
        "id": data.get("id") or getattr(response, "id", None),
        "model": data.get("model") or getattr(response, "model", None),
        "usage": usage_dict,
    }


def extract_gemini_response_text(response: Any) -> str:
    response_text = getattr(response, "text", None)
    if isinstance(response_text, str) and response_text.strip():
        return response_text.strip()

    data = _obj_to_dict(response)
    texts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return "\n".join(t for t in texts if t.strip()).strip()


def extract_gemini_metadata(response: Any, config: Config) -> dict[str, Any]:
    data = _obj_to_dict(response)
    usage_metadata = getattr(response, "usage_metadata", None)

    return {
        "model": config.model,
        "usage_metadata": _obj_to_dict(usage_metadata),
        "response": data,
    }


def call_openai_with_retries(
        client: Any,
        config: Config,
        prompt: str,
        temperature_cache: TemperatureSupportCache,
) -> tuple[str, dict[str, Any], bool]:
    last_exc: Exception | None = None

    for attempt in range(config.max_retries + 1):
        temperature_sent = temperature_cache.supports_temperature(config.model)
        request: dict[str, Any] = {
            "model": config.model,
            "input": prompt,
            "max_output_tokens": config.max_output_tokens,
        }
        if temperature_sent:
            request["temperature"] = config.temperature

        try:
            response = client.responses.create(**request)
            raw_response_text = extract_response_text(response)
            api_metadata = extract_api_metadata(response)
            return raw_response_text, api_metadata, temperature_sent
        except Exception as exc:
            last_exc = exc

            if temperature_sent and _api_error_suggests_temperature_unsupported(exc):
                logging.warning("Model rejected temperature; retrying without temperature for future calls")
                temperature_cache.mark_unsupported(config.model)
                try:
                    request.pop("temperature", None)
                    response = client.responses.create(**request)
                    raw_response_text = extract_response_text(response)
                    api_metadata = extract_api_metadata(response)
                    return raw_response_text, api_metadata, False
                except Exception as second_exc:
                    last_exc = second_exc

            if attempt < config.max_retries:
                sleep_seconds = config.retry_backoff_seconds * (2**attempt)
                logging.warning(
                    "OpenAI API call failed; retrying attempt=%s/%s sleep_seconds=%.2f error=%s",
                    attempt + 1,
                    config.max_retries,
                    sleep_seconds,
                    str(last_exc),
                    )
                time.sleep(sleep_seconds)

    raise RuntimeError(f"OpenAI API error after retries: {last_exc}") from last_exc


def call_gemini_with_retries(
        client: Any,
        config: Config,
        prompt: str,
) -> tuple[str, dict[str, Any], bool]:
    last_exc: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            request: dict[str, Any] = {
                "model": config.model,
                "contents": [prompt],
            }

            response = client.models.generate_content(**request)
            raw_response_text = extract_gemini_response_text(response)
            api_metadata = extract_gemini_metadata(response, config)
            return raw_response_text, api_metadata, False
        except Exception as exc:
            last_exc = exc

            if attempt < config.max_retries:
                sleep_seconds = config.retry_backoff_seconds * (2**attempt)
                logging.warning(
                    "Gemini API call failed; retrying attempt=%s/%s sleep_seconds=%.2f error=%s",
                    attempt + 1,
                    config.max_retries,
                    sleep_seconds,
                    str(last_exc),
                    )
                time.sleep(sleep_seconds)

    raise RuntimeError(f"Gemini API error after retries: {last_exc}") from last_exc


def call_llm_with_retries(
        client: Any,
        config: Config,
        prompt: str,
        temperature_cache: TemperatureSupportCache,
) -> tuple[str, dict[str, Any], bool]:
    if model_family(config.model) == "gemini":
        return call_gemini_with_retries(client, config, prompt)
    return call_openai_with_retries(client, config, prompt, temperature_cache)


def usage_totals_add(totals: dict[str, int], usage: dict[str, Any]) -> None:
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value

    gemini_key_map = {
        "prompt_token_count": "input_tokens",
        "candidates_token_count": "output_tokens",
        "total_token_count": "total_tokens",
    }
    for source_key, target_key in gemini_key_map.items():
        value = usage.get(source_key)
        if isinstance(value, int):
            totals[target_key] = totals.get(target_key, 0) + value


def is_likely_refusal(text: str) -> bool:
    """
    Detect assistant-style refusals without rejecting legitimate quoted source text.

    This checks only the opening of the response and requires refusal-like phrasing
    that refers to the assistant's inability to perform the requested task.
    """
    stripped = text.strip()
    if not stripped:
        return False

    first_lines = "\n".join(stripped.splitlines()[:6]).strip()
    first_chunk = first_lines[:800].lower()

    first_chunk = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", first_chunk).strip()
    first_chunk = re.sub(r"^#+\s*", "", first_chunk).strip()
    first_chunk = re.sub(r"^>\s*", "", first_chunk).strip()

    refusal_patterns = [
        r"^(i\s+am\s+sorry|i'm\s+sorry|sorry),?\s+(but\s+)?i\s+(cannot|can't|am unable to)\b",
        r"^(i\s+cannot|i\s+can't|i\s+am\s+unable\s+to)\s+(assist|help|comply|provide|process|complete|do)\b",
        r"^as\s+an\s+ai\b.{0,200}\b(i\s+cannot|i\s+can't|i\s+am\s+unable\s+to)\b",
        r"^(cannot|can't)\s+comply\b",
        r"^(desculpe|sinto muito),?\s+(mas\s+)?(não\s+posso|não\s+consigo|sou\s+incapaz\s+de)\b",
        r"^(não\s+posso|não\s+consigo)\s+(ajudar|atender|cumprir|fornecer|processar|realizar|fazer)\b",
        r"^como\s+(um|uma)\s+(modelo|assistente|ia|inteligência artificial)\b.{0,200}\b(não\s+posso|não\s+consigo)\b",
    ]

    return any(re.search(pattern, first_chunk, flags=re.DOTALL) for pattern in refusal_patterns)


def validate_denoised_markdown(text: Any) -> tuple[bool, str | None]:
    if not isinstance(text, str):
        return False, "Response text is not a string"
    stripped = text.strip()
    if not stripped:
        return False, "Response text is empty"
    if PLACEHOLDER in stripped:
        return False, "Response contains prompt placeholder"
    if re.fullmatch(r"```[a-zA-Z0-9_-]*\s*```", stripped, flags=re.DOTALL):
        return False, "Response consists only of Markdown code fences"

    if is_likely_refusal(stripped):
        return False, "Response appears to be a refusal"

    wrapper_patterns = [
        "here is the denoised",
        "segue o texto",
        "texto denoised",
        "denoised version",
        "aqui está",
    ]
    lowered = stripped.lower()
    if any(pattern in lowered[:300] for pattern in wrapper_patterns):
        return False, "Response appears to contain an explanatory wrapper"

    try:
        stripped.encode("utf-8")
    except UnicodeEncodeError:
        return False, "Response cannot be encoded as UTF-8"

    return True, None


def base_metadata(config: Config, item: PlanItem, manifest_hash: str, prompt_hash: str) -> dict[str, Any]:
    return {
        "filename": item.filename,
        "excerpt_id": item.excerpt_id,
        "state": item.state,
        "input": {
            "manifest_file": relpath(config.manifest, config.base_dir),
            "source_file": item.filepath_raw,
            "prompt_file": relpath(config.prompt, config.base_dir),
        },
        "output": {
            "markdown_file": relpath(item.markdown_path, config.base_dir),
            "metadata_json": relpath(item.metadata_path, config.base_dir),
        },
        "manifest_row": item.row,
        "hashes": {
            "manifest_file_sha256": manifest_hash,
            "prompt_template_sha256": prompt_hash,
        },
    }


def build_failure_record(
        config: Config,
        item: PlanItem,
        manifest_hash: str,
        prompt_hash: str,
        error_type: str,
        error: str,
        started_at: float,
) -> dict[str, Any]:
    record = base_metadata(config, item, manifest_hash, prompt_hash)
    record.update(
        {
            "status": "failed",
            "error_type": error_type,
            "error": error,
            "created_at": utc_now_iso(),
            "duration_seconds": round(time.time() - started_at, 3),
        }
    )
    return record


def build_invalid_response_record(
        config: Config,
        item: PlanItem,
        manifest_hash: str,
        prompt_hash: str,
        raw_response_text: str,
        validation_error: str,
        api_metadata: dict[str, Any],
        started_at: float,
) -> dict[str, Any]:
    record = base_metadata(config, item, manifest_hash, prompt_hash)
    record.update(
        {
            "status": "invalid_response",
            "raw_response_text": raw_response_text,
            "validation_error": validation_error,
            "api_metadata": api_metadata,
            "created_at": utc_now_iso(),
            "duration_seconds": round(time.time() - started_at, 3),
        }
    )
    return record


def build_success_record(
        config: Config,
        item: PlanItem,
        manifest_hash: str,
        prompt_hash: str,
        source_text_hash: str,
        rendered_prompt_hash: str,
        raw_response_text: str,
        denoised_markdown: str,
        api_metadata: dict[str, Any],
        temperature_sent: bool,
        started_at: float,
) -> dict[str, Any]:
    record = base_metadata(config, item, manifest_hash, prompt_hash)
    record.update(
        {
            "status": "success",
            "model": {
                "configured_model": config.model,
                "model_family": model_family(config.model),
                "response_model": api_metadata.get("model") or config.model,
            },
            "hashes": {
                **record["hashes"],
                "source_text_sha256": source_text_hash,
                "rendered_prompt_sha256": rendered_prompt_hash,
                "raw_response_text_sha256": sha256_text(raw_response_text),
                "denoised_markdown_sha256": sha256_text(denoised_markdown),
            },
            "api_metadata": api_metadata,
            "raw_response_text": raw_response_text,
            "temperature": config.temperature,
            "temperature_sent_to_api": temperature_sent,
            "max_output_tokens": config.max_output_tokens,
            "max_output_tokens_sent_to_api": model_family(config.model) == "openai",
            "created_at": utc_now_iso(),
            "duration_seconds": round(time.time() - started_at, 3),
            "error": None,
        }
    )
    return record


def process_item(
        item: PlanItem,
        config: Config,
        prompt_template: str,
        manifest_hash: str,
        prompt_hash: str,
        client: Any,
        temperature_cache: TemperatureSupportCache,
) -> dict[str, Any]:
    started_at = time.time()
    logging.info("Processing index=%s filename=%s state=%s", item.index, item.filename, item.state)

    if not item.valid:
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            item.error_type or "invalid_manifest_row",
            item.error or "",
            started_at,
            )
        write_json_file(item.metadata_path, record)
        return record

    if not item.source_path.exists():
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "missing_source_file",
            "Source file not found",
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    if not item.source_path.is_file():
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "source_path_not_file",
            "Source path is not a file",
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    try:
        source_text = read_source_text(item.source_path)
    except Exception as exc:
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "unreadable_source_file",
            str(exc),
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    if not source_text.strip():
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "empty_source_file",
            "Source file is empty",
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    source_text_hash = sha256_text(source_text)
    rendered_prompt = build_denoising_prompt(prompt_template, source_text)
    rendered_prompt_hash = sha256_text(rendered_prompt)

    try:
        raw_response_text, api_metadata, temperature_sent = call_llm_with_retries(
            client,
            config,
            rendered_prompt,
            temperature_cache,
        )
    except Exception as exc:
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "api_error_after_retries",
            str(exc),
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    if not raw_response_text.strip():
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "empty_llm_response",
            "No usable response text found",
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    is_valid, validation_error = validate_denoised_markdown(raw_response_text)
    if not is_valid:
        record = build_invalid_response_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            raw_response_text,
            validation_error or "Invalid response",
            api_metadata,
            started_at,
            )
        write_json_file(item.metadata_path, record)
        return record

    denoised_markdown = raw_response_text.strip() + "\n"

    try:
        write_text_atomic(item.markdown_path, denoised_markdown)
    except Exception as exc:
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "markdown_output_write_failure",
            str(exc),
            started_at,
        )
        write_json_file(item.metadata_path, record)
        return record

    record = build_success_record(
        config,
        item,
        manifest_hash,
        prompt_hash,
        source_text_hash,
        rendered_prompt_hash,
        raw_response_text,
        denoised_markdown,
        api_metadata,
        temperature_sent,
        started_at,
    )

    try:
        write_json_file(item.metadata_path, record)
    except Exception as exc:
        record = build_failure_record(
            config,
            item,
            manifest_hash,
            prompt_hash,
            "metadata_json_write_failure",
            str(exc),
            started_at,
        )
        return record

    logging.info("Finished index=%s filename=%s status=success", item.index, item.filename)
    return record


def build_consolidated_success_row(config: Config, record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record["manifest_row"])
    hashes = record.get("hashes", {})
    api_metadata = record.get("api_metadata", {})

    row["llm_denoise"] = {
        "markdown_file": record["output"]["markdown_file"],
    }
    row["llm_denoise_metadata"] = {
        "status": record["status"],
        "model": record.get("model", {}).get("configured_model"),
        "model_family": record.get("model", {}).get("model_family"),
        "prompt_file": record["input"]["prompt_file"],
        "prompt_template_sha256": hashes.get("prompt_template_sha256"),
        "source_text_sha256": hashes.get("source_text_sha256"),
        "denoised_markdown_sha256": hashes.get("denoised_markdown_sha256"),
        "denoised_at": record.get("created_at"),
        "metadata_json": record["output"]["metadata_json"],
        "usage": api_metadata.get("usage", {}),
        "usage_metadata": api_metadata.get("usage_metadata", {}),
    }
    return row


def build_dry_run_record(
        config: Config,
        item: PlanItem,
        manifest_hash: str,
        prompt_hash: str,
        prompt_template: str,
) -> dict[str, Any]:
    started_at = time.time()
    record = base_metadata(config, item, manifest_hash, prompt_hash)
    record["status"] = "dry_run"

    if not item.valid:
        record["status"] = "failed"
        record["error_type"] = item.error_type
        record["error"] = item.error
    elif not item.source_path.exists():
        record["status"] = "failed"
        record["error_type"] = "missing_source_file"
        record["error"] = "Source file not found"
    elif not item.source_path.is_file():
        record["status"] = "failed"
        record["error_type"] = "source_path_not_file"
        record["error"] = "Source path is not a file"
    else:
        try:
            source_text = read_source_text(item.source_path)
            if not source_text.strip():
                record["status"] = "failed"
                record["error_type"] = "empty_source_file"
                record["error"] = "Source file is empty"
            else:
                rendered_prompt = build_denoising_prompt(prompt_template, source_text)
                record["hashes"].update(
                    {
                        "source_text_sha256": sha256_text(source_text),
                        "rendered_prompt_sha256": sha256_text(rendered_prompt),
                    }
                )
                record["dry_run"] = {
                    "source_chars": len(source_text),
                    "rendered_prompt_chars": len(rendered_prompt),
                    "would_write_markdown_file": relpath(item.markdown_path, config.base_dir),
                    "would_write_metadata_json": relpath(item.metadata_path, config.base_dir),
                }
        except Exception as exc:
            record["status"] = "failed"
            record["error_type"] = "unreadable_source_file"
            record["error"] = str(exc)

    record["created_at"] = utc_now_iso()
    record["duration_seconds"] = round(time.time() - started_at, 3)
    return record


def build_summary(
        run_id: str,
        config: Config,
        counts: dict[str, int],
        usage_totals: dict[str, int],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "programme": PROGRAMME,
        "model": config.model,
        "model_family": model_family(config.model),
        "prompt": relpath(config.prompt, config.base_dir),
        "manifest": relpath(config.manifest, config.base_dir),
        "output": relpath(config.output, config.base_dir),
        "denoised_ndjson": relpath(config.denoised_ndjson, config.base_dir),
        "counts": counts,
        "usage_totals": usage_totals,
    }


def build_run_manifest(
        run_id: str,
        config: Config,
        start_time: str,
        end_time: str,
        status: str,
        env_metadata: dict[str, Any],
        manifest_hash: str,
        prompt_hash: str,
        counts: dict[str, int],
        usage_totals: dict[str, int],
        excerpts: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "programme": PROGRAMME,
        "start_time": start_time,
        "end_time": end_time,
        "status": status,
        "paths": {
            "manifest": relpath(config.manifest, config.base_dir),
            "output": relpath(config.output, config.base_dir),
            "prompt": relpath(config.prompt, config.base_dir),
            "log_file": relpath(config.log_file, config.base_dir),
            "metadata_dir": relpath(config.metadata_dir, config.base_dir),
            "denoised_ndjson": relpath(config.denoised_ndjson, config.base_dir),
            "failures_ndjson": relpath(config.failures_ndjson, config.base_dir),
            "invalid_responses_ndjson": relpath(config.invalid_responses_ndjson, config.base_dir),
        },
        "environment": {
            "env_file": relpath(config.env_file, config.base_dir),
            "env_file_found": env_metadata["env_file_found"],
            "model_family": model_family(config.model),
            "openai_api_key_available": env_metadata["openai_api_key_available"],
            "openai_api_key_source": env_metadata["openai_api_key_source"],
            "gemini_api_key_available": env_metadata["gemini_api_key_available"],
            "gemini_api_key_source": env_metadata["gemini_api_key_source"],
            "api_keys_logged": False,
        },
        "model_configuration": {
            "model": config.model,
            "model_family": model_family(config.model),
            "temperature": config.temperature,
            "max_output_tokens": config.max_output_tokens,
        },
        "processing": {
            "workers": config.workers,
            "limit": config.limit,
            "only_filename": config.only_filename,
            "resume": config.resume,
            "reprocess": config.reprocess,
            "dry_run": config.dry_run,
            "max_retries": config.max_retries,
            "retry_backoff_seconds": config.retry_backoff_seconds,
            "output_extension": config.output_extension,
        },
        "hashes": {
            "manifest_file_sha256": manifest_hash,
            "prompt_template_sha256": prompt_hash,
        },
        "counts": counts,
        "usage_totals": usage_totals,
        "excerpts": excerpts,
    }


def make_excerpt_index(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": record.get("filename"),
        "excerpt_id": record.get("excerpt_id"),
        "state": record.get("state"),
        "status": record.get("status"),
        "markdown_file": record.get("output", {}).get("markdown_file"),
        "metadata_json": record.get("output", {}).get("metadata_json"),
    }


def main(argv: list[str] | None = None) -> int:
    start_time = utc_now_iso()
    run_id = make_run_id()

    try:
        args = parse_args(argv)
        config = make_config(args)
        validate_basic_options(config)
        setup_logging(config)

        logging.info("Starting %s run_id=%s", PROGRAMME, run_id)
        logging.info("Manifest: %s", config.manifest)
        logging.info("Output: %s", config.output)
        logging.info("Prompt: %s", config.prompt)
        logging.info("Model: %s family=%s", config.model, model_family(config.model))
        logging.info(
            "Workers: %s dry_run=%s resume=%s reprocess=%s only_filename=%s",
            config.workers,
            config.dry_run,
            config.resume,
            config.reprocess,
            config.only_filename,
        )

        env_metadata = load_dotenv_file(config.env_file)
        if not config.dry_run:
            validate_api_key_available(config, env_metadata)

        prompt_template = load_prompt(config)
        prompt_hash = sha256_text(prompt_template)
        manifest_hash = sha256_file(config.manifest)

        if not config.dry_run:
            make_llm_client(config)

        rows = load_manifest_rows(config.manifest)
        filtered_rows = filter_rows_by_filename(rows, config)
        plan = build_plan(config, filtered_rows)

        for item in plan:
            item.markdown_path.parent.mkdir(parents=True, exist_ok=True)
            item.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        results_by_index: dict[int, dict[str, Any]] = {}

        to_process: list[PlanItem] = []
        for item in plan:
            if config.resume and not config.reprocess and existing_success(item):
                metadata = json.loads(item.metadata_path.read_text(encoding="utf-8"))
                metadata["status"] = "skipped_existing"
                results_by_index[item.index] = metadata
                logging.info("Skipped existing success filename=%s", item.filename)
            else:
                to_process.append(item)

        if config.dry_run:
            for item in to_process:
                results_by_index[item.index] = build_dry_run_record(
                    config,
                    item,
                    manifest_hash,
                    prompt_hash,
                    prompt_template,
                )
        else:
            client = make_llm_client(config)
            temperature_cache = TemperatureSupportCache()

            with concurrent.futures.ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(
                        process_item,
                        item,
                        config,
                        prompt_template,
                        manifest_hash,
                        prompt_hash,
                        client,
                        temperature_cache,
                    ): item
                    for item in to_process
                }

                for future in concurrent.futures.as_completed(futures):
                    item = futures[future]
                    try:
                        results_by_index[item.index] = future.result()
                    except Exception as exc:
                        logging.exception("Unexpected worker failure index=%s filename=%s", item.index, item.filename)
                        record = build_failure_record(
                            config,
                            item,
                            manifest_hash,
                            prompt_hash,
                            "unexpected_worker_failure",
                            str(exc),
                            time.time(),
                        )
                        try:
                            write_json_file(item.metadata_path, record)
                        except Exception:
                            logging.exception("Could not write failure metadata")
                        results_by_index[item.index] = record

        ordered_results = [results_by_index[i] for i in sorted(results_by_index)]

        failures = [r for r in ordered_results if r.get("status") == "failed"]
        invalid = [r for r in ordered_results if r.get("status") == "invalid_response"]
        successes = [r for r in ordered_results if r.get("status") == "success"]
        dry_runs = [r for r in ordered_results if r.get("status") == "dry_run"]
        skipped = [r for r in ordered_results if r.get("status") == "skipped_existing"]

        consolidated = [build_consolidated_success_row(config, r) for r in successes]

        write_ndjson_file(config.failures_ndjson, failures)
        write_ndjson_file(config.invalid_responses_ndjson, invalid)
        write_ndjson_file(config.denoised_ndjson, consolidated)

        usage_totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for record in ordered_results:
            api_metadata = record.get("api_metadata", {})
            usage_totals_add(usage_totals, api_metadata.get("usage", {}))
            usage_totals_add(usage_totals, api_metadata.get("usage_metadata", {}))

        counts = {
            "manifest_rows_total": len(rows),
            "manifest_rows_matched": len(filtered_rows),
            "excerpts_planned": len(plan),
            "excerpts_succeeded": len(successes),
            "excerpts_failed": len(failures),
            "excerpts_invalid_response": len(invalid),
            "excerpts_skipped_existing": len(skipped),
            "excerpts_dry_run": len(dry_runs),
        }

        run_status = "success" if not failures and not invalid else "completed_with_errors"
        end_time = utc_now_iso()

        summary = build_summary(run_id, config, counts, usage_totals)
        write_json_file(config.summary_json, summary)

        run_manifest = build_run_manifest(
            run_id,
            config,
            start_time,
            end_time,
            run_status,
            env_metadata,
            manifest_hash,
            prompt_hash,
            counts,
            usage_totals,
            [make_excerpt_index(r) for r in ordered_results],
        )
        write_json_file(config.manifest_file, run_manifest)
        write_json_file(config.output / f"llm_denoise_manifest_{run_id}.json", run_manifest)

        logging.info("Completed run_id=%s status=%s counts=%s", run_id, run_status, counts)
        return 0 if run_status == "success" else 1

    except KeyboardInterrupt:
        logging.error("Interrupted")
        return 130
    except FatalSetupError as exc:
        logging.error("Fatal setup error: %s", exc)
        return 1
    except Exception as exc:
        logging.exception("Fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())