#!/usr/bin/env python3
"""Selected-page ENADE denoising and chapter consolidation."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import logging
import math
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROGRAMME = "llm_denoise.py"
PLACEHOLDER = "<<<ENADE_REPORT_TEXT>>>"
REQUIRED_FIELDS = ("chapter_of_interest", "filename_stem", "filepath_ori", "chapter_page_filepath_txt")
PAGE_PATTERN = re.compile(r"_page_(\d+)\.txt$", re.IGNORECASE)
SCHEMA_VERSION = "selected-page-json-v1"
__all__ = [
    "Config", "FatalProviderError", "FatalSetupError", "Page", "PLACEHOLDER", "build_pages", "build_prompt",
    "call_with_retries", "chapter_output_path", "consolidate_chapter", "context_pages", "is_fatal_provider_error",
    "load_existing_success", "main", "parse_page_number", "process_work_queue", "request_fingerprint",
    "validate_response",
]


class FatalSetupError(RuntimeError):
    """Fatal configuration or input error discovered before processing."""


class FatalProviderError(RuntimeError):
    """Provider configuration error that makes further requests futile."""


@dataclass(frozen=True)
class Config:
    base_dir: Path
    manifest: Path
    prompt: Path
    output: Path
    model: str
    window_size: int
    workers: int
    max_retries: int
    retry_backoff_seconds: float
    temperature: float | None
    max_output_tokens: int
    env_file: Path
    limit: int | None
    only_filename: str | None
    resume: bool
    reprocess: bool
    dry_run: bool


@dataclass(frozen=True)
class Page:
    row: dict[str, Any]
    group: tuple[str, str, str]
    page_number: int
    source_path: Path
    source_text: str
    source_hash: str
    document_id: str
    result_path: Path

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "filepath_ori": self.group[0],
            "filename_stem": self.group[1],
            "chapter_of_interest": self.group[2],
            "page_number": self.page_number,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path_part(value: str, default: str = "unknown") -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip()).strip("._")
    return value or default


def resolve_path(value: str | Path, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (base_dir / path).resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    base_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Denoise selected ENADE pages and consolidate prose by chapter.")
    parser.add_argument("--input-manifest", "--manifest", dest="manifest",
                        default="corpus/enade_chapters_clean_up_revised_dataset.ndjson")
    parser.add_argument("--prompt", default="denoising_prompts/denoising_v1.md")
    parser.add_argument("--output", default="corpus/03_enade_denoised")
    parser.add_argument("--model", required=True)
    parser.add_argument("--window-size", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--temperature", type=float, default=None,
                        help="Explicitly set sampling temperature; omitted by default for model compatibility.")
    parser.add_argument("--max-output-tokens", type=int, default=10000)
    parser.add_argument("--env-file", default="env/.env")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only-filename", help="Process only rows whose filename_stem matches this value.")
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument("--resume", action="store_true", help="Reuse successful results with matching request fingerprints.")
    cache_group.add_argument("--reprocess", action="store_true", help="Ignore cached results and call the model again.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and report planned windows without calling the API.")
    args = parser.parse_args(argv)
    args.base_dir = base_dir
    return args


def make_config(args: argparse.Namespace) -> Config:
    base_dir = args.base_dir
    return Config(
        base_dir=base_dir,
        manifest=resolve_path(args.manifest, base_dir),
        prompt=resolve_path(args.prompt, base_dir),
        output=resolve_path(args.output, base_dir),
        model=args.model.strip(),
        window_size=args.window_size,
        workers=args.workers,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        env_file=resolve_path(args.env_file, base_dir),
        limit=args.limit,
        only_filename=args.only_filename.strip() if args.only_filename else None,
        resume=args.resume,
        reprocess=args.reprocess,
        dry_run=args.dry_run,
    )


def validate_config(config: Config) -> None:
    if not config.model:
        raise FatalSetupError("--model must not be empty")
    if config.window_size <= 0 or config.window_size % 2 == 0:
        raise FatalSetupError("--window-size must be a positive odd integer")
    if config.workers <= 0 or config.workers > 64:
        raise FatalSetupError("--workers must be between 1 and 64")
    if config.max_retries < 0 or config.max_retries > 10:
        raise FatalSetupError("--max-retries must be between 0 and 10")
    if (not math.isfinite(config.retry_backoff_seconds) or config.retry_backoff_seconds < 0
            or config.retry_backoff_seconds > 300):
        raise FatalSetupError("--retry-backoff-seconds must be between 0 and 300")
    if config.temperature is not None and (not math.isfinite(config.temperature) or config.temperature < 0):
        raise FatalSetupError("--temperature must be a finite non-negative number")
    if config.max_output_tokens <= 0:
        raise FatalSetupError("--max-output-tokens must be greater than zero")
    if not config.manifest.is_file():
        raise FatalSetupError(f"Input manifest is not a file: {config.manifest}")
    if not config.prompt.is_file():
        raise FatalSetupError(f"Prompt is not a file: {config.prompt}")
    if config.output == config.manifest or config.output == config.prompt:
        raise FatalSetupError("Output directory must not replace the input manifest or prompt")


def load_dotenv_file(path: Path) -> dict[str, Any]:
    found = path.is_file()
    loaded: list[str] = []
    if found:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return {
        "env_file_found": found,
        "loaded_keys": loaded,
        "openai_api_key_available": bool(os.environ.get("OPENAI_API_KEY")),
        "openai_api_key_source": "env_file" if "OPENAI_API_KEY" in loaded else "process_environment",
        "gemini_api_key_available": bool(os.environ.get("GEMINI_API_KEY")),
        "gemini_api_key_source": "env_file" if "GEMINI_API_KEY" in loaded else "process_environment",
    }


def model_family(model: str) -> str:
    return "gemini" if model.lower().startswith("gemini-") else "openai"


def validate_credentials(model: str, metadata: dict[str, Any]) -> None:
    key = "gemini_api_key_available" if model_family(model) == "gemini" else "openai_api_key_available"
    if not metadata[key]:
        variable = "GEMINI_API_KEY" if model_family(model) == "gemini" else "OPENAI_API_KEY"
        raise FatalSetupError(f"{variable} is unavailable")


def load_prompt(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FatalSetupError(f"Could not read prompt as UTF-8: {exc}") from exc
    if not prompt.strip() or prompt.count(PLACEHOLDER) != 1:
        raise FatalSetupError(f"Prompt must be non-empty and contain exactly one {PLACEHOLDER} marker")
    return prompt


def load_manifest_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FatalSetupError(f"Invalid NDJSON on line {line_number}: {exc.msg}") from exc
                if not isinstance(row, dict):
                    raise FatalSetupError(f"Manifest line {line_number} is not a JSON object")
                row["_manifest_line_number"] = line_number
                rows.append(row)
    except (OSError, UnicodeError) as exc:
        raise FatalSetupError(f"Could not read manifest: {exc}") from exc
    if not rows:
        raise FatalSetupError("Input manifest contains no rows")
    return rows


def parse_page_number(path: str | Path) -> int:
    match = PAGE_PATTERN.search(Path(path).name)
    if not match:
        raise FatalSetupError(f"Page filename must end with _page_<number>.txt: {path}")
    return int(match.group(1))


def group_identity(row: dict[str, Any]) -> tuple[str, str, str]:
    return (str(row["filepath_ori"]), str(row["filename_stem"]), str(row["chapter_of_interest"]))


def read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FatalSetupError(f"Cannot read selected page as UTF-8 ({path}): {exc}") from exc


def build_document_id(filepath_ori: str, filename_stem: str) -> str:
    return f"{safe_path_part(filename_stem, 'document')}_{sha256_text(filepath_ori)[:10]}"


def result_path_for(output: Path, group: tuple[str, str, str], document_id: str, page_number: int) -> Path:
    chapter = safe_path_part(group[2], "chapter")
    return output / "pages" / chapter / document_id / f"page_{page_number}.json"


def build_pages(rows: list[dict[str, Any]], config: Config) -> list[Page]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        missing = [field for field in REQUIRED_FIELDS if not isinstance(row.get(field), str) or not row[field].strip()]
        line = row.get("_manifest_line_number", "?")
        if missing:
            raise FatalSetupError(f"Manifest line {line} is missing required string field(s): {', '.join(missing)}")
        if config.only_filename and row["filename_stem"] != config.only_filename:
            continue
        selected.append(row)
    if config.only_filename and not selected:
        raise FatalSetupError(f"No manifest rows matched --only-filename {config.only_filename!r}")
    if config.limit is not None:
        if config.limit <= 0:
            raise FatalSetupError("--limit must be greater than zero")
        selected = selected[:config.limit]
    if not selected:
        raise FatalSetupError("No selected manifest rows remain after filtering")

    seen: set[tuple[tuple[str, str, str], int]] = set()
    pages: list[Page] = []
    output_paths: set[Path] = set()
    for row in selected:
        group = group_identity(row)
        page_number = parse_page_number(row["chapter_page_filepath_txt"])
        identity = (group, page_number)
        if identity in seen:
            raise FatalSetupError(f"Duplicate target identity for {group!r}, page {page_number}")
        seen.add(identity)
        source_path = resolve_path(row["chapter_page_filepath_txt"], config.base_dir)
        if not source_path.is_file():
            raise FatalSetupError(f"Selected page does not exist or is not a file (manifest line {row['_manifest_line_number']}): {source_path}")
        source_text = read_utf8(source_path)
        document_id = build_document_id(group[0], group[1])
        result_path = result_path_for(config.output, group, document_id, page_number)
        if result_path in output_paths:
            raise FatalSetupError(f"Output collision detected for {result_path}")
        if result_path == source_path:
            raise FatalSetupError(f"Page result would overwrite immutable input: {source_path}")
        output_paths.add(result_path)
        pages.append(Page(row, group, page_number, source_path, source_text, sha256_text(source_text), document_id, result_path))
    pages.sort(key=lambda page: (page.group, page.page_number))
    return pages


def context_pages(target: Page, group_pages: list[Page], window_size: int) -> list[Page]:
    if window_size <= 0 or window_size % 2 == 0:
        raise ValueError("window_size must be a positive odd integer")
    by_number = {page.page_number: page for page in group_pages if page.group == target.group}
    radius = window_size // 2
    numbers = [target.page_number]
    for direction in (-1, 1):
        for offset in range(1, radius + 1):
            number = target.page_number + direction * offset
            if number not in by_number:
                break
            numbers.append(number)
    return [by_number[number] for number in sorted(numbers)]


def render_page_input(pages: list[Page], target: Page) -> str:
    rendered: list[str] = []
    for page in pages:
        role = "target" if page == target else "context"
        page_text = html.escape(page.source_text, quote=False).replace("]]>", "]]&#62;")
        rendered.append(f'<page page_number="{page.page_number}" role="{role}">{page_text}</page>')
    return "\n".join(rendered)


def build_prompt(template: str, pages: list[Page], target: Page) -> str:
    if template.count(PLACEHOLDER) != 1:
        raise FatalSetupError(f"Prompt must contain exactly one {PLACEHOLDER} marker")
    return template.replace(PLACEHOLDER, render_page_input(pages, target))


def request_fingerprint(target: Page, contexts: list[Page], prompt_hash: str, config: Config) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "target": {**target.identity, "content_hash": target.source_hash},
        "context": [{**page.identity, "content_hash": page.source_hash} for page in contexts if page != target],
        "prompt_hash": prompt_hash,
        "window_size": config.window_size,
        "provider": model_family(config.model),
        "model": config.model,
        "temperature": config.temperature,
        "max_output_tokens": config.max_output_tokens,
    }
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key {key!r}")
        result[key] = value
    return result


def is_likely_refusal(text: str) -> bool:
    beginning = text.strip()[:800].lower()
    patterns = (
        r"^(i\s+am\s+sorry|i'm\s+sorry|sorry),?\s+(but\s+)?i\s+(cannot|can't|am unable to)\b",
        r"^(i\s+cannot|i\s+can't|i\s+am\s+unable\s+to)\s+(assist|help|comply|provide|process|complete|do)\b",
        r"^as\s+an\s+ai\b.{0,200}\b(i\s+cannot|i\s+can't|i\s+am\s+unable\s+to)\b",
        r"^(desculpe|sinto muito),?\s+(mas\s+)?(não\s+posso|não\s+consigo|sou incapaz de)\b",
        r"^(não\s+posso|não\s+consigo)\s+(ajudar|atender|cumprir|fornecer|processar|realizar|fazer)\b",
    )
    return any(re.search(pattern, beginning, flags=re.DOTALL) for pattern in patterns)


def validate_response(raw_response: str) -> tuple[str, list[str]]:
    if not raw_response.strip():
        raise ValueError("Provider returned empty response text")
    try:
        parsed = json.loads(raw_response, object_pairs_hook=_reject_duplicate_json_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON response: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Response JSON must be an object")
    if set(parsed) != {"text", "review_notes"}:
        raise ValueError("Response object must contain exactly 'text' and 'review_notes'")
    text = parsed["text"]
    notes = parsed["review_notes"]
    if not isinstance(text, str):
        raise ValueError("Response 'text' must be a string")
    if is_likely_refusal(text):
        raise ValueError("Response appears to be a model refusal")
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        raise ValueError("Response 'review_notes' must be an array of strings")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Response 'text' cannot be encoded as UTF-8") from exc
    return text, notes


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_ndjson(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def load_existing_success(page: Page, fingerprint: str) -> dict[str, Any] | None:
    try:
        record = json.loads(page.result_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    text = record.get("text") if isinstance(record, dict) else None
    if (isinstance(record, dict) and record.get("status") == "success"
            and record.get("identity") == page.identity
            and record.get("request_fingerprint") == fingerprint
            and isinstance(text, str) and record.get("text_sha256") == sha256_text(text)
            and record.get("empty_text") == (text == "")
            and isinstance(record.get("review_notes"), list)
            and all(isinstance(note, str) for note in record["review_notes"])):
        return record
    return None


def _obj_to_dict(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _obj_to_dict(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_obj_to_dict(item) for item in value]
    for method in ("model_dump", "to_dict"):
        if hasattr(value, method):
            try:
                return _obj_to_dict(getattr(value, method)())
            except Exception:
                continue
    if hasattr(value, "__dict__"):
        return {str(key): _obj_to_dict(item) for key, item in vars(value).items() if not key.startswith("_")}
    return str(value)


def _extract_text(response: Any, family: str) -> str:
    direct = getattr(response, "text", None) if family == "gemini" else getattr(response, "output_text", None)
    if isinstance(direct, str):
        return direct
    data = _obj_to_dict(response)
    if isinstance(data, dict):
        direct = data.get("text") if family == "gemini" else data.get("output_text")
        if isinstance(direct, str):
            return direct
    texts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if isinstance(item.get("text"), str):
                texts.append(item["text"])
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(data)
    return "\n".join(texts)


def _extract_metadata(response: Any, family: str, model: str) -> dict[str, Any]:
    data = _obj_to_dict(response)
    if not isinstance(data, dict):
        data = {}
    usage = data.get("usage") if family == "openai" else data.get("usage_metadata")
    return {"model": data.get("model") or model, "response_id": data.get("id"), "usage": _obj_to_dict(usage)}


def make_llm_client(config: Config) -> Any:
    if model_family(config.model) == "gemini":
        try:
            from google import genai
        except ImportError as exc:
            raise FatalSetupError("Google GenAI SDK is unavailable; install google-genai") from exc
        return genai.Client(vertexai=False)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise FatalSetupError("OpenAI Python SDK is unavailable; install openai") from exc
    return OpenAI()


def is_recoverable_provider_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (408, 409, 425, 429) or (isinstance(status, int) and status >= 500):
        return True
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return any(token in name for token in ("timeout", "connection", "ratelimit", "internalserver", "serviceunavailable")) or any(
        token in message for token in ("temporarily unavailable", "service unavailable", "rate limit", "timed out", "connection reset")
    )


def is_fatal_provider_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status in (401, 403, 404):
        return True
    message = str(exc).lower()
    fatal_hints = (
        "invalid api key", "incorrect api key", "api key not valid", "authentication",
        "permission denied", "does not have access", "model not found", "model_not_found",
        "model is not available", "does not exist", "unsupported parameter", "unsupported value",
        "unknown parameter", "not supported with this model", "not supported for this model",
    )
    return any(hint in message for hint in fatal_hints)


def _provider_call(client: Any, config: Config, prompt: str) -> tuple[str, dict[str, Any]]:
    family = model_family(config.model)
    if family == "openai":
        request: dict[str, Any] = {
            "model": config.model,
            "input": prompt,
            "max_output_tokens": config.max_output_tokens,
            "text": {"format": {"type": "json_object"}},
        }
        if config.temperature is not None:
            request["temperature"] = config.temperature
        response = client.responses.create(**request)
    else:
        response = client.models.generate_content(
            model=config.model,
            contents=[prompt],
            config={"response_mime_type": "application/json", "max_output_tokens": config.max_output_tokens,
                    **({"temperature": config.temperature} if config.temperature is not None else {})},
        )
    return _extract_text(response, family), _extract_metadata(response, family, config.model)


def call_with_retries(client: Any, config: Config, prompt: str) -> tuple[str, dict[str, Any], int]:
    for attempt in range(config.max_retries + 1):
        try:
            raw, metadata = _provider_call(client, config, prompt)
            return raw, metadata, attempt
        except Exception as exc:
            if is_fatal_provider_error(exc):
                raise FatalProviderError(
                    f"Provider configuration error ({type(exc).__name__}): {str(exc)[:400]}"
                ) from exc
            if attempt >= config.max_retries or not is_recoverable_provider_error(exc):
                raise RuntimeError(f"Provider request failed ({type(exc).__name__}): {str(exc)[:400]}") from exc
            delay = min(config.retry_backoff_seconds * (2 ** attempt), 300.0)
            logging.warning("Transient provider error (%s); retry %d/%d after %.2fs", type(exc).__name__, attempt + 1,
                            config.max_retries, delay)
            time.sleep(delay)
    raise AssertionError("unreachable")


def sanitize_error(exc: Exception) -> str:
    message = str(exc)
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        secret = os.environ.get(key)
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:500]


def base_page_record(page: Page, prompt_hash: str, fingerprint: str, contexts: list[Page], config: Config) -> dict[str, Any]:
    return {
        "identity": page.identity,
        "status": "failed",
        "input": {"source_path": str(page.source_path), "source_sha256": page.source_hash},
        "model": {"provider": model_family(config.model), "configured_model": config.model},
        "prompt_sha256": prompt_hash,
        "window_size": config.window_size,
        "context_pages": [{"page_number": item.page_number, "source_path": str(item.source_path),
                           "source_sha256": item.source_hash} for item in contexts if item != page],
        "request_fingerprint": fingerprint,
        "created_at": utc_now_iso(),
    }


def process_target(
    page: Page,
    contexts: list[Page],
    template: str,
    prompt_hash: str,
    fingerprint: str,
    config: Config,
    call_provider: Callable[[str], tuple[str, dict[str, Any], int]],
    invalid_dir: Path,
) -> dict[str, Any]:
    record = base_page_record(page, prompt_hash, fingerprint, contexts, config)
    started = time.monotonic()
    try:
        prompt = build_prompt(template, contexts, page)
        record["rendered_prompt_sha256"] = sha256_text(prompt)
        raw_response, api_metadata, retry_count = call_provider(prompt)
        try:
            text, review_notes = validate_response(raw_response)
        except ValueError as exc:
            invalid_path = invalid_dir / safe_path_part(page.group[2]) / page.document_id / f"page_{page.page_number}.json"
            atomic_write_json(invalid_path, {
                **record,
                "raw_response_excerpt": raw_response[:10000],
                "raw_response_truncated": len(raw_response) > 10000,
                "validation_error": str(exc),
                "api_metadata": api_metadata,
            })
            record.update({"status": "invalid_response", "error_type": "invalid_json_or_schema", "error": str(exc),
                           "invalid_response_path": str(invalid_path), "api_metadata": api_metadata, "retry_count": retry_count})
        else:
            record.update({"status": "success", "text": text, "text_sha256": sha256_text(text), "empty_text": text == "",
                           "review_notes": review_notes, "api_metadata": api_metadata, "retry_count": retry_count})
    except Exception as exc:
        record.update({"status": "failed", "error_type": type(exc).__name__, "error": sanitize_error(exc),
                       "run_fatal_error": isinstance(exc, FatalProviderError)})
    record["duration_seconds"] = round(time.monotonic() - started, 3)
    try:
        atomic_write_json(page.result_path, record)
    except Exception as exc:
        record.update({"status": "failed", "error_type": "page_result_write_error", "error": sanitize_error(exc)})
    return record


def process_work_queue(
    work: list[tuple[Page, list[Page], str]],
    records_by_group: dict[tuple[str, str, str], dict[int, dict[str, Any]]],
    template: str,
    prompt_hash: str,
    config: Config,
    call_provider: Callable[[str], tuple[str, dict[str, Any], int]],
    invalid_dir: Path,
) -> str | None:
    def run_item(item: tuple[Page, list[Page], str]) -> dict[str, Any]:
        page, window, fingerprint = item
        try:
            return process_target(page, window, template, prompt_hash, fingerprint, config, call_provider, invalid_dir)
        except Exception as exc:
            record = base_page_record(page, prompt_hash, fingerprint, window, config)
            record.update({"status": "failed", "error_type": type(exc).__name__, "error": sanitize_error(exc),
                           "run_fatal_error": isinstance(exc, FatalProviderError)})
            try:
                atomic_write_json(page.result_path, record)
            except Exception as write_exc:
                record.update({"error_type": "page_result_write_error", "error": sanitize_error(write_exc)})
            return record

    def store_item(item: tuple[Page, list[Page], str], record: dict[str, Any]) -> None:
        page = item[0]
        records_by_group[page.group][page.page_number] = record
        logging.info("Page completed chapter=%s page=%d status=%s", page.group[2], page.page_number,
                     record.get("status"))

    fatal_error: str | None = None
    next_index = 0
    if work:
        first_record = run_item(work[0])
        store_item(work[0], first_record)
        next_index = 1
        if first_record.get("run_fatal_error"):
            fatal_error = first_record.get("error", "Provider configuration error")

    with concurrent.futures.ThreadPoolExecutor(max_workers=config.workers) as executor:
        futures: dict[concurrent.futures.Future[dict[str, Any]], tuple[Page, list[Page], str]] = {}

        def submit_available() -> None:
            nonlocal next_index
            while next_index < len(work) and len(futures) < config.workers:
                item = work[next_index]
                futures[executor.submit(run_item, item)] = item
                next_index += 1

        if fatal_error is None:
            submit_available()
        while futures:
            done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                item = futures.pop(future)
                record = future.result()
                store_item(item, record)
                if record.get("run_fatal_error") and fatal_error is None:
                    fatal_error = record.get("error", "Provider configuration error")
            if fatal_error is None:
                submit_available()

    if fatal_error is not None:
        for page, window, fingerprint in work[next_index:]:
            record = base_page_record(page, prompt_hash, fingerprint, window, config)
            record.update({"status": "not_attempted", "error_type": "run_aborted_configuration_error",
                           "error": f"Not attempted after a run-wide provider configuration error: {fatal_error}"})
            records_by_group[page.group][page.page_number] = record
    return fatal_error


def chapter_output_path(config: Config, group: tuple[str, str, str], document_id: str) -> Path:
    return config.output / "chapters" / safe_path_part(group[2], "chapter") / f"{document_id}.txt"


def build_boundary_flags(pages: list[Page], records: dict[int, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    flags: list[dict[str, Any]] = []
    conditions: list[dict[str, Any]] = []
    for left, right in zip(pages, pages[1:]):
        if right.page_number != left.page_number + 1:
            conditions.append({"type": "page_gap", "after_page": left.page_number, "before_page": right.page_number})
            continue
        left_record = records.get(left.page_number, {})
        right_record = records.get(right.page_number, {})
        if left_record.get("status") != "success" or right_record.get("status") != "success":
            conditions.append({"type": "failed_boundary_page", "after_page": left.page_number, "before_page": right.page_number})
            continue
        left_text = left_record.get("text", "").rstrip()
        right_text = right_record.get("text", "").lstrip()
        if not left_text or not right_text:
            conditions.append({"type": "empty_boundary_page", "after_page": left.page_number, "before_page": right.page_number})
            continue
        if left_text.endswith(("-", "‐", "‑")):
            flags.append({"pages": [left.page_number, right.page_number], "reason": "possible_split_word_hyphen"})
        elif not re.search(r"[.!?…][\"'’”»)]*$", left_text):
            flags.append({"pages": [left.page_number, right.page_number], "reason": "previous_page_may_continue_sentence"})
    return flags, conditions


def chapter_status_record(
    config: Config,
    group: tuple[str, str, str],
    pages: list[Page],
    records: dict[int, dict[str, Any]],
    status: str,
    output_path: Path,
) -> dict[str, Any]:
    flags, conditions = build_boundary_flags(pages, records)
    failed_pages = [page.page_number for page in pages
                    if records.get(page.page_number, {}).get("status") in {"failed", "invalid_response"}]
    unattempted_pages = [page.page_number for page in pages
                         if records.get(page.page_number, {}).get("status") in {None, "not_attempted"}]
    empty_pages = [page.page_number for page in pages if records.get(page.page_number, {}).get("status") == "success"
                   and records[page.page_number].get("text") == ""]
    notes = sum(len(records.get(page.page_number, {}).get("review_notes", [])) for page in pages)
    return {
        "group": {"filepath_ori": group[0], "filename_stem": group[1], "chapter_of_interest": group[2]},
        "status": status,
        "complete": status == "complete",
        "scope_limited": config.limit is not None,
        "selected_pages": [page.page_number for page in pages],
        "successful_page_count": sum(records.get(page.page_number, {}).get("status") == "success" for page in pages),
        "failed_pages": failed_pages,
        "unattempted_pages": unattempted_pages,
        "failed_or_missing_pages": [page.page_number for page in pages
                                    if records.get(page.page_number, {}).get("status") != "success"],
        "empty_success_pages": empty_pages,
        "review_note_count": notes,
        "boundary_review_flags": flags,
        "conditions": conditions,
        "output_path": str(output_path),
        "window_size": config.window_size,
    }


def consolidate_chapter(
    config: Config,
    group: tuple[str, str, str],
    pages: list[Page],
    records: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    output_path = chapter_output_path(config, group, pages[0].document_id)
    complete = config.limit is None and all(records.get(page.page_number, {}).get("status") == "success" for page in pages)
    status = chapter_status_record(config, group, pages, records, "complete" if complete else "incomplete", output_path)
    if complete:
        texts = [records[page.page_number]["text"].rstrip() for page in pages if records[page.page_number]["text"].strip()]
        atomic_write_text(output_path, "\n\n".join(texts) + ("\n" if texts else ""))
    return status


def _validate_output_collisions(config: Config, pages: list[Page]) -> None:
    outputs = [page.result_path for page in pages]
    groups: dict[tuple[str, str, str], list[Page]] = {}
    for page in pages:
        groups.setdefault(page.group, []).append(page)
    outputs.extend(chapter_output_path(config, group, items[0].document_id) for group, items in groups.items())
    resolved = [path.resolve() for path in outputs]
    if len(set(resolved)) != len(resolved):
        raise FatalSetupError("Two selected targets map to the same output path")
    input_paths = {page.source_path.resolve() for page in pages}
    if input_paths.intersection(resolved):
        raise FatalSetupError("An output path would overwrite a selected source page")


def _group_pages(pages: list[Page]) -> dict[tuple[str, str, str], list[Page]]:
    grouped: dict[tuple[str, str, str], list[Page]] = {}
    for page in pages:
        grouped.setdefault(page.group, []).append(page)
    for group in grouped.values():
        group.sort(key=lambda item: item.page_number)
    return grouped


def _summary_counts(records: list[dict[str, Any]], chapter_statuses: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "selected_pages": len(records),
        "successful_pages": sum(record.get("status") == "success" for record in records),
        "empty_success_pages": sum(record.get("status") == "success" and record.get("empty_text") for record in records),
        "failed_pages": sum(record.get("status") == "failed" for record in records),
        "invalid_responses": sum(record.get("status") == "invalid_response" for record in records),
        "unattempted_pages": sum(record.get("status") == "not_attempted" for record in records),
        "resumed_pages": sum(bool(record.get("resumed")) for record in records),
        "retried_pages": sum(int(record.get("retry_count", 0) or 0) > 0 for record in records),
        "complete_chapters": sum(status["complete"] for status in chapter_statuses),
        "incomplete_chapters": sum(not status["complete"] for status in chapter_statuses),
        "review_notes": sum(len(record.get("review_notes", [])) for record in records),
        "boundary_flags": sum(len(status.get("boundary_review_flags", [])) for status in chapter_statuses),
    }


def _usage_totals(records: list[dict[str, Any]]) -> dict[str, int | None]:
    aliases = {
        "input_tokens": ("input_tokens", "prompt_token_count"),
        "output_tokens": ("output_tokens", "candidates_token_count"),
        "total_tokens": ("total_tokens", "total_token_count"),
    }
    totals = {key: 0 for key in aliases}
    observed = set()
    for record in records:
        usage = record.get("api_metadata", {}).get("usage")
        if not isinstance(usage, dict):
            continue
        for target, sources in aliases.items():
            value = next((usage.get(source) for source in sources if isinstance(usage.get(source), int)), None)
            if value is not None:
                totals[target] += value
                observed.add(target)
    return {key: total if key in observed else None for key, total in totals.items()}


def _dry_run_report(config: Config, pages: list[Page], grouped: dict[tuple[str, str, str], list[Page]], template: str,
                    prompt_hash: str, credentials: dict[str, Any]) -> dict[str, Any]:
    planned = []
    for page in pages:
        window = context_pages(page, grouped[page.group], config.window_size)
        rendered = build_prompt(template, window, page)
        planned.append({"identity": page.identity, "window_pages": [item.page_number for item in window],
                        "request_fingerprint": request_fingerprint(page, window, prompt_hash, config),
                        "source_characters": len(page.source_text), "rendered_prompt_characters": len(rendered),
                        "result_path": str(page.result_path)})
    return {"status": "dry_run", "pages": len(pages), "chapters": len(grouped), "window_size": config.window_size,
            "credentials_available": credentials["gemini_api_key_available"] if model_family(config.model) == "gemini"
            else credentials["openai_api_key_available"], "planned_targets": planned}


def main(argv: list[str] | None = None) -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
    started_at = utc_now_iso()
    try:
        config = make_config(parse_args(argv))
        validate_config(config)
        env_metadata = load_dotenv_file(config.env_file)
        if not config.dry_run:
            validate_credentials(config.model, env_metadata)
        template = load_prompt(config.prompt)
        prompt_hash = sha256_text(template)
        manifest_hash = sha256_file(config.manifest)
        pages = build_pages(load_manifest_rows(config.manifest), config)
        _validate_output_collisions(config, pages)
        grouped = _group_pages(pages)
        if config.dry_run:
            print(json.dumps(_dry_run_report(config, pages, grouped, template, prompt_hash, env_metadata), ensure_ascii=False, indent=2))
            return 0

        run_dir = config.output / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s %(message)s",
                            handlers=[logging.FileHandler(run_dir / "run.log", encoding="utf-8"), logging.StreamHandler()], force=True)
        status_path = config.output / "chapter_status.ndjson"
        initial_statuses = [chapter_status_record(config, group, items, {}, "incomplete",
                                                  chapter_output_path(config, group, items[0].document_id))
                            for group, items in grouped.items()]
        atomic_write_ndjson(status_path, initial_statuses)
        client = make_llm_client(config)
        call_provider = lambda prompt: call_with_retries(client, config, prompt)
        work: list[tuple[Page, list[Page], str]] = []
        records_by_group: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {group: {} for group in grouped}
        for page in pages:
            window = context_pages(page, grouped[page.group], config.window_size)
            fingerprint = request_fingerprint(page, window, prompt_hash, config)
            cached = None if config.reprocess or not config.resume else load_existing_success(page, fingerprint)
            if cached is not None:
                cached["resumed"] = True
                records_by_group[page.group][page.page_number] = cached
            else:
                work.append((page, window, fingerprint))
        invalid_dir = config.output / "invalid_responses"
        fatal_error = process_work_queue(work, records_by_group, template, prompt_hash, config, call_provider, invalid_dir)

        chapter_statuses = [consolidate_chapter(config, group, items, records_by_group[group]) for group, items in grouped.items()]
        atomic_write_ndjson(status_path, chapter_statuses)
        flat_records = [records_by_group[page.group][page.page_number] for page in pages]
        failures = [record for record in flat_records if record.get("status") == "failed"]
        invalid = [record for record in flat_records if record.get("status") == "invalid_response"]
        unattempted = [record for record in flat_records if record.get("status") == "not_attempted"]
        atomic_write_ndjson(config.output / "failures.ndjson", failures)
        atomic_write_ndjson(config.output / "invalid_responses.ndjson", invalid)
        atomic_write_ndjson(config.output / "unattempted_pages.ndjson", unattempted)
        counts = _summary_counts(flat_records, chapter_statuses)
        ended_at = utc_now_iso()
        summary = {
            "run_id": run_id,
            "programme": PROGRAMME,
            "status": "aborted_configuration_error" if fatal_error else
            "success" if not failures and not invalid and not counts["incomplete_chapters"] else "completed_with_errors",
            "started_at": started_at,
            "ended_at": ended_at,
            "model": config.model,
            "provider": model_family(config.model),
            "manifest_sha256": manifest_hash,
            "prompt_sha256": prompt_hash,
            "settings": {"window_size": config.window_size, "workers": config.workers, "temperature": config.temperature,
                         "max_output_tokens": config.max_output_tokens, "max_retries": config.max_retries},
            "fatal_error": sanitize_error(RuntimeError(fatal_error)) if fatal_error else None,
            "credentials": {"provider_key_available": True, "secrets_logged": False},
            "counts": counts,
            "usage_totals": _usage_totals(flat_records),
        }
        atomic_write_json(run_dir / "run_manifest.json", {
            "run_id": run_id, "programme": PROGRAMME, "started_at": started_at, "ended_at": ended_at,
            "manifest": str(config.manifest), "output": str(config.output), "prompt": str(config.prompt),
            "manifest_sha256": manifest_hash, "prompt_sha256": prompt_hash, "settings": summary["settings"],
            "environment": {"provider": model_family(config.model), "key_available": True, "secrets_logged": False},
            "counts": counts, "fatal_error": summary["fatal_error"],
        })
        atomic_write_json(run_dir / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["status"] == "success" else 1
    except (FatalSetupError, OSError, ValueError) as exc:
        logging.error("%s", sanitize_error(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())