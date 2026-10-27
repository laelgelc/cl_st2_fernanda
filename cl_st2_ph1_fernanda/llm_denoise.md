# Development Specification: `llm_denoise.py`

## 1. Programme purpose

`llm_denoise.py` denoises Brazilian official educational guideline excerpts with an LLM provider API for a corpus-linguistics research project studying Brazilian curricular guideline language.

The programme takes an immutable NDJSON guideline manifest as input. Each manifest row identifies one guideline excerpt text file and includes the path to the corresponding source `.txt` file. For each guideline excerpt, the programme:

1. reads the guideline metadata from the manifest;
2. reads the guideline excerpt text from the manifest row’s `filepath`;
3. renders an LLM denoising prompt by inserting the guideline excerpt text;
4. submits the prompt to the configured LLM provider API;
5. treats the model response as Markdown/plain text, not JSON;
6. saves one denoised Markdown output file per guideline excerpt;
7. saves one per-excerpt JSON metadata/audit artefact;
8. writes run-level manifests, logs, failures, and summaries;
9. produces a consolidated NDJSON dataset linking original manifest rows to denoised Markdown outputs.

The programme supports OpenAI and Gemini model families. Model routing is determined from the configured model name:

- model names beginning with `gemini-` use the Gemini API;
- other supported model names use the OpenAI API.

The programme is intended for large-scale denoising of Brazilian educational guideline excerpts. It must therefore support:

- resumable execution;
- robust per-excerpt failure handling;
- concurrent workers;
- immutable input data;
- reproducible run metadata;
- prompt version tracking;
- API usage tracking where available;
- safe handling of API credentials;
- corpus-ready Markdown output files;
- provider-specific metadata where available.

---

## 2. Research context

The project studies Brazilian official educational curricular guidelines. Source texts have been extracted from PDFs and organised into per-state text files. Because PDF extraction often introduces artefacts such as line-wrapping, isolated page numbers, form-feed characters, broken hyphenation, and excessive spacing, the corpus requires a denoising pass before downstream corpus-linguistic processing.

The denoising task is conservative. The programme must not perform interpretation, summarisation, translation, discourse analysis, modernisation, stylistic improvement, or substantive rewriting. The LLM is used only to remove obvious PDF/OCR extraction artefacts while preserving original content and structure.

The expected model output is the denoised guideline excerpt in Markdown format.

---

## 3. Core design principles

### 3.1 Immutable input

The input manifest must not be modified in place.

The programme must treat:

```text
corpus/brazilian_educational_guidelines.ndjson
```

as an immutable source manifest.

All denoising outcomes must be written to the output directory supplied by:

```text
--output
```

For the Phase 2 pipeline, the expected output directory is:

```text
corpus/02_extracted
```

---

### 3.2 Manifest-driven processing

The programme must be driven by an NDJSON manifest, not by recursively scanning a source directory.

Each manifest row represents one intended guideline excerpt to denoise.

Expected manifest fields include:

```json
{
  "filename": "ac_ef_1.txt",
  "state": "ac",
  "filepath": "corpus/00_source_per_state/ac/ac_ef_1.txt"
}
```

At minimum, the programme requires:

| Field      | Required | Purpose                                      |
|------------|---------:|----------------------------------------------|
| `filename` | Yes      | Stable source filename for the excerpt       |
| `filepath` | Yes      | Path to the source guideline text file       |
| `state`    | Yes      | Brazilian state code for output organisation |

If optional fields are present, they must be preserved in metadata and consolidated outputs.

---

### 3.3 Per-excerpt Markdown artefacts

Each successfully processed guideline excerpt must produce one corpus-ready Markdown file.

Recommended output path pattern:

```text
<output>/<state>/<filename_stem>.md
```

Example:

```text
corpus/02_extracted/ac/ac_ef_1.md
```

If `state` is missing or empty, the programme may use:

```text
unknown_state
```

The output extension should be `.md` because the target format is Markdown.

---

### 3.4 Per-excerpt metadata artefacts

In addition to the denoised Markdown file, each processed excerpt should produce one JSON metadata/audit artefact.

Recommended output path pattern:

```text
<output>/_llm_denoise_metadata/<state>/<filename_stem>.json
```

Example:

```text
corpus/02_extracted/_llm_denoise_metadata/ac/ac_ef_1.json
```

This supports:

- robust resume;
- parallel processing;
- per-excerpt auditability;
- recovery from partial failures;
- invalid/empty response inspection;
- reprocessing selected excerpts only.

---

### 3.5 Consolidated denoised dataset

The programme must produce a consolidated NDJSON file.

Recommended path:

```text
<output>/llm_denoised_guidelines.ndjson
```

This file should contain one successfully denoised excerpt per line, preserving the original manifest row and adding denoising metadata.

The consolidated file must be generated deterministically in the same order as the input manifest after any explicit filtering and limiting.

---

### 3.6 File-based resume

Resume must be based on successful per-excerpt outputs, not on a “last processed excerpt” pointer.

For each manifest row:

```text
if --resume is enabled
and expected Markdown file exists
and expected metadata JSON exists
and metadata status == "success":
    skip excerpt
else:
    process excerpt
```

This is necessary because concurrent workers may complete excerpts out of manifest order.

The programme should verify both the Markdown file and the metadata JSON. The Markdown file alone is not sufficient for auditability, and the metadata JSON alone is not sufficient for corpus completeness.

---

### 3.7 Reproducibility

The programme must record enough information to reproduce or audit a run:

- input manifest path;
- input manifest hash;
- source text file path;
- source text hash;
- prompt file path;
- prompt template hash;
- rendered prompt hash;
- selected model;
- selected model family;
- model response metadata where available;
- token usage where available;
- output Markdown path;
- denoised Markdown hash;
- timestamp;
- duration;
- error information;
- run ID;
- worker configuration;
- retry configuration;
- dry-run/resume/reprocess status;
- filename filtering status, if applicable.

---

## 4. Command-line interface

### 4.1 Recommended commands

#### Dry run

```shell
python llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --limit 10 \
    --dry-run
```

#### Test run, first time

```shell
python llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --limit 10
```

#### Process a single manifest filename

```shell
python llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --only-filename ac_ef_1.txt \
    --resume
```

#### Gemini test run

```shell
python llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gemini-2.5-flash \
    --limit 10 \
    --resume
```

#### 10 workers test run

```shell
python llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --limit 200 \
    --workers 10 \
    --resume \
    --max-output-tokens 1000
```

#### Full run

```shell
python llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --workers 10 \
    --resume \
    --max-output-tokens 1000 \
    --max-retries 5
```

#### Production mode on an EC2 instance

```shell
bash run_python_ec2.sh \
    llm_denoise.py \
    --manifest corpus/brazilian_educational_guidelines.ndjson \
    --output corpus/02_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --workers 10 \
    --resume \
    --max-output-tokens 1000 \
    --max-retries 5
```

---

### 4.2 Required arguments

| Argument          | Required | Description                                                 |
|-------------------|---------:|-------------------------------------------------------------|
| `--manifest PATH` |      Yes | Input NDJSON guideline manifest                             |
| `--output PATH`   |      Yes | Output directory for denoised Markdown corpus               |
| `--prompt PATH`   |      Yes | Markdown denoising prompt template                          |
| `--model MODEL`   |      Yes | LLM model ID used for denoising; determines provider family |

---

### 4.3 Optional arguments

| Argument                        |                              Default | Description                                                                           |
|---------------------------------|-------------------------------------:|---------------------------------------------------------------------------------------|
| `--limit N`                     |                               `None` | Process only the first `N` planned excerpts after any filename filtering              |
| `--only-filename FILENAME`      |                               `None` | Process only manifest row(s) whose filename field exactly matches `FILENAME`          |
| `--resume`                      |                              `False` | Skip existing successful Markdown + metadata outputs                                  |
| `--reprocess`                   |                              `False` | Reprocess even if successful outputs already exist                                    |
| `--dry-run`                     |                              `False` | Validate inputs and build planned prompts without API calls                           |
| `--workers N`                   |                                  `1` | Number of concurrent worker threads                                                   |
| `--max-retries N`               |                                  `2` | Number of retries per API call after the initial attempt                              |
| `--retry-backoff-seconds FLOAT` |                                `5.0` | Initial retry backoff in seconds                                                      |
| `--temperature FLOAT`           |                                `0.0` | Temperature if supported by the selected provider/model                               |
| `--max-output-tokens N`         |                               `1000` | Maximum output tokens for OpenAI responses; recorded but not currently sent to Gemini |
| `--env-file PATH`               |                           `env/.env` | Optional environment file containing API credentials                                  |
| `--log-file PATH`               |           `<output>/llm_denoise.log` | Optional explicit log file                                                            |
| `--manifest-file PATH`          | `<output>/llm_denoise_manifest.json` | Optional explicit latest run manifest file                                            |
| `--filename-field FIELD`        |                           `filename` | Manifest field containing source filename                                             |
| `--filepath-field FIELD`        |                           `filepath` | Manifest field containing source text path                                            |
| `--state-field FIELD`           |                              `state` | Manifest field containing Brazilian state code                                        |
| `--output-extension EXT`        |                                `.md` | Extension for denoised corpus outputs                                                 |

---

### 4.4 Argument validation

The programme must fail before any API call if:

- `--manifest` is missing;
- `--manifest` does not exist;
- `--manifest` is not a file;
- `--prompt` is missing;
- `--prompt` does not exist;
- `--prompt` is empty;
- `--output` cannot be created;
- `--model` is empty;
- `--limit <= 0`, if supplied;
- `--only-filename` is supplied but empty;
- `--workers <= 0`;
- `--max-retries < 0`;
- `--retry-backoff-seconds < 0`;
- `--temperature < 0`;
- `--max-output-tokens <= 0`;
- `--output-extension` does not start with `.`;
- the required provider SDK is unavailable when not in dry-run mode;
- the required provider API key is unavailable when not in dry-run mode.

Provider-specific setup requirements:

| Model family | Model-name rule                | Required SDK   | Required API key |
|--------------|--------------------------------|----------------|------------------|
| OpenAI       | default for non-`gemini-*` IDs | `openai`       | `OPENAI_API_KEY` |
| Gemini       | starts with `gemini-`          | `google-genai` | `GEMINI_API_KEY` |

The programme should not fail solely because `--env-file` does not exist, provided the required API key for the selected model family is already available in the process environment.

---

## 5. Input manifest

### 5.1 Format

The manifest must be NDJSON: one JSON object per line.

Example:

```json
{"filename":"ac_ef_1.txt","state":"ac","filepath":"corpus/00_source_per_state/ac/ac_ef_1.txt"}
```

Each non-empty line must parse as a JSON object.

---

### 5.2 Required manifest fields

Each row must contain:

```text
filename
state
filepath
```

or the corresponding fields specified by:

```text
--filename-field
--state-field
--filepath-field
```

If a row lacks required fields, that row should be recorded as a per-row failure, but the programme should continue processing other rows.

---

### 5.3 Manifest row preservation

The programme must preserve the original manifest row in per-excerpt metadata JSON and consolidated NDJSON output.

This allows later analysis by original metadata fields.

---

### 5.4 Manifest loading strategy

The programme may either:

1. stream manifest rows line by line; or
2. load all rows into memory.

Loading the manifest into memory is acceptable if implementation is simpler. However, source text files themselves must not be loaded all at once.

Recommended approach:

- read all manifest rows once for validation/planning;
- preserve original row order;
- apply `--only-filename` filtering if supplied;
- apply `--limit` if supplied;
- process source text files individually.

---

### 5.5 Filename filtering

If `--only-filename FILENAME` is supplied, the programme should process only rows whose configured filename field exactly matches `FILENAME`.

The comparison should use the field selected by:

```text
--filename-field
```

Default:

```text
filename
```

If no row matches `--only-filename`, the programme should fail before API calls.

If more than one row matches, the programme may process all matching rows and should log a warning.

`--limit`, if supplied, is applied after filename filtering.

---

## 6. Prompt template

### 6.1 Prompt file

The programme must load the denoising prompt from the path given by:

```text
--prompt
```

Example:

```text
denoising_prompts/denoising_v1.md
```

The prompt must be external to the programme. Prompt contents must not be hardcoded.

---

### 6.2 Guideline excerpt placeholder

The prompt template must contain:

```text
<<<GUIDELINE_EXCERPT_TEXT>>>
```

For each source excerpt, the programme must replace this placeholder with the source text.

If the prompt does not contain this placeholder, the programme must fail before API calls.

---

### 6.3 Recommended prompt ending

The prompt should contain a section similar to:

```text
Guideline excerpt:

<guideline_excerpt>
<<<GUIDELINE_EXCERPT_TEXT>>>
</guideline_excerpt>
```

The programme should not add Markdown code fences around the source text unless the prompt itself does so.

---

### 6.4 Prompt hashing

The programme must compute and record:

```text
prompt_template_sha256
rendered_prompt_sha256
```

The rendered prompt hash should be computed after inserting the guideline excerpt text.

---

## 7. Source text handling

### 7.1 File path resolution

The source `filepath` from the manifest may be:

- relative; or
- absolute.

Relative paths should be resolved against the directory containing `llm_denoise.py`.

Recommended behaviour for this project:

```text
Relative CLI paths and manifest filepaths are resolved against the directory containing llm_denoise.py.
```

This matches project-situated execution from:

```text
cl_st1_ph2_anna/
```

---

### 7.2 Source file reading

Source files must be read as UTF-8 text using:

```python
encoding="utf-8"
errors="replace"
```

This prevents occasional encoding issues from crashing the full run.

---

### 7.3 Empty source files

If a source file is empty or contains only whitespace:

- mark that excerpt as failed;
- write a per-excerpt metadata JSON failure artefact where possible;
- continue processing other excerpts.

---

### 7.4 Missing source files

If a source file does not exist:

- mark that excerpt as failed;
- write a per-excerpt metadata JSON failure artefact;
- include the original manifest row;
- continue processing other excerpts.

---

### 7.5 Source text hashing

For each successfully read source file, record:

```text
source_text_sha256
```

---

## 8. LLM request construction

For each excerpt, the programme should construct the request as:

```text
[prompt template with <<<GUIDELINE_EXCERPT_TEXT>>> replaced by source text]
```

The programme should not add additional denoising rules in code. The prompt template is the source of denoising instructions.

The LLM call must be stateless. It must not reuse prior conversational context between excerpts.

Provider-specific request construction may differ, but the semantic input must remain the rendered prompt.

---

## 9. LLM provider API handling

### 9.1 Provider selection and client creation

The programme should select the provider from the configured model name.

Model-family routing:

```text
if model starts with "gemini-":
    use Gemini
else:
    use OpenAI
```

For OpenAI models, the programme should use the OpenAI Python SDK.

For Gemini models, the programme should use the Google GenAI Python SDK.

The programme must fail before API calls if the required SDK for the selected model family is unavailable.

---

### 9.2 API key loading

The programme should load environment variables from:

```text
--env-file
```

if it exists.

Recommended behaviour:

1. If `--env-file` exists, load simple `KEY=VALUE` lines.
2. Do not overwrite existing environment variables.
3. Determine the selected model family.
4. For OpenAI models, check for `OPENAI_API_KEY`.
5. For Gemini models, check for `GEMINI_API_KEY`.
6. If the required key is not found and not in dry-run mode, fail before API calls.
7. Never log or write API key values.

---

### 9.3 Safe environment metadata

The programme should record only safe metadata:

```json
{
  "environment": {
    "env_file": "env/.env",
    "env_file_found": true,
    "model_family": "openai",
    "openai_api_key_available": true,
    "openai_api_key_source": "env_file_or_process_environment",
    "gemini_api_key_available": false,
    "gemini_api_key_source": null,
    "api_keys_logged": false
  }
}
```

API key values must never appear in:

- logs;
- manifests;
- per-excerpt metadata JSON;
- errors;
- console output.

---

### 9.4 API response text extraction

The programme must robustly extract output text from the provider response.

For OpenAI responses, it should support at least:

- `response.output_text`;
- text content nested under response output items, where applicable.

For Gemini responses, it should support at least:

- `response.text`;
- text content nested inside candidate/content/part structures, where applicable.

If no usable text is found:

- mark the excerpt as failed;
- record error type `empty_llm_response`;
- continue processing.

---

### 9.5 Retry logic

Each API call should be retried on recoverable errors.

Recommended parameters:

```text
--max-retries 2
--retry-backoff-seconds 5.0
```

Backoff strategy:

```text
sleep = retry_backoff_seconds * (2 ** attempt_number)
```

The programme should log retry attempts without logging full prompt content or full source text.

Retry logs should identify the provider family, for example OpenAI or Gemini.

---

### 9.6 Temperature support

Some OpenAI models may not support `temperature`.

For OpenAI calls, the programme should:

1. attempt to send `temperature` if configured;
2. if the API rejects `temperature` as unsupported:
   - retry without `temperature`;
   - remember that this model does not support temperature for the rest of the run;
   - avoid sending `temperature` again for that model;
   - record whether temperature was sent.

This temperature-support cache must be thread-safe.

For Gemini calls, the initial implementation may record the configured temperature but does not need to send provider-specific generation configuration unless Gemini SDK compatibility is explicitly verified.

---

### 9.7 Maximum output tokens

For OpenAI calls, the programme should send:

```text
max_output_tokens
```

using the configured `--max-output-tokens` value.

For Gemini calls, the programme should preserve the configured `--max-output-tokens` value in run and per-excerpt metadata, but the initial Gemini integration should not require sending it to the Gemini API. This avoids depending on Gemini generation-configuration syntax that may vary by SDK version.

Per-excerpt metadata should record whether the value was sent to the API:

```json
{
  "max_output_tokens": 1000,
  "max_output_tokens_sent_to_api": true
}
```

For Gemini responses in the current implementation, `max_output_tokens_sent_to_api` should be `false`.

---

### 9.8 Token usage

If token usage metadata is available from the provider response, record it in:

- per-excerpt metadata JSON;
- run manifest aggregate totals, if feasible.

OpenAI-style usage may be recorded as:

```json
"usage": {
  "input_tokens": 1500,
  "output_tokens": 900,
  "total_tokens": 2400
}
```

Gemini usage metadata may be recorded separately as:

```json
"usage_metadata": {
  "prompt_token_count": 1500,
  "candidates_token_count": 900,
  "total_token_count": 2400
}
```

When computing aggregate totals, the programme may map Gemini usage metadata as follows:

| Gemini field              | Aggregate field |
|---------------------------|-----------------|
| `prompt_token_count`      | `input_tokens`  |
| `candidates_token_count`  | `output_tokens` |
| `total_token_count`       | `total_tokens`  |

---

## 10. LLM response validation

### 10.1 Expected response

The LLM is expected to return only the denoised guideline excerpt formatted in Markdown.

It is not expected to return JSON.

The output should not contain explanations, comments, labels, summaries, or quotation marks unless those were part of the original content and preserved by the denoising process.

---

### 10.2 Response validation rules

The programme should validate:

- response text is present;
- response text is a string;
- response text is not empty after stripping whitespace;
- response text does not appear to be a refusal;
- response text does not appear to be an explanatory wrapper instead of the denoised excerpt;
- response text does not consist only of Markdown code fences;
- response text does not contain the prompt placeholder;
- response text can be written as UTF-8.

The programme should not attempt to validate whether every denoising decision is correct. That is a research/audit matter, not a deterministic schema check.

---

### 10.3 Invalid or suspicious responses

If the model returns no usable text or a clearly invalid response:

- save a per-excerpt metadata JSON artefact with status `invalid_response`;
- include raw response text where available;
- include validation error;
- write to `llm_denoise_invalid_responses.ndjson`;
- continue processing.

Examples of invalid/suspicious responses:

- empty response;
- response only says it cannot comply;
- response contains only metadata or commentary;
- response repeats the prompt instructions;
- response contains the placeholder `<<<GUIDELINE_EXCERPT_TEXT>>>`.

---

## 11. Output directory structure

Given:

```text
--output corpus/02_extracted
```

the programme should create:

```text
corpus/02_extracted/
  ac/
    ac_ef_1.md
    ac_ef_2.md
  al/
    al_ef_1.md
  ...
  _llm_denoise_metadata/
    ac/
      ac_ef_1.json
      ac_ef_2.json
    al/
      al_ef_1.json
  llm_denoise_manifest.json
  llm_denoise_manifest_<RUN_ID>.json
  llm_denoise.log
  llm_denoised_guidelines.ndjson
  llm_denoise_failures.ndjson
  llm_denoise_invalid_responses.ndjson
  llm_denoise_summary.json
```

The state directories contain corpus-ready Markdown files.

The `_llm_denoise_metadata/` directory contains audit metadata and should not be treated as corpus text.

---

## 12. Per-excerpt metadata JSON output

### 12.1 Successful excerpt structure

Example:

```json
{
  "filename": "ac_ef_1.txt",
  "excerpt_id": "ac_ef_1",
  "state": "ac",
  "status": "success",
  "input": {
    "manifest_file": "corpus/brazilian_educational_guidelines.ndjson",
    "source_file": "corpus/00_source_per_state/ac/ac_ef_1.txt",
    "prompt_file": "denoising_prompts/denoising_v1.md"
  },
  "output": {
    "markdown_file": "corpus/02_extracted/ac/ac_ef_1.md",
    "metadata_json": "corpus/02_extracted/_llm_denoise_metadata/ac/ac_ef_1.json"
  },
  "manifest_row": {
    "filename": "ac_ef_1.txt",
    "state": "ac",
    "filepath": "corpus/00_source_per_state/ac/ac_ef_1.txt"
  },
  "model": {
    "configured_model": "gpt-6-luna",
    "model_family": "openai",
    "response_model": "gpt-6-luna"
  },
  "hashes": {
    "manifest_file_sha256": "...",
    "source_text_sha256": "...",
    "prompt_template_sha256": "...",
    "rendered_prompt_sha256": "...",
    "raw_response_text_sha256": "...",
    "denoised_markdown_sha256": "..."
  },
  "api_metadata": {
    "id": "...",
    "model": "gpt-6-luna",
    "usage": {},
    "usage_metadata": {}
  },
  "raw_response_text": "# ...",
  "temperature": 0.0,
  "temperature_sent_to_api": true,
  "max_output_tokens": 1000,
  "max_output_tokens_sent_to_api": true,
  "created_at": "2026-09-22T00:00:00Z",
  "duration_seconds": 1.24,
  "error": null
}
```

For Gemini records, the model block should use `"model_family": "gemini"`, and `max_output_tokens_sent_to_api` should be `false` unless provider-specific generation configuration is later implemented.

---

### 12.2 Failed excerpt structure

Example:

```json
{
  "filename": "ac_ef_1.txt",
  "excerpt_id": "ac_ef_1",
  "state": "ac",
  "status": "failed",
  "input": {
    "manifest_file": "corpus/brazilian_educational_guidelines.ndjson",
    "source_file": "corpus/00_source_per_state/ac/ac_ef_1.txt",
    "prompt_file": "denoising_prompts/denoising_v1.md"
  },
  "output": {
    "markdown_file": "corpus/02_extracted/ac/ac_ef_1.md",
    "metadata_json": "corpus/02_extracted/_llm_denoise_metadata/ac/ac_ef_1.json"
  },
  "manifest_row": {
    "filename": "ac_ef_1.txt",
    "state": "ac",
    "filepath": "corpus/00_source_per_state/ac/ac_ef_1.txt"
  },
  "error_type": "missing_source_file",
  "error": "Source file not found",
  "created_at": "2026-09-22T00:00:00Z",
  "duration_seconds": 0.01
}
```

---

### 12.3 Invalid response structure

Example:

```json
{
  "filename": "ac_ef_1.txt",
  "excerpt_id": "ac_ef_1",
  "state": "ac",
  "status": "invalid_response",
  "input": {
    "manifest_file": "corpus/brazilian_educational_guidelines.ndjson",
    "source_file": "corpus/00_source_per_state/ac/ac_ef_1.txt",
    "prompt_file": "denoising_prompts/denoising_v1.md"
  },
  "output": {
    "markdown_file": "corpus/02_extracted/ac/ac_ef_1.md",
    "metadata_json": "corpus/02_extracted/_llm_denoise_metadata/ac/ac_ef_1.json"
  },
  "manifest_row": {
    "filename": "ac_ef_1.txt",
    "state": "ac",
    "filepath": "corpus/00_source_per_state/ac/ac_ef_1.txt"
  },
  "raw_response_text": "I cannot denoise this text because...",
  "validation_error": "Response appears to be a refusal or explanatory wrapper",
  "api_metadata": {
    "id": "...",
    "usage": {}
  },
  "created_at": "2026-09-22T00:00:00Z",
  "duration_seconds": 1.02
}
```

---

## 13. Consolidated denoised NDJSON

The programme must write:

```text
<output>/llm_denoised_guidelines.ndjson
```

Each line should contain:

- all fields from the original manifest row;
- `llm_denoise`;
- `llm_denoise_metadata`.

Example:

```json
{
  "filename": "ac_ef_1.txt",
  "state": "ac",
  "filepath": "corpus/00_source_per_state/ac/ac_ef_1.txt",
  "llm_denoise": {
    "markdown_file": "corpus/02_extracted/ac/ac_ef_1.md"
  },
  "llm_denoise_metadata": {
    "status": "success",
    "model": "gpt-6-luna",
    "model_family": "openai",
    "prompt_file": "denoising_prompts/denoising_v1.md",
    "prompt_template_sha256": "...",
    "source_text_sha256": "...",
    "denoised_markdown_sha256": "...",
    "denoised_at": "2026-09-22T00:00:00Z",
    "metadata_json": "corpus/02_extracted/_llm_denoise_metadata/ac/ac_ef_1.json",
    "usage": {},
    "usage_metadata": {}
  }
}
```

Only successful denoising records should be included unless a future option explicitly includes failed records.

---

## 14. Failure and invalid-response NDJSON files

### 14.1 Failures

The programme must write:

```text
<output>/llm_denoise_failures.ndjson
```

Each line should correspond to one excerpt-level failure, such as:

- invalid manifest row;
- missing source file;
- unreadable source file;
- empty source file;
- API error after retries;
- no usable LLM response text;
- Markdown output write failure;
- metadata JSON write failure.

---

### 14.2 Invalid responses

The programme must write:

```text
<output>/llm_denoise_invalid_responses.ndjson
```

Each line should correspond to one API response that was received but was considered invalid or suspicious.

---

## 15. Run manifest

### 15.1 Manifest files

The programme must write two run manifests:

```text
<output>/llm_denoise_manifest.json
<output>/llm_denoise_manifest_<RUN_ID>.json
```

The first is the latest run manifest. The second is timestamped/ID-specific and should not be overwritten by later runs.

---

### 15.2 Run manifest content

The run manifest should include:

```json
{
  "run_id": "...",
  "programme": "llm_denoise.py",
  "start_time": "2026-09-22T00:00:00Z",
  "end_time": "2026-09-22T01:00:00Z",
  "status": "success",
  "paths": {
    "manifest": "corpus/brazilian_educational_guidelines.ndjson",
    "output": "corpus/02_extracted",
    "prompt": "denoising_prompts/denoising_v1.md",
    "log_file": "corpus/02_extracted/llm_denoise.log",
    "metadata_dir": "corpus/02_extracted/_llm_denoise_metadata",
    "denoised_ndjson": "corpus/02_extracted/llm_denoised_guidelines.ndjson",
    "failures_ndjson": "corpus/02_extracted/llm_denoise_failures.ndjson",
    "invalid_responses_ndjson": "corpus/02_extracted/llm_denoise_invalid_responses.ndjson"
  },
  "environment": {
    "env_file": "env/.env",
    "env_file_found": true,
    "model_family": "openai",
    "openai_api_key_available": true,
    "openai_api_key_source": "env_file_or_process_environment",
    "gemini_api_key_available": false,
    "gemini_api_key_source": null,
    "api_keys_logged": false
  },
  "model_configuration": {
    "model": "gpt-6-luna",
    "model_family": "openai",
    "temperature": 0.0,
    "max_output_tokens": 1000
  },
  "processing": {
    "workers": 20,
    "limit": null,
    "only_filename": null,
    "resume": true,
    "reprocess": false,
    "dry_run": false,
    "max_retries": 5,
    "retry_backoff_seconds": 5.0,
    "output_extension": ".md"
  },
  "hashes": {
    "manifest_file_sha256": "...",
    "prompt_template_sha256": "..."
  },
  "counts": {
    "manifest_rows_total": 3000,
    "manifest_rows_matched": 3000,
    "excerpts_planned": 3000,
    "excerpts_succeeded": 2990,
    "excerpts_failed": 5,
    "excerpts_invalid_response": 5,
    "excerpts_skipped_existing": 0,
    "excerpts_dry_run": 0
  },
  "usage_totals": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "excerpts": [
    {
      "filename": "ac_ef_1.txt",
      "excerpt_id": "ac_ef_1",
      "state": "ac",
      "status": "success",
      "markdown_file": "corpus/02_extracted/ac/ac_ef_1.md",
      "metadata_json": "corpus/02_extracted/_llm_denoise_metadata/ac/ac_ef_1.json"
    }
  ]
}
```

For very large runs, the `excerpts` list may be large but acceptable. If it becomes unwieldy, a future version may write a separate run index NDJSON.

---

## 16. Summary file

The programme should write:

```text
<output>/llm_denoise_summary.json
```

This file should contain a compact machine-readable summary:

```json
{
  "run_id": "...",
  "programme": "llm_denoise.py",
  "model": "gpt-6-luna",
  "model_family": "openai",
  "prompt": "denoising_prompts/denoising_v1.md",
  "manifest": "corpus/brazilian_educational_guidelines.ndjson",
  "output": "corpus/02_extracted",
  "denoised_ndjson": "corpus/02_extracted/llm_denoised_guidelines.ndjson",
  "counts": {
    "manifest_rows_total": 3000,
    "manifest_rows_matched": 3000,
    "excerpts_planned": 3000,
    "excerpts_succeeded": 2990,
    "excerpts_failed": 5,
    "excerpts_invalid_response": 5,
    "excerpts_skipped_existing": 0,
    "excerpts_dry_run": 0
  },
  "usage_totals": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  }
}
```

---

## 17. Logging

The programme must write a log file:

```text
<output>/llm_denoise.log
```

It should also log to console.

---

### 17.1 Required log information

The log should include:

- programme start;
- run ID;
- resolved manifest path;
- resolved output path;
- resolved prompt path;
- selected model;
- selected model family;
- workers;
- dry-run status;
- resume status;
- reprocess status;
- `--only-filename`, if supplied;
- limit, if supplied;
- output extension;
- prompt hash;
- manifest hash;
- number of manifest rows;
- number of matched manifest rows after filename filtering;
- number of planned excerpts;
- per-excerpt start and finish at reasonable verbosity;
- skipped excerpts;
- failures;
- invalid responses;
- provider-specific retry attempts;
- temperature unsupported warnings, where applicable;
- final success/failure counts;
- programme completion.

---

### 17.2 Sensitive data exclusion

The log must not include:

- `OPENAI_API_KEY`;
- `GEMINI_API_KEY`;
- authentication headers;
- full request payloads;
- full source text;
- full prompt text with source content.

It may log:

- hashes;
- filenames;
- state codes;
- file paths;
- status;
- durations;
- error messages;
- safe API metadata.

---

## 18. Dry-run mode

When `--dry-run` is supplied, the programme must:

- validate CLI arguments;
- load environment metadata, but not require provider API keys;
- load and validate the prompt;
- confirm the guideline excerpt placeholder exists;
- load and validate the manifest;
- apply `--only-filename` filtering if supplied;
- resolve planned source file paths;
- compute expected Markdown and metadata output paths;
- check whether source files exist;
- read source files if feasible;
- compute hashes and approximate prompt sizes;
- create output directories;
- write dry-run manifest/log/summary;
- make no API calls;
- write no successful denoised Markdown corpus files.

Dry-run mode is intended to catch file, path, manifest, prompt, and output-layout issues before spending API budget.

Dry-run may write run-level metadata files but should not write denoised `.md` outputs.

---

## 19. Resume and reprocess behaviour

### 19.1 `--resume`

If `--resume` is supplied:

- skip any excerpt whose expected Markdown file exists;
- and whose expected metadata JSON exists;
- and whose metadata JSON has `status == "success"`;
- count it as `excerpts_skipped_existing`;
- include skipped records in the run manifest.

---

### 19.2 `--reprocess`

If `--reprocess` is supplied:

- ignore existing successful Markdown and metadata outputs;
- call the API again;
- overwrite or replace existing Markdown and metadata outputs.

Recommended behaviour:

- if both `--resume` and `--reprocess` are supplied, `--reprocess` takes precedence;
- log a warning that existing successful outputs will be reprocessed.

---

### 19.3 Partial failures

Existing failed or invalid-response metadata files should not be skipped by `--resume`.

They should be retried unless a future option such as `--skip-failed` is introduced.

---

## 20. Concurrent execution

### 20.1 Workers

The programme should support concurrent processing with:

```text
--workers N
```

Use a thread pool because the workload is I/O-bound and API-bound.

---

### 20.2 Per-excerpt file safety

Each worker writes only its own:

- Markdown output file;
- metadata JSON file.

Workers should not concurrently append to the consolidated NDJSON.

Recommended approach:

1. workers produce per-excerpt Markdown and metadata files;
2. main thread collects results;
3. main thread writes consolidated NDJSON at the end in manifest order.

---

### 20.3 Shared state safety

Any shared state must be thread-safe, including:

- temperature unsupported model cache;
- counters, if updated during processing;
- logging is acceptable through Python logging.

---

## 21. Processing order

High-level processing order:

```text
1. Parse CLI arguments.
2. Resolve paths.
3. Create output directories.
4. Configure logging.
5. Create run ID.
6. Load .env file if present.
7. Determine model family.
8. Check provider-specific API key unless dry-run.
9. Validate options.
10. Load prompt template.
11. Confirm <<<GUIDELINE_EXCERPT_TEXT>>> placeholder exists.
12. Compute prompt hash.
13. Load manifest rows.
14. Apply --only-filename filtering if supplied.
15. Validate manifest rows.
16. Compute manifest hash.
17. Apply --limit if supplied.
18. Determine expected Markdown and metadata output paths for each row.
19. If --resume, skip existing successful outputs.
20. If --dry-run, write dry-run manifest and exit.
21. Initialise the selected provider client.
22. Process excerpts with configured workers:
    - read source text;
    - render prompt;
    - call provider API with retries;
    - extract response text;
    - validate response as usable Markdown/plain text;
    - write Markdown output;
    - write metadata JSON;
    - return status.
23. Write failures NDJSON.
24. Write invalid responses NDJSON.
25. Write consolidated denoised NDJSON in manifest order.
26. Write summary JSON.
27. Write run manifests.
28. Log final counts.
29. Exit.
```

---

## 22. Exit codes

Recommended exit behaviour:

| Condition                                                        | Exit code |
|------------------------------------------------------------------|----------:|
| All planned excerpts succeeded or were skipped successfully      |         0 |
| Some excerpts failed or had invalid responses, but run completed |         1 |
| Fatal setup error before processing                              |         1 |
| Keyboard interruption                                            |       130 |

A run with excerpt-level failures should still write manifests and logs where possible.

---

## 23. Error handling

### 23.1 Fatal errors

The programme should stop before processing if:

- required CLI arguments are invalid;
- output directory cannot be created;
- prompt file is missing or invalid;
- prompt placeholder is missing;
- manifest file is missing or invalid globally;
- filename filtering is requested but matches no rows;
- required provider API key is missing outside dry-run mode;
- required provider SDK is missing outside dry-run mode.

---

### 23.2 Per-excerpt recoverable errors

The programme should mark the excerpt as failed and continue if:

- manifest row is missing required fields;
- source file is missing;
- source file cannot be read;
- source file is empty;
- rendered prompt cannot be created;
- API request fails after retries;
- response has no usable text;
- response is invalid or suspicious;
- Markdown output cannot be written;
- metadata JSON cannot be written.

---

## 24. Recommended helper functions

The implementation should be modular.

Recommended functions:

| Function                            | Responsibility                                      |
|-------------------------------------|-----------------------------------------------------|
| `parse_args()`                      | Parse CLI arguments                                 |
| `make_config()`                     | Resolve paths and create configuration object       |
| `utc_now_iso()`                     | Return UTC timestamp                                |
| `resolve_path()`                    | Resolve relative/absolute paths                     |
| `relpath()`                         | Convert paths to stable display paths               |
| `safe_path_part()`                  | Create safe directory/file path components          |
| `setup_logging()`                   | Configure file and console logging                  |
| `load_dotenv_file()`                | Load safe environment values                        |
| `validate_basic_options()`          | Validate numeric and required options               |
| `model_family()`                    | Determine provider family from model name           |
| `validate_api_key_available()`      | Validate provider-specific API key availability     |
| `load_prompt()`                     | Read prompt template                                |
| `validate_prompt()`                 | Confirm placeholder exists                          |
| `sha256_text()`                     | Hash text                                           |
| `sha256_file()`                     | Hash file                                           |
| `load_manifest_rows()`              | Read NDJSON manifest                                |
| `filter_rows_by_filename()`         | Apply `--only-filename` filtering                   |
| `validate_manifest_row()`           | Validate one manifest row                           |
| `get_excerpt_id()`                  | Derive stable excerpt ID from filename              |
| `expected_markdown_output_path()`   | Compute per-excerpt `.md` path                      |
| `expected_metadata_output_path()`   | Compute per-excerpt metadata JSON path              |
| `existing_success()`                | Check whether excerpt should be skipped             |
| `read_source_text()`                | Read source file safely                             |
| `build_denoising_prompt()`          | Replace guideline excerpt placeholder               |
| `make_openai_client()`              | Initialise OpenAI client                            |
| `make_gemini_client()`              | Initialise Gemini client                            |
| `make_llm_client()`                 | Initialise selected provider client                 |
| `call_openai_with_retries()`        | Call OpenAI API with retry/backoff                  |
| `call_gemini_with_retries()`        | Call Gemini API with retry/backoff                  |
| `call_llm_with_retries()`           | Route provider call with retry/backoff              |
| `extract_response_text()`           | Extract OpenAI model output text                    |
| `extract_gemini_response_text()`    | Extract Gemini model output text                    |
| `extract_api_metadata()`            | Extract OpenAI metadata                             |
| `extract_gemini_metadata()`         | Extract Gemini metadata                             |
| `usage_totals_add()`                | Aggregate OpenAI/Gemini token usage where available |
| `validate_denoised_markdown()`      | Validate response is usable Markdown/plain text     |
| `build_success_record()`            | Build per-excerpt success metadata JSON             |
| `build_failure_record()`            | Build per-excerpt failure metadata JSON             |
| `build_invalid_response_record()`   | Build per-excerpt invalid-response metadata JSON    |
| `write_text_atomic()`               | Write Markdown atomically                           |
| `write_json_file()`                 | Write JSON atomically                               |
| `write_ndjson_file()`               | Write NDJSON outputs                                |
| `build_consolidated_success_row()`  | Build one consolidated NDJSON success row           |
| `build_run_manifest()`              | Build run-level manifest                            |
| `build_summary()`                   | Build compact summary                               |
| `main()`                            | Coordinate full programme                           |

---

## 25. Atomic writes

Where feasible, Markdown and JSON output files should be written atomically:

```text
1. write to temporary file in same directory;
2. flush and close;
3. rename temporary file to final path.
```

This helps prevent corrupted outputs if the programme is interrupted during a write.

Both `.md` corpus files and `.json` metadata files should use atomic writes.

---

## 26. Future extensions

The first version should focus on full-excerpt denoising. Future versions may add:

| Feature                           | Purpose                                                  |
|-----------------------------------|----------------------------------------------------------|
| `--max-input-chars N`             | Hard cap input size                                      |
| `--failed-only`                   | Reprocess only failed/invalid records                    |
| `--state-filter STATE`            | Process only one or more states                          |
| `--filename-filter PATTERN`       | Process only files matching a pattern                    |
| `--write-raw-response`            | Control whether raw response text is stored in metadata  |
| `--side-by-side-dir PATH`         | Write source/denoised comparison files                   |
| `--batch-api`                     | Use provider batch API                                   |
| `--validate-markdown`             | Run optional Markdown syntax checks                      |
| `--copy-source-on-failure`        | Copy source text to output if denoising fails            |
| Gemini generation configuration   | Send provider-specific options such as max output tokens |
| Provider selection override       | Explicitly choose provider independently of model prefix |

These are non-goals for the first implementation unless explicitly requested.

---

## 27. Non-goals for first version

The first version should not:

- perform discourse analysis;
- summarise guideline text;
- translate guideline text;
- modernise or stylistically improve text;
- correct spelling, accents, grammar, or punctuation except where clearly caused by PDF extraction artefacts;
- infer educational meanings;
- reconstruct missing content;
- modify the input manifest;
- overwrite source `.txt` files;
- delete source files;
- recursively scan source directories instead of using the manifest;
- build a human annotation interface;
- perform multi-model adjudication;
- use a second-pass model;
- automatically sample or evaluate denoising quality beyond basic response validation;
- require Gemini generation configuration for the initial Gemini integration.

---

## 28. Acceptance criteria

The programme is acceptable when:

1. It is named `llm_denoise.py`.
2. It accepts `--manifest`, `--output`, `--prompt`, and `--model`.
3. It reads an NDJSON manifest containing guideline metadata and source file paths.
4. It treats the input manifest as immutable.
5. It reads prompt instructions from an external Markdown file.
6. It requires the prompt placeholder `<<<GUIDELINE_EXCERPT_TEXT>>>`.
7. It reads source text from each manifest row’s `filepath`.
8. It supports relative and absolute paths.
9. It reads source files as UTF-8 with replacement for invalid bytes.
10. It routes model calls by model family, using Gemini for `gemini-*` models and OpenAI otherwise.
11. It checks the appropriate provider API key outside dry-run mode.
12. It calls the selected provider API unless `--dry-run` is enabled.
13. It uses stateless API calls per excerpt.
14. It treats the LLM response as Markdown/plain text, not JSON.
15. It validates that the response is non-empty and usable as denoised text.
16. It writes one `.md` denoised corpus file per successful excerpt.
17. It writes one metadata JSON artefact per processed excerpt.
18. It preserves the original manifest row in per-excerpt metadata outputs.
19. It records model, model family, prompt hash, source hash, output hash, timestamps, duration, and API metadata.
20. It records raw response text for audit/debugging unless a future option disables it.
21. It writes invalid responses to `llm_denoise_invalid_responses.ndjson`.
22. It writes failures to `llm_denoise_failures.ndjson`.
23. It writes a consolidated `llm_denoised_guidelines.ndjson`.
24. The consolidated denoised NDJSON preserves original manifest order.
25. It writes `llm_denoise_manifest.json`.
26. It writes a timestamped/ID-specific manifest.
27. It writes `llm_denoise_summary.json`.
28. It writes `llm_denoise.log`.
29. It supports `--limit`.
30. It supports `--only-filename`.
31. It supports `--dry-run`.
32. It supports `--resume`.
33. It supports `--reprocess`.
34. It supports `--workers`.
35. Resume is based on existing successful `.md` plus metadata JSON outputs.
36. Concurrent workers do not corrupt shared outputs.
37. Per-excerpt failures do not stop the full run.
38. Fatal setup failures occur before API calls.
39. API retries and backoff are implemented.
40. API key values are never logged or written.
41. Prompt and manifest hashes are recorded.
42. Output directory is created if missing.
43. Denoised output files use the `.md` extension by default.
44. Output Markdown files are organised by state.
45. OpenAI calls send `max_output_tokens`.
46. Gemini calls preserve `max_output_tokens` in metadata but do not need to send it to the API in the initial integration.
47. Exit code is `0` when all planned excerpts succeeded or were skipped.
48. Exit code is non-zero when fatal errors, failed excerpts, or invalid responses occur.
49. The workflow is suitable for constructing the Phase 2 denoised Markdown corpus.