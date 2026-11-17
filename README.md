# Corpus Linguistics - Study 2 - Fernanda

## Phase 1 - ENADE Course Reports Lexical Multi-dimensional Analysis

### Data Collection, Preprocessing, and Target Corpus Compilation

Phase 1 has assembled the available [ENADE course reports](https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-educacionais/enade/resultados), indexed their PDFs and extracted pages, selected pages from three report sections, made manual revisions to the selections, and produced LLM-denoised text. The indexed reports span 2009–2023; this range does not imply that reports are available for every year.

The chapter identifiers used in the metadata are internal labels for these target section titles:

- `c4` — *Percepção sobre a Prova* (Perception of the Exam)
- `c5` — *Distribuição dos Conceitos* (Distribution of Scores)
- `c6` — *Análise Técnica da Prova* (Technical Analysis of the Exam)

### Work completed

1. **Source and page metadata.** The [Jupyter notebook](cl_st2_ph1_fernanda/cl_st2_ph1_fernanda.ipynb) organizes source-report metadata and page-level PDF/text metadata. The indexed source PDFs are in [`corpus/00_sources/enade_raw`](cl_st2_ph1_fernanda/corpus/00_sources/enade_raw/); the current manifests are [`enade_dataset.ndjson`](cl_st2_ph1_fernanda/corpus/enade_dataset.ndjson) and [`enade_pdf_pages_dataset.ndjson`](cl_st2_ph1_fernanda/corpus/enade_pdf_pages_dataset.ndjson). Page PDFs and extracted text are stored in [`corpus/01_enade_pdf_pages`](cl_st2_ph1_fernanda/corpus/01_enade_pdf_pages/).
2. **Section selection and revision.** [`enade_clean_up.py`](cl_st2_ph1_fernanda/enade_clean_up.py) detects pages for the three section titles. Selected page text is stored in [`corpus/02_enade_selected_chapters`](cl_st2_ph1_fernanda/corpus/02_enade_selected_chapters/), with the finalized page list in [`enade_chapters_clean_up_revised_dataset.ndjson`](cl_st2_ph1_fernanda/corpus/enade_chapters_clean_up_revised_dataset.ndjson). Automated boundaries can produce false positives; the [manual cleanup notes](cl_st2_ph1_fernanda/corpus/enade_chapters_clean_up_dataset_c6_manual.md) document review of known issues, including chapter 6 propagation and chapter 5 false positives.
3. **Denoising.** [`llm_denoise.py`](cl_st2_ph1_fernanda/llm_denoise.py) processes selected pages using the [denoising prompt](cl_st2_ph1_fernanda/denoising_prompts/denoising_v1.md), with neighboring pages as context. The prompt preserves prose while excluding tables and graphs; outputs and page-level audit data are in [`corpus/03_enade_selected_chapters_denoised`](cl_st2_ph1_fernanda/corpus/03_enade_selected_chapters_denoised/).

The [latest recorded run summary](cl_st2_ph1_fernanda/corpus/03_enade_selected_chapters_denoised/runs/20261115T092418Z_000ea222/summary.json) reports 30,770 selected pages processed successfully across 1,032 complete chapter groups, with no failed pages. Processing completion is not the same as linguistic validation: the run also records 6,831 boundary flags and 23,583 review notes. These flagged boundaries and notes still need human inspection; [`chapter_status.ndjson`](cl_st2_ph1_fernanda/corpus/03_enade_selected_chapters_denoised/chapter_status.ndjson) records per-chapter status and review information.

Assembled chapter filenames include a suffix containing the first 10 hexadecimal characters of the SHA-256 hash of the source PDF's path, not its contents. Chapters from the same PDF share this suffix, which helps distinguish reports with similar names; the source mapping is recorded in `chapter_status.ndjson`.

For commands and the full sequence, see the [Phase 1 pipeline](cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_pipeline.md).

### Lexical Multi-dimensional Analysis

#### Tag the corpus

The compiled target corpus is organized by year and chapter in [`corpus/04_enade`](cl_st2_ph1_fernanda/corpus/04_enade/), with source and selection provenance recorded in [`enade_target_corpus.ndjson`](cl_st2_ph1_fernanda/corpus/04_enade/enade_target_corpus.ndjson). The corpus contains 1,032 texts across 42 year/chapter groups and remains marked `accepted_subject_to_audit`; this records the agreed selection, not resolution of the denoising boundary flags or review notes. [`tag.py`](cl_st2_ph1_fernanda/tag.py) applies the Portuguese TreeTagger model (`tree-tagger-portuguese2`) to produce token, POS-tag, and lemma columns. Tagged files and corpus-level provenance are in [`corpus/05_enade_tagged`](cl_st2_ph1_fernanda/corpus/05_enade_tagged/).

#### Extract key lemmas by group

[`keylemmas.py`](cl_st2_ph1_fernanda/keylemmas.py) compares each year/chapter group with the documents in all other groups combined. It uses document presence (a lemma counts at most once per text), not raw token frequency, to calculate per-1,000-document prevalence rates and log-likelihood scores; `POSKW`, `NEGKW`, and `NOTKW` classifications use an `LL` threshold of 3.84. The active POS prefixes (`NOUN`, `VERB`, `ADJ`) and stopwords are configurable in [`keylemmas_pos.txt`](cl_st2_ph1_fernanda/keylemmas_pos.txt) and [`keylemmas_stopwords.txt`](cl_st2_ph1_fernanda/keylemmas_stopwords.txt); the current run manifest records seven stopwords. Group-level profiles and run provenance are in [`corpus/06_enade_keylemmas`](cl_st2_ph1_fernanda/corpus/06_enade_keylemmas/), with counts, configuration hashes, and output checksums in [`keylemmas_run.json`](cl_st2_ph1_fernanda/corpus/06_enade_keylemmas/keylemmas_run.json).

#### Select a stratified keyword set

[`select_kws_stratified.py`](cl_st2_ph1_fernanda/select_kws_stratified.py) selects the highest-ranked eligible `POSKW` lemmas separately within each year/chapter group. In the recorded run, eight lemmas were selected for each of 42 groups; the 400-occurrence cap was applied before deduplication and did not bind. The result was 336 selected occurrences, 218 unique keywords, and 118 duplicates removed. The ranked group selections, consolidated [`keywords.txt`](cl_st2_ph1_fernanda/corpus/07_enade_kw_selected/keywords.txt), and run details are in [`corpus/07_enade_kw_selected`](cl_st2_ph1_fernanda/corpus/07_enade_kw_selected/) and [`select_kws_stratified_run.json`](cl_st2_ph1_fernanda/corpus/07_enade_kw_selected/select_kws_stratified_run.json). This produces the candidate keyword set used in the subsequent analysis.

#### Build the keyword matrix

[`columns.py`](cl_st2_ph1_fernanda/columns.py) creates binary keyword-presence columns for the texts and records document and keyword mappings. Its [`columns_run.json`](cl_st2_ph1_fernanda/columns_run.json) records 1,032 documents and 218 keywords. [`merge_columns.py`](cl_st2_ph1_fernanda/merge_columns.py) combines the clean columns into the SAS counts matrix ([`counts.txt`](cl_st2_ph1_fernanda/sas/counts.txt)); [`merge_columns_run.json`](cl_st2_ph1_fernanda/sas/merge_columns_run.json) records the matrix dimensions and input provenance. [`sas_formats.py`](cl_st2_ph1_fernanda/sas_formats.py) generates SAS formats mapping keyword variables to lemmas, with provenance in [`sas_formats_run.json`](cl_st2_ph1_fernanda/sas/sas_formats_run.json).

#### Run SAS LMDA and extract factors

The external SAS LMDA workflow has been run using the counts matrix and keyword formats. Its recorded outputs include rotated loadings, document scores, group means, ANOVA and parameter summaries, and communalities under [`sas/output_cl_st2_ph1_fernanda`](cl_st2_ph1_fernanda/sas/output_cl_st2_ph1_fernanda/); these results contain four factors. [`factor_lists.py`](cl_st2_ph1_fernanda/factor_lists.py) converts the rotation output into positive and negative loading lists, including primary and qualifying secondary loadings. The generated lists and processing details are in [`factors`](cl_st2_ph1_fernanda/factors/) and [`factor_lists_run.json`](cl_st2_ph1_fernanda/factors/factor_lists_run.json).

#### Reporting and interpretation

The post-SAS scripts produce corpus-size summaries ([`corpus_size.tsv`](cl_st2_ph1_fernanda/corpus_size/corpus_size.tsv)), factor-score plots and group mosaics ([`latex_boxplots/slides`](cl_st2_ph1_fernanda/latex_boxplots/slides/)), an ANOVA table ([`anova_year_chapter.tex`](cl_st2_ph1_fernanda/latex_tables/anova_year_chapter.tex)), selected examples ([`examples`](cl_st2_ph1_fernanda/examples/)), score details ([`score_details.txt`](cl_st2_ph1_fernanda/examples/score_details.txt)), and full-text examples for review ([`examples_txt`](cl_st2_ph1_fernanda/examples_txt/)). [`interpretation_prompts.py`](cl_st2_ph1_fernanda/interpretation_prompts.py) assembles factor-pole prompts in [`interpretation/input`](cl_st2_ph1_fernanda/interpretation/input/); the repository also contains generated responses in [`interpretation/output`](cl_st2_ph1_fernanda/interpretation/output/). Generating new responses with [`generate_interpretation_gpt.py`](cl_st2_ph1_fernanda/generate_interpretation_gpt.py) requires an available model and `OPENAI_API_KEY`. These artifacts document completed processing stages, but do not by themselves resolve the outstanding corpus audit flags or establish that statistical reports and generated interpretations have been substantively reviewed.

For all commands, validation rules, and rerun guidance—including the instruction not to delete `columns/` or `columns_clean/` to force a rebuild—see the [detailed Phase 1 pipeline](cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_pipeline.md) and its [pipeline description](cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_pipeline_description.md).