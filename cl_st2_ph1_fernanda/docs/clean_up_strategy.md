## Me
Please tell me what `find` command syntax is needed to discover the largest files in the `cl_st2_ph1_fernanda/corpus/01_enade_txt` directory.

## AI Assistant
Use this from the project root:

```shell script
find cl_st2_ph1_fernanda/corpus/01_enade_txt -type f -printf '%s\t%p\n' | sort -nr | head -20
```


That lists the **20 largest files**, sorted by size in bytes.

If you want human-readable sizes:

```shell script
find cl_st2_ph1_fernanda/corpus/01_enade_txt -type f -printf '%s\t%p\n' \
  | sort -nr \
  | head -20 \
  | numfmt --field=1 --to=iec
```


Example output format:

```plain text
12M    cl_st2_ph1_fernanda/corpus/01_enade_txt/2023/some_file.txt
8.4M   cl_st2_ph1_fernanda/corpus/01_enade_txt/2021/another_file.txt
```


On macOS, where BSD `find` does not support `-printf`, use:

```shell script
find cl_st2_ph1_fernanda/corpus/01_enade_txt -type f -exec stat -f '%z	%N' {} + \
  | sort -nr \
  | head -20
```


## Me
Taking `enade_2021_ci_bio.txt` as an input example, please let me know if the `--max-output=tokens` set as 10000 is enough.

## AI Assistant
No — for `enade_2021_ci_bio.txt`, `--max-output-tokens 10000` is **very likely not enough** if the model is expected to return the full denoised/extracted text for the whole file.

The example file is a very large ENADE report: the table of contents alone shows it runs to about **893 pages**. Even after removing noise, tables, headers, repeated page markers, and some annex material, the meaningful extracted text can easily exceed **10,000 output tokens**.

A rough rule of thumb:

```plain text
1 token ≈ 3–4 characters of Portuguese text
```


So `10000` output tokens is only around:

```plain text
30,000–40,000 characters
```


That is roughly:

```plain text
15–25 pages of dense plain text
```


For a document like `enade_2021_ci_bio.txt`, that limit is likely enough only if the prompt extracts **a small subset** of the report, not if it returns the whole cleaned document.

To check the approximate size of the input file locally, run:

```shell script
wc -c corpus/01_enade_txt/2021/enade_2021_ci_bio.txt
```


Then estimate tokens with:

```shell script
python - <<'PY'
from pathlib import Path

path = Path("corpus/01_enade_txt/2021/enade_2021_ci_bio.txt")
text = path.read_text(encoding="utf-8", errors="ignore")

chars = len(text)
rough_tokens_low = chars / 4
rough_tokens_high = chars / 3

print(f"Characters: {chars:,}")
print(f"Rough tokens: {rough_tokens_low:,.0f}–{rough_tokens_high:,.0f}")
PY
```


If the output is supposed to preserve most of the report text, I would expect you to need **chunking**, not simply a larger `--max-output-tokens`.

A safer strategy would be:

```shell script
python llm_denoise.py \
    --manifest corpus/enade_dataset.ndjson \
    --output corpus/02_enade_extracted \
    --prompt denoising_prompts/denoising_v1.md \
    --model gpt-6-luna \
    --max-output-tokens 10000 \
    --only-filename enade_2021_ci_bio.txt \
    --dry-run
```


Then inspect whether the dry run estimates or preview indicate truncation risk.

**Bottom line:** `10000` is probably fine for smaller reports, but for `enade_2021_ci_bio.txt` it is probably **too low** unless the denoising prompt asks for a compressed extract rather than the full cleaned text.

## Me
I am prompting the LLM to only denoise selected chapters. Does that improve anything?

## AI Assistant
Yes, it **improves things substantially**, but for `enade_2021_ci_bio.txt` it probably **does not make `--max-output-tokens 10000` reliably enough**.

Your prompt is not asking for the whole report; it asks only for chapters titled:

- `percepção da prova` / `percepção sobre a prova`
- `distribuição dos conceitos` / `distribuição de conceitos`
- `análise técnica da prova`

That reduces the output a lot. However, in the 2021 Ciências Biológicas example, those chapters are still large:

```plain text
Chapter 4: Percepção da Prova              pages ~176–249
Chapter 5: Distribuição dos Conceitos      pages ~250–276
Chapter 6: Análise Técnica da Prova        pages ~277–366
```


So the selected material is roughly:

```plain text
~190 pages of source report
```


Even after denoising, that can easily exceed:

```plain text
10000 output tokens
```


especially because the prompt says to:

- preserve wording,
- preserve sentence order,
- preserve headings,
- preserve tables,
- avoid summarising,
- avoid paraphrasing,
- keep substantive repeated reporting content.

So the answer is:

> **Selecting only those chapters helps a lot, but `10000` is still likely too low for the largest reports, including `enade_2021_ci_bio.txt`.**

A more realistic output cap for that file might be closer to:

```plain text
20000–40000 output tokens
```


depending on how much table material and repeated statistical text is retained.

There is also a separate issue: even if the **output** is limited to selected chapters, the model still receives the **entire report as input** unless your script pre-extracts chapters before sending the request. That means:

- `--max-output-tokens` controls only the generated JSON response;
- it does **not** reduce input context size;
- the LLM still has to scan the full file to locate the selected chapters.

For safety, the best architecture is:

1. **Pre-extract candidate chapter spans locally** by heading/title.
2. Send only those spans to the LLM for denoising.
3. Keep `--max-output-tokens 10000` only if each request covers a reasonably small chapter or chunk.

If you keep sending the full report and ask the LLM to select chapters, then for large 2021 reports I would increase the cap or expect truncation.

A quick practical check is to compare output size after a completed run:

```shell script
wc -c corpus/02_enade_extracted/enade_2021_ci_bio.*
```


If the generated file is suspiciously close to a size consistent with 10k tokens — roughly `30k–45k` characters — it may have been cut off.

## Me
Please refer to the attached AI Assistant chat. Is it possible to design a programme named `enade_clean-up.py` to safely clean up the ENADE raw txt documents and store them in the `corpus/02_enade_txt_cleaned` directory? I do not know if something like the attached offline programme is suitable for this purpose.

## AI Assistant
Yes — it is possible, and I think an **offline Python programme named `enade_clean-up.py`** is suitable for this purpose.

For your ENADE raw `.txt` files, I would **not** start with LLM denoising. A safer first step is a deterministic, offline clean-up programme that:

1. reads files from:

```plain text
corpus/01_enade_txt
```


2. writes cleaned `.txt` files to:

```plain text
corpus/02_enade_txt_cleaned
```


3. preserves the same subdirectory structure, for example:

```plain text
corpus/01_enade_txt/2009/enade_2009_admin.txt
```


would become:

```plain text
corpus/02_enade_txt_cleaned/2009/enade_2009_admin.txt
```


4. does **not** overwrite raw source files;
5. logs what it changed;
6. produces a manifest for reproducibility.

This would be a good intermediate step before any later LLM denoising or chapter extraction.

## Suitability of an offline clean-up programme

An offline programme is suitable because many problems in the ENADE `.txt` files are **mechanical extraction artefacts**, not interpretation problems. For example:

- excessive blank lines;
- form-feed or control characters;
- isolated page numbers;
- repeated headers/footers;
- broken paragraph line wrapping;
- hyphenation at line breaks;
- whitespace damage;
- obvious PDF extraction debris.

These can be handled more safely and cheaply with deterministic rules than with an LLM.

However, the programme should be **conservative**. It should clean obvious noise without trying to “improve” the prose. It should not correct spelling, rewrite sentences, translate, summarise, or infer missing text.

## Important caveat

A simple clean-up script can improve readability, but it will **not fully solve OCR/font encoding corruption** like this kind of text:

```plain text
.!
A
.!
```


That type of corruption is usually caused by PDF font extraction or encoding problems. A clean-up script can detect and flag it, but automatic repair is risky unless you build a specific mapping and validate it carefully.

So I would design `enade_clean-up.py` to do two things:

1. **clean safe, structural artefacts**;
2. **flag suspicious files or lines** for later inspection.

## Recommended design for `enade_clean-up.py`

### Inputs

Default input directory:

```plain text
corpus/01_enade_txt
```


Optional input manifest:

```plain text
corpus/enade_dataset.ndjson
```


The script can work either way:

- directory-walk mode: process all `.txt` files under `corpus/01_enade_txt`;
- manifest mode: process only files listed in `corpus/enade_dataset.ndjson`.

### Outputs

Default cleaned text directory:

```plain text
corpus/02_enade_txt_cleaned
```


Recommended additional files:

```plain text
corpus/02_enade_txt_cleaned/enade_clean-up_manifest.json
corpus/02_enade_txt_cleaned/enade_clean-up_manifest_<run_id>.json
corpus/02_enade_txt_cleaned/enade_clean-up.log
```


Optionally, for quality control:

```plain text
corpus/02_enade_txt_cleaned/enade_clean-up_warnings.tsv
```


## What the programme should clean

I would include these safe cleaning stages.

### 1. Unicode and control-character normalisation

Remove or normalise:

- null bytes;
- form-feed characters;
- unusual invisible control characters;
- repeated non-breaking spaces;
- tabs converted to spaces;
- trailing whitespace.

Conservative replacements:

```plain text
\r\n → \n
\r → \n
\t → space
non-breaking space → normal space
multiple spaces → single space, except where table alignment should be preserved
```


### 2. Remove obvious page separators

Raw ENADE files often contain page breaks like:

```plain text
12
Capítulo 3
```


or:

```plain text
29
```


The script can remove isolated page-number lines when they are clearly page markers.

Safe rule:

- remove a line if it contains only digits;
- but optionally keep it if it appears inside a table-like block.

This should be configurable because numbers can sometimes be meaningful in extracted tables.

### 3. Remove repeated headers and footers

Examples of repeated header/footer material may include:

```plain text
Relatório Síntese de Área – ENADE/2023
Fonte: MEC/INEP/DAES – ENADE/2009
```


This should be configurable. Some “Fonte:” lines are part of tables and may be useful, so I would not delete all source lines by default. Instead:

- remove repeated page headers;
- optionally keep source/caption lines unless `--aggressive` is used.

### 4. Collapse excessive blank lines

Convert long vertical whitespace blocks into one or two blank lines.

For example:

```plain text
line



next line
```


becomes:

```plain text
line

next line
```


### 5. Join broken paragraph lines

Older ENADE files often have PDF-extracted line wrapping like:

```plain text
O presente relatório tem como objetivo apresentar de forma sintética os resultados do
Exame Nacional de Desempenho dos Estudantes ENADE/2009 na área de
ADMINISTRAÇÃO.
```


This can be safely joined into:

```plain text
O presente relatório tem como objetivo apresentar de forma sintética os resultados do Exame Nacional de Desempenho dos Estudantes ENADE/2009 na área de ADMINISTRAÇÃO.
```


But the script should **not** join:

- headings;
- table rows;
- bullet lists;
- numbered section titles;
- figure/table captions;
- very short labels;
- lines ending in punctuation that strongly suggests paragraph boundary.

### 6. Fix line-break hyphenation

Example:

```plain text
desvio-
padrão
```


can become:

```plain text
desvio-padrão
```


or:

```plain text
socio-
econômico
```


can become:

```plain text
socioeconômico
```


This is tricky in Portuguese because some hyphens are real. I would implement conservative rules:

- if a line ends with a hyphen and the next line begins with lowercase, join;
- keep the hyphen only when the resulting form appears likely to be a compound;
- otherwise remove the line-break hyphen.

This should be controlled by an option such as:

```plain text
--fix-hyphenation
```


enabled by default but logged.

### 7. Preserve headings

The script should recognise headings such as:

```plain text
Capítulo 4
Percepção sobre a Prova

4.1 Grau de dificuldade da prova

5 Distribuição dos Conceitos
```


and keep them on separate lines.

It should also avoid forcing all headings into Markdown unless you explicitly want that. For a first clean-up stage, plain `.txt` is safer.

### 8. Preserve tables as much as possible

Tables are important in ENADE reports. The clean-up script should not aggressively reflow table-like blocks.

A simple table detector can look for lines with:

- many numbers;
- repeated short columns;
- percentage signs;
- multiple spaces separating fields;
- `Tabela`, `Quadro`, `Gráfico`, `Fonte`.

When inside a table-like block, the script should:

- preserve line breaks;
- avoid joining wrapped lines unless clearly safe;
- avoid collapsing internal spacing too aggressively.

### 9. Detect suspicious encoding corruption

The script should flag files with many characters such as:

```plain text
�   Ǥ ͳ ʹ ͵
```


or unusually high proportions of symbols/control-like characters.

It should not necessarily try to repair them automatically. It should report:

```plain text
status: warning
warning_type: possible_encoding_or_font_corruption
```


This is especially important for some newer reports where PDF extraction produces corrupted capital headings.

## Suggested command-line interface

Default run:

```textmate
python enade_clean-up.py
```


Recommended options:

```textmate
python enade_clean-up.py \
  --input-dir corpus/01_enade_txt \
  --output-dir corpus/02_enade_txt_cleaned
```


Dry run:

```textmate
python enade_clean-up.py --dry-run
```


Overwrite existing cleaned files:

```textmate
python enade_clean-up.py --overwrite
```


Process one file:

```textmate
python enade_clean-up.py \
  --only-filename enade_2009_admin.txt \
  --overwrite
```


Conservative mode:

```textmate
python enade_clean-up.py --mode conservative
```


More aggressive paragraph joining:

```textmate
python enade_clean-up.py --mode aggressive
```


I would make `conservative` the default.

## Suggested processing modes

### `conservative`

Default. Safe for corpus preparation.

Does:

- whitespace cleanup;
- control-character removal;
- obvious page-number removal;
- excessive blank-line collapse;
- cautious paragraph joining;
- cautious hyphenation repair;
- warning generation.

Does **not**:

- remove many repeated table captions;
- rewrite headings;
- repair corrupted PDF font encoding;
- delete annexes;
- extract only target chapters.

### `aggressive`

Optional. More readable output, but higher risk.

May additionally:

- remove repeated headers/footers more strongly;
- join more lines;
- remove more isolated numeric/table-like debris.

### `diagnose-only`

Useful before cleaning a full corpus.

Reports:

- file size;
- line count;
- likely page-number lines;
- suspicious encoding ratio;
- number of blank lines;
- likely headings;
- likely chapters found.

Example:

```textmate
python enade_clean-up.py --diagnose-only
```


## Manifest design

A manifest is important so you can later audit what happened.

Example structure:

```json
{
  "run_metadata": {
    "run_id": "20261030T120000Z",
    "tool_name": "enade_clean-up.py",
    "tool_version": "v1",
    "input_dir": "corpus/01_enade_txt",
    "output_dir": "corpus/02_enade_txt_cleaned",
    "mode": "conservative",
    "dry_run": false
  },
  "summary": {
    "files_discovered": 300,
    "files_processed": 300,
    "files_written": 300,
    "files_with_warnings": 12,
    "files_failed": 0
  },
  "files": [
    {
      "source_path": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
      "output_path": "corpus/02_enade_txt_cleaned/2009/enade_2009_admin.txt",
      "status": "success",
      "input_chars": 500000,
      "output_chars": 455000,
      "lines_removed_as_page_numbers": 120,
      "paragraph_joins": 3200,
      "hyphenation_fixes": 85,
      "warnings": []
    }
  ]
}
```


## Recommended safety rules

The programme should:

- never modify files in `corpus/01_enade_txt`;
- fail if output files already exist unless `--overwrite` or `--resume` is used;
- write UTF-8 output;
- keep relative paths;
- write a log;
- write a manifest;
- support `--dry-run`;
- support one-file testing;
- report suspicious files rather than silently “fixing” them.

## Suggested pipeline position

I would update the project pipeline to include this as a step **before** LLM denoising:

```plain text
corpus/01_enade_txt
        ↓
enade_clean-up.py
        ↓
corpus/02_enade_txt_cleaned
        ↓
LLM or rule-based chapter extraction/denoising
```


Then your existing denoising step could later use the cleaned folder as input, or the manifest could be updated to point to cleaned files.

## Bottom line

Yes, `enade_clean-up.py` is a good idea, and an offline programme is well suited for the first clean-up stage. I would design it as a **conservative, auditable preprocessor**, not as a full denoising or chapter-extraction system.

Its main purpose should be:

- preserve source meaning;
- reduce obvious PDF/text-extraction noise;
- protect raw files;
- create reproducible cleaned files in `corpus/02_enade_txt_cleaned`;
- produce warnings for files needing special handling.

## Me
Additionally, can it single out the chapters of interest?

## AI Assistant
Yes. It can **single out only the chapters of interest** by detecting chapter headings/titles and extracting just those sections.

For the ENADE reports you showed, the relevant logic should be:

- identify chapters by **title**, not by chapter number;
- include only chapters whose titles match the target set;
- stop each extracted chapter at the next same-level chapter heading;
- return metadata flags indicating which target chapters were found.

For the older ENADE format, the chapters of interest are:

| Internal label | Chapter title to detect |
|---|---|
| `c4` | `Percepção sobre a Prova` / `Percepção da Prova` |
| `c5` | `Distribuição dos Conceitos` / `Distribuição de Conceitos` |
| `c6` | `Análise Técnica da Prova` |

One important detail: in some reports, the **chapter numbers vary**. For example, in 2009, *Análise Técnica da Prova* is Chapter 3, while *Percepção sobre a Prova* is Chapter 4 and *Distribuição dos Conceitos* is Chapter 5. So the extraction should not assume that `c4`, `c5`, and `c6` correspond literally to source chapter numbers 4, 5, and 6. The labels should be internal labels for the content type.

For newer ENADE layouts, the order/numbering can also change, e.g.:

- `Percepção da Prova` may be Chapter 3;
- `Distribuição de Conceitos` may be Chapter 4;
- `Análise Técnica da Prova` may be Chapter 5.

So yes: the safest approach is to have it **single out chapters by normalized title matching**, then return only those chapters and set presence flags such as:

```json
{
  "chapters": "...selected denoised chapter text...",
  "metadata": {
    "c4_present": true,
    "c5_present": true,
    "c6_present": true
  }
}
```


This should work well as long as the prompt explicitly says that `c4`, `c5`, and `c6` are **internal content labels**, not fixed chapter numbers.

## Me
Are we ready to write the `enade_clean-up.md` programme specification for development?

## AI Assistant
Yes — we’re ready to write the **`enade_clean-up.md` programme specification for development**.

The key design decisions are now clear:

1. **Purpose**
   - Build an offline ENADE clean-up/extraction programme.
   - It should process locally extracted `.txt` ENADE reports.
   - It should extract and denoise only the chapters of interest.

2. **Chapters of interest**
   - Use internal labels:
     - `c4` → *Percepção sobre a Prova* / *Percepção da Prova*
     - `c5` → *Distribuição dos Conceitos* / *Distribuição de Conceitos*
     - `c6` → *Análise Técnica da Prova*
   - Detect by **chapter title**, not by source chapter number.
   - This is essential because chapter numbering changes across report years.

3. **Architecture**
   - Prefer a two-stage workflow:
     1. **Local pre-extraction** of candidate chapter spans from raw `.txt` reports.
     2. **LLM denoising** only on those extracted spans.
   - This avoids sending very large full reports to the LLM unnecessarily.

4. **Output**
   - Canonical output should likely be structured text plus metadata.
   - Suggested per-report JSON-like record:
     - source metadata;
     - cleaned chapter text;
     - `c4_present`;
     - `c5_present`;
     - `c6_present`;
     - extraction/denoising status;
     - warnings/errors.

5. **Resilience**
   - Must handle:
     - older ENADE layouts;
     - newer ENADE layouts;
     - OCR corruption in headings;
     - missing chapters;
     - chapter title variations;
     - very large files;
     - incomplete or invalid LLM responses.

6. **Programme scope**
   - The spec should cover:
     - CLI arguments;
     - input manifest;
     - output directory;
     - local heading detection;
     - fallback LLM title detection if needed;
     - chunking rules;
     - retry/resume;
     - validation;
     - logs;
     - manifest/reporting;
     - acceptance criteria.

One thing to decide before writing: should `enade_clean-up.md` specify a **new programme**, probably something like:

```textmate
python enade_clean_up.py
```


or should it specify an extension/replacement of the existing denoising workflow?

My recommendation: write it as a **new programme spec** for `enade_clean_up.py`, with compatibility notes for the existing pipeline. This keeps the design clean and lets the current denoising script remain a lower-level component or be superseded later.

## Me
Yes. Let's consider `enade_clean_up.py` as a new programme. I am also renaming the specification to `enade_clean_up.md` replacing the hyphen to an underscore.

## AI Assistant
Agreed. We should now treat **`enade_clean_up.py`** as a new programme, with the specification file named:

```plain text
enade_clean_up.md
```


That naming is better: it aligns with the Python module name and avoids the hyphen/underscore mismatch.

## Proposed framing

The specification should define **`enade_clean_up.py`** as a new, higher-level clean-up programme whose purpose is to:

1. Read ENADE `.txt` reports from the corpus manifest.
2. Detect the relevant chapter spans locally.
3. Extract only:
   - `c4`: *Percepção da Prova* / *Percepção sobre a Prova*
   - `c5`: *Distribuição dos Conceitos* / *Distribuição de Conceitos*
   - `c6`: *Análise Técnica da Prova*
4. Denoise those extracted spans.
5. Produce validated, resumable, corpus-ready outputs.

## Important design point

The new programme should **not** depend on chapter numbers. It should use chapter titles as the semantic anchor.

This is especially important because the target chapters can appear under different source chapter numbers across ENADE years. For example, in some layouts *Análise Técnica da Prova* can be chapter 3, while in others it can be chapter 6.

## Recommended specification structure

I suggest writing `enade_clean_up.md` with these sections:

1. **Purpose**
2. **Scope**
3. **Inputs**
4. **Outputs**
5. **Chapter taxonomy**
6. **Processing pipeline**
7. **Heading detection**
8. **Chapter-span extraction**
9. **Local clean-up rules**
10. **LLM denoising mode**
11. **Validation rules**
12. **CLI interface**
13. **Resume/reprocess behaviour**
14. **Logging and audit files**
15. **Failure modes**
16. **Acceptance criteria**
17. **Example commands**

## Key architectural recommendation

`enade_clean_up.py` should support two processing modes:

### 1. Local-only extraction/clean-up

Useful for repeatability and cheap validation.

```textmate
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output corpus/02_enade_clean \
  --mode local \
  --resume
```


### 2. Local extraction + LLM denoising

Useful for final corpus preparation.

```textmate
python enade_clean_up.py \
  --manifest corpus/enade_dataset.ndjson \
  --input-root corpus/01_enade_txt \
  --output corpus/02_enade_clean \
  --mode llm \
  --prompt denoising_prompts/denoising_v1.md \
  --model gpt-6-luna \
  --workers 10 \
  --resume \
  --max-retries 5
```


## Proposed output directory

I would use a fresh output path to avoid confusion with previous denoising runs:

```plain text
corpus/02_enade_clean/
```


or, if you want the name to make chapter extraction explicit:

```plain text
corpus/02_enade_chapters_clean/
```


My preference is:

```plain text
corpus/02_enade_clean/
```


It is short and fits the role of a canonical cleaned corpus stage.

## Proposed canonical output per report

For each source `.txt`, generate:

```plain text
corpus/02_enade_clean/<year>/<filename_stem>.md
corpus/02_enade_clean/<year>/<filename_stem>.json
```


Where:

- `.md` contains only the cleaned selected chapters, in original order.
- `.json` contains metadata, status, chapter-presence flags, extraction spans, warnings, and provenance.

A separate run manifest should also be produced:

```plain text
corpus/02_enade_clean/manifest.ndjson
corpus/02_enade_clean/run_summary.json
```


## One decision before drafting

The main decision is whether `enade_clean_up.py` should:

### Option A — produce one combined Markdown file per report

Example:

```plain text
enade_2021_ci_bio.md
```


containing all found target chapters in report order.

### Option B — produce one Markdown file per chapter

Example:

```plain text
enade_2021_ci_bio.c4.md
enade_2021_ci_bio.c5.md
enade_2021_ci_bio.c6.md
```


### Recommendation

Use **both** internally, but make the combined file the corpus-facing output:

```plain text
corpus/02_enade_clean/2021/enade_2021_ci_bio.md
corpus/02_enade_clean/2021/enade_2021_ci_bio.json
```


The JSON can preserve per-chapter information without multiplying corpus files unnecessarily.

So yes — we can now write the first full draft of **`enade_clean_up.md`**.

## Me
Please go ahead and write it!

## AI Assistant

