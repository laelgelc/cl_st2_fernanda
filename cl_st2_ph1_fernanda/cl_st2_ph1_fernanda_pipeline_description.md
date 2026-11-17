# cl_st2_ph1_fernanda - Phase 1 Pipeline Description

This document summarizes the 20-stage Phase 1 workflow, from ENADE report metadata and chapter preparation through lexical multi-dimensional analysis (LMDA), reporting, and factor-pole interpretation. Run commands from the [`cl_st2_ph1_fernanda`](.) phase directory. See the [detailed pipeline](cl_st2_ph1_fernanda_pipeline.md) for commands, validation rules, configuration options, and output layouts.

The chapter labels `c4`, `c5`, and `c6` are project-internal labels for *Percepção sobre a Prova*, *Distribuição dos Conceitos*, and *Análise Técnica da Prova*; they are not guaranteed to match literal chapter numbers in every report edition. The indexed source reports span 2009–2023, which does not mean that every year is represented.

| Step | Programme / command | Purpose | Main inputs | Main outputs |
|-----:|---------------------|---------|-------------|--------------|
| 1 | [Jupyter notebook](cl_st2_ph1_fernanda.ipynb) | Organizes source-report and PDF-page metadata. | ENADE source PDFs | `corpus/enade_dataset.ndjson`; `corpus/enade_pdf_pages_dataset.ndjson`; page PDFs and extracted text |
| 2 | [`enade_clean_up.py`](enade_clean_up.py), notebook, [manual cleanup notes](corpus/enade_chapters_clean_up_dataset_c6_manual.md) | Detects pages for the three target sections, copies selected text, and manually revises false-positive selections. | Page metadata and extracted text | `corpus/02_enade_selected_chapters/`; `corpus/enade_chapters_clean_up_revised_dataset.ndjson` |
| 3 | [`llm_denoise.py`](llm_denoise.py) | Denoises selected pages using a prompt and neighboring-page context. | Revised selection manifest; [`denoising_v1.md`](denoising_prompts/denoising_v1.md) | `corpus/03_enade_selected_chapters_denoised/`; run and chapter-status records |
| 4 | [`organise_enade_corpus.py`](organise_enade_corpus.py) | Validates selection and denoising records, then publishes complete chapters grouped by year and chapter. | Revised page manifest; source metadata; denoising status | `corpus/04_enade/<year>_<chapter>/`; target-corpus manifests in NDJSON, TSV, and XLSX |
| 5 | [`tag.py`](tag.py) | Applies the Portuguese TreeTagger model to produce token, POS-tag, and lemma columns. | Finalized target corpus | `corpus/05_enade_tagged/`; tagging manifests; `tagging_failures.ndjson` |
| 6 | [`keylemmas.py`](keylemmas.py) | Compares document-level lemma presence in each year/chapter group with all other groups; uses POS and stopword configurations. | Tagged corpus; POS and stopword configuration | `corpus/06_enade_keylemmas/<year>_<chapter>.tsv`; `keylemmas_run.json` |
| 7 | [`select_kws_stratified.py`](select_kws_stratified.py) | Selects ranked `POSKW` lemmas separately for each year/chapter group and creates a deduplicated keyword list. | Group key-lemma profiles | Per-group selections; `corpus/07_enade_kw_selected/keywords.txt`; run manifest |
| 8 | [`columns.py`](columns.py) | Builds binary keyword-presence columns per text and records document and keyword mappings. | Selected keyword list; tagged and target-corpus manifests | `columns/`; `columns_clean/`; `file_ids.txt`; `index_keywords.txt`; `columns_run.json` |
| 9 | [`merge_columns.py`](merge_columns.py) | Merges clean columns into the headerless matrix expected by the SAS workflow. | Column outputs and provenance | `sas/counts.txt`; `sas/merge_columns_run.json` |
| 10 | [`sas_formats.py`](sas_formats.py) | Maps SAS keyword-variable IDs to readable lemmas. | Ordered keyword index; verified matrix provenance | `sas/word_labels_format.sas`; `sas/word_labels_full_format.sas`; format run manifest |
| 11 | External SAS LMDA workflow | Runs the factor analysis using the counts matrix and keyword formats. | `sas/counts.txt`; SAS format files | Rotation, scores, group means, ANOVA, and parameter outputs under `sas/output_cl_st2_ph1_fernanda/` |
| 12 | [`factor_lists.py`](factor_lists.py) | Converts SAS rotation results into positive/negative factor loading lists, including primary and qualifying secondary loadings. | `rotated.csv`; `index_keywords.txt` | `factors/`; `factors/var_id/`; `factors/primary_loadings/`; run manifest |
| 13 | [`corpus_size.py`](corpus_size.py) | Counts texts and words by year/chapter group and overall, reconciling tagged files with corpus manifests. | Target and tagged-corpus manifests and texts | `corpus_size/corpus_size.tsv` |
| 14 | [`latex_boxplots/latex_boxplots.py`](latex_boxplots/latex_boxplots.py) | Generates factor-score boxplot and mosaic LaTeX/TikZ snippets, grouped by `year_chapter`. | SAS scores-only and parameter summaries | `latex_boxplots/slides/` |
| 15 | [`latex_anova_table.py`](latex_anova_table.py) | Produces an ANOVA summary table for the `year_chapter` effect. | SAS ANOVA and parameter summaries; scores-only file | `latex_tables/anova_year_chapter.tex` |
| 16 | [`examples.py`](examples.py) | Selects high-scoring tagged chapters by factor pole and group, highlighting primary loading lemmas. | SAS scores and group means; factor lists; tagged texts; document IDs | `examples/` snippets and `examples/examples.tex` |
| 17 | [`score_details.py`](score_details.py) | Reports each text's factor scores and the active loading words present. | SAS scores and formats; variable-ID loading lists; document IDs | `examples/score_details.txt` |
| 18 | [`examples_txt.py`](examples_txt.py) | Writes selected full-text chapters with score metadata and loading words for review. | SAS scores and means; tagged and full-text chapters; score-details report | `examples_txt/` |
| 19 | [`interpretation_prompts.py`](interpretation_prompts.py) | Assembles one text prompt per factor pole from means, factor loadings, examples, and score details; does not call an LLM. | Factor lists; SAS means; plaintext examples; score-details report | `interpretation/input/` |
| 20 | [`generate_interpretation_gpt.py`](generate_interpretation_gpt.py) | Submits prompt files to the configured GPT model. | `interpretation/input/`; API credentials and an available model | `interpretation/output/`; run log and any failed-prompt list |

## Pipeline Overview

| Stage | Steps | Summary |
|-------|------:|---------|
| Collection and corpus preparation | 1–4 | Assemble source/page metadata, select and revise chapter pages, denoise text, and publish the year/chapter target corpus. |
| Lexical preparation | 5–7 | Tag the corpus, extract group-level key lemmas, and select candidate keywords. |
| Matrix and LMDA | 8–12 | Build and validate the binary keyword matrix, run SAS LMDA, and create factor loading lists. |
| Post-SAS reporting | 13–18 | Produce corpus summaries, plots, ANOVA tables, selected examples, and score details. |
| Interpretation | 19–20 | Build factor-pole prompts, then optionally submit them to GPT for responses. |

## Notes

- The latest recorded denoising run processed 30,770 selected pages across 1,032 complete chapter groups with no failed pages. It also recorded 6,831 boundary flags and 23,583 review notes; these still require human inspection. The target corpus status `accepted_subject_to_audit` does not mean those flags are resolved.
- The published keyword-selection run selected eight lemmas for each of 42 groups with a 400-occurrence cap, yielding 336 selected occurrences and 218 unique keywords (118 duplicates removed); the cap did not bind. The selector section's older prose still mentions five per group and a cap of 220, while its command and recorded run use eight and 400. The key-lemma run manifest records seven stopwords, despite the stale zero-stopword note in that section.
- The SAS rotation and score files are present as inputs for downstream stages. Their presence does not establish that every report, example, prompt, or interpretation has been generated or reviewed.
- Do not delete `columns/` or `columns_clean/` to force a rebuild: the column and matrix stages verify identical outputs and preserve partial or conflicting outputs. Other downstream generators vary: some overwrite matching files and leave stale files in place, while GPT submission skips same-named existing responses by default. Check each stage's rerun guidance in the [detailed pipeline](cl_st2_ph1_fernanda_pipeline.md) before rerunning.
- `generate_interpretation_gpt.py` requires an available model and `OPENAI_API_KEY` in the shell environment or `env/.env`. Keep credentials out of version control, and review generated interpretations before treating them as research findings.