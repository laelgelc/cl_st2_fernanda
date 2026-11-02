# Development Specification: `enade_clean_up.py`

## 1. Programme purpose

`enade_clean_up.py` is a deterministic, rule-based DataFrame enrichment programme for the ENADE corpus preprocessing pipeline.

The programme reads the page-level ENADE PDF-pages manifest:
```text
corpus/enade_pdf_pages_dataset.ndjson
```
and writes an enriched page-level dataset that identifies whether each page belongs to one of the selected ENADE chapters of interest:

| Internal label | Chapter title variants                                    |
|----------------|-----------------------------------------------------------|
| `c4`           | `percepção sobre a prova`; `percepção da prova`           |
| `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6`           | `análise técnica da prova`                                |

The programme must **not** extract, concatenate, denoise, rewrite, reorganise, or modify page text files. Its scope is limited to enriching the input manifest/DataFrame with chapter-of-interest metadata.

The enriched dataset must be saved as:
```text
corpus/enade_chapters_dataset.ndjson
corpus/enade_chapters_dataset.tsv
corpus/enade_chapters_dataset.xlsx
```
The NDJSON file is the canonical machine-readable output. TSV and XLSX are review formats.

---

## 2. Research context

The project studies Brazilian ENADE reports for corpus-linguistics research. The source ENADE PDFs have been split into page-level PDF and text files. Each row in the input manifest represents one PDF page and includes the path to its extracted text file.

The aim of this stage is to identify, at page level, which pages belong to selected report chapters so that later pipeline stages can:

1. reorganise or copy text-page files according to `chapter_of_interest`;
2. submit only selected pages or small page batches to `llm_denoise.py`;
3. avoid sending whole reports or overly large chapters to an LLM;
4. preserve deterministic, inspectable chapter-selection metadata before denoising.

This programme therefore performs **structural page classification**, not content denoising.

---

## 3. Core design principles

### 3.1 DataFrame enrichment only

`enade_clean_up.py` must only enrich the page-level dataset.

It must not:

- extract chapter text spans;
- concatenate page text files;
- move or copy page text files;
- denoise page text;
- call an LLM;
- alter source `.txt` files;
- alter source `.pdf` files;
- overwrite the input manifest.

### 3.2 Deterministic processing

The programme must be rule-based and reproducible. Given the same input files and configuration, it should produce the same enriched dataset.

### 3.3 Title-based chapter detection

The programme must identify chapters by title variants, not by chapter number.

Chapter numbers vary across ENADE years and disciplines. Therefore, a page must not be assigned to `c4`, `c5`, or `c6` merely because it contains `CAPÍTULO 4`, `CAPÍTULO 5`, or `CAPÍTULO 6`.

### 3.4 Conservative classification

The programme should prefer false negatives over false positives.

If a boundary is ambiguous, conflicting, or unsafe, the programme should mark the affected page/document with an audit status rather than guessing.

### 3.5 Detection normalisation only

Matching may be:

- case-insensitive;
- accent-insensitive;
- whitespace-normalised;
- tolerant of simple punctuation and dash variants.

However, this normalisation is only for detection. Source text files must remain untouched.

### 3.6 Page-level state propagation

The programme must classify chapter ranges, not only heading pages.

Once a target chapter heading is confidently detected, the chapter label should propagate forward page by page within the same PDF until another relevant boundary is detected.

---

## 4. Input manifest

### 4.1 Default input path

The default input manifest is:
```text
corpus/enade_pdf_pages_dataset.ndjson
```
The input file is expected to be NDJSON: one JSON object per line.

### 4.2 Input DataFrame name

After loading the manifest, the programme should store it as:
```python
enade_df_pdf_pages
```
### 4.3 Expected input columns

The input manifest should contain at least:

| Column              | Required | Purpose                                      |
|---------------------|---------:|----------------------------------------------|
| `filename`          | Yes      | Normalised source PDF filename               |
| `filepath_ori`      | Yes      | Original source PDF path                     |
| `page_number`       | Yes      | Page number within the source PDF            |
| `page_filename`     | Yes      | Page-level PDF filename                      |
| `page_filepath`     | Yes      | Page-level PDF path                          |
| `page_filename_txt` | Yes      | Page-level extracted text filename           |
| `page_filepath_txt` | Yes      | Page-level extracted text path               |

Example row shape:
```json
{
  "filename": "enade_2009_admin.pdf",
  "filepath_ori": "corpus/00_sources/enade_raw/2009/ENADE_2009_ADMINISTRAÇÃO.pdf",
  "page_number": 77,
  "page_filename": "enade_2009_admin_page_77.pdf",
  "page_filepath": "corpus/01_enade_pdf_pages/enade_2009_admin/enade_2009_admin_page_77.pdf",
  "page_filename_txt": "enade_2009_admin_page_77.txt",
  "page_filepath_txt": "corpus/01_enade_pdf_pages/enade_2009_admin/enade_2009_admin_page_77.txt"
}
```
### 4.4 Input immutability

The programme must treat the input manifest and all page text files as immutable.

---

## 5. Output dataset

### 5.1 Output basename

The default output basename is:
```text
corpus/enade_chapters_dataset
```
The programme must write:
```text
corpus/enade_chapters_dataset.ndjson
corpus/enade_chapters_dataset.tsv
corpus/enade_chapters_dataset.xlsx
```
### 5.2 Output preservation

The output dataset must preserve all original input columns and append enrichment columns.

### 5.3 Canonical output format

The NDJSON output is canonical. TSV and XLSX are review copies derived from the same enriched DataFrame.

### 5.4 Row order

The output dataset should preserve the original manifest row order unless explicit filtering or sorting options are supplied.

For internal processing, each document group should be sorted by `page_number`, but final output should be restored to input order.

---

## 6. Required enriched columns

The programme must add at least the following columns.

### 6.1 Page-level chapter classification columns

| Column                           | Type         | Meaning                                                       |
|----------------------------------|--------------|---------------------------------------------------------------|
| `chapter_of_interest`            | string/null  | Page label: `c4`, `c5`, `c6`, or `na`                         |
| `chapter_of_interest_title`      | string/null  | Canonical title associated with the detected label            |
| `chapter_of_interest_variant`    | string/null  | Configured title variant that triggered the chapter detection |
| `chapter_of_interest_status`     | string       | Page-level classification status                              |
| `chapter_of_interest_confidence` | string/null  | `high`, `medium`, `low`, or null                              |
| `page_boundary_role`             | string       | Page’s role in the inferred range                             |
| `chapter_start_page`             | integer/null | Start page of the assigned chapter range                      |
| `chapter_end_page`               | integer/null | End page of the assigned chapter range                        |
| `chapter_boundary_method`        | string/null  | Method used to infer page classification                      |
| `chapter_detection_notes`        | string/null  | Human-readable notes or warnings                              |

### 6.2 Recommended status values

For `chapter_of_interest_status`:

| Status                        | Meaning                                                |
|-------------------------------|--------------------------------------------------------|
| `in_chapter_of_interest`      | Page is inside a confidently detected target chapter   |
| `outside_chapter_of_interest` | Page is confidently outside selected chapters          |
| `candidate_boundary`          | Page contains a possible boundary needing inspection   |
| `ambiguous`                   | Page/document has conflicting or uncertain boundaries  |
| `unsafe`                      | Classification is not safe enough for automatic use    |
| `not_found`                   | No selected chapter was found for this document        |
| `text_missing`                | Page text file is missing                              |
| `text_unreadable`             | Page text file could not be read                       |

### 6.3 Recommended page boundary roles

For `page_boundary_role`:

| Role               | Meaning                                                   |
|--------------------|-----------------------------------------------------------|
| `chapter_start`    | Page where a target chapter starts                        |
| `chapter_middle`   | Page inside an active target chapter                      |
| `chapter_end`      | Last page assigned to a target chapter range              |
| `boundary_overlap` | Page contains a boundary that may overlap chapter content |
| `outside`          | Page is outside target chapters                           |
| `unknown`          | Boundary role could not be safely determined              |

### 6.4 Document-level repeated flags

The programme should add the following document-level fields repeated on each page row for convenience:

| Column             | Type         | Meaning                                   |
|--------------------|--------------|-------------------------------------------|
| `c4_present`       | Boolean      | Whether `c4` was found in the document    |
| `c4_status`        | string       | Document-level `c4` detection status      |
| `c4_start_page`    | integer/null | First page of detected `c4` range         |
| `c4_end_page`      | integer/null | Last page of detected `c4` range          |
| `c4_title_variant` | string/null  | Title variant that triggered `c4`         |
| `c5_present`       | Boolean      | Whether `c5` was found in the document    |
| `c5_status`        | string       | Document-level `c5` detection status      |
| `c5_start_page`    | integer/null | First page of detected `c5` range         |
| `c5_end_page`      | integer/null | Last page of detected `c5` range          |
| `c5_title_variant` | string/null  | Title variant that triggered `c5`         |
| `c6_present`       | Boolean      | Whether `c6` was found in the document    |
| `c6_status`        | string       | Document-level `c6` detection status      |
| `c6_start_page`    | integer/null | First page of detected `c6` range         |
| `c6_end_page`      | integer/null | Last page of detected `c6` range          |
| `c6_title_variant` | string/null  | Title variant that triggered `c6`         |

Recommended document-level status values:

| Status      | Meaning                                                   |
|-------------|-----------------------------------------------------------|
| `found`     | Safe chapter range detected                               |
| `not_found` | No reliable chapter heading found                         |
| `ambiguous` | Multiple plausible starts or conflicting boundaries       |
| `unsafe`    | Boundary logic is unreliable                              |
| `partial`   | Start found, but end/range is only partially recoverable  |

---

## 7. Chapter labels and accepted title variants

The internal target-title mapping should be:
```python
TARGET_TITLES = {
    "c4": [
        "percepção sobre a prova",
        "percepção da prova",
    ],
    "c5": [
        "distribuição dos conceitos",
        "distribuição de conceitos",
    ],
    "c6": [
        "análise técnica da prova",
    ],
}
```
For matching, the programme should normalise these to accentless lowercase forms, for example:
```python
NORMALISED_TARGET_TITLES = {
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
The canonical title for each label should be:

| Label | Canonical title                  |
|-------|----------------------------------|
| `c4`  | `percepção da prova`             |
| `c5`  | `distribuição dos conceitos`     |
| `c6`  | `análise técnica da prova`       |

---

## 8. Boundary detection strategy

### 8.1 Header-zone inspection

For each page, the programme should read only the first lines of the page text file by default:
```text
first 10 lines
```
The default should be configurable through:
```text
--header-lines 10
```
The programme should inspect both:

1. individual header lines;
2. a joined header block made from the first `N` lines.

This is necessary because extracted headings may be split across lines, for example:
```text
CAPÍTULO 4 –
PERCEPÇÃO DA PROVA
```
### 8.2 Page grouping

The programme must process pages grouped by `filename`.

Within each group:

1. sort rows by `page_number`;
2. read each page’s header zone;
3. detect boundaries;
4. propagate current state;
5. assign page-level metadata;
6. derive document-level chapter-range fields.

### 8.3 State machine

The core logic should be a page-level state machine:
```python
current_label = "na"

for page in pages_sorted_by_page_number:
    boundary = detect_boundary(page_header)

    if boundary.kind == "stop_section":
        current_label = "na"

    elif boundary.kind == "target_chapter":
        current_label = boundary.label

    elif boundary.kind == "other_chapter":
        current_label = "na"

    page.chapter_of_interest = current_label
```
### 8.4 Boundary priority

When several boundary signals are detected on the same page, use this priority order:

1. table-of-contents exclusion;
2. stop section;
3. target chapter start;
4. other chapter start;
5. no boundary.

This priority may be adjusted if empirical inspection shows a better ordering, but it must be documented in code comments and logs.

### 8.5 Target chapter start

A page should be considered a target chapter start when:

- a target title variant appears in the header zone;
- the match is not table-of-contents-like;
- the match appears near a chapter marker or as a standalone heading;
- the confidence is `high` or `medium`.

Examples to accept:
```text
Capítulo 4
Percepção sobre a Prova
```

```text
CAPÍTULO 4 –
PERCEPÇÃO DA PROVA
```

```text
Relatório Síntese de Área – ENADE/2023
CAPÍTULO 3
PERCEPÇÃO DA PROVA
```
### 8.6 Other chapter boundary

If a page starts another top-level `CAPÍTULO N` whose title is not one of the target title variants, it should reset the current state to `na`.

This prevents pages from unrelated chapters continuing to be labelled as a previous chapter of interest.

### 8.7 Stop sections

The programme should recognise strong stop-section headings in the first header lines.

Default stop-section titles:
```python
STOP_SECTION_TITLES = [
    "anexo",
    "anexos",
    "referência",
    "referências",
    "bibliografia",
    "apêndice",
    "apêndices",
    "glossário",
]
```
Normalised forms should also be used:
```python
NORMALISED_STOP_SECTION_TITLES = [
    "anexo",
    "anexos",
    "referencia",
    "referencias",
    "bibliografia",
    "apendice",
    "apendices",
    "glossario",
]
```
A stop section should reset `current_label` to `na`.

The programme should only treat these as stops when they appear as headings, not when mentioned inside prose.

Accept as stop:
```text
ANEXO II
Tabulação das respostas
```
Do not treat as stop:
```text
O questionário de percepção da prova encontra-se ao final do Anexo VII...
```
---

## 9. Table-of-contents false-positive prevention

Table-of-contents pages often contain chapter titles but should not start chapter ranges.

The programme must reject title matches that are likely table-of-contents entries.

### 9.1 TOC evidence

Treat a line or header block as TOC-like if it contains one or more of:

- dot leaders such as `.....`;
- repeated unusual leader characters;
- a chapter title followed by many dots and a page number;
- several consecutive chapter entries;
- a high density of short title-like lines;
- a heading such as `SUMÁRIO`, `ÍNDICE`, or `SUMARIO`.

### 9.2 TOC handling

If a target title appears only in a TOC-like context:

- do not change `current_label`;
- set `chapter_boundary_method` to something like `toc_ignored` if useful;
- optionally record `candidate_boundary` or a note in `chapter_detection_notes`.

---

## 10. Text normalisation for detection

The programme should implement a conservative normalisation function used only for matching:

1. lowercase text;
2. strip accents using Unicode normalisation;
3. normalise dash characters to spaces or hyphens;
4. collapse whitespace;
5. remove excessive repeated dot leaders for TOC detection;
6. preserve alphanumeric content.

Example:
```text
CAPÍTULO 4 – PERCEPÇÃO DA PROVA
```
normalises to:
```text
capitulo 4 percepcao da prova
```
Recommended helper function:
```python
def normalise_for_matching(text: str) -> str:
    ...
```
The original text file content must not be rewritten.

---

## 11. Confidence model

Boundary detection should assign a confidence level.

| Confidence | Condition                                                              |
|------------|------------------------------------------------------------------------|
| `high`     | `CAPÍTULO` marker and target title appear in header zone, not TOC-like |
| `medium`   | Target title appears as a standalone heading in header zone            |
| `low`      | Target phrase appears but context is ambiguous or prose-like           |

Only `high` and `medium` target detections should change the chapter state.

`low` detections should be recorded for audit but should not set `chapter_of_interest`.

---

## 12. Page-range assignment

### 12.1 Basic range logic

For each document:

- target chapter range starts at the page where the target chapter heading is detected;
- range continues until the page before the next peer top-level chapter boundary or stop section;
- all pages inside the range receive the same `chapter_of_interest` label.

### 12.2 Boundary-overlap pages

Some chapters may start or end mid-page.

Default rule:

- if a page contains the start heading of a target chapter, include that page in the target chapter;
- if a page contains the start heading of a non-target chapter after a target range, mark that page as outside by default;
- if a page appears to contain both ending target content and a new boundary, mark `page_boundary_role = "boundary_overlap"` and record a note.

This behaviour may be configurable in a future version, but the first version should use the conservative default.

### 12.3 Blank pages inside active ranges

If a page text file is empty or nearly empty while a target chapter is already active, the default behaviour should be to keep the current label, because blank pages, figure pages, or table-only pages may occur inside a chapter.

The row should receive a note such as:
```text
empty_text_inside_active_chapter
```
If an empty page occurs when no target chapter is active, assign:
```text
chapter_of_interest = "na"
```
---

## 13. Missing or unreadable page text

### 13.1 Missing text file

If `page_filepath_txt` does not exist:

- set `chapter_of_interest = "na"` unless a stricter future mode supports carrying state through missing pages;
- set `chapter_of_interest_status = "text_missing"`;
- record a note in `chapter_detection_notes`;
- continue processing.

### 13.2 Unreadable text file

If the page text file exists but cannot be read:

- set `chapter_of_interest = "na"`;
- set `chapter_of_interest_status = "text_unreadable"`;
- record the read error in audit notes;
- continue processing.

### 13.3 Encoding

Text files should be read as UTF-8 with replacement:
```python
encoding="utf-8"
errors="replace"
```
---

## 14. Command-line interface

### 14.1 Basic command

Run from the project phase directory:
```shell
python enade_clean_up.py \
    --manifest corpus/enade_pdf_pages_dataset.ndjson \
    --output-basename corpus/enade_chapters_dataset
```
### 14.2 Dry run
```shell
python enade_clean_up.py \
    --manifest corpus/enade_pdf_pages_dataset.ndjson \
    --output-basename corpus/enade_chapters_dataset \
    --dry-run
```
### 14.3 Process a limited number of documents
```shell
python enade_clean_up.py \
    --manifest corpus/enade_pdf_pages_dataset.ndjson \
    --output-basename corpus/enade_chapters_dataset \
    --limit-documents 10
```
### 14.4 Process one PDF
```shell
python enade_clean_up.py \
    --manifest corpus/enade_pdf_pages_dataset.ndjson \
    --output-basename corpus/enade_chapters_dataset \
    --only-filename enade_2009_admin.pdf
```
---

## 15. CLI options

| Option                       | Default                                  | Description                                      |
|------------------------------|------------------------------------------|--------------------------------------------------|
| `--manifest PATH`            | `corpus/enade_pdf_pages_dataset.ndjson`  | Input page-level NDJSON manifest                 |
| `--output-basename PATH`     | `corpus/enade_chapters_dataset`          | Output basename without extension                |
| `--header-lines N`           | `10`                                     | Number of first lines to inspect per page        |
| `--filename-field FIELD`     | `filename`                               | Document grouping field                          |
| `--page-number-field FIELD`  | `page_number`                            | Page order field                                 |
| `--page-text-field FIELD`    | `page_filepath_txt`                      | Page text path field                             |
| `--only-filename FILENAME`   | `None`                                   | Process one source PDF filename                  |
| `--limit-documents N`        | `None`                                   | Process first `N` documents after filtering      |
| `--dry-run`                  | `False`                                  | Validate and inspect without writing full output |
| `--write-audit`              | `True`                                   | Write audit files                                |
| `--log-file PATH`            | `corpus/enade_clean_up.log`              | Log file path                                    |
| `--reprocess`                | `False`                                  | Overwrite existing outputs                       |

The first implementation may omit `--reprocess` if output files are always overwritten after explicit confirmation or standard run behaviour.

---

## 16. Argument validation

The programme should fail before processing if:

- `--manifest` does not exist;
- `--manifest` is not a file;
- `--output-basename` is empty;
- `--header-lines <= 0`;
- required manifest fields are missing globally;
- `--limit-documents <= 0`, if supplied;
- `--only-filename` is supplied but matches no rows;
- output parent directory cannot be created.

Per-row issues, such as a missing page text file, should be recorded in output metadata rather than causing the whole run to fail.

---

## 17. Audit outputs

In addition to the three enriched datasets, the programme should write audit artefacts.

### 17.1 Recommended audit files
```text
corpus/enade_clean_up_audit_ranges.tsv
corpus/enade_clean_up_audit_boundaries.tsv
corpus/enade_clean_up_summary.json
corpus/enade_clean_up.log
```
### 17.2 Range audit

`enade_clean_up_audit_ranges.tsv` should contain one row per detected chapter range.

Recommended columns:

| Column                | Meaning                                 |
|-----------------------|-----------------------------------------|
| `filename`            | Source PDF filename                     |
| `chapter_of_interest` | `c4`, `c5`, or `c6`                     |
| `start_page`          | First page in range                     |
| `end_page`            | Last page in range                      |
| `page_count`          | Number of pages in range                |
| `title_variant`       | Matched title variant                   |
| `confidence`          | Detection confidence                    |
| `start_match`         | Text snippet or matched normalised form |
| `end_reason`          | Why range ended                         |
| `status`              | `found`, `partial`, `ambiguous`, etc.   |
| `notes`               | Human-readable notes                    |

### 17.3 Boundary audit

`enade_clean_up_audit_boundaries.tsv` should contain one row per detected boundary or candidate boundary.

Recommended columns:

| Column            | Meaning                                                                |
|-------------------|------------------------------------------------------------------------|
| `filename`        | Source PDF filename                                                    |
| `page_number`     | Page number                                                            |
| `boundary_kind`   | `target_chapter`, `other_chapter`, `stop_section`, `toc_ignored`, etc. |
| `label`           | `c4`, `c5`, `c6`, or null                                              |
| `confidence`      | Boundary confidence                                                    |
| `matched_variant` | Matched configured variant                                             |
| `header_sample`   | First lines inspected, truncated if needed                             |
| `notes`           | Human-readable notes                                                   |

### 17.4 Summary JSON

`enade_clean_up_summary.json` should include:
```json
{
  "programme": "enade_clean_up.py",
  "manifest": "corpus/enade_pdf_pages_dataset.ndjson",
  "output_basename": "corpus/enade_chapters_dataset",
  "counts": {
    "input_rows": 0,
    "output_rows": 0,
    "documents_total": 0,
    "documents_processed": 0,
    "pages_c4": 0,
    "pages_c5": 0,
    "pages_c6": 0,
    "pages_na": 0,
    "documents_with_c4": 0,
    "documents_with_c5": 0,
    "documents_with_c6": 0,
    "documents_with_no_target_chapters": 0,
    "missing_text_files": 0,
    "unreadable_text_files": 0,
    "ambiguous_documents": 0,
    "unsafe_documents": 0
  }
}
```
---

## 18. Logging

The programme must log to both console and file.

The log should include:

- programme start and end;
- resolved input manifest path;
- resolved output basename;
- number of input rows;
- number of documents;
- filtering options;
- number of processed documents;
- number of pages per label;
- number of missing/unreadable text files;
- number of detected boundaries;
- number of ambiguous or unsafe cases;
- output paths written;
- fatal errors, if any.

The log should not include full page text. It may include short header samples where useful.

---

## 19. Processing order

Recommended processing order:
```text
1. Parse CLI arguments.
2. Resolve paths.
3. Validate input manifest and output directory.
4. Configure logging.
5. Load NDJSON manifest into enade_df_pdf_pages.
6. Validate required columns.
7. Preserve original row order in an internal column.
8. Apply --only-filename if supplied.
9. Apply --limit-documents if supplied.
10. Initialise enrichment columns with safe defaults.
11. Group rows by filename.
12. For each document:
    a. sort by page_number;
    b. read first N lines from each page text file;
    c. normalise header text for detection;
    d. detect target chapter starts;
    e. detect non-target chapter starts;
    f. detect stop sections;
    g. ignore TOC-like matches;
    h. propagate chapter state;
    i. assign page-level labels and audit metadata;
    j. derive document-level chapter-range metadata.
13. Restore original row order.
14. Write NDJSON, TSV, and XLSX outputs unless dry-run.
15. Write audit files unless disabled.
16. Write summary JSON.
17. Log final counts.
18. Exit with appropriate status.
```
---

## 20. Recommended helper functions

The implementation should be modular.

| Function                           | Responsibility                                           |
|------------------------------------|----------------------------------------------------------|
| `parse_args()`                     | Parse CLI arguments                                      |
| `resolve_path()`                   | Resolve relative and absolute paths                      |
| `setup_logging()`                  | Configure console and file logging                       |
| `load_ndjson_dataframe()`          | Load input NDJSON into a pandas DataFrame                |
| `validate_required_columns()`      | Validate required manifest columns                       |
| `read_first_lines()`               | Read first `N` lines from a page text file               |
| `normalise_for_matching()`         | Normalise text for detection only                        |
| `is_toc_like()`                    | Detect table-of-contents style matches                   |
| `is_heading_like()`                | Detect whether a line/block resembles a heading          |
| `detect_target_chapter()`          | Detect `c4`, `c5`, or `c6` starts                        |
| `detect_stop_section()`            | Detect `ANEXO`, `REFERÊNCIAS`, etc.                      |
| `detect_other_chapter()`           | Detect non-target top-level chapter starts               |
| `detect_boundary()`                | Combine boundary detection logic                         |
| `classify_document_pages()`        | Apply state machine to one document group                |
| `derive_document_flags()`          | Add repeated `c4/c5/c6` document-level fields            |
| `build_range_audit()`              | Build range audit rows                                   |
| `build_boundary_audit()`           | Build boundary audit rows                                |
| `write_outputs()`                  | Write NDJSON, TSV, XLSX                                  |
| `write_summary()`                  | Write summary JSON                                       |
| `main()`                           | Coordinate full programme                                |

---

## 21. Suggested internal data structures

### 21.1 Boundary result

A simple dataclass is recommended:
```python
@dataclass
class BoundaryResult:
    kind: str
    label: str | None = None
    title: str | None = None
    variant: str | None = None
    confidence: str | None = None
    match_text: str | None = None
    notes: str | None = None
```
Possible `kind` values:
```text
target_chapter
other_chapter
stop_section
toc_ignored
candidate
none
```
### 21.2 Chapter range
```python
@dataclass
class ChapterRange:
    label: str
    start_page: int
    end_page: int | None
    title_variant: str | None
    confidence: str | None
    status: str
    end_reason: str | None
    notes: str | None
```
---

## 22. Output writing requirements

### 22.1 NDJSON

Write with UTF-8 encoding and one JSON object per line.

Recommended pandas approach:
```python
df.to_json(
    output_ndjson,
    orient="records",
    lines=True,
    force_ascii=False,
)
```
### 22.2 TSV

Write with UTF-8 encoding and tab separator:
```python
df.to_csv(output_tsv, sep="\t", index=False, encoding="utf-8")
```
### 22.3 XLSX

Write with a stable worksheet name such as:
```text
enade_chapters_dataset
```
If Excel row limits are ever exceeded, the programme should fail clearly or skip XLSX with a warning. For the expected dataset size, XLSX should be acceptable.

### 22.4 Atomic writes

Where feasible, outputs should be written atomically:

1. write to a temporary file in the same directory;
2. close the file;
3. rename to the final path.

This is especially recommended for NDJSON and JSON summary outputs.

---

## 23. Dry-run behaviour

When `--dry-run` is supplied, the programme should:

- validate CLI arguments;
- load the manifest;
- validate required columns;
- apply filters;
- inspect a small sample of page text files;
- compute planned output paths;
- report document/page counts;
- report whether output parent directories can be created;
- not write the enriched NDJSON/TSV/XLSX dataset;
- optionally write a dry-run summary/log.

Dry-run should not modify corpus data.

---

## 24. Error handling

### 24.1 Fatal errors

The programme should stop before classification if:

- the input manifest cannot be loaded;
- required columns are absent;
- output directory cannot be created;
- CLI arguments are invalid;
- filename filtering matches no rows.

### 24.2 Recoverable errors

The programme should continue processing other rows/documents if:

- an individual page text file is missing;
- an individual page text file is unreadable;
- a page text file is empty;
- a document has ambiguous chapter boundaries;
- a target chapter is not found in a document.

Recoverable errors must be recorded in enrichment columns, audit files, logs, or summary counts.

---

## 25. Exit codes

Recommended exit behaviour:

| Condition                                               | Exit code |
|---------------------------------------------------------|----------:|
| All planned processing completed without fatal errors   | `0`       |
| Completed with recoverable warnings only                | `0`       |
| Fatal setup or input error                              | `1`       |
| Keyboard interruption                                   | `130`     |

Ambiguous or unsafe documents should not necessarily cause a non-zero exit, because they are expected audit outcomes in a conservative classifier.

---

## 26. Non-goals

The first version of `enade_clean_up.py` must not:

- call any LLM API;
- denoise page text;
- correct OCR errors;
- rewrite page text files;
- concatenate pages into chapters;
- extract raw chapter text spans;
- create final corpus `.md` files;
- copy or move page files into chapter directories;
- infer chapter labels from chapter numbers alone;
- perform semantic matching beyond the closed title-variant list;
- decide final inclusion/exclusion of ambiguous boundary-overlap pages beyond recording metadata;
- replace manual audit or research judgement.

---

## 27. Future extensions

Possible future additions:

| Feature                        | Purpose                                                |
|--------------------------------|--------------------------------------------------------|
| `--include-boundary-overlaps`  | Control whether overlap pages are included or excluded |
| `--strict-empty-pages`         | Reset classification on blank pages                    |
| `--year-filter`                | Process selected ENADE years                           |
| `--discipline-filter`          | Process selected disciplines if metadata is available  |
| manual correction input        | Apply reviewed overrides to page labels                |
| confidence score               | Numeric confidence in addition to labels               |
| HTML audit report              | Easier manual inspection of detected ranges            |
| page text sample export        | Export first lines for all candidate boundaries        |
| separate reorganisation script | Copy/group page files by `chapter_of_interest`         |

These are not required for the first implementation.

---

## 28. Acceptance criteria

The programme is acceptable when:

1. It is named `enade_clean_up.py`.
2. It reads `corpus/enade_pdf_pages_dataset.ndjson` by default.
3. It imports the manifest into a DataFrame named `enade_df_pdf_pages`.
4. It preserves all original manifest columns.
5. It adds `chapter_of_interest`.
6. It uses only the accepted title variants for `c4`, `c5`, and `c6`.
7. It does not infer chapter type from chapter number alone.
8. It reads page text through `page_filepath_txt`.
9. It inspects the first 10 lines by default.
10. It supports configurable header-line count.
11. It detects target chapter starts in page headers.
12. It ignores table-of-contents title matches.
13. It detects non-target chapter boundaries and resets state to `na`.
14. It detects stop sections such as `ANEXO` and `REFERÊNCIAS`.
15. It propagates target chapter labels across contiguous page ranges.
16. It marks pages outside target chapters as `na`.
17. It handles missing page text files without crashing the full run.
18. It handles unreadable page text files without crashing the full run.
19. It records confidence and boundary/audit metadata.
20. It writes `corpus/enade_chapters_dataset.ndjson`.
21. It writes `corpus/enade_chapters_dataset.tsv`.
22. It writes `corpus/enade_chapters_dataset.xlsx`.
23. It writes audit files for detected ranges and boundaries.
24. It writes a summary JSON.
25. It writes a log file.
26. It supports dry-run mode.
27. It supports processing a single `filename`.
28. It supports limiting the number of documents for testing.
29. It never modifies the input manifest.
30. It never modifies source page text files.
31. It never calls an LLM.
32. It produces deterministic output for the same input and configuration.
33. It is suitable as the deterministic metadata-enrichment step before page reorganisation and page-level LLM denoising.