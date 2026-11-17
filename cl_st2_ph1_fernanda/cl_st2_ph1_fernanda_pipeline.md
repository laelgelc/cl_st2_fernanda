# Corpus Linguistics - Study 2 - Phase 1 - Fernanda

Run the commands from the project phase directory, e.g.:

```text
cl_st2_ph1_fernanda/
```

## 1. Organise the ENADE dataset metadata

Please refer to the Jupyter notebook: `cl_st2_ph1_fernanda.ipynb`

Outputs:

- `corpus/enade_dataset.ndjson`
- `corpus/enade_pdf_pages_dataset.ndjson`

## 2. Clean and extract ENADE report chapters

### 2.1. Automated chapter of interest detection

```shell
python enade_clean_up.py
```

Output: `corpus/enade_chapters_dataset.ndjson`

### 2.2. Copy the automated selected chapters to `corpus/02_enade_selected_chapters`

Please refer to the Jupyter notebook: `cl_st2_ph1_fernanda.ipynb`

### 2.3. Manual clean-up revision
Manual page clean-up is required because the automated process could not avoid false positive cases.

Please refer to the document: `corpus/enade_chapters_clean_up_dataset_c6_manual.md`

### 2.4. Create the `enade_chapters_clean_up_revised_dataset` manifest

## 3. Denoise the ENADE report chapters of interest

### Dry run

```shell
python llm_denoise.py \
    --input-manifest corpus/enade_chapters_clean_up_revised_dataset.ndjson \
    --prompt denoising_prompts/denoising_v1.md \
    --output corpus/03_enade_selected_chapters_denoised \
    --window-size 3 \
    --model gpt-6-luna \
    --only-filename enade_2009_admin \
    --dry-run
```

### Test run, first time

```shell
python llm_denoise.py \
    --input-manifest corpus/enade_chapters_clean_up_revised_dataset.ndjson \
    --prompt denoising_prompts/denoising_v1.md \
    --output corpus/03_enade_selected_chapters_denoised \
    --window-size 3 \
    --model gpt-6-luna \
    --only-filename enade_2009_admin
```

### Production mode on an EC2 instance

```shell
bash run_python_ec2.sh \
    llm_denoise.py \
    --input-manifest corpus/enade_chapters_clean_up_revised_dataset.ndjson \
    --prompt denoising_prompts/denoising_v1.md \
    --output corpus/03_enade_selected_chapters_denoised \
    --window-size 3 \
    --model gpt-6-luna \
    --workers 10 \
    --resume \
    --max-retries 5
```

### Full run for retrying the invalid responses

```shell
python llm_denoise.py \
    --input-manifest corpus/enade_chapters_clean_up_revised_dataset.ndjson \
    --prompt denoising_prompts/denoising_v1.md \
    --output corpus/03_enade_selected_chapters_denoised \
    --window-size 3 \
    --model gpt-6-luna \
    --resume \
    --max-retries 5
```

## 4. Organise the final ENADE target corpus

This step validates the revised page-selection manifest against the source metadata and denoising chapter status, then copies each complete assembled chapter to `corpus/04_enade/<year>_<chapter>/`. It publishes the chapter-level target manifest in NDJSON, TSV, and XLSX formats; the page-level selection manifest and earlier pipeline outputs are not changed.

The organiser requires Python 3.10 or later and `openpyxl` in the same Python environment used to run the pipeline. NDJSON and TSV use only the standard library.

### Dry run

Run the dry run first. It reconciles the full group identities and page sets, verifies the source PDF and assembled chapter paths, checks destination safety and collisions, and prints page/chapter totals. It creates no output files or directories.

```shell
python organise_enade_corpus.py --dry-run
```

For the recorded production inputs, compare the dry-run totals with 30,770 selected pages and 1,032 complete chapter groups. These counts are a one-run cross-check, not fixed programme requirements; investigate any discrepancy before publishing.

### Full run

After reviewing a successful dry run, publish the corpus:

```shell
python organise_enade_corpus.py
```

The output layout is:

```text
corpus/04_enade/
├── 2009_c4/
│   └── enade_2009_admin_b2a0b87461.txt
├── enade_target_corpus.ndjson
├── enade_target_corpus.tsv
└── enade_target_corpus.xlsx
```

The organiser copies chapter bytes without renaming them, verifies copied SHA-256 checksums and sizes, validates the three equivalent manifests, and publishes from a staging directory. Each manifest row traces the original PDF, selected pages, denoised source, chapter checksum, and detailed chapter-status record. The corpus status is `accepted_subject_to_audit`: it records the agreed selection subject to human audit and is not a claim that boundary flags or review notes have been resolved.

An identical rerun verifies the existing corpus and makes no changes. If files, manifests, or review decisions differ—or if unexpected files exist—the organiser stops and preserves the target rather than overwriting it. To intentionally rebuild, choose a separate destination or archive the existing corpus manually first. Relative command-line paths are resolved from this phase directory, independent of the current working directory.

## 5. Tag the corpus

This stage tags the finalized ENADE target corpus with POS tags and lemmas using TreeTagger (`tree-tagger-portuguese2`), producing 3-column tab-delimited files in `corpus/05_enade_tagged/` alongside provenance manifests.

### Dry run
```shell
python tag.py --dry-run
```

### Production run
```shell
python tag.py --workers 8 --resume
```

The output layout is:
```text
corpus/05_enade_tagged/
├── 2009_c4/
│   └── enade_2009_admin_b2a0b87461.txt
├── enade_tagged_corpus.ndjson
├── enade_tagged_corpus.tsv
├── enade_tagged_corpus.xlsx
└── tagging_failures.ndjson
```

## 6. Extract key lemmas by group

This stage extracts and quantifies distinctive keywords (key lemmas) across subcorpora of the ENADE dataset. The programme processes tagged token files by reading records from `corpus/05_enade_tagged/enade_tagged_corpus.ndjson` (with fallback to direct directory traversal). For each (`year`, `chapter`) evaluation group, it compares binary document presence in the target group with all documents in all other groups combined. A lemma is counted at most once per file; normalized rates (`target_per_1k`, `comparison_per_1k`) represent document-prevalence rates per 1,000 files rather than raw token frequencies.

POS tag filtering and stopword exclusions are externalized into auditable configuration files: `keylemmas_pos.txt` (defaulting to content word prefixes `NOUN`, `VERB`, and `ADJ`) and `keylemmas_stopwords.txt`. Alternate profiles can be supplied via `--pos-config` and `--stopwords`. The active configuration paths, cryptographic hashes (SHA-256), group definitions, document counts, and output TSV checksums are recorded in `keylemmas_run.json`.

### Dry run

```shell
python keylemmas.py --cutoff 3 --dry-run
```

### Production run

```shell
python keylemmas.py --cutoff 3
```

The output layout is:

```text
corpus/06_enade_keylemmas/
├── 2009_c4.tsv
├── 2009_c5.tsv
├── 2011_c6.tsv
├── 2021_c6.tsv
└── keylemmas_run.json
```

The output directory `corpus/06_enade_keylemmas/` contains one UTF-8 tab-delimited file per group, named `<year>_<chapter>.tsv`, and the provenance manifest `keylemmas_run.json`. TSV columns are:
- `lemma`: Canonical extracted lemma (lowercased).
- `target_count`: Number of target group documents containing the lemma ($a$).
- `comparison_count`: Number of comparison group documents containing the lemma ($b$).
- `target_per_1k`: Target prevalence rate per 1,000 documents ($\text{perA}$).
- `comparison_per_1k`: Comparison prevalence rate per 1,000 documents ($\text{perB}$).
- `expected`: Expected target document count under the null distribution ($E$).
- `LL`: Log-likelihood ($G^2$) contingency test statistic.
- `diff_percent`: Symmetrical percentage difference in prevalence ($\%DIFF$).
- `status`: Descriptive keyword classification (`POSKW`, `NEGKW`, or `NOTKW` using threshold $\text{LL} \ge 3.84$).

Output rows are sorted deterministically by status priority (`POSKW` $\rightarrow$ `NEGKW` $\rightarrow$ `NOTKW`), descending `LL`, and ascending alphabetical `lemma`. By default, all eligible corpus lemmas are reported (`--cutoff 0.0`), with optional target presence filtering supported via `--cutoff`.

An identical rerun verifies existing output without modifying it; conflicting or unexpected files are preserved and reported rather than overwritten. Relative command-line paths resolve against the phase directory.

## 7. Select a stratified keyword set

The selector reads each group's ranked profile from `corpus/06_enade_keylemmas/`. It keeps the first eligible `POSKW` lemmas in source order, applying the same quota independently to each `<year>_<chapter>` group. The consolidated cap, when active, is applied to the naturally ordered group selections before deduplication; per-group files are not truncated by that cap.

For an initial run, use five lemmas per group and a consolidated cap of 220. Run the dry run first to inspect available and selected counts without creating output files:

```shell
python select_kws_stratified.py \
    --input corpus/06_enade_keylemmas \
    --output corpus/07_enade_kw_selected \
    --per-group 8 \
    --max-total 400 \
    --dry-run
```

Review the counts, then run the same command without `--dry-run` to publish the outputs. The stage writes one ranked selection per group, the sorted, deduplicated consolidated list `corpus/07_enade_kw_selected/keywords.txt`, and `select_kws_stratified_run.json` with parameters, counts, and input/output checksums. Existing outputs are verified on an identical rerun; conflicting or unexpected files are preserved and reported. Relative paths resolve from this phase directory.

The upstream run manifest currently records 1,032 texts across 42 groups. Five per group yields at most 210 selected occurrences before deduplication, so the 220 cap will not bind for that group count. The rule of thumb of five texts per variable suggests about 206 (roughly 210) variables, but fewer unique lemmas may result when groups have fewer than five eligible candidates or selections overlap. The selector does not top up groups or guarantee a target unique count. Confirm the upstream manifest's recorded zero stopwords is intentional before interpreting the selected vocabulary.

```shell
=== ENADE Keyword Selection ===
2009_c4                → selected 8/8 from 163 eligible POSKW lemmas
2009_c5                → selected 8/8 from 67 eligible POSKW lemmas
2009_c6                → selected 8/8 from 516 eligible POSKW lemmas
2010_c4                → selected 8/8 from 104 eligible POSKW lemmas
2010_c5                → selected 8/8 from 19 eligible POSKW lemmas
2010_c6                → selected 8/8 from 1067 eligible POSKW lemmas
2011_c4                → selected 8/8 from 157 eligible POSKW lemmas
2011_c5                → selected 8/8 from 35 eligible POSKW lemmas
2011_c6                → selected 8/8 from 1093 eligible POSKW lemmas
2012_c4                → selected 8/8 from 104 eligible POSKW lemmas
2012_c5                → selected 8/8 from 31 eligible POSKW lemmas
2012_c6                → selected 8/8 from 886 eligible POSKW lemmas
2013_c4                → selected 8/8 from 107 eligible POSKW lemmas
2013_c5                → selected 8/8 from 35 eligible POSKW lemmas
2013_c6                → selected 8/8 from 1013 eligible POSKW lemmas
2014_c4                → selected 8/8 from 159 eligible POSKW lemmas
2014_c5                → selected 8/8 from 55 eligible POSKW lemmas
2014_c6                → selected 8/8 from 1708 eligible POSKW lemmas
2015_c4                → selected 8/8 from 131 eligible POSKW lemmas
2015_c5                → selected 8/8 from 52 eligible POSKW lemmas
2015_c6                → selected 8/8 from 1369 eligible POSKW lemmas
2016_c4                → selected 8/8 from 105 eligible POSKW lemmas
2016_c5                → selected 8/8 from 44 eligible POSKW lemmas
2016_c6                → selected 8/8 from 1498 eligible POSKW lemmas
2017_c4                → selected 8/8 from 160 eligible POSKW lemmas
2017_c5                → selected 8/8 from 83 eligible POSKW lemmas
2017_c6                → selected 8/8 from 1692 eligible POSKW lemmas
2018_c4                → selected 8/8 from 120 eligible POSKW lemmas
2018_c5                → selected 8/8 from 63 eligible POSKW lemmas
2018_c6                → selected 8/8 from 1537 eligible POSKW lemmas
2019_c4                → selected 8/8 from 170 eligible POSKW lemmas
2019_c5                → selected 8/8 from 77 eligible POSKW lemmas
2019_c6                → selected 8/8 from 1934 eligible POSKW lemmas
2021_c4                → selected 8/8 from 138 eligible POSKW lemmas
2021_c5                → selected 8/8 from 75 eligible POSKW lemmas
2021_c6                → selected 8/8 from 777 eligible POSKW lemmas
2022_c4                → selected 8/8 from 194 eligible POSKW lemmas
2022_c5                → selected 8/8 from 121 eligible POSKW lemmas
2022_c6                → selected 8/8 from 1541 eligible POSKW lemmas
2023_c4                → selected 8/8 from 237 eligible POSKW lemmas
2023_c5                → selected 8/8 from 121 eligible POSKW lemmas
2023_c6                → selected 8/8 from 890 eligible POSKW lemmas

Group count: 42
Selected occurrences before cap: 336
Occurrences after cap: 336
Unique keywords: 218
Duplicates removed: 118
Published outputs: /home/eyamrog/PycharmProjects/cl_st2_fernanda/cl_st2_ph1_fernanda/corpus/07_enade_kw_selected
```

## 8. Build binary keyword columns

This stage reads the selected keywords from `corpus/07_enade_kw_selected/keywords.txt` and the tagged files listed by `corpus/05_enade_tagged/enade_tagged_corpus.ndjson`. It reconciles those records with `corpus/04_enade/enade_target_corpus.ndjson`, accepts tagged-manifest statuses `success` and `skipped`, and stops if target documents are missing, duplicated, failed, unsafe, or inconsistent with recorded paths, sizes, or SHA-256 checksums.

Run the dry run first. It validates the inputs and checks whether any existing outputs are complete and identical, without creating or changing files:

```shell
python columns.py --dry-run
```

After a successful dry run, publish the columns:

```shell
python columns.py
```

The outputs remain in the phase directory for downstream compatibility:

```text
columns/                 Full columns: <document ID> <year_chapter> <0|1>
columns_clean/           Clean columns: <keyword ID>, then one binary value per row
file_ids.txt             Document IDs mapped to full tagged-corpus relative paths
index_keywords.txt       Keyword IDs mapped to normalized lemmas
columns_run.json         Input/output checksums, counts, groups, and logic provenance
```

Document IDs are assigned deterministically using natural ordering of group and relative path. The second field in each full column is the combined ENADE group (for example, `2009_c4`); `file_ids.txt` retains the full path (for example, `2009_c4/enade_2009_admin_b2a0b87461.txt`) so repeated basenames in different groups remain distinct. Each keyword is present (`1`) when its normalized lemma occurs at least once in the third tagged-text column; repeated occurrences still count once, `<unknown>` is ignored, and no POS filter is applied. These semantics intentionally preserve the original `columns.py` logic and therefore differ from the POS-filtered and unknown-lemma fallback behavior in `keylemmas.py`.

The recorded production inputs suggest 1,032 documents and 218 unique keywords; treat these as cross-checks, not fixed program requirements. An identical rerun verifies all outputs and makes no changes. Partial, conflicting, or unexpected files within either columns directory are preserved and reported rather than overwritten. Do not remove outputs automatically; to rebuild intentionally, use a separate output location or archive the existing outputs manually. A tagged-file checksum validates its recorded bytes, but a resumed `skipped` record does not prove that the bytes were generated from the current source chapter.

## 9. Merge columns into the SAS counts matrix

Run the dry run first. It verifies `columns_run.json`, `index_keywords.txt`, the ordered document IDs in `file_ids.txt`, every full and clean column checksum and row, and the expected keyword file set. It also checks that the matrix and its provenance can be published without overwriting existing files.

```shell
python merge_columns.py --dry-run
```

After a successful dry run, publish the matrix and provenance:

```shell
python merge_columns.py
```

The merge keeps the original SAS-compatible matrix format: one headerless, space-separated row per document, containing its document ID, combined `<year>_<chapter>` label, and one binary value per keyword in `index_keywords.txt` order. It reads the clean keyword columns for the values and verifies each against the matching full column and its document/group alignment; the output contains no keyword labels or other metadata.

By default the outputs are `sas/counts.txt` and `sas/merge_columns_run.json`. The provenance records counts, input checksums, and the matrix checksum and size. An identical rerun verifies the pair without changing it; partial or conflicting outputs are preserved and rejected. Relative paths resolve from the phase directory. Use `--columns-dir`, `--clean-dir`, `--file-ids`, `--keyword-index`, `--columns-manifest`, `--output`, and `--provenance` to override inputs or outputs; `--phase-dir` changes the base for relative paths.

The recorded production inputs suggest 1,032 documents and 218 keyword columns (220 fields per matrix row including the document ID and group). These are cross-checks, not fixed program limits.

## 10. Generate SAS format files

Run the dry run first. It verifies the ordered keyword index against `columns_run.json` and `sas/merge_columns_run.json`, checks their recorded checksums and keyword counts, and confirms that `sas/counts.txt` matches the matrix checksum in the merge provenance. It also checks that all three output files can be published without overwriting existing files.

```shell
python sas_formats.py --dry-run
```

After a successful dry run, generate the formats and provenance:

```shell
python sas_formats.py
```

Outputs:

- `sas/word_labels_format.sas` — `$lexlabels` maps strings such as `v000001` to the lemma.
- `sas/word_labels_full_format.sas` — `$lexlabelsfull` maps the same variable-name strings to the lemma plus ID.
- `sas/sas_formats_run.json` — keyword count and input/output paths, sizes, and SHA-256 checksums.

The recorded production data contains 218 keywords; this is a cross-check, not a fixed program limit. The format mapping, ID order, and quote escaping retain the original script's behavior. An identical rerun verifies all three outputs without rewriting them; partial or conflicting outputs are preserved and rejected. Relative paths resolve from this phase directory. Use `--keyword-index`, `--columns-manifest`, `--matrix`, and `--merge-provenance` to override inputs; use `--output-dir`, `--short-output`, `--full-output`, and `--provenance` to override output locations.

These formats label variable-name strings, not the matrix's binary values. Downstream SAS code must assign names such as `v000001` to matrix columns in `index_keywords.txt` order and load the formats in the SAS session where they are used. Confirm that the SAS session's encoding supports the UTF-8 lemmas before production. This script generates only the two format files above and their provenance; it does not create additional SAS helper formats.

## 11. Run SAS

## 12. Build factor loading lists

This stage reads the factor rotation results from SAS (`sas/output_cl_st2_ph1_fernanda/rotated.csv`) and maps variable IDs (`v000001` through `v000218`) to their lemmas using `index_keywords.txt`. It extracts primary factor loadings (where `loaded = 1`) and secondary loadings meeting the absolute loading cutoff (default: `0.3`).

Run the dry run first. It validates input files, calculates factor-pole assignments, checks that all output files can be published safely without colliding with inputs, and verifies existing outputs if present:

```shell
python factor_lists.py --dry-run
```

After a successful dry run, generate the factor lists and run provenance:

```shell
python factor_lists.py
```

Outputs:

```text
factors/
    f1_pos.txt, f1_neg.txt, f2_pos, f2_neg.txt, ...  (full word version: primary and secondary loadings)
    factor_lists_run.json                            (run metadata, counts, input/output checksums)
factors/var_id/
    f1_pos_var_id.txt, f1_neg_var_id.txt, ...        (variable ID version)
factors/primary_loadings/
    f1_pos.txt, f1_neg.txt, ...                      (primary loadings only)
```

Each factor list begins with the header line `variables loading on this pole = <count>` and lists entries sorted descending by absolute loading value. Secondary loadings meeting the cutoff are enclosed in outer parentheses, e.g., `(lemma (.35))` or `(v000001 (.35))`.

For the recorded production inputs:
- 4 rotated factors (`Factor1` through `Factor4`) across 8 factor poles (`f1_pos`, `f1_neg`, `f2_pos`, `f2_neg`, `f3_pos`, `f3_neg`, `f4_pos`, `f4_neg`).
- 206 loaded variables out of 214 rotation rows (8 unloaded variables).
- 25 total output files published (8 full word lists, 8 variable-ID lists, 8 primary loading lists, and `factor_lists_run.json`).

An identical rerun verifies all outputs without rewriting them; partial or conflicting outputs are preserved and rejected. Relative paths resolve from this phase directory. Use `--project`, `--sas-output-dir`, `--index-file`, `--output-dir`, `--cutoff`, `--provenance`, and `--phase-dir` to override paths or parameters.


## 13. Calculate corpus size summaries

This stage reads the tagged texts listed in `corpus/05_enade_tagged/enade_tagged_corpus.ndjson` and reconciles them against `corpus/04_enade/enade_target_corpus.ndjson`. It rejects missing, duplicate, failed, unlisted, unsafe, or inconsistent records and checks recorded file sizes and SHA-256 checksums before counting.

Run the dry run first; it validates the inputs and existing output without creating or changing files:

```shell
python corpus_size.py --dry-run
```

After a successful dry run, generate the summary:

```shell
python corpus_size.py
```

The output is `corpus_size/corpus_size.tsv`, with one row per naturally ordered `<year>_<chapter>` group and the existing `Strata`, `Text Count`, and `Word Count` TSV columns, followed by an `overall` row. Each manifest-listed text counts once. A tagged line counts as a word only when its token begins with a Unicode letter and its tag does not start with `PUNCT` or `SYM`; for example, `-la` and numeric-starting tokens are excluded, while `curso6` is included. Manifest `token_count` values are not used because they include tokens this word-count rule excludes.

An identical rerun verifies the existing TSV without rewriting it; a conflicting output is preserved and reported instead of overwritten. Relative `--output` paths resolve from the phase directory; `--phase-dir` changes that base. For the recorded corpus, compare the result with 1,032 texts in 42 groups; these are cross-checks, not fixed program limits.

## 14. Generate LaTeX/TikZ boxplots

This stage reads the scores-only TSV and matching model summaries exported by SAS:

- `sas/output_cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_scores_only.tsv`, using `year_chapter` for group labels and the detected `fac<n>` score columns.
- `sas/output_cl_st2_ph1_fernanda/params_year_chapter_f<n>.tsv`, using its finite `RSquare` value in the corresponding factor caption. If a parameter file includes `Dependent`, it must match that factor.

Run the dry run from the phase directory first. It validates score columns and group labels, checks that every group has at least one usable value for every factor, validates all matching parameter files, renders the complete output set, and checks for conflicting or partial existing outputs without writing files:

```shell
python latex_boxplots/latex_boxplots.py --dry-run
```

After a successful dry run, generate the snippets:

```shell
python latex_boxplots/latex_boxplots.py
```

By default the plotter groups by `year_chapter`, detects all `fac<n>` columns, and writes one `boxplot_f<n>_by_group.tex` per factor plus `mosaic_by_group.tex` under `latex_boxplots/slides/`. The mosaic retains the existing one-row layout and includes up to the first four detected factors.

For the currently checked-in SAS outputs, use 1,032 score rows, 42 groups, four detected factors, and captions of `97.88%`, `97.97%`, `97.15%`, and `96.61%` as cross-checks, not fixed limits.

The SAS phase models `year_chapter`; the scores TSV also exports `group` as an alias. If you plot with that alias, choose the corresponding model explicitly:

```shell
python latex_boxplots/latex_boxplots.py --group-column group --params-group year_chapter --dry-run
python latex_boxplots/latex_boxplots.py --group-column group --params-group year_chapter
```

`--params-group` defaults to `--group-column`; use it only when the SAS model filename uses another group name, and ensure that model corresponds to the plotted grouping. `--phase-dir` selects the phase directory; relative `--sas-output-dir` and `--output-dir` overrides resolve from it (not from the current working directory). For example:

```shell
python latex_boxplots/latex_boxplots.py \
  --phase-dir /path/to/cl_st2_ph1_fernanda \
  --sas-output-dir sas/output_cl_st2_ph1_fernanda \
  --output-dir latex_boxplots/slides
```

An identical rerun verifies and reuses the full output set. Partial or conflicting expected outputs are rejected without overwriting existing files, and outputs may not collide with input files. These files are LaTeX snippets, not standalone documents or PDFs; include them in a compatible LaTeX document with `float`, TikZ, PGFPlots, and its statistics library configured. The SAS results are inputs to this stage and are not modified.

## 15. Generate LaTeX ANOVA table

This stage reads the scores-only file to detect the available `fac<n>` dimensions, then reads the matching `year_chapter` ANOVA and parameter summaries:

- `sas/output_cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_scores_only.tsv`
- `sas/output_cl_st2_ph1_fernanda/anova_year_chapter_f<n>.tsv`
- `sas/output_cl_st2_ph1_fernanda/params_year_chapter_f<n>.tsv`

Run the generator from the phase directory:

```shell
python latex_anova_table.py
```

Output: `latex_tables/anova_year_chapter.tex`

The project name and default paths are based on the script's phase directory, so the command also works when launched from another current working directory. Use `--project`, `--effect`, `--input-dir`, `--output-dir`, `--caption`, and `--label` to override the corresponding defaults; relative input and output directory overrides are resolved from the phase directory, while absolute paths are preserved.

For the checked-in SAS results, cross-check the four F values against `1115.32`, `1164.71`, `823.63`, and `688.87`, and the R² percentages against `97.88`, `97.97`, `97.15`, and `96.61`. The generator selects the requested `Source` from `HypothesisType = 1`, falling back to the first Type I row if that source is absent. Existing output files are overwritten.

## 16. Generate LaTeX example extracts

This stage selects tagged chapter texts using each document's factor score and the group means. By default, the project name comes from the phase directory, the grouping is `year_chapter`, and all relative paths resolve from this phase directory rather than the current working directory.

Inputs:

- `sas/output_<project>/<project>_scores_only.tsv`, including `filename`, `year_chapter`, and `fac<n>` columns.
- `sas/output_<project>/means_year_chapter_f<n>.tsv` for each detected factor, with `year_chapter` and `Mean fac<n>` columns.
- `factors/f<n>_pos.txt` and `factors/f<n>_neg.txt`; unparenthesized entries are treated as primary lemmas for highlighting.
- `file_ids.txt`, mapping SAS IDs such as `t000001` to paths such as `2009_c4/enade_2009_admin_b2a0b87461.txt`.
- Tagged texts under `corpus/05_enade_tagged/<year>_<chapter>/`.

```shell
python examples.py
```

The script writes individual snippets under `examples/f<n>_pos/` and `examples/f<n>_neg/`. Since `examples/top_header` is provided, it also writes `examples/examples.tex`, which can be compiled with LuaLaTeX from the phase directory, for example:

```shell
lualatex -interaction=nonstopmode -halt-on-error examples/examples.tex
```

The header uses `fontspec` and the `DejaVu Serif` and `Noto Color Emoji` fonts; those fonts and the packages in the header must be available to LuaLaTeX.

The selection behavior is preserved: groups are ranked by descending mean for the positive pole and ascending mean for the negative pole; within each group, scores are sorted in the matching direction. The defaults select up to 20 examples from the top-ranked group and 10 from every other group for each pole, skipping only rows whose score is exactly zero. The score's sign is not checked against the pole. Each selected example contains the entire tagged chapter, not a short passage; with 42 groups and four factors, the quotas allow up to 3,440 chapter snippets.

Outputs are overwritten when names collide, old snippets are not removed, and the master document includes every `.tex` file present in each factor/pole output directory. Review or archive prior generated snippets before rerunning if stale examples must not appear. Missing tagged files are listed in phase-root `missing_files.txt`; the script does not perform manifest/checksum reconciliation or resolve the corpus's outstanding boundary/review audit flags, so consult the upstream corpus audit records before interpreting examples.

Use `--group` only when the scores and means files use another grouping column; `--project`, `--sas-output-dir`, `--tagged-base`, `--factor-folder`, `--examples-dir`, and `--file-ids` override defaults. Relative path overrides resolve from the phase directory, while absolute paths are preserved. `--top-group-examples` and `--other-group-examples` adjust the quotas. The script has no dry-run mode.

## 17. Generate score-details report

```shell
python score_details.py
```

Output: `examples/score_details.txt`
