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
Please refer to the attached AI Assistant chat. Is it possible to design a programme named `enade_clean_up.py` to safely clean up the ENADE raw txt documents and store them in the `corpus/02_enade_txt_clean` directory? The clean-up process should consist of locating the chapters of interest and having them in individual text files like `corpus/01_enade_txt/2009/enade_2009_admin_c4.txt`. The intention is to reduce the number of tokens to be sent to the LLM for denoising. Remember that `c4`, `c5`, and `c6` are internal labels because the actual chapters may not correspond to the internal labels' numbers. There should be a safe way to identify the chapter's boundaries. The files with individualised chapters should be stored in the same subdirectory structure. The text should not be denoised or altered in any way because that will be done by `llm_denoise.py` (of course, this programme should be adapted according to what is going to be defined in this stage). There might be a few documents that will have some or none of the chapters of interest. Therefore, a manifest should be provided to indicate the presence or absence of each chapter. Is it clear? Am I missing anything? Let's discuss before writing the programme development specification, `enade_clean_up.md`.

## AI Assistant
Yes, it is clear. The proposed `enade_clean_up.py` would be a **local pre-extraction stage** between raw TXT conversion and LLM denoising:

```plain text
corpus/01_enade_txt
        ↓
enade_clean_up.py
        ↓
corpus/02_enade_txt_clean
        ↓
llm_denoise.py
```


The goal would **not** be to denoise, normalize, correct OCR, remove tables, or rewrite anything. It would only **copy exact raw text spans** corresponding to the chapters of interest into smaller files, so that `llm_denoise.py` can later work on reduced input.

## What is clear

The programme should:

1. Read raw ENADE TXT files from:

```plain text
corpus/01_enade_txt/<year>/<filename>.txt
```


2. Identify whether the chapters of interest are present.

3. Extract each chapter into a separate file, preserving the same subdirectory structure, for example:

```plain text
corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt
   corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt
   corpus/02_enade_txt_clean/2009/enade_2009_admin_c6.txt
```


4. Treat `c4`, `c5`, and `c6` as **internal labels**, not as guaranteed chapter numbers.

5. Preserve extracted text **exactly as found** in the source TXT.

6. Produce a manifest indicating whether each internal chapter label was found, not found, ambiguous, or skipped.

7. Support documents where:
   - all target chapters are present;
   - only some are present;
   - none are present;
   - boundaries are ambiguous.

## The key design point: safe boundary detection

The important issue is how to identify chapter boundaries safely. I agree that the script should **not blindly trust numeric chapter labels** such as “Capítulo 4”, because the actual chapter of interest can shift across years.

Instead, the safest strategy would be a **multi-signal boundary detection approach**:

### 1. Prefer semantic chapter titles over chapter numbers

The programme should search for target chapter headings by title patterns such as:

| Internal label | Target topic | Possible headings |
|---|---|---|
| `c4` | Perception of the exam | `Percepção da Prova`, `Percepção sobre a Prova`, `Percepção dos Estudantes sobre a Prova` |
| `c5` | Distribution of concepts | `Distribuição dos Conceitos`, `Distribuição de Conceitos`, `Distribuição do Conceito Enade` |
| `c6` | Technical analysis of the exam | `Análise Técnica da Prova`, `Análise técnica`, possibly in later reports: `Análise Técnica da Prova` under a different chapter number |

However, based on the 2023 sample, the internal mapping may need to be flexible because the report structure changed substantially. For example, in recent ENADE reports, `Percepção da Prova`, `Distribuição de Conceitos`, and `Análise Técnica da Prova` may correspond to **Chapters 3, 4, and 5**, not 4, 5, and 6.

So yes: `c4`, `c5`, and `c6` should be treated as **project labels**, perhaps better described internally as:

```plain text
c4 = perception_chapter
c5 = concept_distribution_chapter
c6 = technical_analysis_chapter
```


The output filenames can still use `_c4`, `_c5`, `_c6`.

### 2. Use table of contents as a guide, but not as the only source

The script can parse the `SUMÁRIO` to identify likely chapter titles and page references, but it should not rely exclusively on page numbers because TXT extraction may have irregular page breaks.

The table of contents can be used to build candidates:

```plain text
4 Percepção sobre a Prova 66
5 Distribuição dos Conceitos 97
6 Características dos Estudantes 106
```


But actual extraction should preferably be anchored on **the real heading occurrence in the body**, not only the table of contents entry.

### 3. Avoid extracting from the table of contents

A common hazard is that the first occurrence of a target title appears in the `SUMÁRIO`, not in the body. The script should therefore:

- locate the table of contents span;
- record title candidates from it;
- then search for the corresponding body heading **after the summary section**.

A simple safety rule could be:

```plain text
Do not use target heading occurrences before the end of the table of contents as chapter starts.
```


### 4. Boundaries should be from heading to next peer heading

Once a target chapter heading is found in the body, the end boundary should be the next **peer-level heading**, not the next subheading.

For example, if extracting:

```plain text
Capítulo 4
Percepção sobre a Prova
```


the extraction should continue through:

```plain text
4.1 ...
4.2 ...
4.3 ...
```


and stop before:

```plain text
Capítulo 5
Distribuição dos Conceitos
```


or before another top-level heading such as:

```plain text
5 Distribuição dos Conceitos
```


For newer reports, it should stop before the next top-level `CAPÍTULO N` heading, regardless of whether the target internal label is `c4`.

### 5. Use heading confidence levels

The script should probably classify each chapter extraction as one of:

```plain text
found
not_found
ambiguous
unsafe
```


Possible meanings:

- `found`: one reliable start and one reliable end boundary found.
- `not_found`: no plausible target heading found.
- `ambiguous`: multiple plausible starts or ends found.
- `unsafe`: a start was found, but the end boundary was not reliable.
- `empty_or_too_short`: extracted text is suspiciously short.
- `skipped`: intentionally skipped due to safety rules.

This is better than a simple Boolean manifest, although Boolean fields can still be provided for compatibility.

## What you may be missing

A few things are worth deciding before writing `enade_clean_up.md`.

### 1. What exactly should happen when an end boundary is missing?

Suppose the script finds:

```plain text
Capítulo 4
Percepção sobre a Prova
```


but cannot confidently identify the next chapter heading.

Options:

1. **Do not extract** and mark `unsafe`.
2. Extract until the end of file and mark `end_boundary_missing`.
3. Extract until `ANEXOS`, `REFERÊNCIAS`, or another fallback heading.

For safety, I would recommend:

> If no safe end boundary is found, do not write the chapter file by default; record it in the manifest as `unsafe`.

An optional `--allow-unsafe` flag could write it for inspection.

### 2. Should the output contain only the chapter body or also the chapter heading?

I recommend including the heading exactly as found, because it provides useful context for `llm_denoise.py`.

So the output should start at the heading line itself:

```plain text
Capítulo 4
Percepção sobre a Prova
...
```


or:

```plain text
4
Percepção sobre a Prova
...
```


depending on how it appears in the raw TXT.

### 3. Should output files be created for absent chapters?

I recommend **no**. If a chapter is absent or unsafe, the file should not be created, and the manifest should record the status.

Creating empty files can be confusing for downstream processing.

### 4. Manifest format

A manifest should probably be both machine-readable and auditable. I would suggest:

```plain text
corpus/02_enade_txt_clean/enade_clean_up_manifest.ndjson
```


with one record per source file, or one record per source-file/chapter pair.

A useful structure would be one record per source file:

```json
{
  "source_path": "corpus/01_enade_txt/2009/enade_2009_admin.txt",
  "year": "2009",
  "base_filename": "enade_2009_admin.txt",
  "output_dir": "corpus/02_enade_txt_clean/2009",
  "chapters": {
    "c4": {
      "status": "found",
      "title_matched": "Percepção sobre a Prova",
      "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt",
      "start_line": 1234,
      "end_line": 1789,
      "start_char": 45678,
      "end_char": 78901,
      "char_count": 33223
    },
    "c5": {
      "status": "found",
      "title_matched": "Distribuição dos Conceitos",
      "output_path": "corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt",
      "start_line": 1790,
      "end_line": 2010,
      "start_char": 78902,
      "end_char": 89012,
      "char_count": 10110
    },
    "c6": {
      "status": "not_found",
      "title_matched": null,
      "output_path": null
    }
  }
}
```


This is better than only:

```json
{"c4_present": true, "c5_present": true, "c6_present": false}
```


because it allows audit and debugging.

### 5. Downstream implications for `llm_denoise.py`

Yes, `llm_denoise.py` should eventually be adapted. The clean-up stage changes the unit of processing from:

```plain text
one whole report
```


to:

```plain text
one pre-extracted chapter file
```


or possibly:

```plain text
one source report with up to three child chapter files
```


The current denoising validation expects metadata such as:

```plain text
c4_present
c5_present
c6_present
```


After this clean-up stage, there are two possible downstream designs:

#### Option A: `llm_denoise.py` processes each chapter file independently

Then the prompt no longer needs to ask the LLM to locate chapters. It only needs to denoise the provided chapter.

In this case, metadata could become simpler:

```json
{
  "chapter_label": "c4",
  "chapter_present": true
}
```


#### Option B: `llm_denoise.py` receives all extracted chapters for one report

Then the clean-up stage can concatenate only the safely extracted chapters or pass them as separate inputs, while still preserving the existing `c4_present`, `c5_present`, `c6_present` idea.

I would lean toward **Option A** because it reduces token usage further and makes failures easier to isolate.

### 6. Naming conventions

The output file naming convention seems clear:

```plain text
enade_2009_admin_c4.txt
enade_2009_admin_c5.txt
enade_2009_admin_c6.txt
```


But we should define whether the script always derives this from the input filename by inserting `_c4` before `.txt`.

Example:

```plain text
input:  corpus/01_enade_txt/2009/enade_2009_admin.txt
output: corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt
```


This is simple and safe.

### 7. Raw text preservation

This requirement is very important. The programme should not:

- normalize Unicode;
- fix mojibake;
- remove page numbers;
- remove headers or footers;
- merge broken lines;
- delete blank lines;
- trim interior whitespace;
- rewrite chapter titles;
- correct OCR errors.

At most, it may need to preserve the extracted substring exactly between character offsets. That means extraction should be based on character offsets rather than reconstructed lines if possible.

It may trim only the boundaries if explicitly defined, but I would recommend:

> Preserve the exact source substring from the start boundary to immediately before the end boundary.

### 8. Audit mode / dry run

Before writing files, a dry run would be very useful:

```shell script
python enade_clean_up.py --dry-run
```


It should show:

- source file;
- detected target chapters;
- heading text;
- start/end line;
- char count;
- output path that would be written;
- warnings.

This is especially important because the extraction is safety-critical.

### 9. A review directory for ambiguous cases

It may be useful to create an optional diagnostic file for ambiguous cases, for example:

```plain text
corpus/02_enade_txt_clean/_diagnostics/enade_2023_arqui_urb_candidates.txt
```


This could list all heading candidates found. But this is optional and can be kept out of the first version.

## Suggested extraction philosophy

I would define the programme as conservative:

> It is better to miss a chapter and report `not_found` or `ambiguous` than to extract the wrong span.

This is important because a wrong extraction would silently contaminate the denoising stage.

## Proposed high-level workflow

The eventual programme could work like this:

1. Discover input files under `corpus/01_enade_txt/**/*.txt`.
2. For each file:
   - read text as UTF-8, preserving content;
   - identify likely table of contents region;
   - detect body-level top headings;
   - match target chapter titles against known patterns;
   - determine start and end boundaries;
   - validate span length and ordering;
   - write safe chapter files only;
   - record manifest entry.
3. Write manifest to `corpus/02_enade_txt_clean/enade_clean_up_manifest.ndjson`.
4. Optionally write a summary report:

```plain text
corpus/02_enade_txt_clean/enade_clean_up_summary.tsv
```


## Open questions before writing `enade_clean_up.md`

I think we should decide these before drafting the development specification:

1. **Which exact chapter topics map to `c4`, `c5`, and `c6`?**  
   My understanding is:
   - `c4` = perception of the exam;
   - `c5` = distribution of concepts;
   - `c6` = technical analysis of the exam.

2. **Should `c6` always mean “Análise Técnica da Prova”, even when it appears before the other two chapters?**  
   In older files, it can be Chapter 3. In newer files, it can be Chapter 5. This confirms the internal label must be semantic, not numeric.

3. **Should unsafe detections write no file by default?**  
   I recommend yes.

4. **Should the manifest be one record per source file or one record per extracted chapter?**  
   I recommend one record per source file, with nested chapter entries, plus maybe a flattened TSV summary.

5. **Should the script support `--only-year`, `--only-file`, and `--dry-run` from the beginning?**  
   I recommend yes, because this will make testing much easier.

6. **Should the programme process all files or only files listed in `corpus/enade_dataset.ndjson`?**  
   If `enade_dataset.ndjson` is the canonical dataset manifest, using it may be safer. If not, recursive file discovery is simpler.

7. **How strict should matching be with corrupted OCR headings?**  
   The 2023 sample shows mojibake-like text in the table of contents, but the body headings are clearer. We should decide whether to implement fuzzy matching in version 1 or only normalized heading matching.

## My recommendation

Yes, the programme is feasible and useful. I would specify it as a **conservative raw-span extractor** with:

- semantic chapter labels;
- title-based body heading detection;
- table-of-contents-assisted validation;
- exact text preservation;
- no denoising;
- same directory structure;
- per-chapter output files;
- robust manifest;
- dry-run and audit support.

You are not missing anything major, but the development specification should explicitly define the safety rules for ambiguous boundaries and the exact semantic meaning of `c4`, `c5`, and `c6`.

## Me
Please refer to the attached AI Assistant chat. I agree with your recommendations. I just think that there should be a narrower number of title variants (case insensitive) as the following excerpt from `llm_denoise.py` programme development specification. The reason is that, for example, `percepção sobre a prova` is the same chapter of `percepção da prova` but is not the same chapter of `percepção dos estudantes sobre a prova`. If we do not narrow down, we might end up with more than 3 eligible chapters leading to ambiguity.

| Internal label | Chapter title variants                                    |
|----------------|-----------------------------------------------------------|
| `c4`           | `percepção sobre a prova`; `percepção da prova`           |
| `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6`           | `análise técnica da prova`                                |


## AI Assistant
Yes — I agree completely. The title matching for `enade_clean_up.py` should be **narrow and conservative**, and it should use exactly the same intended chapter-title variants as the `llm_denoise.py` specification unless we later discover a strong reason to expand them.

The safer mapping should be:

| Internal label | Accepted chapter title variants                           |
|----------------|-----------------------------------------------------------|
| `c4`           | `percepção sobre a prova`; `percepção da prova`           |
| `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
| `c6`           | `análise técnica da prova`                                |

All matching should be **case-insensitive**.

I would also add two important clarifications to the future `enade_clean_up.md` specification.

## 1. Match exact normalized titles, not broad semantic phrases

The clean-up programme should not treat every heading containing the words `percepção`, `estudantes`, and `prova` as equivalent.

So this should match `c4`:

```plain text
Percepção sobre a Prova
```


and this should match `c4`:

```plain text
Percepção da Prova
```


But this should **not** match `c4`:

```plain text
Percepção dos Estudantes sobre a Prova
```


unless we later explicitly decide to add it as a valid variant.

That distinction is important because the clean-up stage is supposed to be a **safe extractor**, not a semantic classifier.

## 2. Normalisation should be limited to matching only

For heading comparison, the script can normalise candidate headings internally, for example:

- lowercase;
- collapse repeated whitespace;
- remove leading chapter numbering such as `4`, `4.`, `Capítulo 4`, `CAPÍTULO 4`;
- optionally remove trailing page numbers when parsing table-of-contents entries;
- compare accents as written, unless we decide to support accent-insensitive matching.

But this normalisation must be used **only for detection**. The extracted output text must remain exactly as it appears in the source file.

So the matching logic can interpret:

```plain text
Capítulo 4
Percepção sobre a Prova
```


as the normalised candidate title:

```plain text
percepção sobre a prova
```


but the output file should still include the original raw text span exactly.

## Recommended rule for `enade_clean_up.md`

I would write the specification along these lines:

> The programme must use a closed, conservative list of accepted chapter-title variants. A heading candidate is eligible only if, after heading-level normalisation, its title equals one of the configured variants for the corresponding internal chapter label. The programme must not use fuzzy semantic matching, substring matching, or broad keyword matching to infer chapter identity.

That would prevent accidental matches such as:

```plain text
Percepção dos Estudantes sobre a Prova
```


or:

```plain text
Percepção sobre os conteúdos das questões objetivas da prova
```


which appears as a subsection in older reports and should definitely not be treated as the target chapter.

## Proposed matching behaviour

For each candidate top-level chapter heading, the script should derive a normalised title and compare it against the accepted variants:

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


A chapter should be marked as `found` only when:

1. the normalised body heading exactly matches one accepted variant;
2. the heading is detected as a body-level chapter heading, not a table-of-contents entry;
3. the next peer-level chapter boundary is identified safely;
4. no competing body-level heading matches the same internal label.

If more than one body-level heading matches the same internal label, the status should be:

```plain text
ambiguous
```


and no file should be written by default.

## Why this is the right approach

Your example is exactly the risk:

```plain text
percepção sobre a prova
```


and:

```plain text
percepção da prova
```


refer to the same intended chapter type.

But:

```plain text
percepção dos estudantes sobre a prova
```


could plausibly belong to a different report structure or different analytical chapter. If the extractor accepted broader variants, it could identify too many “eligible” chapters and make the extraction unsafe.

So, yes: **narrow matching is better here**. The programme should prefer false negatives over false positives. If a true chapter is missed because its title differs, the manifest can show `not_found`, and we can inspect it later. That is safer than silently extracting the wrong chapter.

## Me
Are we ready to write `enade_clean_up.md` programme development specification?

## AI Assistant
Yes — we are ready to write `enade_clean_up.md`.

The main design decisions are now clear enough:

1. **Programme name**
   - `enade_clean_up.py`

2. **Purpose**
   - Pre-extract selected ENADE report chapters from raw TXT files.
   - Reduce the amount of text sent later to `llm_denoise.py`.
   - Preserve extracted text exactly; no denoising, rewriting, cleaning, or normalisation of output content.

3. **Input**
   - Use the ENADE manifest as the canonical input source, preferably:

```plain text
corpus/enade_dataset.ndjson
```


   - Read source paths from each row’s `filepath_txt`.

4. **Output**
   - Write extracted chapter files to:

```plain text
corpus/02_enade_txt_clean/<year>/
```


   - Example output names:

```plain text
corpus/02_enade_txt_clean/2009/enade_2009_admin_c4.txt
   corpus/02_enade_txt_clean/2009/enade_2009_admin_c5.txt
   corpus/02_enade_txt_clean/2009/enade_2009_admin_c6.txt
```


5. **Internal chapter labels**
   - `c4`, `c5`, and `c6` are semantic internal labels, not guaranteed report chapter numbers.

6. **Accepted title variants**
   - Matching should be narrow, case-insensitive, and based on a closed list:

   | Internal label | Accepted variants                                         |
   |----------------|-----------------------------------------------------------|
   | `c4`           | `percepção sobre a prova`; `percepção da prova`           |
   | `c5`           | `distribuição dos conceitos`; `distribuição de conceitos` |
   | `c6`           | `análise técnica da prova`                                |

7. **Safety philosophy**
   - Conservative extraction.
   - Prefer `not_found`, `ambiguous`, or `unsafe` over extracting the wrong span.
   - Do not write files for absent, ambiguous, or unsafe chapters by default.

8. **Boundary detection**
   - Avoid table-of-contents matches as extraction starts.
   - Find body-level chapter headings.
   - Extract from matched heading to the next peer-level top heading.
   - Preserve the exact raw substring between those boundaries.

9. **Manifest**
   - Write a detailed clean-up manifest, probably:

```plain text
corpus/02_enade_txt_clean/enade_clean_up_manifest.ndjson
```


   - It should record per-source-file and per-chapter statuses, paths, matched titles, offsets, line numbers, character counts, and warnings.

10. **CLI**
   - Include at least:
     - `--manifest`
     - `--output`
     - `--dry-run`
     - `--only-filename`
     - `--limit`
     - `--resume`
     - `--reprocess`

11. **Diagnostics**
   - Include logging and optional candidate diagnostics for ambiguous or unsafe cases.

The only small point still worth deciding is whether the first version should implement **accent-insensitive matching**. My recommendation is:

> Yes, for heading detection only, compare titles with case-insensitive and accent-insensitive normalisation, while preserving output text exactly.

That would allow matching `analise tecnica da prova` if accents are lost in OCR/TXT extraction, without broadening the semantic title list.

So, unless you want to adjust that final point, we can proceed to draft the full `enade_clean_up.md` development specification.

## Me
I agree! Please go ahead and write the programme development specification.
