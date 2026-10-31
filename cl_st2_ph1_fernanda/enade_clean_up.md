# Development Specification: `enade_clean_up.py`

## 1. Programme purpose

`enade_clean_up.py` is a conservative local pre-extraction programme for Brazilian ENADE report text files.

The programme reads raw ENADE `.txt` files listed in an immutable NDJSON manifest and extracts only selected chapter spans into smaller per-chapter text files. These extracted chapter files are intended to reduce the amount of text later sent to `llm_denoise.py`.

The programme **must not denoise, clean, rewrite, summarise, translate, correct, normalise, or otherwise alter the extracted text**. It must copy exact raw text spans from the source files into separate output files.

The intended pipeline is:

```plain text
corpus/01_enade_txt
        ↓
enade_clean_up.py
        ↓
corpus/02_enade_txt_clean
        ↓
llm_denoise.py
        ↓
corpus/02_enade_extracted
```


For each ENADE report, the programme should:

1. read one manifest row;
2. locate the corresponding raw ENADE TXT file;
3. identify body-level top chapter headings for selected chapter types;
4. extract the raw text span for each safely identified selected chapter;
5. write one output `.txt` file per safely extracted chapter;
6. preserve the same year-based directory structure;
7. write detailed manifest, metadata, diagnostics, logs, and summary outputs;
8. avoid writing output files for ambiguous, unsafe, or absent chapters by default.

The selected ENADE chapter types are identified by **chapter title**, not by chapter number alone.

The internal labels are:

| Internal label | Semantic meaning               | Output filename suffix |
|----------------|--------------------------------|------------------------|
| `c4`           | Perception of the exam         | `_c4.txt`              |
| `c5`           | Distribution of ENADE concepts | `_c5.txt`              |
| `c6`           | Technical analysis of the exam | `_c6.txt`              |

The labels `c4`, `c5`, and `c6` are **project-internal semantic labels**. They do **not** mean that the matching chapter must be numbered 4, 5, or 6 in the source report.

---

## 2. Research context

The project studies Brazilian official ENADE reports. Source PDFs have already been converted to raw TXT files. These raw TXT files can contain PDF extraction artefacts, but the clean-up programme must not fix such artefacts.

The objective of `enade_clean_up.py` is narrower than denoising:

> Extract only the raw source spans corresponding to selected report chapters, preserving them exactly, so that later LLM processing receives smaller inputs.

This helps avoid sending entire long reports to an LLM when only a few chapters are needed.

The chapter titles of interest are narrowly defined:

| Internal label | Accepted chapter title variants                           |
|----------------|-----------------------------------------------------------|
| `c4`           | `percepção sobre a prova`; `percepção da prova`           |
| `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6`           | `análise técnica da prova`                                |

Matching is:

- case-insensitive;
- accent-insensitive for heading detection;
- based on a closed list of accepted title variants;
- not based on broad semantic similarity;
- not based on fuzzy keyword matching;
- not based on chapter number alone.

For example:

```plain text
Percepção sobre a Prova
```


and:

```plain text
Percepção da Prova
```


are valid matches for `c4`.

However:

```plain text
Percepção dos Estudantes sobre a Prova
```


must **not** match `c4` unless explicitly added in a future specification revision.

Likewise, subsection titles such as:

```plain text
Percepção sobre os conteúdos das questões objetivas da prova
```


must **not** match `c4`.

---

## 3. Core design principles

### 3.1 Conservative extraction

The programme must be conservative.

It is better to mark a chapter as:

```plain text
not_found
ambiguous
unsafe
```


than to extract an incorrect text span.

The programme must not silently guess when chapter identity or boundaries are uncertain.

---

### 3.2 Exact raw text preservation

The programme must preserve extracted text exactly as it appears in the source TXT.

It must not:

- denoise text;
- normalise whitespace;
- normalise Unicode in the output;
- fix mojibake;
- fix OCR errors;
- correct spelling or accents;
- merge lines;
- unwrap paragraphs;
- remove headers;
- remove footers;
- remove page numbers;
- remove tables;
- remove blank lines;
- remove form-feed characters;
- alter punctuation;
- rewrite headings;
- translate content;
- summarise content.

The extraction should be based on original character offsets where possible.

The output chapter file should contain the exact source substring from the detected start boundary to immediately before the detected end boundary.

---

### 3.3 Manifest-driven processing

The programme must be driven by an NDJSON manifest, not by recursively scanning the source directory.

The default manifest path for this project is:

```plain text
corpus/enade_dataset.ndjson
```


Each manifest row represents one ENADE report.

The input manifest must be treated as immutable.

The programme must not modify:

```plain text
corpus/enade_dataset.ndjson
```


or any source `.txt` file under:

```plain text
corpus/01_enade_txt
```


---

### 3.4 Same year-based directory structure

The output should preserve the input year grouping.

Given this input:

```plain text
corpus/01_enade_txt/2009/enade_2009_admin.txt
```


the output files should be:

```plain text
corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt
corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt
corpus/02_enade_txt_clean/2009/enade_2009_admin_c6.txt
```


Only safely extracted chapters should produce files.

Absent, ambiguous, unsafe, or skipped chapters should be recorded in the manifest but should not produce empty chapter files by default.

---

### 3.5 Closed title-variant list

The accepted title variants must be a closed list.

Initial accepted variants:

```plain text
c4:
  percepção sobre a prova
  percepção da prova

c5:
  distribuição dos conceitos
  distribuição de conceitos

c6:
  análise técnica da prova
```


The programme must not infer additional variants from context.

The programme must not treat these as valid variants unless added explicitly later:

```plain text
percepção dos estudantes sobre a prova
percepção sobre os conteúdos das questões objetivas da prova
distribuição do conceito enade
análise técnica
características dos estudantes
```


---

### 3.6 Body headings preferred over table-of-contents entries

The programme may use the table of contents as an auxiliary signal, but extraction must be anchored on body-level headings, not on table-of-contents entries.

The first occurrence of a target title may occur in the table of contents. Such occurrences must not be used as chapter start boundaries.

The programme should identify, or approximate, the end of the table-of-contents region and search for extraction starts only after that region.

---

### 3.7 Peer-level chapter boundaries

A chapter starts at the detected body-level top chapter heading and ends immediately before the next peer-level top chapter heading.

A target chapter may contain many subheadings, for example:

```plain text
4.1 Grau de dificuldade da prova
4.1.1 Formação Geral
4.1.2 Componente Específico
4.2 Extensão da prova em relação ao tempo total
```


The programme must not stop at subheadings. It should stop only before the next top-level chapter or another safe end boundary.

---

### 3.8 Reproducibility and auditability

The programme must record enough information to audit extraction decisions:

- source file path;
- source text hash;
- manifest hash;
- detected headings;
- title variant matched;
- start and end offsets;
- start and end line numbers;
- character counts;
- extraction status per target chapter;
- warnings;
- candidate headings when relevant;
- run configuration;
- programme version if available;
- timestamps.

---

## 4. Command-line interface

### 4.1 Recommended commands

Run from the project phase directory:

```plain text
cl_st2_ph1_fernanda/
```


#### Dry run

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_txt_clean \
    --limit 10 \
    --dry-run
```


#### Process one source report

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_txt_clean \
    --only-filename enade_2009_admin.txt
```


#### Process one source report with diagnostics

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_txt_clean \
    --only-filename enade_2009_admin.txt \
    --write-diagnostics
```


#### Full run with resume

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_txt_clean \
    --resume
```


#### Full reprocess

```textmate
python enade_clean_up.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_txt_clean \
    --reprocess
```


---

### 4.2 Required arguments

| Argument          | Required | Description                                          |
|-------------------|---------:|------------------------------------------------------|
| `--manifest PATH` |      Yes | Input NDJSON ENADE manifest                          |
| `--output PATH`   |      Yes | Output directory for extracted raw chapter TXT files |

---

### 4.3 Optional arguments

| Argument                   |                                   Default | Description                                                           |
|----------------------------|------------------------------------------:|-----------------------------------------------------------------------|
| `--limit N`                |                                    `None` | Process only the first `N` planned manifest rows after filtering      |
| `--only-filename FILENAME` |                                    `None` | Process only rows whose filename field exactly matches `FILENAME`     |
| `--dry-run`                |                                   `False` | Validate inputs and simulate extraction without writing chapter files |
| `--resume`                 |                                   `False` | Skip source reports whose successful clean-up metadata already exists |
| `--reprocess`              |                                   `False` | Reprocess even if previous outputs exist                              |
| `--filename-field FIELD`   |                            `filename_txt` | Manifest field containing source TXT filename                         |
| `--filepath-field FIELD`   |                            `filepath_txt` | Manifest field containing source TXT path                             |
| `--group-field FIELD`      |                                    `year` | Manifest field used for output grouping                               |
| `--state-field FIELD`      |                                    `year` | Backwards-compatible alias for `--group-field`                        |
| `--manifest-file PATH`     |   `<output>/enade_clean_up_manifest.json` | Latest run manifest path                                              |
| `--log-file PATH`          |             `<output>/enade_clean_up.log` | Log file path                                                         |
| `--summary-file PATH`      |    `<output>/enade_clean_up_summary.json` | Summary JSON path                                                     |
| `--cleaned-ndjson PATH`    |  `<output>/enade_cleaned_chapters.ndjson` | Consolidated extracted-chapter dataset                                |
| `--failures-file PATH`     | `<output>/enade_clean_up_failures.ndjson` | Failure records                                                       |
| `--write-diagnostics`      |                                   `False` | Write heading-candidate diagnostics for audit                         |
| `--diagnostics-dir PATH`   |                   `<output>/_diagnostics` | Diagnostics output directory                                          |
| `--allow-unsafe`           |                                   `False` | Write unsafe spans when start is found but end is not safe            |
| `--min-chapter-chars N`    |                                     `500` | Minimum expected character count for a found chapter                  |
| `--max-chapter-chars N`    |                                    `None` | Optional upper limit for suspiciously large chapter spans             |
| `--output-extension EXT`   |                                    `.txt` | Extension for extracted chapter files                                 |
| `--metadata-dir PATH`      |       `<output>/_enade_clean_up_metadata` | Per-report metadata directory                                         |

If both `--group-field` and `--state-field` are supplied, `--group-field` should take precedence, or the programme should fail with a clear ambiguity error.

---

### 4.4 Argument validation

The programme must fail before processing if:

- `--manifest` is missing;
- `--manifest` does not exist;
- `--manifest` is not a file;
- `--output` cannot be created;
- `--limit <= 0`, if supplied;
- `--only-filename` is supplied but empty;
- `--min-chapter-chars < 0`;
- `--max-chapter-chars <= 0`, if supplied;
- `--max-chapter-chars < --min-chapter-chars`, if both supplied;
- `--output-extension` does not start with `.`;
- both `--resume` and `--reprocess` are supplied and implementation does not define precedence.

Recommended precedence:

```plain text
--reprocess overrides --resume
```


The programme should log a warning when both are supplied.

---

## 5. Input manifest

### 5.1 Format

The manifest must be NDJSON: one JSON object per non-empty line.

Each row should contain at least:

```json
{
  "year": "2009",
  "filename_txt": "enade_2009_admin.txt",
  "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
}
```


Optional fields should be preserved in metadata and consolidated outputs, including:

```plain text
filename_ori
filepath_ori
mnemonic
discipline
filename
```


---

### 5.2 Required fields

By default, the required fields are:

| Field          | Required | Purpose                    |
|----------------|---------:|----------------------------|
| `filename_txt` |      Yes | Stable source TXT filename |
| `filepath_txt` |      Yes | Source TXT path            |
| `year`         |      Yes | Output grouping field      |

These defaults may be overridden by:

```plain text
--filename-field
--filepath-field
--group-field
--state-field
```


If a manifest row lacks required fields:

- mark the row as failed;
- write a failure record where possible;
- continue processing other rows.

---

### 5.3 Manifest row preservation

The original manifest row must be preserved in:

- per-report metadata JSON;
- consolidated chapter NDJSON;
- failure records where applicable.

This supports later traceability from extracted chapter files back to source reports and original PDFs.

---

### 5.4 Manifest loading strategy

The programme may load all manifest rows into memory.

Recommended approach:

1. read all manifest rows;
2. validate global manifest format;
3. preserve original row order;
4. apply `--only-filename`, if supplied;
5. apply `--limit`, if supplied;
6. process rows individually.

If `--only-filename` matches no rows, the programme should fail before extraction.

If more than one row matches, the programme may process all matching rows and should log a warning.

---

## 6. Source text handling

### 6.1 File path resolution

Manifest `filepath_txt` values may be relative or absolute.

Relative paths should be resolved against the directory containing `enade_clean_up.py`.

For this project, this supports execution from:

```plain text
cl_st2_ph1_fernanda/
```


---

### 6.2 Source file reading

Source files must be read as UTF-8 text using:

```python
encoding="utf-8"
errors="replace"
```


This avoids crashing the run because of occasional invalid bytes.

---

### 6.3 Source file immutability

The programme must not modify source files.

It must not write to:

```plain text
corpus/01_enade_txt
```


It must not overwrite, move, delete, or rename source files.

---

### 6.4 Empty source files

If a source file is empty or contains only whitespace:

- mark the report as failed;
- write failure metadata where possible;
- continue processing other reports.

---

### 6.5 Missing source files

If a source file does not exist:

- mark the report as failed;
- write failure metadata;
- include original manifest row;
- continue processing other reports.

---

### 6.6 Source text hashing

For each source file read successfully, compute:

```plain text
source_text_sha256
```


This hash must be recorded in per-report metadata and consolidated outputs.

---

## 7. Target chapter definitions

### 7.1 Internal labels

The programme should use the following internal labels:

| Internal label | Meaning                        |
|----------------|--------------------------------|
| `c4`           | Perception of the exam         |
| `c5`           | Distribution of concepts       |
| `c6`           | Technical analysis of the exam |

These are semantic labels, not necessarily source chapter numbers.

---

### 7.2 Accepted title variants

The initial closed title list is:

```plain text
c4:
  percepção sobre a prova
  percepção da prova

c5:
  distribuição dos conceitos
  distribuição de conceitos

c6:
  análise técnica da prova
```


These variants must be treated case-insensitively.

They should also be compared accent-insensitively for heading detection.

For example, the following heading candidates may all normalise to the same comparison form:

```plain text
Análise Técnica da Prova
ANÁLISE TÉCNICA DA PROVA
Analise Tecnica da Prova
```


But the output text must remain unchanged.

---

### 7.3 Disallowed broad matching

The programme must not use broad semantic matching.

The following must not match `c4` unless added explicitly in a future version:

```plain text
percepção dos estudantes sobre a prova
percepção sobre os conteúdos das questões objetivas da prova
questionário de percepção da prova
tabulação das respostas do questionário de percepção da prova
```


The following must not match `c5` unless added explicitly:

```plain text
conceito enade
distribuição do conceito enade
panorama nacional da distribuição dos conceitos
```


The following must not match `c6` unless added explicitly:

```plain text
análise técnica
estatísticas básicas da prova
análise das questões objetivas
análise das questões discursivas
```


The closed title list is a safety requirement.

---

## 8. Heading normalisation for matching

### 8.1 Detection-only normalisation

Heading normalisation is permitted only for detection and comparison.

It must not affect output text.

The programme may normalise candidate headings by:

- converting to lowercase;
- stripping leading and trailing whitespace;
- collapsing internal whitespace;
- removing accents;
- replacing non-breaking spaces with regular spaces;
- removing leading top-level numbering;
- removing leading `capítulo` markers;
- removing trailing page numbers when parsing table-of-contents-like lines.

Example detection normalisation:

```plain text
CAPÍTULO 4
Percepção sobre a Prova
```


may produce:

```plain text
percepcao sobre a prova
```


for comparison.

But output extraction should still start at the original raw heading text.

---

### 8.2 Heading line assembly

Because TXT extraction can split headings across lines, the programme should support limited heading candidate assembly.

For example, these lines:

```plain text
Capítulo 4
Percepção sobre a Prova
```


should be interpreted as one top-level heading candidate.

Similarly:

```plain text
4
Percepção sobre a Prova
```


or:

```plain text
4 
Percepção sobre a Prova
```


may be treated as a top-level heading candidate.

The assembly must be conservative and should be used only when:

- a numeric or `Capítulo N` line is immediately followed by a plausible title line;
- the candidate appears after the table-of-contents region;
- the candidate does not look like a table-of-contents entry;
- the resulting title exactly matches one of the accepted variants after normalisation.

---

## 9. Table-of-contents handling

### 9.1 Table-of-contents region detection

The programme should attempt to identify the table-of-contents region.

Possible start markers include:

```plain text
SUMÁRIO
Sumário
SUMARIO
```


Possible end conditions include:

- first body heading after the summary;
- first introduction/presentation body heading;
- repeated page break followed by body content;
- a configurable or heuristic maximum summary span.

The algorithm does not need perfect table-of-contents parsing, but it must avoid using summary entries as extraction start boundaries.

---

### 9.2 Summary entries as auxiliary evidence

The programme may record target title occurrences found in the table of contents as auxiliary evidence.

However:

- table-of-contents entries must not be used as extraction starts;
- page numbers in the summary should not be trusted as direct extraction offsets;
- summary entries may help identify expected chapter order.

---

### 9.3 Body search start

The programme should search for body chapter starts only after the likely table-of-contents region.

If no table-of-contents region is found, the programme should still search the full document, but it must apply stricter heading-validation rules to avoid matching incidental mentions.

---

## 10. Body heading detection

### 10.1 Top-level heading candidates

The programme should identify possible top-level chapter headings in the body.

Examples of top-level headings:

```plain text
Capítulo 4
Percepção sobre a Prova
```


```plain text
4
Percepção sobre a Prova
```


```plain text
4 Percepção sobre a Prova
```


```plain text
CAPÍTULO 3
PERCEPÇÃO DA PROVA
```


```plain text
CAPÍTULO 5
ANÁLISE TÉCNICA DA PROVA
```


The top-level chapter number is not used as the internal label. It is used only to detect peer-level boundaries.

---

### 10.2 Peer-level heading patterns

The programme should recognise peer-level top headings such as:

```plain text
Capítulo 1
Capítulo 2
CAPÍTULO 3
1
2
3
1 Distribuição dos cursos
2 Características dos Estudantes
3 Percepção da Prova
4 Distribuição de Conceitos
5 Análise Técnica da Prova
```


The detection should distinguish top-level headings from subheadings such as:

```plain text
3.1
3.1.1
4.2
5.3
```


Subheadings must not terminate extraction.

---

### 10.3 Candidate heading metadata

For every candidate heading, the programme should be able to record:

```json
{
  "raw_heading_text": "Capítulo 4\nPercepção sobre a Prova",
  "normalised_title": "percepcao sobre a prova",
  "chapter_number": "4",
  "start_char": 123456,
  "start_line": 4321,
  "source": "body",
  "is_target_candidate": true,
  "matched_label": "c4",
  "matched_variant": "percepção sobre a prova"
}
```


When `--write-diagnostics` is enabled, all relevant candidates should be written to a diagnostic file.

---

## 11. Chapter extraction logic

### 11.1 Start boundary

A target chapter start boundary is valid only when:

1. it is in the body, not in the table of contents;
2. the normalised candidate title exactly matches an accepted title variant;
3. it appears to be a top-level chapter heading;
4. it is not a subsection heading;
5. it is not an incidental sentence or paragraph mention.

The extraction should start at the raw start character of the heading.

If the heading is represented by a two-line sequence such as:

```plain text
Capítulo 4
Percepção sobre a Prova
```


the extraction should start at `Capítulo 4`, not at the title line.

---

### 11.2 End boundary

The normal safe end boundary is the next peer-level top chapter heading after the start boundary.

Example:

```plain text
Capítulo 4
Percepção sobre a Prova
...
Capítulo 5
Distribuição dos Conceitos
```


The `c4` output should end immediately before `Capítulo 5`.

If the next target chapter is also a peer heading, it may serve as the end boundary for the preceding target chapter.

---

### 11.3 Fallback end boundaries

If no next peer-level chapter heading is found, fallback boundaries may include:

```plain text
ANEXOS
Anexos
REFERÊNCIAS
Referências
GLOSSÁRIO
Glossário
```


However, fallback boundaries should be considered lower confidence than peer-level chapter headings.

By default, if a start boundary is found but no safe end boundary is found, the programme should not write the output chapter file and should mark the chapter as:

```plain text
unsafe
```


If `--allow-unsafe` is supplied, the programme may write the span to the fallback boundary or end of file and mark:

```plain text
status: unsafe_written
```


---

### 11.4 Ambiguity handling

If more than one body-level start candidate matches the same internal label, the chapter should be marked:

```plain text
ambiguous
```


and no output file should be written by default.

Example:

```json
{
  "status": "ambiguous",
  "candidate_count": 2,
  "output_path": null
}
```


The manifest should record the candidate headings and positions.

---

### 11.5 Multiple target chapters

The programme should process target labels independently:

```plain text
c4
c5
c6
```


A report may contain:

- all three target chapters;
- only two;
- only one;
- none.

Each chapter label receives its own manifest status.

---

### 11.6 Source order

The programme should record the order in which extracted chapters appear in the source file.

The source order may differ from the internal label order.

For example, `c6` may appear before `c4` in some report structures.

The programme must not assume:

```plain text
c4 before c5 before c6
```


It should infer source order from character offsets.

---

## 12. Chapter statuses

Each chapter label should have one of the following statuses:

| Status               | Meaning                                                   | Write file by default |
|----------------------|-----------------------------------------------------------|----------------------:|
| `found`              | Safe start and end boundaries found                       |                   Yes |
| `not_found`          | No eligible body heading found                            |                    No |
| `ambiguous`          | Multiple eligible body headings found                     |                    No |
| `unsafe`             | Start found, but end boundary not safe                    |                    No |
| `unsafe_written`     | Unsafe span written because `--allow-unsafe` was supplied |                   Yes |
| `empty_or_too_short` | Extracted span below minimum size                         |                    No |
| `skipped_existing`   | Existing successful output skipped by `--resume`          |          No new write |
| `failed`             | Processing failed due to error                            |                    No |

A source report should also have an aggregate status, for example:

| Report status        | Meaning                                                                            |
|----------------------|------------------------------------------------------------------------------------|
| `success`            | At least one chapter safely extracted or all labels processed without fatal errors |
| `no_target_chapters` | No target chapters found                                                           |
| `partial_success`    | Some chapters found, others not found or unsafe                                    |
| `ambiguous`          | One or more chapters ambiguous                                                     |
| `failed`             | Source-level failure prevented processing                                          |

---

## 13. Output files

### 13.1 Extracted chapter files

Given:

```plain text
--output corpus/02_enade_txt_clean
```


the programme should write extracted raw chapter text files as:

```plain text
corpus/02_enade_txt_clean/<year>/<filename_txt_stem>_<chapter_label>.txt
```


Example:

```plain text
corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt
corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt
corpus/02_enade_txt_clean/2009/enade_2009_admin_c6.txt
```


The output filename should be derived by inserting:

```plain text
_<chapter_label>
```


before the `.txt` extension.

---

### 13.2 Per-report metadata files

Each processed report should produce one metadata JSON file:

```plain text
<output>/_enade_clean_up_metadata/<year>/<filename_txt_stem>.json
```


Example:

```plain text
corpus/02_enade_txt_clean/_enade_clean_up_metadata/2009/enade_2009_admin.json
```


This file records all chapter-level decisions for one source report.

---

### 13.3 Consolidated extracted-chapter NDJSON

The programme should write:

```plain text
<output>/enade_cleaned_chapters.ndjson
```


This file should contain one record per successfully written chapter file.

Example:

```json
{
  "year": "2009",
  "filename_txt": "enade_2009_admin.txt",
  "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
  "chapter_label": "c4",
  "chapter_title_matched": "Percepção sobre a Prova",
  "chapter_title_variant": "percepção sobre a prova",
  "output_filename": "enade_2009_admin_c4.txt",
  "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt",
  "clean_up": {
    "status": "found",
    "source_text_sha256": "...",
    "extracted_text_sha256": "...",
    "start_line": 1234,
    "end_line": 1789,
    "start_char": 45678,
    "end_char": 78901,
    "char_count": 33223
  }
}
```


This consolidated NDJSON is the recommended downstream manifest for `llm_denoise.py` if denoising is later adapted to process one pre-extracted chapter per request.

---

### 13.4 Run-level manifest files

The programme should write:

```plain text
<output>/enade_clean_up_manifest.json
<output>/enade_clean_up_manifest_<RUN_ID>.json
```


The first is the latest run manifest. The second is run-specific and should not be overwritten.

---

### 13.5 Per-source-file clean-up manifest

The programme should write:

```plain text
<output>/enade_clean_up_manifest.ndjson
```


This file should contain one record per source report processed.

Example:

```json
{
  "source_path": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
  "filename_txt": "enade_2009_admin.txt",
  "year": "2009",
  "report_id": "enade_2009_admin",
  "status": "partial_success",
  "chapters": {
    "c4": {
      "status": "found",
      "title_matched": "Percepção sobre a Prova",
      "title_variant": "percepção sobre a prova",
      "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt",
      "start_line": 4321,
      "end_line": 5678,
      "start_char": 123456,
      "end_char": 178901,
      "char_count": 55445,
      "warnings": []
    },
    "c5": {
      "status": "found",
      "title_matched": "Distribuição dos Conceitos",
      "title_variant": "distribuição dos conceitos",
      "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt",
      "start_line": 5679,
      "end_line": 6123,
      "start_char": 178902,
      "end_char": 201234,
      "char_count": 22332,
      "warnings": []
    },
    "c6": {
      "status": "not_found",
      "title_matched": null,
      "title_variant": null,
      "output_path": null,
      "warnings": []
    }
  }
}
```


---

### 13.6 TSV summary

The programme may also write a flattened TSV summary:

```plain text
<output>/enade_clean_up_summary.tsv
```


Recommended columns:

```plain text
year
filename_txt
report_id
chapter_label
status
title_matched
output_path
start_line
end_line
start_char
end_char
char_count
warnings
```


This is optional but useful for manual review.

---

### 13.7 Diagnostics files

If `--write-diagnostics` is supplied, the programme should write diagnostics under:

```plain text
<output>/_diagnostics
```


Suggested diagnostic path:

```plain text
<output>/_diagnostics/<year>/<filename_txt_stem>_heading_candidates.txt
```


Diagnostics may include:

- table-of-contents region estimate;
- all candidate body headings;
- matched candidates;
- rejected candidates;
- reasons for rejection;
- ambiguous candidate lists.

Diagnostics should never alter source text or extraction outputs.

---

## 14. Output directory structure

Given:

```plain text
--output corpus/02_enade_txt_clean
```


the programme should create:

```plain text
corpus/02_enade_txt_clean/
  2009/
    enade_2009_admin_c4.txt
    enade_2009_admin_c5.txt
    enade_2009_des_c4.txt
    ...
  2010/
    ...
  _enade_clean_up_metadata/
    2009/
      enade_2009_admin.json
      enade_2009_des.json
      ...
    2010/
      ...
  _diagnostics/
    2009/
      enade_2009_admin_heading_candidates.txt
      ...
  enade_clean_up_manifest.json
  enade_clean_up_manifest_<RUN_ID>.json
  enade_clean_up_manifest.ndjson
  enade_cleaned_chapters.ndjson
  enade_clean_up_failures.ndjson
  enade_clean_up_summary.json
  enade_clean_up_summary.tsv
  enade_clean_up.log
```


The year directories contain extracted raw chapter text files.

The metadata and diagnostics directories must not be treated as corpus text.

---

## 15. Per-report metadata JSON

### 15.1 Successful or partially successful report

Example:

```json
{
  "filename": "enade_2009_admin.txt",
  "report_id": "enade_2009_admin",
  "group": "2009",
  "year": "2009",
  "status": "partial_success",
  "input": {
    "manifest_file": "corpus/enade_dataset.ndjson",
    "source_file": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
  },
  "output": {
    "output_dir": "corpus/02_enade_txt_clean/2009",
    "metadata_json": "corpus/02_enade_txt_clean/_enade_clean_up_metadata/2009/enade_2009_admin.json"
  },
  "manifest_row": {
    "year": "2009",
    "filename_txt": "enade_2009_admin.txt",
    "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
  },
  "hashes": {
    "manifest_file_sha256": "...",
    "source_text_sha256": "..."
  },
  "chapters": {
    "c4": {
      "status": "found",
      "title_matched": "Percepção sobre a Prova",
      "title_variant": "percepção sobre a prova",
      "chapter_number_detected": "4",
      "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt",
      "extracted_text_sha256": "...",
      "start_line": 1234,
      "end_line": 1789,
      "start_char": 45678,
      "end_char": 78901,
      "char_count": 33223,
      "warnings": []
    },
    "c5": {
      "status": "found",
      "title_matched": "Distribuição dos Conceitos",
      "title_variant": "distribuição dos conceitos",
      "chapter_number_detected": "5",
      "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt",
      "extracted_text_sha256": "...",
      "start_line": 1790,
      "end_line": 2010,
      "start_char": 78902,
      "end_char": 89012,
      "char_count": 10110,
      "warnings": []
    },
    "c6": {
      "status": "not_found",
      "title_matched": null,
      "title_variant": null,
      "chapter_number_detected": null,
      "output_path": null,
      "warnings": []
    }
  },
  "created_at": "2026-10-31T00:00:00Z",
  "duration_seconds": 0.42,
  "error": null
}
```


---

### 15.2 No target chapters found

Example:

```json
{
  "filename": "enade_2023_example.txt",
  "report_id": "enade_2023_example",
  "group": "2023",
  "year": "2023",
  "status": "no_target_chapters",
  "chapters": {
    "c4": {
      "status": "not_found",
      "output_path": null
    },
    "c5": {
      "status": "not_found",
      "output_path": null
    },
    "c6": {
      "status": "not_found",
      "output_path": null
    }
  },
  "error": null
}
```


This is not necessarily a failure. Some reports may legitimately lack target chapters.

---

### 15.3 Ambiguous report

Example:

```json
{
  "filename": "enade_2023_example.txt",
  "report_id": "enade_2023_example",
  "group": "2023",
  "year": "2023",
  "status": "ambiguous",
  "chapters": {
    "c4": {
      "status": "ambiguous",
      "candidate_count": 2,
      "candidates": [
        {
          "raw_heading_text": "Capítulo 3\nPercepção da Prova",
          "start_line": 1000,
          "start_char": 50000
        },
        {
          "raw_heading_text": "Capítulo 7\nPercepção da Prova",
          "start_line": 9000,
          "start_char": 450000
        }
      ],
      "output_path": null
    }
  }
}
```


No chapter file should be written by default for ambiguous chapters.

---

### 15.4 Failed report

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
    "source_file": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
  },
  "manifest_row": {
    "year": "2009",
    "filename_txt": "enade_2009_admin.txt",
    "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt"
  },
  "error_type": "missing_source_file",
  "error": "Source file not found",
  "created_at": "2026-10-31T00:00:00Z",
  "duration_seconds": 0.01
}
```


---

## 16. Consolidated extracted-chapter NDJSON

The programme must write one record per successfully written chapter file to:

```plain text
<output>/enade_cleaned_chapters.ndjson
```


Only chapters with statuses:

```plain text
found
unsafe_written
```


should be included by default.

Each record should preserve original manifest fields and add clean-up metadata.

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
  "enade_clean_up": {
    "chapter_label": "c4",
    "chapter_title_matched": "Percepção sobre a Prova",
    "chapter_title_variant": "percepção sobre a prova",
    "chapter_number_detected": "4",
    "output_file": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt",
    "metadata_json": "corpus/02_enade_txt_clean/_enade_clean_up_metadata/2009/enade_2009_admin.json",
    "status": "found",
    "source_text_sha256": "...",
    "extracted_text_sha256": "...",
    "start_line": 1234,
    "end_line": 1789,
    "start_char": 45678,
    "end_char": 78901,
    "char_count": 33223,
    "cleaned_at": "2026-10-31T00:00:00Z"
  }
}
```


This file should be deterministic and preserve original manifest order, with extracted chapter records ordered by source order within each report.

---

## 17. Failure NDJSON

The programme must write failures to:

```plain text
<output>/enade_clean_up_failures.ndjson
```


Each line should correspond to one row-level or report-level failure, such as:

- invalid manifest row;
- missing required manifest field;
- missing source file;
- unreadable source file;
- empty source file;
- output write failure;
- metadata write failure;
- unexpected exception.

Example:

```json
{
  "filename_txt": "enade_2009_admin.txt",
  "filepath_txt": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
  "year": "2009",
  "status": "failed",
  "error_type": "missing_source_file",
  "error": "Source file not found"
}
```


Chapter-level statuses such as `not_found`, `ambiguous`, or `unsafe` should be recorded in normal metadata and manifest outputs, not necessarily in the failures file, unless they result from an unexpected error.

---

## 18. Run manifest

### 18.1 Manifest files

The programme should write:

```plain text
<output>/enade_clean_up_manifest.json
<output>/enade_clean_up_manifest_<RUN_ID>.json
```


---

### 18.2 Run manifest content

Example:

```json
{
  "run_id": "20261031T120000Z",
  "programme": "enade_clean_up.py",
  "start_time": "2026-10-31T12:00:00Z",
  "end_time": "2026-10-31T12:10:00Z",
  "status": "success",
  "paths": {
    "manifest": "corpus/enade_dataset.ndjson",
    "output": "corpus/02_enade_txt_clean",
    "metadata_dir": "corpus/02_enade_txt_clean/_enade_clean_up_metadata",
    "diagnostics_dir": "corpus/02_enade_txt_clean/_diagnostics",
    "cleaned_chapters_ndjson": "corpus/02_enade_txt_clean/enade_cleaned_chapters.ndjson",
    "source_report_manifest_ndjson": "corpus/02_enade_txt_clean/enade_clean_up_manifest.ndjson",
    "failures_ndjson": "corpus/02_enade_txt_clean/enade_clean_up_failures.ndjson",
    "summary_json": "corpus/02_enade_txt_clean/enade_clean_up_summary.json",
    "summary_tsv": "corpus/02_enade_txt_clean/enade_clean_up_summary.tsv",
    "log_file": "corpus/02_enade_txt_clean/enade_clean_up.log"
  },
  "processing": {
    "limit": null,
    "only_filename": null,
    "resume": true,
    "reprocess": false,
    "dry_run": false,
    "allow_unsafe": false,
    "write_diagnostics": false,
    "filename_field": "filename_txt",
    "filepath_field": "filepath_txt",
    "group_field": "year",
    "output_extension": ".txt",
    "min_chapter_chars": 500,
    "max_chapter_chars": null
  },
  "target_chapters": {
    "c4": [
      "percepção sobre a prova",
      "percepção da prova"
    ],
    "c5": [
      "distribuição dos conceitos",
      "distribuição de conceitos"
    ],
    "c6": [
      "análise técnica da prova"
    ]
  },
  "hashes": {
    "manifest_file_sha256": "..."
  },
  "counts": {
    "manifest_rows_total": 260,
    "manifest_rows_matched": 260,
    "reports_planned": 260,
    "reports_processed": 260,
    "reports_failed": 0,
    "reports_with_any_chapter_found": 250,
    "reports_with_no_target_chapters": 10,
    "chapters_found_c4": 240,
    "chapters_found_c5": 238,
    "chapters_found_c6": 120,
    "chapters_not_found": 180,
    "chapters_ambiguous": 2,
    "chapters_unsafe": 3,
    "chapter_files_written": 598,
    "reports_skipped_existing": 0,
    "reports_dry_run": 0
  }
}
```


---

## 19. Summary JSON

The programme should write:

```plain text
<output>/enade_clean_up_summary.json
```


Example:

```json
{
  "run_id": "20261031T120000Z",
  "programme": "enade_clean_up.py",
  "manifest": "corpus/enade_dataset.ndjson",
  "output": "corpus/02_enade_txt_clean",
  "cleaned_chapters_ndjson": "corpus/02_enade_txt_clean/enade_cleaned_chapters.ndjson",
  "counts": {
    "reports_planned": 260,
    "reports_processed": 260,
    "reports_failed": 0,
    "chapter_files_written": 598,
    "chapters_found_c4": 240,
    "chapters_found_c5": 238,
    "chapters_found_c6": 120,
    "chapters_ambiguous": 2,
    "chapters_unsafe": 3,
    "reports_with_no_target_chapters": 10
  }
}
```


---

## 20. Logging

The programme must write a log file:

```plain text
<output>/enade_clean_up.log
```


It should also log to console.

### 20.1 Required log information

The log should include:

- programme start;
- run ID;
- resolved manifest path;
- resolved output path;
- configured fields;
- dry-run status;
- resume status;
- reprocess status;
- allow-unsafe status;
- diagnostics status;
- limit, if supplied;
- only-filename, if supplied;
- manifest hash;
- number of manifest rows;
- number of matched rows after filtering;
- number of planned reports;
- per-report processing status;
- chapter statuses;
- ambiguous detections;
- unsafe detections;
- failures;
- final counts;
- programme completion.

### 20.2 Sensitive data exclusion

The programme does not use API keys.

Still, logs must not include full source text or full extracted chapter text.

Logs may include:

- filenames;
- paths;
- line numbers;
- character offsets;
- hashes;
- status values;
- warnings;
- exception messages.

---

## 21. Dry-run mode

When `--dry-run` is supplied, the programme must:

- validate CLI arguments;
- load and validate manifest;
- apply filtering and limit;
- resolve source paths;
- check source file existence;
- read source files if feasible;
- compute source hashes if feasible;
- detect candidate headings;
- simulate chapter extraction decisions;
- compute expected output paths;
- write run-level metadata, summary, log, and optionally diagnostics;
- not write extracted chapter `.txt` files;
- not write success chapter records to `enade_cleaned_chapters.ndjson` unless explicitly marked as dry-run records.

Dry-run should be used to audit extraction safety before writing the clean corpus.

---

## 22. Resume and reprocess behaviour

### 22.1 Resume

If `--resume` is supplied, the programme should skip a report when:

- expected per-report metadata JSON exists;
- metadata JSON status is one of:
  - `success`;
  - `partial_success`;
  - `no_target_chapters`;
- expected chapter files for `found` chapters exist and have matching hashes.

Skipped reports should be counted as:

```plain text
reports_skipped_existing
```


Chapter statuses may be marked:

```plain text
skipped_existing
```


---

### 22.2 Reprocess

If `--reprocess` is supplied:

- ignore existing metadata and output files;
- rerun detection and extraction;
- overwrite or replace existing outputs atomically.

If both `--resume` and `--reprocess` are supplied:

```plain text
--reprocess
```


should take precedence.

---

### 22.3 Partial failures

Existing failed metadata should not be skipped by `--resume`.

Reports with previous status:

```plain text
failed
ambiguous
unsafe
```


may be reprocessed unless a future option specifies otherwise.

---

## 23. Atomic writes

All text, JSON, and NDJSON outputs should be written atomically where feasible.

Recommended process:

```plain text
1. write to temporary file in the same directory;
2. flush and close;
3. replace target file with atomic rename.
```


Atomic writes should be used for:

- extracted `.txt` chapter files;
- metadata JSON files;
- manifest JSON files;
- summary JSON;
- NDJSON outputs where practical.

For NDJSON files written at the end of the run, write the full NDJSON to a temporary file and then rename it.

---

## 24. Error handling

### 24.1 Fatal errors

The programme should stop before processing if:

- required CLI arguments are invalid;
- output directory cannot be created;
- manifest file is missing;
- manifest file is not readable;
- manifest is globally invalid;
- `--only-filename` is supplied but matches no rows.

---

### 24.2 Recoverable per-row errors

The programme should continue processing other rows if:

- one manifest row is invalid;
- a source file is missing;
- a source file is unreadable;
- a source file is empty;
- heading detection fails for one report;
- output writing fails for one report;
- metadata writing fails for one report.

Such cases should produce failure records.

---

### 24.3 Chapter-level non-errors

These chapter statuses should not by themselves stop the report or run:

```plain text
not_found
ambiguous
unsafe
empty_or_too_short
```


They are expected extraction outcomes and should be recorded for audit.

---

## 25. Processing order

High-level processing order:

```plain text
1. Parse CLI arguments.
2. Resolve paths.
3. Create output directories.
4. Configure logging.
5. Create run ID.
6. Validate options.
7. Load manifest rows.
8. Compute manifest hash.
9. Apply --only-filename filtering if supplied.
10. Apply --limit if supplied.
11. Validate manifest rows.
12. For each planned row:
    - resolve source path;
    - derive report ID;
    - determine output paths;
    - if --resume, check existing metadata and outputs;
    - read source text;
    - compute source hash;
    - identify table-of-contents region;
    - detect top-level body heading candidates;
    - match candidates against closed title-variant list;
    - determine start and end boundaries;
    - classify each target chapter status;
    - validate character counts;
    - write safe chapter files unless dry-run;
    - write per-report metadata unless dry-run policy suppresses it;
    - optionally write diagnostics.
13. Write source-report manifest NDJSON.
14. Write extracted-chapter consolidated NDJSON.
15. Write failures NDJSON.
16. Write summary JSON.
17. Write summary TSV.
18. Write latest and run-specific manifests.
19. Log final counts.
20. Exit with appropriate code.
```


---

## 26. Recommended helper functions

The implementation should be modular.

Recommended functions:

| Function                          | Responsibility                                     |
|-----------------------------------|----------------------------------------------------|
| `parse_args()`                    | Parse CLI arguments                                |
| `make_config()`                   | Resolve paths and create configuration object      |
| `utc_now_iso()`                   | Return UTC timestamp                               |
| `make_run_id()`                   | Create stable run ID                               |
| `resolve_path()`                  | Resolve relative and absolute paths                |
| `relpath()`                       | Convert paths to stable display paths              |
| `safe_path_part()`                | Create safe file or directory path parts           |
| `setup_logging()`                 | Configure file and console logging                 |
| `sha256_text()`                   | Hash text                                          |
| `sha256_file()`                   | Hash file                                          |
| `load_manifest_rows()`            | Read NDJSON manifest                               |
| `validate_manifest_row()`         | Validate required manifest fields                  |
| `filter_rows_by_filename()`       | Apply `--only-filename`                            |
| `get_report_id()`                 | Derive report ID from filename                     |
| `expected_chapter_output_path()`  | Compute chapter output path                        |
| `expected_metadata_output_path()` | Compute metadata path                              |
| `existing_success()`              | Determine whether report should be skipped         |
| `read_source_text()`              | Read source TXT safely                             |
| `normalise_heading_for_match()`   | Case- and accent-insensitive heading normalisation |
| `strip_heading_numbering()`       | Remove top-level chapter numbering for matching    |
| `find_toc_region()`               | Detect table-of-contents region                    |
| `iter_heading_candidates()`       | Yield candidate top-level headings                 |
| `classify_heading_candidate()`    | Determine candidate type                           |
| `match_target_title()`            | Match normalised title against closed variant list |
| `find_peer_end_boundary()`        | Find next top-level peer heading                   |
| `extract_span()`                  | Extract exact raw source substring                 |
| `line_number_for_offset()`        | Map character offsets to line numbers              |
| `validate_chapter_span()`         | Validate span length and boundaries                |
| `build_chapter_record()`          | Build chapter-level metadata                       |
| `build_report_metadata()`         | Build per-report JSON metadata                     |
| `build_failure_record()`          | Build failure record                               |
| `write_text_atomic()`             | Write text atomically                              |
| `write_json_atomic()`             | Write JSON atomically                              |
| `write_ndjson_atomic()`           | Write NDJSON atomically                            |
| `write_summary_tsv()`             | Write flattened TSV summary                        |
| `write_diagnostics()`             | Write heading-candidate diagnostics                |
| `build_run_manifest()`            | Build run-level manifest                           |
| `build_summary()`                 | Build summary JSON                                 |
| `main()`                          | Coordinate full programme                          |

---

## 27. Suggested heading detection approach

The first implementation may use deterministic heuristics rather than complex parsing.

Recommended approach:

1. split source text into lines while preserving line endings or offset mapping;
2. compute character offsets for line starts;
3. identify likely table-of-contents span;
4. generate heading candidates after the table-of-contents span;
5. for each line, test whether it resembles:
   - `Capítulo N`;
   - `CAPÍTULO N`;
   - a line containing only an integer;
   - a single-line top-level heading with leading integer;
6. assemble possible title line immediately following numeric heading line;
7. normalise assembled title for detection;
8. compare against closed target variants;
9. record all matching candidates;
10. determine chapter spans using next peer-level heading candidate.

The implementation should be conservative and transparent rather than overly clever.

---

## 28. Non-goals for first version

The first version should not:

- denoise text;
- rewrite text;
- normalise extracted output;
- remove PDF artefacts;
- remove repeated headers or footers;
- remove page numbers;
- remove form-feed characters;
- remove tables;
- infer chapter identity from broad semantic similarity;
- infer chapter identity from chapter number alone;
- use an LLM;
- call external APIs;
- modify the input manifest;
- modify source TXT files;
- recursively scan source directories instead of using the manifest;
- produce final Markdown corpus files;
- evaluate denoising quality;
- build a manual annotation UI.

---

## 29. Future extensions

Possible future extensions include:

| Feature                              | Purpose                                                       |
|--------------------------------------|---------------------------------------------------------------|
| `--year-filter YEAR`                 | Process one or more years                                     |
| `--discipline-filter TEXT`           | Process selected disciplines                                  |
| `--filename-filter REGEX`            | Process filename pattern                                      |
| `--include-failures-in-consolidated` | Include failed reports in consolidated NDJSON                 |
| `--write-source-context N`           | Include nearby lines around candidate headings in diagnostics |
| `--title-variants-file PATH`         | Load title variants from external config                      |
| `--strict-accents`                   | Disable accent-insensitive matching                           |
| `--allow-fuzzy-title-matching`       | Explicit future fuzzy mode, disabled by default               |
| `--max-source-chars N`               | Skip or flag very large source files                          |
| `--chapter-labels c4,c5,c6`          | Process subset of chapter labels                              |
| `--copy-unsafe-to-review`            | Write unsafe spans to review directory only                   |
| `--html-report`                      | Generate human-readable audit report                          |

Fuzzy title matching should remain a future, explicitly enabled feature. It must not be part of the safe default mode.

---

## 30. Downstream implications for `llm_denoise.py`

After `enade_clean_up.py` is implemented, `llm_denoise.py` should eventually be adapted to process the smaller extracted chapter files rather than entire report files.

A future denoising manifest can be:

```plain text
corpus/02_enade_txt_clean/enade_cleaned_chapters.ndjson
```


In that future architecture, each LLM request may process one extracted chapter file, making the denoising step:

- cheaper;
- less prone to input-context overflow;
- easier to audit;
- easier to retry per chapter;
- less dependent on the LLM locating chapters.

The denoising prompt can then focus only on denoising the provided chapter text, rather than identifying chapter boundaries.

---

## 31. Exit codes

Recommended exit behaviour:

| Condition                                             | Exit code |
|-------------------------------------------------------|----------:|
| All planned reports processed or skipped successfully |       `0` |
| Some reports failed, but run completed                |       `1` |
| Fatal setup error before processing                   |       `1` |
| Keyboard interruption                                 |     `130` |

Chapter-level `not_found`, `ambiguous`, or `unsafe` statuses do not necessarily require a non-zero exit code unless the project decides to treat them as failures.

Recommended first-version behaviour:

```plain text
Exit 0 if there are no row-level failures.
Exit 1 if any source report failed due to file, manifest, or write errors.
```


---

## 32. Acceptance criteria

The programme is acceptable when:

1. It is named `enade_clean_up.py`.
2. It accepts `--manifest` and `--output`.
3. It reads an NDJSON manifest.
4. It treats the input manifest as immutable.
5. It reads source text from each row’s `filepath_txt` by default.
6. It uses `filename_txt` as the default filename field.
7. It uses `year` as the default output grouping field.
8. It supports relative and absolute paths.
9. It reads source files as UTF-8 with replacement for invalid bytes.
10. It searches for selected chapters by accepted title variants, not by chapter number alone.
11. It uses the closed target variant list for `c4`, `c5`, and `c6`.
12. It performs case-insensitive matching.
13. It performs accent-insensitive matching for detection.
14. It does not broaden matches to semantic variants not listed.
15. It does not match `percepção dos estudantes sobre a prova` as `c4`.
16. It does not match subsections as top-level target chapters.
17. It avoids using table-of-contents entries as extraction starts.
18. It identifies body-level target headings.
19. It identifies safe end boundaries using next peer-level headings.
20. It preserves extracted text exactly.
21. It writes one `.txt` file per safely extracted chapter.
22. It preserves year-based directory structure.
23. It names outputs by inserting `_c4`, `_c5`, or `_c6` before `.txt`.
24. It does not write files for absent chapters.
25. It does not write files for ambiguous chapters by default.
26. It does not write files for unsafe chapters by default.
27. It supports `--allow-unsafe` for explicit unsafe writing.
28. It writes per-report metadata JSON.
29. It writes `enade_clean_up_manifest.ndjson`.
30. It writes `enade_cleaned_chapters.ndjson`.
31. It writes failure records to `enade_clean_up_failures.ndjson`.
32. It writes run manifests.
33. It writes summary JSON.
34. It writes summary TSV.
35. It writes a log file.
36. It supports `--dry-run`.
37. It supports `--only-filename`.
38. It supports `--limit`.
39. It supports `--resume`.
40. It supports `--reprocess`.
41. It optionally writes diagnostics with `--write-diagnostics`.
42. It records source hashes.
43. It records extracted text hashes.
44. It records start/end character offsets.
45. It records start/end line numbers.
46. It records matched title variants.
47. It records chapter statuses for all target labels.
48. It records warnings for suspicious spans.
49. It uses atomic writes where feasible.
50. It continues processing after per-report failures.
51. It returns a non-zero exit code on fatal setup errors or row-level failures.
52. It is suitable as a safe pre-extraction stage before LLM denoising.
