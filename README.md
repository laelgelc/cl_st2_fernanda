# Corpus Linguistics - Study 2 - Fernanda

## Phase 1 - Data Collection, Preprocessing and Lexical Multi-dimensional Analysis

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
