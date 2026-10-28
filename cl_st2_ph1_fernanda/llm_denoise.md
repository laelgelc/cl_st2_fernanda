# Development Specification: `llm_denoise.py`

## 1. Programme purpose

`llm_denoise.py` denoises and extracts selected chapters from Brazilian ENADE report text files with an LLM provider API for a corpus-linguistics research project studying *Exame Nacional de Desempenho dos Estudantes* reports.

The programme takes an immutable NDJSON ENADE manifest as input. Each manifest row identifies one ENADE report and includes the path to the corresponding extracted `.txt` file. For each ENADE report, the programme:

1. reads the ENADE report metadata from the manifest;
2. reads the ENADE report text from the manifest row’s `filepath_txt`;
3. renders an LLM prompt by inserting the report text into an external prompt template;
4. submits the prompt to the configured LLM provider API;
5. expects the model response to be a valid JSON object;
6. parses the JSON response;
7. saves only the JSON `chapters` value as one corpus-ready Markdown output file per ENADE report;
8. saves the JSON chapter-presence metadata flags in the per-report metadata/audit artefact;
9. writes run-level manifests, logs, failures, invalid responses, and summaries;
10. produces a consolidated NDJSON dataset linking original manifest rows to denoised/extracted Markdown outputs.

The programme supports OpenAI and Gemini model families. Model routing is determined from the configured model name:

- model names beginning with `gemini-` use the Gemini API;
- other supported model names use the OpenAI API.

The programme is intended for large-scale denoising/extraction of ENADE report chapters. It must therefore support:

- resumable execution;
- robust per-report failure handling;
- concurrent workers;
- immutable input data;
- reproducible run metadata;
- prompt version tracking;
- API usage tracking where available;
- safe handling of API credentials;
- corpus-ready Markdown output files;
- provider-specific metadata where available;
- strict parsing and validation of the LLM’s JSON response.

---

## 2. Research context

The project studies Brazilian official ENADE reports. Source PDF documents have been converted into per-report text files. Because PDF extraction often introduces artefacts such as line wrapping, isolated page numbers, form-feed characters, broken hyphenation, excessive spacing, and duplicated blank lines, selected chapters require a conservative denoising pass before downstream corpus-linguistic processing.

The denoising task is conservative. The programme must not perform interpretation, summarisation, translation, discourse analysis, modernisation, stylistic improvement, or substantive rewriting. The LLM is used only to identify selected report chapters and remove obvious PDF/OCR extraction artefacts while preserving original content and structure.

The selected ENADE chapter types are identified by title, not by chapter number alone:

| Internal label | Chapter title variants                                    |
|----------------|-----------------------------------------------------------|
| `c4`           | `percepção sobre a prova`; `percepção da prova`           |
| `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6`           | `análise técnica da prova`                                |

The expected model output is a JSON object containing:

- `chapters`: a string containing the denoised Markdown text of the selected chapters, in source order;
- `metadata`: Boolean flags indicating which chapter types were found and included.

Only the `chapters` string should be written to the corpus `.md` output file. The metadata flags should be written to audit metadata and the consolidated NDJSON.

---

## 3. Core design principles

### 3.1 Immutable input

The input manifest must not be modified in place.

The programme must treat:
```text
corpus/enade_dataset.ndjson
```
as an immutable source manifest.

All denoising/extraction outcomes must be written to the output directory supplied by:
```text
--output
```
For this ENADE pipeline, the expected output directory is:
```text
corpus/02_enade_extracted
```
---

### 3.2 Manifest-driven processing

The programme must be driven by an NDJSON manifest, not by recursively scanning a source directory.

Each manifest row represents one intended ENADE report to process.

Expected manifest fields include:
```json
{
  "year": "2009",
  "filename_ori": "ENADE_2009_ADMINISTRAÇÃO.pdf",
  "filepath_ori": "corpus/00_sources/enade_raw/2009/ENADE_2009_ADMINISTRAÇÃO.pdf",
  "mnemonic": "admin",
  "discipline": "Administração",
  "filename": "enade_2009_admin.pdf",
  "filename_txt": "enade_2009_admin.txt",
  "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
}
```
At minimum, the programme requires:

| Field          | Required | Purpose                                          |
|----------------|---------:|--------------------------------------------------|
| `filename_txt` |      Yes | Stable source text filename for the ENADE report |
| `filepath_txt` |      Yes | Path to the extracted report text file           |
| `year`         |      Yes | ENADE year, used for output organisation         |

The default CLI field mappings for this project should be:

| CLI option                         | Default        |
|------------------------------------|----------------|
| `--filename-field`                 | `filename_txt` |
| `--filepath-field`                 | `filepath_txt` |
| `--group-field` or `--state-field` | `year`         |

The programme may keep the option name `--state-field` for compatibility, but semantically it should be treated as the output grouping field. In this ENADE project, that field is `year`.

If optional fields are present, such as `discipline`, `mnemonic`, `filename_ori`, `filepath_ori`, and `filename`, they must be preserved in per-report metadata and consolidated outputs.

---

### 3.3 Per-report Markdown artefacts

Each successfully processed ENADE report must produce one corpus-ready Markdown file.

The Markdown file must contain only the parsed JSON `chapters` value returned by the LLM. It must not contain the JSON wrapper, chapter-presence metadata, audit metadata, or explanatory text.

Recommended output path pattern:
```text
<output>/<year>/<filename_txt_stem>.md
```
Example:
```text
corpus/02_enade_extracted/2009/enade_2009_admin.md
```
If the configured group field is missing or empty, the programme may use:
```text
unknown_group
```
The output extension should be `.md` because the downstream corpus format is Markdown/plain text.

---

### 3.4 Per-report metadata artefacts

In addition to the denoised/extracted Markdown file, each processed report should produce one JSON metadata/audit artefact.

Recommended output path pattern:
```text
<output>/_llm_denoise_metadata/<year>/<filename_txt_stem>.json
```
Example:
```text
corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_admin.json
```
This supports:

- robust resume;
- parallel processing;
- per-report auditability;
- recovery from partial failures;
- invalid/empty response inspection;
- chapter-presence auditing;
- reprocessing selected reports only.

---

### 3.5 Consolidated denoised dataset

The programme must produce a consolidated NDJSON file.

Recommended path:
```text
<output>/llm_denoised_enade.ndjson
```
This file should contain one successfully processed ENADE report per line, preserving the original manifest row and adding denoising/extraction metadata.

The consolidated file must be generated deterministically in the same order as the input manifest after any explicit filtering and limiting.

Only successful records should be included unless a future option explicitly includes failed records.

---

### 3.6 File-based resume

Resume must be based on successful per-report outputs, not on a “last processed report” pointer.

For each manifest row:
```text
if --resume is enabled
and expected Markdown file exists
and expected metadata JSON exists
and metadata status == "success":
    skip report
else:
    process report
```
This is necessary because concurrent workers may complete reports out of manifest order.

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
- denoised/extracted Markdown hash;
- raw LLM response hash;
- parsed JSON response metadata;
- ENADE chapter-presence flags;
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

Run commands from the project phase directory, for example:
```text
cl_st2_ph1_fernanda/
```
#### Dry run
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --limit 10 \
    --max-output-tokens 10000 \
    --dry-run
```
#### Test run, first time
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --limit 10 \
    --max-output-tokens 10000
```
#### Process a single manifest filename
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --only-filename enade_2009_admin.txt \
    --max-output-tokens 10000 \
    --resume
```
#### Gemini test run
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gemini-3.8-flash \
    --limit 10 \
    --max-output-tokens 10000 \
    --resume
```
#### 10 workers test run
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --limit 200 \
    --workers 10 \
    --resume \
    --max-output-tokens 10000
```
#### Full run
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --workers 10 \
    --resume \
    --max-output-tokens 10000 \
    --max-retries 5
```
#### Production mode on an EC2 instance
```shell
bash run_python_ec2.sh \
    llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --workers 10 \
    --resume \
    --max-output-tokens 10000 \
    --max-retries 5
```
#### Retry one specific report
```shell
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --max-output-tokens 10000 \
    --max-retries 5 \
    --only-filename enade_2009_admin.txt \
    --reprocess
```
---

### 4.2 Required arguments

| Argument          | Required | Description                                                  |
|-------------------|---------:|--------------------------------------------------------------|
| `--manifest PATH` |      Yes | Input NDJSON ENADE manifest                                  |
| `--output PATH`   |      Yes | Output directory for denoised/extracted Markdown corpus      |
| `--prompt PATH`   |      Yes | Markdown prompt template                                     |
| `--model MODEL`   |      Yes | LLM model ID used for processing; determines provider family |

---

### 4.3 Optional arguments

| Argument                        |                              Default | Description                                                                             |
|---------------------------------|-------------------------------------:|-----------------------------------------------------------------------------------------|
| `--limit N`                     |                               `None` | Process only the first `N` planned reports after any filename filtering                 |
| `--only-filename FILENAME`      |                               `None` | Process only manifest row(s) whose filename field exactly matches `FILENAME`            |
| `--resume`                      |                              `False` | Skip existing successful Markdown + metadata outputs                                    |
| `--reprocess`                   |                              `False` | Reprocess even if successful outputs already exist                                      |
| `--dry-run`                     |                              `False` | Validate inputs and build planned prompts without API calls                             |
| `--workers N`                   |                                  `1` | Number of concurrent worker threads                                                     |
| `--max-retries N`               |                                  `2` | Number of retries per API call after the initial attempt                                |
| `--retry-backoff-seconds FLOAT` |                                `5.0` | Initial retry backoff in seconds                                                        |
| `--temperature FLOAT`           |                                `0.0` | Temperature if supported by the selected provider/model                                 |
| `--max-output-tokens N`         |                              `10000` | Maximum output tokens for OpenAI responses; recorded but not necessarily sent to Gemini |
| `--env-file PATH`               |                           `env/.env` | Optional environment file containing API credentials                                    |
| `--log-file PATH`               |           `<output>/llm_denoise.log` | Optional explicit log file                                                              |
| `--manifest-file PATH`          | `<output>/llm_denoise_manifest.json` | Optional explicit latest run manifest file                                              |
| `--filename-field FIELD`        |                       `filename_txt` | Manifest field containing source text filename                                          |
| `--filepath-field FIELD`        |                       `filepath_txt` | Manifest field containing source text path                                              |
| `--state-field FIELD`           |                               `year` | Backwards-compatible name for output grouping field                                     |
| `--group-field FIELD`           |                               `year` | Optional clearer alias for output grouping field, if implemented                        |
| `--output-extension EXT`        |                                `.md` | Extension for denoised/extracted corpus outputs                                         |

If both `--state-field` and `--group-field` are implemented and both are supplied, `--group-field` should take precedence, or the programme should fail with a clear ambiguity error. Simpler implementation may retain only `--state-field`, with default `year`.

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
- the required prompt placeholder is missing;
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
{"year":"2009","filename_ori":"ENADE_2009_ADMINISTRAÇÃO.pdf","filepath_ori":"corpus/00_sources/enade_raw/2009/ENADE_2009_ADMINISTRAÇÃO.pdf","mnemonic":"admin","discipline":"Administração","filename":"enade_2009_admin.pdf","filename_txt":"enade_2009_admin.txt","filepath_txt":"corpus/01_enade_txt/2009/enade_2009_admin.txt"}
```
Each non-empty line must parse as a JSON object.

---

### 5.2 Required manifest fields

Each row must contain, by default:
```text
filename_txt
year
filepath_txt
```
or the corresponding fields specified by:
```text
--filename-field
--state-field / --group-field
--filepath-field
```
If a row lacks required fields, that row should be recorded as a per-row failure, but the programme should continue processing other rows.

---

### 5.3 Manifest row preservation

The programme must preserve the original manifest row in per-report metadata JSON and consolidated NDJSON output.

This allows later analysis by original metadata fields such as:

- `year`;
- `discipline`;
- `mnemonic`;
- `filename_ori`;
- `filepath_ori`;
- `filename`;
- `filename_txt`;
- `filepath_txt`.

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
filename_txt
```
Example:
```shell
--only-filename enade_2009_admin.txt
```
If no row matches `--only-filename`, the programme should fail before API calls.

If more than one row matches, the programme may process all matching rows and should log a warning.

`--limit`, if supplied, is applied after filename filtering.

---

## 6. Prompt template

### 6.1 Prompt file

The programme must load the denoising/extraction prompt from the path given by:
```text
--prompt
```
Example:
```text
denoising_prompts/denoising_v1.md
```
The prompt must be external to the programme. Prompt contents must not be hardcoded.

---

### 6.2 ENADE report placeholder

The prompt template must contain:
```text
<<<ENADE_REPORT_TEXT>>>
```
For each source report, the programme must replace this placeholder with the source text.

If the prompt does not contain this placeholder, the programme must fail before API calls.

The previous placeholder used in other projects, `<<<GUIDELINE_EXCERPT_TEXT>>>`, is not the default for this ENADE implementation.

---

### 6.3 Recommended prompt ending

The prompt should contain a section similar to:
```text
ENADE report:

<enade_report>
<<<ENADE_REPORT_TEXT>>>
</enade_report>
```
The programme should not add Markdown code fences around the source text unless the prompt itself does so.

---

### 6.4 Prompt hashing

The programme must compute and record:
```text
prompt_template_sha256
rendered_prompt_sha256
```
The rendered prompt hash should be computed after inserting the ENADE report text.

---

## 7. Source text handling

### 7.1 File path resolution

The source `filepath_txt` from the manifest may be:

- relative; or
- absolute.

Relative paths should be resolved against the directory containing `llm_denoise.py`.

Recommended behaviour for this project:
```text
Relative CLI paths and manifest filepaths are resolved against the directory containing llm_denoise.py.
```
This matches project-situated execution from:
```text
cl_st2_ph1_fernanda/
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

- mark that report as failed;
- write a per-report metadata JSON failure artefact where possible;
- continue processing other reports.

---

### 7.4 Missing source files

If a source file does not exist:

- mark that report as failed;
- write a per-report metadata JSON failure artefact;
- include the original manifest row;
- continue processing other reports.

---

### 7.5 Source text hashing

For each successfully read source file, record:
```text
source_text_sha256
```
---

## 8. LLM request construction

For each ENADE report, the programme should construct the request as:
```text
[prompt template with <<<ENADE_REPORT_TEXT>>> replaced by source text]
```
The programme should not add additional denoising or extraction rules in code. The prompt template is the source of task instructions.

The LLM call must be stateless. It must not reuse prior conversational context between reports.

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
- per-report metadata JSON;
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

- mark the report as failed;
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

For Gemini calls, the programme should preserve the configured `--max-output-tokens` value in run and per-report metadata, but the initial Gemini integration does not need to send it to the Gemini API unless SDK compatibility is verified.

Per-report metadata should record whether the value was sent to the API:
```json
{
  "max_output_tokens": 10000,
  "max_output_tokens_sent_to_api": true
}
```
For Gemini responses in the initial implementation, `max_output_tokens_sent_to_api` should be `false`.

---

### 9.8 Token usage

If token usage metadata is available from the provider response, record it in:

- per-report metadata JSON;
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

| Gemini field             | Aggregate field |
|--------------------------|-----------------|
| `prompt_token_count`     | `input_tokens`  |
| `candidates_token_count` | `output_tokens` |
| `total_token_count`      | `total_tokens`  |

---

## 10. LLM response parsing and validation

### 10.1 Expected response

The LLM is expected to return only a valid JSON object with this structure:
```json
{
  "chapters": "Denoised Markdown text of the selected chapters, in the order they appear.",
  "metadata": {
    "c4_present": true,
    "c5_present": true,
    "c6_present": true
  }
}
```
The response must not include Markdown code fences, comments, or explanatory text outside the JSON object.

The `chapters` field must be a string.

The `metadata` field must be an object with exactly these Boolean fields:
```text
c4_present
c5_present
c6_present
```
If no selected chapter type is present, the model should return:
```json
{
  "chapters": "",
  "metadata": {
    "c4_present": false,
    "c5_present": false,
    "c6_present": false
  }
}
```
The programme should treat such a response as structurally valid. Whether it should be considered a successful corpus output is specified below.

---

### 10.2 JSON extraction

The programme should parse the raw response as JSON.

Recommended strict behaviour:

1. Strip leading/trailing whitespace.
2. Reject responses wrapped in Markdown code fences.
3. Attempt `json.loads`.
4. Require the parsed value to be a JSON object.
5. Require the object to contain `chapters` and `metadata`.
6. Require `chapters` to be a string.
7. Require `metadata` to be an object.
8. Require `metadata.c4_present`, `metadata.c5_present`, and `metadata.c6_present` to be Booleans.

Optional tolerant behaviour, if needed for practical robustness:

- If the response is wrapped in a single JSON code fence, strip the fence and parse the inner content.
- This tolerance should be logged and recorded as `json_fence_stripped: true`.

The strict default is preferable because the prompt explicitly instructs the model not to use Markdown fences.

---

### 10.3 Validation rules

The programme should validate:

- response text is present;
- response text is a string;
- response text is not empty after stripping whitespace;
- response text does not contain the prompt placeholder `<<<ENADE_REPORT_TEXT>>>`;
- response text does not appear to be a refusal;
- response text does not appear to be an explanatory wrapper;
- response text is valid JSON;
- parsed JSON is an object;
- parsed JSON has the required schema;
- `chapters` can be written as UTF-8;
- if any chapter flag is `true`, `chapters` must be non-empty after stripping;
- if all chapter flags are `false`, `chapters` must be an empty string or whitespace-only.

The programme should not attempt to validate whether every denoising or chapter-selection decision is correct. That is a research/audit matter, not a deterministic schema check.

---

### 10.4 Handling reports with no selected chapters

If the response is valid JSON and all metadata flags are false:
```json
{
  "chapters": "",
  "metadata": {
    "c4_present": false,
    "c5_present": false,
    "c6_present": false
  }
}
```
the programme should treat the processing as a valid success, because the prompt explicitly allows this condition.

Recommended output behaviour:

- write an empty `.md` file, or a zero-length/whitespace-free `.md` file;
- record `chapters_empty: true`;
- record all chapter flags as false;
- include the record in the consolidated NDJSON;
- set status to `success`.

This preserves one output artefact per successfully processed manifest row and keeps resume behaviour simple.

---

### 10.5 Invalid or suspicious responses

If the model returns no usable text or a clearly invalid response:

- save a per-report metadata JSON artefact with status `invalid_response`;
- include raw response text where available;
- include validation error;
- include API metadata where available;
- write to `llm_denoise_invalid_responses.ndjson`;
- continue processing.

Examples of invalid/suspicious responses:

- empty response;
- response only says it cannot comply;
- response contains explanatory text outside JSON;
- response contains Markdown fences, if strict mode is used;
- response contains invalid JSON;
- response is a JSON array rather than an object;
- `chapters` is missing or not a string;
- `metadata` is missing or not an object;
- chapter-presence flags are missing or not Boolean;
- any chapter flag is true but `chapters` is empty;
- all chapter flags are false but `chapters` contains substantive text;
- response repeats the prompt instructions;
- response contains the placeholder `<<<ENADE_REPORT_TEXT>>>`.

---

## 11. Output directory structure

Given:
```text
--output corpus/02_enade_extracted
```
the programme should create:
```text
corpus/02_enade_extracted/
  2009/
    enade_2009_admin.md
    enade_2009_arquivol.md
    ...
  2010/
    enade_2010_agro.md
    ...
  ...
  _llm_denoise_metadata/
    2009/
      enade_2009_admin.json
      enade_2009_arquivol.json
      ...
    2010/
      enade_2010_agro.json
      ...
  llm_denoise_manifest.json
  llm_denoise_manifest_<RUN_ID>.json
  llm_denoise.log
  llm_denoised_enade.ndjson
  llm_denoise_failures.ndjson
  llm_denoise_invalid_responses.ndjson
  llm_denoise_summary.json
```
The year directories contain corpus-ready Markdown files.

The `_llm_denoise_metadata/` directory contains audit metadata and should not be treated as corpus text.

---

## 12. Per-report metadata JSON output

### 12.1 Successful report structure

Example:
```json
{
  "filename": "enade_2009_admin.txt",
  "report_id": "enade_2009_admin",
  "group": "2009",
  "year": "2009",
  "status": "success",
  "input": {
    "manifest_file": "corpus/enade_dataset.ndjson",
    "source_file": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
    "prompt_file": "denoising_prompts/denoising_v1.md"
  },
  "output": {
    "markdown_file": "corpus/02_enade_extracted/2009/enade_2009_admin.md",
    "metadata_json": "corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_admin.json"
  },
  "manifest_row": {
    "year": "2009",
    "filename_ori": "ENADE_2009_ADMINISTRAÇÃO.pdf",
    "filepath_ori": "corpus/00_sources/enade_raw/2009/ENADE_2009_ADMINISTRAÇÃO.pdf",
    "mnemonic": "admin",
    "discipline": "Administração",
    "filename": "enade_2009_admin.pdf",
    "filename_txt": "enade_2009_admin.txt",
    "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
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
  "llm_response": {
    "raw_response_text": "{\"chapters\":\"...\",\"metadata\":{\"c4_present\":true,\"c5_present\":true,\"c6_present\":false}}",
    "parsed_json_valid": true,
    "json_fence_stripped": false,
    "chapters_empty": false,
    "chapter_metadata": {
      "c4_present": true,
      "c5_present": true,
      "c6_present": false
    }
  },
  "api_metadata": {
    "id": "...",
    "model": "gpt-6-luna",
    "usage": {},
    "usage_metadata": {}
  },
  "temperature": 0.0,
  "temperature_sent_to_api": true,
  "max_output_tokens": 10000,
  "max_output_tokens_sent_to_api": true,
  "created_at": "2026-10-28T00:00:00Z",
  "duration_seconds": 1.24,
  "error": null
}
```
For Gemini records, the model block should use `"model_family": "gemini"`, and `max_output_tokens_sent_to_api` should be `false` unless provider-specific generation configuration is later implemented.

For compatibility with existing helper functions or downstream expectations, the implementation may use `excerpt_id` instead of `report_id`, but the ENADE-specific term `report_id` is preferred.

---

### 12.2 Successful report with no selected chapters

Example:
```json
{
  "filename": "enade_2009_example.txt",
  "report_id": "enade_2009_example",
  "group": "2009",
  "year": "2009",
  "status": "success",
  "output": {
    "markdown_file": "corpus/02_enade_extracted/2009/enade_2009_example.md",
    "metadata_json": "corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_example.json"
  },
  "llm_response": {
    "parsed_json_valid": true,
    "chapters_empty": true,
    "chapter_metadata": {
      "c4_present": false,
      "c5_present": false,
      "c6_present": false
    }
  },
  "error": null
}
```
---

### 12.3 Failed report structure

Example:
```json
{
  "filename": "enade_2009_admin.txt",
  "report_id": "enade_2009_admin",
  "group": "2009",
  "year": "2009",
  "status": "failed",
  "input": {
    "manifest_file": "corpus/enade_dataset.ndjson",
    "source_file": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
    "prompt_file": "denoising_prompts/denoising_v1.md"
  },
  "output": {
    "markdown_file": "corpus/02_enade_extracted/2009/enade_2009_admin.md",
    "metadata_json": "corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_admin.json"
  },
  "manifest_row": {
    "year": "2009",
    "filename_txt": "enade_2009_admin.txt",
    "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
  },
  "error_type": "missing_source_file",
  "error": "Source file not found",
  "created_at": "2026-10-28T00:00:00Z",
  "duration_seconds": 0.01
}
```
---

### 12.4 Invalid response structure

Example:
```json
{
  "filename": "enade_2009_admin.txt",
  "report_id": "enade_2009_admin",
  "group": "2009",
  "year": "2009",
  "status": "invalid_response",
  "input": {
    "manifest_file": "corpus/enade_dataset.ndjson",
    "source_file": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
    "prompt_file": "denoising_prompts/denoising_v1.md"
  },
  "output": {
    "markdown_file": "corpus/02_enade_extracted/2009/enade_2009_admin.md",
    "metadata_json": "corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_admin.json"
  },
  "manifest_row": {
    "year": "2009",
    "filename_txt": "enade_2009_admin.txt",
    "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
  },
  "raw_response_text": "Here is the JSON: ...",
  "validation_error": "Response contains explanatory text outside JSON",
  "api_metadata": {
    "id": "...",
    "usage": {}
  },
  "created_at": "2026-10-28T00:00:00Z",
  "duration_seconds": 1.02
}
```
---

## 13. Consolidated denoised NDJSON

The programme must write:
```text
<output>/llm_denoised_enade.ndjson
```
Each line should contain:

- all fields from the original manifest row;
- `llm_denoise`;
- `llm_denoise_metadata`.

Example:
```json
{
  "year": "2009",
  "filename_ori": "ENADE_2009_ADMINISTRAÇÃO.pdf",
  "filepath_ori": "corpus/00_sources/enade_raw/2009/ENADE_2009_ADMINISTRAÇÃO.pdf",
  "mnemonic": "admin",
  "discipline": "Administração",
  "filename": "enade_2009_admin.pdf",
  "filename_txt": "enade_2009_admin.txt",
  "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
  "llm_denoise": {
    "markdown_file": "corpus/02_enade_extracted/2009/enade_2009_admin.md"
  },
  "llm_denoise_metadata": {
    "status": "success",
    "model": "gpt-6-luna",
    "model_family": "openai",
    "prompt_file": "denoising_prompts/denoising_v1.md",
    "prompt_template_sha256": "...",
    "source_text_sha256": "...",
    "denoised_markdown_sha256": "...",
    "denoised_at": "2026-10-28T00:00:00Z",
    "metadata_json": "corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_admin.json",
    "chapters_empty": false,
    "chapter_metadata": {
      "c4_present": true,
      "c5_present": true,
      "c6_present": false
    },
    "usage": {},
    "usage_metadata": {}
  }
}
```
Only successful denoising/extraction records should be included unless a future option explicitly includes failed records.

The consolidated denoised NDJSON must preserve original manifest order after filtering and limiting.

---

## 14. Failure and invalid-response NDJSON files

### 14.1 Failures

The programme must write:
```text
<output>/llm_denoise_failures.ndjson
```
Each line should correspond to one report-level failure, such as:

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
Each line should correspond to one API response that was received but was considered invalid or suspicious, such as:

- invalid JSON;
- schema mismatch;
- explanatory wrapper;
- refusal;
- inconsistent `chapters` and metadata flags.

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
  "start_time": "2026-10-28T00:00:00Z",
  "end_time": "2026-10-28T01:00:00Z",
  "status": "success",
  "paths": {
    "manifest": "corpus/enade_dataset.ndjson",
    "output": "corpus/02_enade_extracted",
    "prompt": "denoising_prompts/denoising_v1.md",
    "log_file": "corpus/02_enade_extracted/llm_denoise.log",
    "metadata_dir": "corpus/02_enade_extracted/_llm_denoise_metadata",
    "denoised_ndjson": "corpus/02_enade_extracted/llm_denoised_enade.ndjson",
    "failures_ndjson": "corpus/02_enade_extracted/llm_denoise_failures.ndjson",
    "invalid_responses_ndjson": "corpus/02_enade_extracted/llm_denoise_invalid_responses.ndjson"
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
    "max_output_tokens": 10000
  },
  "processing": {
    "workers": 10,
    "limit": null,
    "only_filename": null,
    "resume": true,
    "reprocess": false,
    "dry_run": false,
    "max_retries": 5,
    "retry_backoff_seconds": 5.0,
    "filename_field": "filename_txt",
    "filepath_field": "filepath_txt",
    "group_field": "year",
    "output_extension": ".md"
  },
  "hashes": {
    "manifest_file_sha256": "...",
    "prompt_template_sha256": "..."
  },
  "counts": {
    "manifest_rows_total": 260,
    "manifest_rows_matched": 260,
    "reports_planned": 260,
    "reports_succeeded": 258,
    "reports_failed": 1,
    "reports_invalid_response": 1,
    "reports_skipped_existing": 0,
    "reports_dry_run": 0,
    "reports_with_c4": 250,
    "reports_with_c5": 249,
    "reports_with_c6": 248,
    "reports_with_no_selected_chapters": 2
  },
  "usage_totals": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0
  },
  "reports": [
    {
      "filename": "enade_2009_admin.txt",
      "report_id": "enade_2009_admin",
      "group": "2009",
      "year": "2009",
      "status": "success",
      "markdown_file": "corpus/02_enade_extracted/2009/enade_2009_admin.md",
      "metadata_json": "corpus/02_enade_extracted/_llm_denoise_metadata/2009/enade_2009_admin.json",
      "chapter_metadata": {
        "c4_present": true,
        "c5_present": true,
        "c6_present": false
      }
    }
  ]
}
```
For very large runs, the `reports` list may be large but acceptable. If it becomes unwieldy, a future version may write a separate run index NDJSON.

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
  "manifest": "corpus/enade_dataset.ndjson",
  "output": "corpus/02_enade_extracted",
  "denoised_ndjson": "corpus/02_enade_extracted/llm_denoised_enade.ndjson",
  "counts": {
    "manifest_rows_total": 260,
    "manifest_rows_matched": 260,
    "reports_planned": 260,
    "reports_succeeded": 258,
    "reports_failed": 1,
    "reports_invalid_response": 1,
    "reports_skipped_existing": 0,
    "reports_dry_run": 0,
    "reports_with_c4": 250,
    "reports_with_c5": 249,
    "reports_with_c6": 248,
    "reports_with_no_selected_chapters": 2
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
- configured filename field;
- configured filepath field;
- configured group/year field;
- output extension;
- prompt hash;
- manifest hash;
- number of manifest rows;
- number of matched manifest rows after filename filtering;
- number of planned reports;
- per-report start and finish at reasonable verbosity;
- skipped reports;
- failures;
- invalid responses;
- JSON parsing/schema validation failures;
- provider-specific retry attempts;
- temperature unsupported warnings, where applicable;
- final success/failure counts;
- chapter-presence summary counts;
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
- year/group values;
- disciplines;
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
- confirm the ENADE report placeholder exists;
- load and validate the manifest;
- apply `--only-filename` filtering if supplied;
- apply `--limit` if supplied;
- resolve planned source file paths;
- compute expected Markdown and metadata output paths;
- check whether source files exist;
- read source files if feasible;
- compute source hashes and rendered prompt hashes where feasible;
- compute approximate prompt sizes;
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

- skip any report whose expected Markdown file exists;
- and whose expected metadata JSON exists;
- and whose metadata JSON has `status == "success"`;
- count it as `reports_skipped_existing`;
- include skipped records in the run manifest.

Existing success metadata should include chapter-presence flags. If older success metadata lacks these flags, the programme may still skip it, but the run manifest should handle missing flags safely.

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

### 20.2 Per-report file safety

Each worker writes only its own:

- Markdown output file;
- metadata JSON file.

Workers should not concurrently append to the consolidated NDJSON.

Recommended approach:

1. workers produce per-report Markdown and metadata files;
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
11. Confirm <<<ENADE_REPORT_TEXT>>> placeholder exists.
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
22. Process reports with configured workers:
    - read source text;
    - render prompt;
    - call provider API with retries;
    - extract response text;
    - parse response as JSON;
    - validate JSON schema;
    - extract chapters string;
    - extract chapter metadata flags;
    - validate consistency between chapters and flags;
    - write chapters string to Markdown output;
    - write metadata JSON;
    - return status.
23. Write failures NDJSON.
24. Write invalid responses NDJSON.
25. Write consolidated denoised ENADE NDJSON in manifest order.
26. Write summary JSON.
27. Write run manifests.
28. Log final counts.
29. Exit.
```
---

## 22. Exit codes

Recommended exit behaviour:

| Condition                                                       | Exit code |
|-----------------------------------------------------------------|----------:|
| All planned reports succeeded or were skipped successfully      |       `0` |
| Some reports failed or had invalid responses, but run completed |       `1` |
| Fatal setup error before processing                             |       `1` |
| Keyboard interruption                                           |     `130` |

A run with report-level failures should still write manifests and logs where possible.

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

### 23.2 Per-report recoverable errors

The programme should mark the report as failed and continue if:

- manifest row is missing required fields;
- source file is missing;
- source file cannot be read;
- source file is empty;
- rendered prompt cannot be created;
- API request fails after retries;
- response has no usable text;
- response is invalid or suspicious;
- response is not valid JSON;
- response JSON does not match the expected schema;
- Markdown output cannot be written;
- metadata JSON cannot be written.

---

## 24. Recommended helper functions

The implementation should be modular.

Recommended functions:

| Function                           | Responsibility                                                    |
|------------------------------------|-------------------------------------------------------------------|
| `parse_args()`                     | Parse CLI arguments                                               |
| `make_config()`                    | Resolve paths and create configuration object                     |
| `utc_now_iso()`                    | Return UTC timestamp                                              |
| `resolve_path()`                   | Resolve relative/absolute paths                                   |
| `relpath()`                        | Convert paths to stable display paths                             |
| `safe_path_part()`                 | Create safe directory/file path components                        |
| `setup_logging()`                  | Configure file and console logging                                |
| `load_dotenv_file()`               | Load safe environment values                                      |
| `validate_basic_options()`         | Validate numeric and required options                             |
| `model_family()`                   | Determine provider family from model name                         |
| `validate_api_key_available()`     | Validate provider-specific API key availability                   |
| `load_prompt()`                    | Read prompt template                                              |
| `validate_prompt()`                | Confirm ENADE placeholder exists                                  |
| `sha256_text()`                    | Hash text                                                         |
| `sha256_file()`                    | Hash file                                                         |
| `load_manifest_rows()`             | Read NDJSON manifest                                              |
| `filter_rows_by_filename()`        | Apply `--only-filename` filtering                                 |
| `validate_manifest_row()`          | Validate one manifest row                                         |
| `get_report_id()`                  | Derive stable report ID from `filename_txt`                       |
| `expected_markdown_output_path()`  | Compute per-report `.md` path                                     |
| `expected_metadata_output_path()`  | Compute per-report metadata JSON path                             |
| `existing_success()`               | Check whether report should be skipped                            |
| `read_source_text()`               | Read source file safely                                           |
| `build_denoising_prompt()`         | Replace ENADE report placeholder                                  |
| `make_openai_client()`             | Initialise OpenAI client                                          |
| `make_gemini_client()`             | Initialise Gemini client                                          |
| `make_llm_client()`                | Initialise selected provider client                               |
| `call_openai_with_retries()`       | Call OpenAI API with retry/backoff                                |
| `call_gemini_with_retries()`       | Call Gemini API with retry/backoff                                |
| `call_llm_with_retries()`          | Route provider call with retry/backoff                            |
| `extract_response_text()`          | Extract OpenAI model output text                                  |
| `extract_gemini_response_text()`   | Extract Gemini model output text                                  |
| `extract_api_metadata()`           | Extract OpenAI metadata                                           |
| `extract_gemini_metadata()`        | Extract Gemini metadata                                           |
| `strip_optional_json_fence()`      | Optionally strip JSON code fences if tolerant mode is implemented |
| `parse_llm_json_response()`        | Parse raw response text as JSON                                   |
| `validate_enade_response_json()`   | Validate JSON schema and consistency                              |
| `extract_chapters_markdown()`      | Extract JSON `chapters` string                                    |
| `extract_chapter_metadata()`       | Extract `c4_present`, `c5_present`, `c6_present`                  |
| `usage_totals_add()`               | Aggregate OpenAI/Gemini token usage where available               |
| `build_success_record()`           | Build per-report success metadata JSON                            |
| `build_failure_record()`           | Build per-report failure metadata JSON                            |
| `build_invalid_response_record()`  | Build per-report invalid-response metadata JSON                   |
| `write_text_atomic()`              | Write Markdown atomically                                         |
| `write_json_file()`                | Write JSON atomically                                             |
| `write_ndjson_file()`              | Write NDJSON outputs                                              |
| `build_consolidated_success_row()` | Build one consolidated NDJSON success row                         |
| `build_run_manifest()`             | Build run-level manifest                                          |
| `build_summary()`                  | Build compact summary                                             |
| `main()`                           | Coordinate full programme                                         |

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

The first version should focus on ENADE selected-chapter extraction and denoising. Future versions may add:

| Feature                              | Purpose                                                     |
|--------------------------------------|-------------------------------------------------------------|
| `--max-input-chars N`                | Hard cap input size                                         |
| `--failed-only`                      | Reprocess only failed/invalid records                       |
| `--year-filter YEAR`                 | Process only one or more ENADE years                        |
| `--discipline-filter TEXT`           | Process only selected disciplines                           |
| `--filename-filter PATTERN`          | Process only files matching a pattern                       |
| `--write-raw-response`               | Control whether raw response text is stored in metadata     |
| `--side-by-side-dir PATH`            | Write source/denoised comparison files                      |
| `--batch-api`                        | Use provider batch API                                      |
| `--validate-markdown`                | Run optional Markdown syntax checks on extracted `chapters` |
| `--copy-source-on-failure`           | Copy source text to output if denoising fails               |
| Gemini generation configuration      | Send provider-specific options such as max output tokens    |
| Provider selection override          | Explicitly choose provider independently of model prefix    |
| Strict/tolerant JSON mode            | Control whether JSON code fences may be stripped            |
| `--include-failures-in-consolidated` | Include failed/invalid records in consolidated NDJSON       |

These are non-goals for the first implementation unless explicitly requested.

---

## 27. Non-goals for first version

The first version should not:

- perform discourse analysis;
- summarise ENADE report text;
- translate ENADE report text;
- modernise or stylistically improve text;
- correct spelling, accents, grammar, or punctuation except where clearly caused by PDF extraction artefacts;
- infer educational meanings;
- reconstruct missing content;
- infer chapter type from chapter number alone;
- include chapters outside the selected chapter-title types;
- modify the input manifest;
- overwrite source `.txt` files;
- delete source files;
- recursively scan source directories instead of using the manifest;
- build a human annotation interface;
- perform multi-model adjudication;
- use a second-pass model;
- automatically sample or evaluate denoising quality beyond JSON/schema validation;
- require Gemini generation configuration for the initial Gemini integration.

---

## 28. Acceptance criteria

The programme is acceptable when:

1. It is named `llm_denoise.py`.
2. It accepts `--manifest`, `--output`, `--prompt`, and `--model`.
3. It reads an NDJSON manifest containing ENADE metadata and source text paths.
4. It treats the input manifest as immutable.
5. It reads prompt instructions from an external Markdown file.
6. It requires the prompt placeholder `<<<ENADE_REPORT_TEXT>>>`.
7. It reads source text from each manifest row’s `filepath_txt` by default.
8. It uses `filename_txt` as the default filename field.
9. It uses `year` as the default output grouping field.
10. It supports relative and absolute paths.
11. It reads source files as UTF-8 with replacement for invalid bytes.
12. It routes model calls by model family, using Gemini for `gemini-*` models and OpenAI otherwise.
13. It checks the appropriate provider API key outside dry-run mode.
14. It calls the selected provider API unless `--dry-run` is enabled.
15. It uses stateless API calls per report.
16. It expects the LLM response to be valid JSON.
17. It parses the JSON response.
18. It validates that the parsed JSON contains `chapters` as a string.
19. It validates that the parsed JSON contains metadata Boolean flags `c4_present`, `c5_present`, and `c6_present`.
20. It writes only the parsed `chapters` string to the `.md` corpus output file.
21. It records the chapter-presence flags in per-report metadata.
22. It records the chapter-presence flags in the consolidated NDJSON.
23. It treats all-false metadata with empty `chapters` as a valid success.
24. It writes one `.md` corpus file per successful report.
25. It writes one metadata JSON artefact per processed report.
26. It preserves the original manifest row in per-report metadata outputs.
27. It records model, model family, prompt hash, source hash, output hash, timestamps, duration, and API metadata.
28. It records raw response text for audit/debugging unless a future option disables it.
29. It writes invalid responses to `llm_denoise_invalid_responses.ndjson`.
30. It writes failures to `llm_denoise_failures.ndjson`.
31. It writes a consolidated `llm_denoised_enade.ndjson`.
32. The consolidated denoised NDJSON preserves original manifest order.
33. It writes `llm_denoise_manifest.json`.
34. It writes a timestamped/ID-specific manifest.
35. It writes `llm_denoise_summary.json`.
36. It writes `llm_denoise.log`.
37. It supports `--limit`.
38. It supports `--only-filename`.
39. It supports `--dry-run`.
40. It supports `--resume`.
41. It supports `--reprocess`.
42. It supports `--workers`.
43. Resume is based on existing successful `.md` plus metadata JSON outputs.
44. Concurrent workers do not corrupt shared outputs.
45. Per-report failures do not stop the full run.
46. Fatal setup failures occur before API calls.
47. API retries and backoff are implemented.
48. API key values are never logged or written.
49. Prompt and manifest hashes are recorded.
50. Output directory is created if missing.
51. Denoised output files use the `.md` extension by default.
52. Output Markdown files are organised by year by default.
53. OpenAI calls send `max_output_tokens`.
54. Gemini calls preserve `max_output_tokens` in metadata but do not need to send it to the API in the initial integration.
55. Exit code is `0` when all planned reports succeeded or were skipped.
56. Exit code is non-zero when fatal errors, failed reports, or invalid responses occur.
57. The workflow is suitable for constructing the Phase 1 ENADE denoised/extracted Markdown corpus.