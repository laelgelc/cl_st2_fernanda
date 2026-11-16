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

The programme reads the validated tagged-file records in `corpus/05_enade_tagged/enade_tagged_corpus.ndjson`. For each (`year`, `chapter`) group it compares lemma presence in that group with all files in every other group combined. A lemma counts at most once per file; the per-1,000 rates are file-prevalence rates, not token frequencies.

The version-controlled `keylemmas_pos.txt` profile selects base POS categories (`NOUN`, `VERB`, and `ADJ`). `keylemmas_stopwords.txt` is an initially empty project-specific exclusion list. Alternate profiles can be provided with `--pos-config` and `--stopwords`; the selected paths, hashes, effective values, tagged-file hashes, group definitions, and TSV checksums are recorded in `keylemmas_run.json`.

### Dry run

```shell
python keylemmas.py --dry-run
```

### Production run

```shell
python keylemmas.py
```

The output directory `corpus/06_enade_keylemmas/` contains one UTF-8 TSV per group, named `<year>_<chapter>.tsv`, and `keylemmas_run.json`. TSV columns include present/absent/total file counts, prevalence per 1,000 files, the signed prevalence difference, unadjusted `g2`, and descriptive direction. Every eligible corpus lemma is reported; there is no target-only cutoff.

These are exploratory file-presence comparisons. No significance threshold or multiple-testing correction is applied, and chapters from the same report may not be independent observations. An identical rerun verifies existing output without changing it; conflicting or extra files are preserved and reported rather than overwritten.
