## Me
Please help me design the `enade_clean_up.py` programme that:

- Takes the `corpus/enade_pdf_pages_dataset.ndjson` file as input manifest, import it as the `enade_df_pdf_pages` DataFrame and enrich it with the `chapter_of_interest` column.
- Uses the `page_filepath_txt` column to parse each PDF page's extracted text.
- Reads the first 10 lines of each text file to find the beginning of the chapters of interest

Examples of page beginnings with chapter of interest headers

```plain text
77
Capítulo 4 
Percepção sobre a Prova 
 
As percepções dos estudantes sobre a prova aplicada no ENADE/2009 na área de 
ADMINISTRAÇÃO foram mensuradas por meio de nove itens que avaliaram desde o grau 
de dificuldade da prova até o tempo gasto para concluí-la. As questões foram analisadas 
separando-se concluintes e ingressantes, e as percepções sobre a prova foram
```


```plain text
83 
CAPÍTULO 4 – 
PERCEPÇÃO DA PROVA 
As análises feitas neste capítulo tratam das percepções dos concluintes da Área 
de Agronomia sobre a prova aplicada no Enade/2016. Estas percepções foram 
mensuradas por meio de nove questões que avaliaram desde o grau de dificuldade da 
prova até o tempo gasto para concluí-la. As percepções sobre a prova foram 
relacionadas com o desempenho dos estudantes e com a Grande Região de 
funcionamento do curso. O questionário de percepção da prova encontra-se ao final do
```


```plain text
79 
Relatório Síntese de Área – ENADE/2023 
CAPÍTULO 3 
PERCEPÇÃO DA PROVA 
Neste capítulo, constam as percepções dos concluintes da área de Fonoaudiologia sobre a prova 
aplicada. Essas percepções foram mensuradas por meio de nove questões que avaliaram desde o grau de
```


The chapters of interest can be identified as follows:

```markdown
| Internal label | Chapter title variants                                    |
|----------------|-----------------------------------------------------------|
| `c4`           | `percepção sobre a prova`; `percepção da prova`           |
| `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6`           | `análise técnica da prova`                                |
```


The intention is to mark the ranges of pages related to the chapters of interest with the corresponding `Internal label`. The programme should be able to identify the pages with chapter changes, sections of no interest, such as `ANEXO`, `REFERÊNCIAS`, etc.. The challenge is to mark contiguous pages within a chapter of interest (subchapters) without letting pages from unwanted chapters or sections pass. There should be an internal label for not applicable pages. What do you think we could do?

## AI Assistant
Yes — I would design `enade_clean_up.py` as a **deterministic page-classification programme**, not as an LLM denoiser. The key idea is to turn the page manifest into a page-level state machine:

1. **Read** `corpus/enade_pdf_pages_dataset.ndjson` into `enade_df_pdf_pages`.
2. **Inspect only the first 10 non-empty-ish lines** of each page text file.
3. **Detect strong chapter-start headers** for the three target chapter types.
4. **Detect strong stop headers** for unwanted later sections, such as `ANEXO`, `REFERÊNCIAS`, `APÊNDICE`, etc.
5. **Propagate the current chapter label forward page by page** within each PDF until another chapter/section boundary is found.
6. Mark everything else as a not-applicable label, e.g. `na`.

## Recommended labels

Use a compact controlled vocabulary:

| Label | Meaning |
|---|---|
| `c4` | `percepção sobre a prova` / `percepção da prova` |
| `c5` | `distribuição dos conceitos` / `distribuição de conceitos` |
| `c6` | `análise técnica da prova` |
| `na` | not applicable / outside chapters of interest |

The output column should be:

```plain text
chapter_of_interest
```


Optionally add audit columns:

```plain text
chapter_boundary_type
chapter_boundary_match
chapter_boundary_confidence
page_header_sample
```


These are very useful for debugging false positives.

## Core strategy

### 1. Do not rely on chapter numbers

This is important because the same chapter type appears with different chapter numbers across years:

- `percepção da prova` can be `CAPÍTULO 3`, `CAPÍTULO 4`, or `CAPÍTULO 5`;
- `distribuição de/dos conceitos` can appear as `CAPÍTULO 4`, `CAPÍTULO 5`, or `CAPÍTULO 6`;
- `análise técnica da prova` can be `CAPÍTULO 3`, `CAPÍTULO 5`, `CAPÍTULO 6`, or `CAPÍTULO 7`.

So the classifier should identify chapters by **title variants**, not number.

### 2. Use a boundary-state machine

For each `filename`, sort by `page_number` and walk pages in order:

```python
current_label = "na"

for page in pages:
    header = first_10_lines(page_text)

    if is_stop_section(header):
        current_label = "na"

    elif starts_target_chapter(header) is not None:
        current_label = detected_label

    elif starts_any_other_chapter(header):
        current_label = "na"

    page.chapter_of_interest = current_label
```


This handles contiguous pages naturally. Once a target chapter starts, all following pages remain `c4`, `c5`, or `c6` until the next boundary.

### 3. Use strong header detection only

Avoid matching arbitrary mentions such as:

```plain text
O questionário de percepção da prova encontra-se...
```


That should not start a chapter. A good detector should prefer patterns where the target phrase appears in a page header zone and is near a chapter marker or formatted as a standalone heading.

Examples to accept:

```plain text
Capítulo 4
Percepção sobre a Prova
```


```plain text
CAPÍTULO 4 –
PERCEPÇÃO DA PROVA
```


```plain text
Relatório Síntese de Área – ENADE/2023
CAPÍTULO 3
PERCEPÇÃO DA PROVA
```


Also accept a direct standalone heading:

```plain text
PERCEPÇÃO DA PROVA
```


but only if it appears in the first few lines and looks heading-like.

## Text normalisation

Implement a conservative normaliser for matching only:

- lowercase;
- Unicode accent stripping;
- dash normalisation;
- whitespace collapse;
- remove repeated dot leaders from table-of-contents lines.

Example:

```python
"CAPÍTULO 4 – PERCEPÇÃO DA PROVA"
```


becomes:

```plain text
capitulo 4 percepcao da prova
```


This makes the rules robust across OCR and PDF extraction variation.

## Pattern sets

### Target chapter title variants

Normalised phrase mapping:

```python
TARGET_TITLES = {
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


### Stop sections

Use these as hard transitions to `na` when found as headers in first lines:

```python
STOP_SECTION_TITLES = [
    "anexo",
    "anexos",
    "referencias",
    "referencia",
    "bibliografia",
    "apendice",
    "apendices",
    "glossario",
]
```


Important: stop only when the line looks like a section heading, not when `Anexo VII` is mentioned inside a paragraph. For example, this should **not** stop classification:

```plain text
O questionário de percepção da prova encontra-se ao final do Anexo VII...
```


But this should stop:

```plain text
ANEXO II
Tabulação das respostas...
```


### Other chapter boundary

If a page starts another `CAPÍTULO N` whose title is not one of the target titles, set `na`.

This prevents pages from unwanted chapters passing through.

## Handling table of contents false positives

The first pages often contain table-of-contents lines like:

```plain text
CAPÍTULO 4 PERCEPÇÃO DA PROVA ..................................... 125
```


If we simply match that, we may incorrectly mark table-of-contents pages as `c4`.

So the programme should distinguish **real chapter starts** from **TOC entries**. Clues for TOC:

- line contains many repeated dots;
- line ends with a page number after dot leaders;
- several consecutive lines look like chapter entries;
- page is very early in the PDF;
- header contains many entries, not prose.

Recommendation:

- If line contains dot leaders like `.....` or `ǤǤǤ`, treat it as **TOC evidence**, not a chapter start.
- Do not start a chapter from TOC-style lines.
- Still allow real starts where the title appears without dot leaders and is followed by body prose.

## Confidence levels

I would implement confidence internally:

| Confidence | Condition |
|---|---|
| `high` | `CAPÍTULO` marker and target title appear in the first 10 lines, not TOC-like |
| `medium` | target title appears as a standalone uppercase/titlecase heading in first 10 lines |
| `low` | phrase appears, but context is ambiguous |

Only `high` and maybe `medium` should change state. `low` should be recorded for audit but should not change `chapter_of_interest`.

## Suggested output files

The programme should not modify the source manifest in place. It should write a new enriched manifest, e.g.:

```plain text
corpus/enade_pdf_pages_dataset_cleaned.ndjson
corpus/enade_pdf_pages_dataset_cleaned.tsv
corpus/enade_pdf_pages_dataset_cleaned.xlsx
```


At minimum, the new NDJSON should contain all original fields plus:

```json
{
  "chapter_of_interest": "c4"
}
```


Recommended additional audit columns:

```json
{
  "chapter_of_interest": "c4",
  "chapter_boundary_type": "target_chapter_start",
  "chapter_boundary_match": "percepcao da prova",
  "chapter_boundary_confidence": "high"
}
```


## Edge cases to handle

### Pages with missing text files

Set:

```plain text
chapter_of_interest = "na"
```


and record an audit note if you include audit columns.

### Empty text pages

Also `na`, unless the current chapter is already active. I would recommend **keeping current state** for blank pages inside a chapter, because blank/figure/table pages can occur. But add an option if you want stricter behaviour.

### Annex pages after target chapters

A strong `ANEXO`, `ANEXOS`, or `REFERÊNCIAS` header should reset state to `na`.

### Multi-column extraction artefacts

Some headings may appear as:

```plain text
CAPÍTULO 4 –
PERCEPÇÃO DA PROVA
```


So matching should join the first 10 lines into a header block, not only inspect line by line.

## Minimal pseudo-implementation

```python
for filename, group in enade_df_pdf_pages.groupby("filename", sort=False):
    current_label = "na"

    for row_index, row in group.sort_values("page_number").iterrows():
        header_lines = read_first_lines(row["page_filepath_txt"], n=10)
        header_text = normalize_header(header_lines)

        boundary = detect_boundary(header_lines, header_text)

        if boundary.kind == "stop_section":
            current_label = "na"
        elif boundary.kind == "other_chapter":
            current_label = "na"
        elif boundary.kind == "target_chapter":
            current_label = boundary.label

        enade_df_pdf_pages.loc[row_index, "chapter_of_interest"] = current_label
```


## What I would do first

I would build this in two passes:

### Pass 1: classification

Generate the enriched manifest.

### Pass 2: audit report

Create a summary table listing, per PDF:

- first page of each detected `c4`, `c5`, `c6`;
- last page of each range;
- number of pages per label;
- detected stop sections;
- suspicious cases where a target chapter was never found.

Example audit output:

```plain text
corpus/enade_clean_up_audit.tsv
```


Columns:

```plain text
filename
chapter_of_interest
start_page
end_page
page_count
start_match
end_reason
```


This will make it much easier to inspect whether the range propagation worked.

## Overall recommendation

Use a **rule-based boundary detector plus state propagation**. That is more appropriate than asking an LLM to label every page, because the task is structural and reproducible. The most important safeguards are:

1. match titles, not chapter numbers;
2. ignore table-of-contents entries;
3. reset on non-target chapter headings;
4. reset on annex/reference sections;
5. preserve an audit trail so you can manually inspect edge cases.

## Me
I agree! Are we ready to write `enade_clean_up.md`, the programme development specification?

## AI Assistant
Yes — we’re ready. The design decisions are settled enough to write `enade_clean_up.md`.

The specification should define `enade_clean_up.py` as a **conservative, manifest-driven raw-span extractor** that:

- reads the canonical ENADE manifest;
- identifies only the closed list of chapter-title variants;
- extracts exact source text spans without denoising or alteration;
- writes one file per safely detected chapter;
- writes a detailed manifest/audit trail;
- avoids table-of-contents false positives;
- marks ambiguous/unsafe cases instead of guessing.

A good next step is to draft the document with sections parallel to the denoising specification, but focused on local extraction rather than API calls:

```markdown
# Development Specification: `enade_clean_up.py`

## 1. Programme purpose
## 2. Research context
## 3. Core design principles
## 4. Input manifest
## 5. Chapter labels and accepted title variants
## 6. Boundary detection strategy
## 7. Text preservation requirements
## 8. Output directory structure
## 9. Clean-up manifest and audit outputs
## 10. Command-line interface
## 11. Dry-run, resume, and reprocess behaviour
## 12. Error handling
## 13. Logging
## 14. Processing order
## 15. Recommended helper functions
## 16. Non-goals
## 17. Acceptance criteria
```


The only final design point I would explicitly lock in is:

> Matching may be case-insensitive and accent-insensitive **for detection only**, but extracted output must preserve the exact original source substring.

So, yes: we can proceed to write the full `enade_clean_up.md` programme development specification.

## Me
Instead of extracting the text, I'd like the programme's scope to consider only the DataFrame enrichment. As second outside step, I intend to use the DataFrame's `chapter_of_interest` column to reorganise the text pages accordingly. After, I'll have `llm_denoise.py` to LLM denoise each page, solving the issue of excessive window of context. The updated DataFrame can be saved as `corpus/enade_chapters_dataset` in NDJSON, TSV and XLSX formats. What do you think?

## AI Assistant
I think that is a **better architecture** for this stage.

Instead of making `enade_clean_up.py` extract raw chapter text, it should become a **page-level metadata enrichment programme**. Its job would be to classify each PDF page row as belonging, or not belonging, to one of the chapters of interest. Then a later deterministic step can use that enriched dataset to copy/reorganise page text files, and `llm_denoise.py` can denoise **one page at a time** or small page batches.

This is safer and more flexible than raw chapter-span extraction.

## Why this is a good change

### 1. It reduces context-window pressure more effectively

If the unit sent to the LLM is a page, then the prompt remains small and predictable. This avoids the earlier problem where even one selected chapter could still be too large.

Pipeline becomes:

```plain text
corpus/enade_pdf_pages_dataset.*
        ↓
enade_clean_up.py
        ↓
corpus/enade_chapters_dataset.*
        ↓
page reorganisation step
        ↓
page-level llm_denoise.py
        ↓
final corpus assembly
```


### 2. It avoids risky text-span extraction

Chapter-span extraction has tricky failure modes:

- wrong start heading;
- wrong end heading;
- table-of-contents false positives;
- missing end boundary;
- shifted chapter numbering;
- repeated chapter titles in annexes;
- OCR noise around headings.

A DataFrame/page enrichment approach can be more conservative. It only needs to say:

> This page is probably inside `c4`, `c5`, `c6`, or none/unknown.

The actual page text files remain untouched.

### 3. It gives you a stronger audit trail

Saving an enriched page dataset means every page gets a traceable classification. You can inspect, filter, sort, and correct the dataset before any text is moved or denoised.

That is especially useful for cases where:

- only some chapters exist;
- chapter headings are not present in every document;
- a document has unusual structure;
- a boundary is ambiguous;
- page-level classification should be reviewed manually.

### 4. It makes later processing deterministic

Once the DataFrame has reliable columns such as:

```plain text
chapter_of_interest
chapter_of_interest_status
chapter_of_interest_source
chapter_of_interest_confidence
```


the next step can simply reorganise pages according to that metadata. No extra inference is needed at that stage.

## Suggested scope for `enade_clean_up.py`

I would redefine `enade_clean_up.py` as:

> A manifest/DataFrame enrichment programme that reads the page-level ENADE dataset, detects chapter-of-interest page ranges for each report, and writes an enriched page-level dataset with chapter classification metadata.

It should **not**:

- extract chapter text;
- concatenate pages;
- denoise text;
- alter page text files;
- create final corpus files.

It should only enrich metadata.

## Recommended input

The natural input should be the existing page-level dataset:

```plain text
corpus/enade_pdf_pages_dataset.ndjson
```


with optional TSV/XLSX equivalents if needed.

Each row represents one page and already includes fields like:

```plain text
filename
filepath_ori
page_number
page_filename
page_filepath
page_filename_txt
page_filepath_txt
```


The programme can group rows by `filename`, sort by `page_number`, inspect page text where needed, and assign chapter metadata back to each page row.

## Recommended output

Your proposed output name is good:

```plain text
corpus/enade_chapters_dataset.ndjson
corpus/enade_chapters_dataset.tsv
corpus/enade_chapters_dataset.xlsx
```


I would use the same basename without extension:

```plain text
corpus/enade_chapters_dataset
```


and let the programme write the three formats.

## Core enriched columns

I recommend adding at least these fields.

### Essential columns

| Column | Meaning |
|---|---|
| `chapter_of_interest` | Internal label for page: `c4`, `c5`, `c6`, or empty/null |
| `chapter_of_interest_title` | Matched canonical title, if any |
| `chapter_of_interest_variant` | Exact configured title variant matched |
| `chapter_of_interest_status` | Page classification status |
| `chapter_of_interest_confidence` | Conservative confidence label or score |
| `chapter_start_page` | Start page of the detected chapter range |
| `chapter_end_page` | End page of the detected chapter range |
| `chapter_boundary_method` | How the range was inferred |
| `chapter_detection_notes` | Human-readable notes/warnings |

### Useful document-level flags repeated per page

These can be repeated on every page row for convenience:

| Column | Meaning |
|---|---|
| `c4_present` | Whether `c4` was found for this document |
| `c5_present` | Whether `c5` was found for this document |
| `c6_present` | Whether `c6` was found for this document |
| `c4_start_page` | Detected start page for `c4` |
| `c4_end_page` | Detected end page for `c4` |
| `c5_start_page` | Detected start page for `c5` |
| `c5_end_page` | Detected end page for `c5` |
| `c6_start_page` | Detected start page for `c6` |
| `c6_end_page` | Detected end page for `c6` |

This makes filtering easy, e.g.:

```plain text
chapter_of_interest == "c4"
```


or:

```plain text
c6_present == true
```


## Status values

For page rows, I would use:

| Status | Meaning |
|---|---|
| `in_chapter_of_interest` | Page is inside a confidently detected chapter range |
| `outside_chapter_of_interest` | Page is confidently outside selected chapters |
| `candidate_boundary` | Page contains a possible start/end heading |
| `ambiguous` | Page belongs to a document with ambiguous boundaries |
| `unsafe` | Page belongs to a document where page classification is not safe |
| `not_found` | No selected chapter was found in the document |

For document-level chapter detection, use:

| Status | Meaning |
|---|---|
| `found` | Safe start and end page boundaries found |
| `not_found` | No reliable chapter heading found |
| `ambiguous` | Multiple plausible starts or conflicting boundaries |
| `unsafe` | Start found but end/boundary logic is unreliable |
| `partial` | Start found, but page range only partially recoverable |

## Matching should remain narrow

I would keep the closed list:

| Internal label | Accepted title variants |
|---|---|
| `c4` | `percepção sobre a prova`; `percepção da prova` |
| `c5` | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6` | `análise técnica da prova` |

Detection can be:

- case-insensitive;
- accent-insensitive for matching only;
- whitespace-normalised for matching only;
- tolerant of `CAPÍTULO N`, `Capítulo N:`, or similar prefixes.

But it should **not** use broad semantic matching.

## Important design point: classify page ranges, not just heading pages

The programme should not mark only the page where the title appears. It should infer a range:

```plain text
start page = page where target top-level heading begins
end page = page before the next peer top-level chapter heading
```


Then all pages in that range get:

```plain text
chapter_of_interest = "c4" / "c5" / "c6"
```


This is exactly what will let the later reorganisation step work.

## Handling pages that overlap boundaries

Page-level classification has one unavoidable issue: a chapter can start or end mid-page.

For practical corpus work, I recommend a simple rule:

- if a page contains the start heading of a chapter of interest, include the page in that chapter;
- if a page contains the next chapter heading, assign that page to the **new** chapter if the new chapter is also of interest, otherwise mark it as `boundary_overlap` or exclude it by default depending on safety preference.

A cleaner option is to add:

```plain text
page_boundary_role
```


with values such as:

```plain text
chapter_start
chapter_middle
chapter_end
boundary_overlap
outside
```


This lets the reorganisation step decide whether to include overlap pages.

## Recommended column design

A practical schema could include:

```plain text
filename
filepath_ori
page_number
page_filename
page_filepath
page_filename_txt
page_filepath_txt

chapter_of_interest
chapter_of_interest_title
chapter_of_interest_variant
chapter_of_interest_status
chapter_of_interest_confidence
page_boundary_role
chapter_start_page
chapter_end_page
chapter_boundary_method
chapter_detection_notes

c4_present
c4_status
c4_start_page
c4_end_page
c4_title_variant

c5_present
c5_status
c5_start_page
c5_end_page
c5_title_variant

c6_present
c6_status
c6_start_page
c6_end_page
c6_title_variant
```


## Recommended output formats

Writing all three is useful:

```plain text
corpus/enade_chapters_dataset.ndjson
corpus/enade_chapters_dataset.tsv
corpus/enade_chapters_dataset.xlsx
```


Use NDJSON as the canonical machine-readable format. TSV and XLSX are excellent for review.

## Should `enade_clean_up.md` still be the specification?

Yes. The document can still be called:

```plain text
enade_clean_up.md
```


But the programme purpose should be rewritten from:

> extract selected chapter text

to:

> enrich the ENADE page-level dataset with conservative chapter-of-interest metadata.

The programme name `enade_clean_up.py` is still acceptable, but if you want a more precise name, alternatives would be:

```plain text
enade_chapter_page_enrich.py
enade_page_chapter_classifier.py
enade_chapters_dataset.py
```


However, keeping `enade_clean_up.py` is fine if this is the broader “clean-up preparation” stage.

## Main implication for `llm_denoise.py`

This change means `llm_denoise.py` should eventually process a **page-level or reorganised-page manifest**, not the original whole-report manifest.

It should probably stop trying to locate the selected chapters itself. The prompt can be simpler:

> Denoise this single page, preserving substantive text.

The metadata can come from the enriched dataset instead of the model.

That is a strong improvement: the LLM denoises, while deterministic preprocessing decides what pages are in scope.

## My recommendation

Yes — I would adopt your revised plan.

The new design should be:

1. `enade_clean_up.py`: enrich page-level DataFrame with `chapter_of_interest`.
2. Separate deterministic reorganisation step: copy or group page text files according to `chapter_of_interest`.
3. `llm_denoise.py`: denoise each selected page or small page batch.
4. Later assembly step: combine denoised pages into document/chapter-level corpus files if needed.

This is safer, more inspectable, and much better for context-window control.
