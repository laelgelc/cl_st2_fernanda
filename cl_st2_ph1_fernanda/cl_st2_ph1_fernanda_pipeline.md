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
