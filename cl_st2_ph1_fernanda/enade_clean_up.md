# `enade_clean_up.py` — Programme Specification for Development

## 1. High-level Functionality Specification

### Programme Summary

`enade_clean_up.py` is an offline corpus-preparation programme for ENADE report text files.

The programme reads raw `.txt` ENADE reports, detects chapters of interest by title, extracts only those chapter spans, applies conservative deterministic clean-up rules, optionally sends the extracted spans to an LLM for denoising, and writes validated corpus-ready outputs.

The programme is intended to replace the earlier workflow in which whole ENADE reports were sent directly to the LLM. Its main purpose is to reduce input size, improve reliability, avoid unnecessary LLM cost, and make the clean-up process reproducible.

The programme must never modify the raw source files.

Default raw input directory:
```text
corpus/01_enade_txt
```
Default input manifest:
```text
corpus/enade_dataset.ndjson
```
Default output directory:
```text
corpus/02_enade_clean
```
The programme should produce, for each processed report:
```text
corpus/02_enade_clean/<year>/<filename_stem>.md
corpus/02_enade_clean/<year>/<filename_stem>.json
```
The Markdown file is the corpus-facing text output. The JSON file is the structured provenance, extraction, validation, warning, and status record.

The programme must also produce run-level audit files:
```text
corpus/02_enade_clean/manifest.ndjson
corpus/02_enade_clean/run_summary.json
corpus/02_enade_clean/enade_clean_up.log
```
A timestamped run summary should also be written:
```text
corpus/02_enade_clean/run_summary_<run_id>.json
```
---

## 2. Key Behaviours

The programme must:

- read ENADE `.txt` reports from a manifest or by walking an input directory;
- preserve the raw files unchanged;
- preserve the input subdirectory structure in the output directory;
- identify chapters by normalized chapter title, not by chapter number;
- extract only the target chapter types;
- support deterministic local clean-up;
- optionally support LLM denoising after local extraction;
- avoid sending full reports to the LLM when local chapter extraction succeeds;
- preserve substantive report content;
- avoid summarising, paraphrasing, correcting, translating, or rewriting content;
- preserve tables and numerical data as much as possible;
- flag possible PDF/OCR/font extraction corruption;
- support dry runs;
- support one-file testing;
- support resume and reprocess modes;
- write per-file JSON metadata;
- write a run-level NDJSON manifest;
- write a run-level JSON summary;
- write an append-only log;
- exit with clear status codes.

---

## 3. Chapters of Interest

## 3.1 Internal chapter labels

The programme must use the following internal content labels:

| Internal label | Target chapter title variants |
|---|---|
| `c4` | `Percepção sobre a Prova`; `Percepção da Prova` |
| `c5` | `Distribuição dos Conceitos`; `Distribuição de Conceitos` |
| `c6` | `Análise Técnica da Prova` |

These labels are internal semantic labels. They must not be interpreted as fixed source chapter numbers.

For example:

- in older reports, `Análise Técnica da Prova` may appear as Chapter 3;
- in other reports, `Percepção da Prova` may appear as Chapter 3;
- in still other reports, `Distribuição dos Conceitos` may appear as Chapter 5.

The programme must therefore detect chapters by normalized title matching.

## 3.2 Target-title matching policy

The programme should match titles after normalization:

- convert to lowercase;
- strip accents;
- collapse whitespace;
- remove punctuation where safe;
- normalize OCR-like punctuation where possible;
- ignore chapter-number prefixes;
- ignore repeated dotted leader page-number formatting from tables of contents.

Examples of normalized target titles:
```text
percepcao sobre a prova
percepcao da prova
distribuicao dos conceitos
distribuicao de conceitos
analise tecnica da prova
```
The programme must not infer a target chapter from chapter number alone.

## 3.3 Newer ENADE layouts

Newer reports may not contain exactly the same chapter numbering or may place chapters in a different order. The programme should support title-based extraction for layouts where target chapters may appear as:
```text
Capítulo 3 Percepção da Prova
Capítulo 4 Distribuição de Conceitos
Capítulo 5 Análise Técnica da Prova
```
or as equivalent uppercase headings.

---

## 4. Input Specification

## 4.1 Manifest input

Default manifest:
```text
corpus/enade_dataset.ndjson
```
The manifest is expected to contain one JSON object per line.

The implementation should be flexible about exact field names, but should attempt to resolve the source path from common fields such as:
```text
path
source_path
txt_path
file_path
filename
```
If a manifest entry contains a relative path, it should be resolved relative to either:

1. the current working directory; or
2. `--input-root`, if the path is only a filename or relative corpus path.

If no manifest is provided, the programme should process all `.txt` files under `--input-root`.

## 4.2 Directory-walk input

Default input root:
```text
corpus/01_enade_txt
```
In directory-walk mode, the programme processes every `.txt` file under this directory, preserving relative paths.

Example input:
```text
corpus/01_enade_txt/2009/enade_2009_admin.txt
```
Corresponding output:
```text
corpus/02_enade_clean/2009/enade_2009_admin.md
corpus/02_enade_clean/2009/enade_2009_admin.json
```
## 4.3 Supported encodings

The primary expected encoding is UTF-8.

The programme should read with:
```python
encoding="utf-8", errors="replace"
```
It may optionally support fallback encoding detection, but v1 should avoid complex automatic encoding repair.

---

## 5. Output Specification

## 5.1 Per-report Markdown output

For each report, write:
```text
corpus/02_enade_clean/<year>/<filename_stem>.md
```
The Markdown output should contain only the selected chapters that were found and extracted.

Recommended structure:
```
markdown
# <source filename stem>

## Análise Técnica da Prova

...

## Percepção sobre a Prova

...

## Distribuição dos Conceitos

...
```
The exact heading text should preferably be preserved from the source after clean-up. The programme should not invent missing chapters or headings.

If no target chapters are found, the Markdown file may be omitted unless `--write-empty` is set.

## 5.2 Per-report JSON output

For each report, write:
```text
corpus/02_enade_clean/<year>/<filename_stem>.json
```
The JSON file must include:

- source path;
- output path;
- status;
- target chapter presence flags;
- detected headings;
- extracted spans;
- clean-up statistics;
- warnings;
- errors if any;
- run metadata.

Suggested structure:
```json
{
  "source_path": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
  "output_markdown_path": "corpus/02_enade_clean/2009/enade_2009_admin.md",
  "output_json_path": "corpus/02_enade_clean/2009/enade_2009_admin.json",
  "status": "success",
  "processing_mode": "local",
  "chapter_presence": {
    "c4_present": true,
    "c5_present": true,
    "c6_present": true
  },
  "chapters": [
    {
      "label": "c6",
      "matched_title": "Análise Técnica da Prova",
      "source_chapter_number": "3",
      "start_line": 1024,
      "end_line": 2540,
      "input_chars": 98544,
      "output_chars": 87210,
      "warnings": []
    },
    {
      "label": "c4",
      "matched_title": "Percepção sobre a Prova",
      "source_chapter_number": "4",
      "start_line": 2541,
      "end_line": 3690,
      "input_chars": 74320,
      "output_chars": 69200,
      "warnings": []
    },
    {
      "label": "c5",
      "matched_title": "Distribuição dos Conceitos",
      "source_chapter_number": "5",
      "start_line": 3691,
      "end_line": 4300,
      "input_chars": 31300,
      "output_chars": 29750,
      "warnings": []
    }
  ],
  "cleanup_stats": {
    "input_chars": 520000,
    "candidate_chars": 204164,
    "output_chars": 186160,
    "lines_removed_as_page_numbers": 84,
    "blank_lines_collapsed": 412,
    "paragraph_joins": 925,
    "hyphenation_fixes": 31,
    "control_chars_removed": 4
  },
  "warnings": [],
  "errors": [],
  "run_id": "20261030T120000Z"
}
```
## 5.3 Run-level manifest

The run-level manifest should be written as NDJSON:
```text
corpus/02_enade_clean/manifest.ndjson
```
Each line should be the same per-report JSON object, or a compact subset of it.

## 5.4 Run summary

The run summary should be written to:
```text
corpus/02_enade_clean/run_summary.json
corpus/02_enade_clean/run_summary_<run_id>.json
```
Suggested structure:
```json
{
  "run_metadata": {
    "run_id": "20261030T120000Z",
    "tool_name": "enade_clean_up.py",
    "tool_version": "v1",
    "mode": "local",
    "input_root": "corpus/01_enade_txt",
    "input_manifest": "corpus/enade_dataset.ndjson",
    "output_dir": "corpus/02_enade_clean",
    "started_at": "2026-10-30T12:00:00Z",
    "ended_at": "2026-10-30T12:10:00Z"
  },
  "summary": {
    "files_discovered": 300,
    "files_selected": 300,
    "files_processed": 300,
    "files_written": 292,
    "files_with_no_target_chapters": 5,
    "files_with_warnings": 18,
    "files_failed": 3,
    "c4_present": 287,
    "c5_present": 285,
    "c6_present": 260
  }
}
```
## 5.5 Log output

Default log file:
```text
corpus/02_enade_clean/enade_clean_up.log
```
The log should be append-only.

---

## 6. Processing Modes

## 6.1 `local` mode

Local mode performs:

1. source reading;
2. Unicode/control-character normalization;
3. chapter heading detection;
4. chapter-span extraction;
5. deterministic clean-up;
6. validation;
7. output writing.

It does not call an LLM.

This should be the default mode.

Example:
```shell
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output-dir corpus/02_enade_clean \
  --mode local
```
## 6.2 `llm` mode

LLM mode performs:

1. source reading;
2. local chapter extraction;
3. deterministic pre-clean-up;
4. LLM denoising of extracted chapter text only;
5. JSON response validation;
6. output writing.

The LLM must receive only extracted target chapter spans when local extraction succeeds.

Example:
```shell
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output-dir corpus/02_enade_clean \
  --mode llm \
  --prompt denoising_prompts/denoising_v1.md \
  --model gpt-6-luna \
  --max-output-tokens 10000 \
  --workers 10 \
  --resume \
  --max-retries 5
```
## 6.3 `diagnose-only` mode

Diagnose-only mode performs no output cleaning. It reports:

- source file size;
- line count;
- suspected encoding corruption;
- detected heading candidates;
- detected target chapters;
- likely chapter spans;
- likely page-number lines;
- warnings.

Example:
```shell
python enade_clean_up.py \
  --mode diagnose-only \
  --only-filename enade_2009_admin.txt
```
---

## 7. Heading Detection

## 7.1 Heading candidate detection

The programme should identify heading candidates using multiple signals:

- line is short;
- line is mostly uppercase;
- line begins with `Capítulo`;
- line begins with a chapter-like number, e.g. `4`, `4.1`, `5.3`;
- line matches known target title variants after normalization;
- line is followed by body text or lower-level section headings;
- line appears in both summary and body, but body occurrence should be preferred.

Examples:
```text
Capítulo 4
Percepção sobre a Prova

4 Percepção sobre a Prova

4.1 Grau de dificuldade da prova

CAPÍTULO 5 DISTRIBUIÇÃO DE CONCEITOS
```
## 7.2 Avoid extracting from the table of contents

The programme must avoid treating table-of-contents entries as chapter starts.

Signals that a heading candidate is probably in the table of contents:

- it appears before the report presentation or before the first body chapter;
- it contains dotted leaders;
- it ends with a page number;
- many nearby lines are short and alternate between title and page number;
- it appears inside a block headed `SUMÁRIO`.

Example table-of-contents line:
```text
4 Percepção sobre a Prova 66
```
The programme should record TOC matches for diagnostics but not use them as extraction starts unless no body heading can be found.

## 7.3 Body heading detection

The programme should prefer body headings that occur after:
```text
Apresentação
```
or after the first real chapter start.

It should identify chapter start lines such as:
```text
Capítulo 3
Análise Técnica da Prova
```
and combined heading lines such as:
```text
CAPÍTULO 3 PERCEPÇÃO DA PROVA
```
## 7.4 Corrupted headings

Some reports contain corrupted uppercase heading text from PDF font extraction.

The programme should not attempt broad automatic decoding of corrupted text in v1.

It should detect and warn when headings or TOC lines contain high proportions of suspicious characters, such as:
```text
         Ǥ ͳ ʹ ͵
```
Suggested warning:
```text
possible_pdf_font_encoding_corruption
```
If title detection fails because of corrupted headings, the file should be marked as `warning` or `needs_review`, not silently treated as clean.

---

## 8. Chapter-span Extraction

## 8.1 Span start

A target chapter span begins at the detected body heading matching one of the target title variants.

The span should include:

- the chapter heading line;
- following subtitle lines, if any;
- all content until the next same-level chapter heading.

## 8.2 Span end

A target chapter span ends immediately before the next same-level chapter heading.

Examples of same-level chapter headings:
```text
Capítulo 5
Distribuição dos Conceitos

Capítulo 6
Características dos Estudantes

CAPÍTULO 4 DISTRIBUIÇÃO DE CONCEITOS

5 Distribuição dos Conceitos
```
The end should not be triggered by lower-level headings such as:
```text
4.1 Grau de dificuldade da prova
5.2 Conceitos por Categoria Administrativa
6.3.1 Componente de Formação Geral
```
## 8.3 Multiple occurrences

If a target title appears more than once, the programme should:

1. ignore occurrences inside the table of contents;
2. prefer the first body chapter occurrence;
3. warn if multiple body-level target chapter occurrences are found.

Suggested warning:
```text
multiple_body_target_heading_candidates
```
## 8.4 Order of output chapters

The Markdown output should preserve the order in which target chapters appear in the source report.

This means the output order may be:
```text
c6, c4, c5
```
for older layouts, or:
```text
c4, c5, c6
```
for other layouts.

The JSON metadata should always identify the internal labels.

---

## 9. Local Clean-up Rules

## 9.1 Design principle

Clean-up must be conservative.

The programme should remove obvious extraction artefacts without rewriting content.

It must not:

- summarise;
- paraphrase;
- translate;
- modernise spelling;
- silently repair uncertain OCR errors;
- remove substantive content;
- reorder paragraphs;
- remove tables because they are repetitive.

## 9.2 Unicode normalization

The programme should normalize or remove:

- null bytes;
- form-feed characters;
- carriage returns;
- repeated non-breaking spaces;
- unusual invisible control characters;
- trailing whitespace.

Suggested replacements:
```text
\r\n -> \n
\r -> \n
\t -> space
non-breaking space -> normal space
form feed -> blank line or removed marker
```
## 9.3 Page-number removal

The programme may remove isolated page-number lines.

Safe rule:

- remove a line if it contains only digits or roman numerals;
- do not remove numeric lines inside likely table blocks;
- count removals in metadata.

Examples removable outside tables:
```text
66
117
```
## 9.4 Header/footer removal

The programme may remove repeated headers and footers such as:
```text
Relatório Síntese de Área – ENADE/2023
Fonte: MEC/INEP/DAES – ENADE/2009
```
However, `Fonte:` lines can be meaningful table-source lines. Therefore:

- do not remove all `Fonte:` lines by default;
- remove only high-frequency repeated page headers by default;
- remove table source lines only in aggressive mode, if ever.

## 9.5 Blank-line collapse

Collapse excessive blank lines.

Default:

- three or more consecutive blank lines become two blank lines.

## 9.6 Paragraph joining

The programme should join broken wrapped paragraph lines when safe.

Example input:
```text
O presente relatório tem como objetivo apresentar de forma sintética os resultados do
Exame Nacional de Desempenho dos Estudantes ENADE/2009 na área de
ADMINISTRAÇÃO.
```
Example output:
```text
O presente relatório tem como objetivo apresentar de forma sintética os resultados do Exame Nacional de Desempenho dos Estudantes ENADE/2009 na área de ADMINISTRAÇÃO.
```
Do not join lines that are likely:

- headings;
- table rows;
- bullet items;
- numbered section headings;
- figure captions;
- table captions;
- source lines;
- short labels;
- formulas.

## 9.7 Hyphenation repair

The programme should support line-break hyphenation repair.

Example:
```text
desvio-
padrão
```
may become:
```text
desvio-padrão
```
or, when clearly a word split:
```text
socio-
econômico
```
may become:
```text
socioeconômico
```
This must be conservative and counted in metadata.

Suggested option:
```text
--fix-hyphenation
```
enabled by default.

## 9.8 Table preservation

The programme should detect likely table-like blocks and avoid paragraph joining inside them.

Signals of table-like lines:

- multiple numeric columns;
- many percentages;
- repeated spacing;
- words such as `Tabela`, `Quadro`, `Gráfico`, `Fonte`;
- short repeated row labels;
- many lines with similar structure.

Inside table-like blocks:

- preserve line breaks;
- avoid aggressive whitespace normalization;
- do not remove isolated numeric lines unless clearly page numbers outside the table.

---

## 10. LLM Denoising Mode

## 10.1 Purpose

LLM denoising is optional and should operate only after local chapter extraction.

The LLM should receive candidate chapter text, not the whole report, unless explicitly requested by an override option.

## 10.2 Prompt

Default prompt:
```text
denoising_prompts/denoising_v1.md
```
The prompt must instruct the LLM to:

- preserve wording;
- preserve order;
- preserve headings;
- preserve tables;
- avoid summarisation;
- avoid paraphrasing;
- return valid JSON if JSON output is requested.

## 10.3 LLM response schema

When using the existing denoising prompt, the LLM response should be a single JSON object:
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
The programme must validate this response before accepting it.

## 10.4 Invalid LLM responses

An LLM response is invalid if:

- it is not valid JSON;
- it lacks `chapters`;
- it lacks `metadata`;
- any of `c4_present`, `c5_present`, `c6_present` is missing;
- `chapters` is empty while local extraction found non-empty target chapters, unless explicitly allowed;
- output appears truncated;
- output contains refusal text;
- output contains Markdown fences around the JSON object.

Invalid responses should trigger retries up to `--max-retries`.

## 10.5 Output-token risk

`--max-output-tokens 10000` may be insufficient for very large extracted chapter spans. The programme should support chunking in LLM mode.

Chunking should happen after local extraction and before LLM submission.

Recommended chunking logic:

- split by target chapter first;
- if a chapter is still too large, split by section headings;
- avoid splitting inside tables where possible;
- reassemble chunks in source order;
- validate that all chunks are present.

---

## 11. Command-line Interface

## 11.1 Default command
```shell
python enade_clean_up.py
```
Default behavior:

- read from `corpus/enade_dataset.ndjson` if present;
- otherwise walk `corpus/01_enade_txt`;
- write to `corpus/02_enade_clean`;
- run in `local` mode;
- skip existing outputs unless `--overwrite`, `--resume`, or `--reprocess` is used.

## 11.2 Arguments

### Input manifest
```shell
--manifest PATH
```
Default:
```text
corpus/enade_dataset.ndjson
```
### Input root
```shell
--input-root PATH
```
Default:
```text
corpus/01_enade_txt
```
### Output directory
```shell
--output-dir PATH
```
Default:
```text
corpus/02_enade_clean
```
### Mode
```shell
--mode local|llm|diagnose-only
```
Default:
```text
local
```
### Prompt
```shell
--prompt PATH
```
Required only for `--mode llm`.

Default:
```text
denoising_prompts/denoising_v1.md
```
### Model
```shell
--model MODEL_NAME
```
Required only for `--mode llm`.

Example:
```text
gpt-6-luna
```
### Max output tokens
```shell
--max-output-tokens N
```
Default:
```text
10000
```
### Workers
```shell
--workers N
```
Default:
```text
1
```
Used for LLM calls and optionally for local file processing.

### Limit
```shell
--limit N
```
Process only the first `N` selected files.

### Only filename
```shell
--only-filename FILENAME
```
Process only files whose basename matches the provided filename.

Example:
```shell
python enade_clean_up.py \
  --only-filename enade_2009_admin.txt \
  --mode local \
  --overwrite
```
### Dry run
```shell
--dry-run
```
Perform discovery, heading detection, span extraction diagnostics, and output planning without writing cleaned report outputs.

### Resume
```shell
--resume
```
Skip files that already have successful output JSON records.

### Reprocess
```shell
--reprocess
```
Reprocess selected files even if successful output already exists.

### Overwrite
```shell
--overwrite
```
Allow overwriting existing per-file outputs.

### Write empty
```shell
--write-empty
```
Write empty Markdown and JSON records even when no target chapters are found.

### Fix hyphenation
```shell
--fix-hyphenation
```
Enable line-break hyphenation repair. This should be enabled by default.

### No fix hyphenation
```shell
--no-fix-hyphenation
```
Disable line-break hyphenation repair.

### Aggressive cleanup
```shell
--cleanup-level conservative|aggressive
```
Default:
```text
conservative
```
### Strict mode
```shell
--strict
```
Exit non-zero if any selected file fails or no target chapters are found.

---

## 12. Example Commands

## 12.1 Local clean-up for all files
```shell
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output-dir corpus/02_enade_clean \
  --mode local
```
## 12.2 Dry run
```shell
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output-dir corpus/02_enade_clean \
  --mode local \
  --dry-run
```
## 12.3 Process one file
```shell
python enade_clean_up.py \
  --only-filename enade_2009_admin.txt \
  --mode local \
  --overwrite
```
## 12.4 Diagnose one large file
```shell
python enade_clean_up.py \
  --only-filename enade_2021_ci_bio.txt \
  --mode diagnose-only
```
## 12.5 LLM denoising after local extraction
```shell
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output-dir corpus/02_enade_clean \
  --mode llm \
  --prompt denoising_prompts/denoising_v1.md \
  --model gpt-6-luna \
  --max-output-tokens 10000 \
  --workers 10 \
  --resume \
  --max-retries 5
```
---

## 13. Validation Rules

## 13.1 Per-file validation

For each processed file, validate:

- source file exists;
- source file is readable;
- extracted chapter spans are non-overlapping;
- extracted chapter spans are in source order;
- output Markdown is valid UTF-8;
- JSON metadata is valid JSON;
- chapter presence flags match extracted chapters;
- LLM output, if used, is valid and not truncated.

## 13.2 Chapter validation

For each target label:

- if chapter is found, `*_present` must be `true`;
- if chapter is not found, `*_present` must be `false`;
- if chapter title is ambiguous, add a warning;
- if only TOC entries are found, do not mark the chapter present unless body extraction succeeds.

## 13.3 Truncation validation

The programme should warn about possible truncation if:

- LLM output ends abruptly;
- JSON response is incomplete;
- output length is suspiciously near token limit;
- local extracted text is much larger than accepted output;
- final Markdown lacks expected later chapters.

Suggested warning:
```text
possible_llm_output_truncation
```
---

## 14. Warning Types

The programme should support warning codes such as:
```text
no_target_chapters_found
toc_only_target_headings_found
multiple_body_target_heading_candidates
possible_pdf_font_encoding_corruption
high_control_character_ratio
high_replacement_character_ratio
chapter_span_unusually_short
chapter_span_unusually_long
possible_table_damage
possible_llm_output_truncation
llm_response_invalid_json
llm_response_missing_metadata
llm_response_missing_chapters
```
Warnings should be stored in per-file JSON and summarized in the run summary.

---

## 15. Error Handling

## 15.1 Configuration errors

Configuration errors should stop the programme before processing.

Examples:

- manifest does not exist;
- input root does not exist;
- prompt file missing in LLM mode;
- invalid mode;
- invalid numeric argument;
- output exists and neither `--overwrite`, `--resume`, nor `--reprocess` is set.

Exit code:
```text
2
```
## 15.2 File-level errors

File-level errors should be recorded and should not necessarily stop the run unless `--strict` is enabled.

Examples:

- unreadable source file;
- decoding failure;
- output write failure;
- extraction logic failure;
- repeated invalid LLM responses.

Default behavior:

- log error;
- write JSON error record if possible;
- continue to next file;
- exit `1` at end if any file failed.

## 15.3 Keyboard interruption

On keyboard interruption:

- stop scheduling new work;
- allow active safe writes to finish if possible;
- write partial manifest and summary;
- mark run as interrupted;
- exit `130`.

---

## 16. Exit Codes

| Exit code | Meaning |
|---:|---|
| `0` | Completed successfully |
| `1` | Completed with file-level failures or warnings treated as failures |
| `2` | Configuration or validation error before processing |
| `130` | Interrupted by user |

---

## 17. Suggested Implementation Architecture

## 17.1 Suggested constants
```python
TOOL_NAME = "enade_clean_up.py"
TOOL_VERSION = "v1"

DEFAULT_INPUT_ROOT = "corpus/01_enade_txt"
DEFAULT_MANIFEST = "corpus/enade_dataset.ndjson"
DEFAULT_OUTPUT_DIR = "corpus/02_enade_clean"
DEFAULT_PROMPT = "denoising_prompts/denoising_v1.md"

TARGET_CHAPTERS = {
    "c4": [
        "percepcao sobre a prova",
        "percepcao da prova",
    ],
    "c5": [
        "distribuicao dos conceitos",
        "distribuicao de conceitos",
    ],
    "c6": [
        "analise tecnica da prova",
    ],
}
```
## 17.2 Suggested functions
```python
def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
```

```python
def setup_logging(log_path: Path) -> logging.Logger:
    """Set up console and append-only file logging."""
```

```python
def load_manifest(path: Path) -> list[dict]:
    """Load an NDJSON manifest."""
```

```python
def discover_input_files(args: argparse.Namespace) -> list[Path]:
    """Discover source TXT files from manifest or input-root walking."""
```

```python
def read_text_file(path: Path) -> str:
    """Read a source text file safely as UTF-8."""
```

```python
def normalize_for_matching(text: str) -> str:
    """Normalize text for title and heading matching."""
```

```python
def detect_heading_candidates(lines: list[str]) -> list[dict]:
    """Detect possible chapter and section headings."""
```

```python
def detect_target_chapters(lines: list[str]) -> list[dict]:
    """Detect target chapter starts by title, excluding table-of-contents matches."""
```

```python
def extract_chapter_spans(lines: list[str], target_headings: list[dict]) -> list[dict]:
    """Extract target chapter spans from heading positions."""
```

```python
def clean_extracted_text(text: str, options: dict) -> tuple[str, dict, list[str]]:
    """Apply conservative deterministic clean-up rules."""
```

```python
def detect_table_like_block(lines: list[str], index: int) -> bool:
    """Return whether a line appears to be inside a table-like block."""
```

```python
def detect_encoding_warnings(text: str) -> list[str]:
    """Detect suspicious OCR/PDF/font corruption indicators."""
```

```python
def denoise_with_llm(text: str, metadata: dict, args: argparse.Namespace) -> dict:
    """Send extracted text to the configured LLM and validate response."""
```

```python
def write_report_outputs(record: dict, markdown_text: str, args: argparse.Namespace) -> None:
    """Write per-report Markdown and JSON outputs."""
```

```python
def write_run_outputs(records: list[dict], summary: dict, args: argparse.Namespace) -> None:
    """Write run-level manifest and summary files."""
```

```python
def main() -> int:
    """Run the ENADE clean-up pipeline and return an exit code."""
```
---

## 18. Logging Specification

The log should include:

- run start and end;
- run ID;
- command-line arguments;
- input manifest path;
- input root;
- output directory;
- processing mode;
- number of discovered files;
- number of selected files;
- per-file processing start;
- per-file target chapter detection results;
- warnings;
- failures;
- output paths;
- summary counts.

Suggested log format:
```text
[YYYY-MM-DD HH:MM:SS] LEVEL message
```
Example:
```text
[2026-10-30 12:00:00] INFO Starting enade_clean_up.py run_id=20261030T120000Z mode=local
```
---

## 19. Development Notes

## 19.1 Initial implementation scope

The first version should prioritize:

- robust local chapter detection;
- conservative clean-up;
- high-quality metadata and warnings;
- clear dry-run diagnostics;
- one-file testing;
- resumability;
- safe output writing.

LLM mode may be implemented after local extraction and metadata are stable.

## 19.2 Out of scope for v1

The following are out of scope for v1:

- repairing corrupted PDF font encodings automatically;
- reconstructing missing text;
- redrawing tables;
- correcting spelling or grammar;
- translating;
- summarising;
- replacing the original raw corpus;
- producing final statistical analysis.

## 19.3 Future extensions

Potential future enhancements:

- year-specific heading profiles;
- validated repair maps for known corrupted heading encodings;
- chapter extraction confidence scores;
- side-by-side source/cleaned QA reports;
- HTML output for table inspection;
- integration with downstream corpus tagging.

---

## 20. Acceptance Criteria

The programme is considered complete for v1 when the following are true:

1. Running:
```shell
python enade_clean_up.py --mode local
```
processes ENADE `.txt` reports from the default corpus input.

2. Raw files in `corpus/01_enade_txt` are never modified.

3. Output is written under:
```text
corpus/02_enade_clean
```
4. Relative year subdirectories are preserved.

5. The programme detects target chapters by title, not by chapter number.

6. The programme correctly handles reports where:
```text
Análise Técnica da Prova
```
is Chapter 3 rather than Chapter 6.

7. The programme correctly handles reports where:
```text
Percepção da Prova
```
or:
```text
Percepção sobre a Prova
```
appears under varying chapter numbers.

8. The programme extracts only target chapter spans.

9. The programme avoids using table-of-contents entries as body chapter starts.

10. The programme writes one Markdown file per successful report.

11. The programme writes one JSON metadata file per processed report.

12. The programme writes a run-level `manifest.ndjson`.

13. The programme writes `run_summary.json`.

14. The programme writes an append-only log.

15. The programme supports `--dry-run`.

16. The programme supports `--only-filename`.

17. The programme supports `--resume`.

18. The programme supports `--reprocess`.

19. The programme supports `--overwrite`.

20. The programme identifies and reports files with no target chapters.

21. The programme identifies and reports suspicious encoding corruption.

22. The programme preserves tables as plain text as much as possible.

23. The programme preserves headings and section numbers.

24. The programme removes obvious isolated page numbers outside tables.

25. The programme collapses excessive blank lines.

26. The programme repairs simple line wrapping conservatively.

27. The programme repairs simple line-break hyphenation conservatively.

28. The programme exits with code `0` on clean success.

29. The programme exits with code `1` when file-level failures occur.

30. The programme exits with code `2` for configuration errors.

31. The programme exits with code `130` when interrupted.

---

## 21. Pipeline Documentation Update

The project pipeline should add `enade_clean_up.py` before downstream tagging or LLM interpretation.

Suggested replacement for the current ENADE denoising step:
```
markdown
## 1. Clean and extract ENADE report chapters

Run from the project phase directory:

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --input-root corpus/01_enade_txt \
    --output-dir corpus/02_enade_clean \
    --mode local \
    --resume
```


This programme extracts and cleans the ENADE chapters of interest:

- `c4`: `Percepção da Prova` / `Percepção sobre a Prova`
- `c5`: `Distribuição dos Conceitos` / `Distribuição de Conceitos`
- `c6`: `Análise Técnica da Prova`

The programme identifies chapters by title, not by chapter number.

Outputs:

```plain text
corpus/02_enade_clean/<year>/<filename_stem>.md
corpus/02_enade_clean/<year>/<filename_stem>.json
corpus/02_enade_clean/manifest.ndjson
corpus/02_enade_clean/run_summary.json
corpus/02_enade_clean/enade_clean_up.log
```


For a one-file test:

```textmate
python enade_clean_up.py \
    --only-filename enade_2009_admin.txt \
    --mode local \
    --overwrite
```


For diagnosis only:

```textmate
python enade_clean_up.py \
    --only-filename enade_2021_ci_bio.txt \
    --mode diagnose-only
```


Optional LLM denoising mode:

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --input-root corpus/01_enade_txt \
    --output-dir corpus/02_enade_clean \
    --mode llm \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --max-output-tokens 10000 \
    --workers 10 \
    --resume \
    --max-retries 5
```

---

## 22. Summary

`enade_clean_up.py` should be implemented as a conservative, auditable, offline-first ENADE report preprocessor.

Its core responsibility is to:

1. preserve raw source files;
2. identify target chapters by title;
3. extract only the chapters of interest;
4. clean obvious PDF/text-extraction artefacts;
5. preserve substantive content;
6. write Markdown text plus JSON provenance;
7. warn about suspicious files requiring manual review;
8. optionally support LLM denoising on extracted chapter spans only.

The canonical cleaned corpus stage should be:
```text
corpus/02_enade_clean
```