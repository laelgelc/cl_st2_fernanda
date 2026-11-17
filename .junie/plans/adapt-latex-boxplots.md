---
sessionId: session-261117-162025-6x9n
---

# Requirements

### Goal
Adapt `latex_boxplots/latex_boxplots.py` to this phase’s existing SAS results without changing its boxplot statistics, outlier rules, natural ordering, TikZ layout, or four-panel mosaic logic.

### Expected behavior
- Group scores by `year_chapter` by default and use the matching SAS model’s R² in each caption.
- Generate one `boxplot_f<n>_by_group.tex` per detected factor and `mosaic_by_group.tex` under `latex_boxplots/slides/` by default. The current data has four factors, 1,032 rows, and 42 groups; these are cross-checks, not limits.
- Validate inputs before publishing; do not silently turn a missing or invalid R² into a plausible `0.00%`.
- Support a no-write dry run and protect existing output from conflicting or partial reruns, consistent with neighboring pipeline stages.
- Generating a complete LaTeX document or changing SAS analysis is out of scope.

# Technical Design

### Current implementation
- `sas/cl_st2_ph1_fernanda.sas` exports `<project>_scores_only.tsv` with `year_chapter`, its `group` alias, and `fac<n>` columns; it exports `params_year_chapter_f<n>.tsv` from a GLM using `year_chapter`. The scores file also contains keyword columns, which the plotter need not use.
- `latex_boxplots/latex_boxplots.py` already finds the correct project and scores file, but defaults to nonexistent `state` and reads `params_group_f<n>.tsv`; `read_rsquare` silently returns zero on failure.
- `factor_lists.py` and `corpus_size.py` demonstrate phase-relative overrides, dry-run validation, and safe reruns.

### Changes
- Default `--group-column` to `year_chapter`. Resolve model files as `params_<model-group>_f<n>.tsv`, defaulting the model group to the selected grouping column. Provide an explicit `--params-group` override for aliases or other SAS models; document that the chosen model must correspond to the plotted grouping (for example, `group` is the current SAS alias of `year_chapter`).
- Check the scores TSV, grouping labels, detected numeric factor values, and corresponding parameter files before writing. Require a finite `RSquare` and, when present, a matching `Dependent` factor; report a useful error rather than fabricate R². Permit missing individual scores as the existing plotter does, but reject a group with no usable values for a factor.
- Keep `compute_boxplot_stats`, outlier/mean calculations, label ordering, plot filenames, and mosaic extraction intact. Preserve the existing multiplication of SAS `RSquare` by 100.
- Make relative overrides phase-relative, add `--phase-dir` and `--dry-run`, and document the change from the original working-directory-relative overrides. Render and check the complete output set before publishing; reuse identical results and reject partial or conflicting expected outputs without overwriting them, following `factor_lists.py`’s staged publication pattern. Avoid collisions with input files.

### File structure
- Modify `cl_st2_ph1_fernanda/latex_boxplots/latex_boxplots.py` and section 14 of `cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_pipeline.md`.
- Add `cl_st2_ph1_fernanda/tests/test_latex_boxplots.py` using temporary TSVs and directories, following the existing `unittest` conventions.

### Risks
The existing one-row mosaic is limited to the first four factors and 42 labels may be crowded; preserve that layout rather than redesign it. Generated files are snippets requiring a compatible LaTeX document and TikZ/PGFPlots setup, not standalone PDFs.

# Testing

### Validation
- Use small fixtures to check grouping, natural label order and escaping, factor discovery, R² percentage, quartiles, whiskers, outliers, mean markers, and mosaic contents against the original plotting behavior.
- Check missing or malformed scores/parameters, nonnumeric or empty factor groups, mismatched factor metadata, custom group/model paths, phase-relative paths, dry-run no-write behavior, identical reruns, and preservation of partial or conflicting outputs.
- Run the adapted command against the available SAS outputs into a temporary directory: verify four plots and one mosaic, 42 groups, and captions of `97.88%`, `97.97%`, `97.15%`, and `96.61%`. Do not modify the source SAS results.

# Delivery Steps

### ✓ Step 1: Adapt SAS input and model mapping
The plotter reads the phase’s year/chapter scores and the corresponding SAS R² values.

- Update `latex_boxplots/latex_boxplots.py` defaults and parameter-file selection, including explicit model-group overrides for alternative grouping columns.
- Validate score and parameter inputs before generation without changing the existing statistical or TikZ algorithms.
- Add focused fixture tests for SAS mapping, numeric validation, and preserved plot statistics.

### ✓ Step 2: Make plot publication safe and reproducible
Plot output can be previewed and rerun without overwriting conflicting results.

- Add phase-relative path resolution and a no-write `--dry-run`.
- Validate the complete expected output set and use staged publication, reusing identical files and rejecting partial or conflicting results.
- Test custom paths, dry runs, input collisions, reruns, and mosaic generation with temporary directories.

### ✓ Step 3: Document and verify the pipeline stage
The phase pipeline explains how to generate and use the current year/chapter plots.

- Update section 14 of `cl_st2_ph1_fernanda_pipeline.md` with commands, inputs, outputs, model-group overrides, dependencies, and LaTeX snippet limitations.
- Run regression tests and exercise the real SAS results in a temporary output directory, checking four factor plots, the mosaic, group count, and R² captions.