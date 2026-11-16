# `select_kws_stratified.py` Development Specification

## 1. Programme Purpose & Scope

`select_kws_stratified.py` selects a small, balanced set of positive key lemmas (`POSKW`) from the ENADE group profiles produced by `keylemmas.py`. Each stratum is one `<year>_<chapter>` group. The selector consumes the upstream ranking as-is; it does not calculate new keyword statistics or rerank lemmas.

The programme reads group profiles from:

```text
corpus/06_enade_keylemmas/<year>_<chapter>.tsv
```

and publishes the per-group selections and one deduplicated keyword list under the proposed stage-7 directory:

```text
corpus/07_enade_kw_selected/
```

### Scope and Constraints

- **In Scope**:
  - Adapt the input and output defaults and documentation to the ENADE pipeline.
  - Preserve the existing lexical filters, source row ranking, natural stratum order, per-group quota, total-cap position, and output ordering.
  - Add a non-writing `--dry-run`, phase-directory-relative path resolution, safe output checks, and selection provenance.
  - Test the actual upstream TSV format, selection behavior, invalid inputs, and output safety.
- **Out of Scope / Non-Goals**:
  - Recomputing `LL`, changing POSKW classifications, or introducing a new ranking or significance threshold.
  - Topping up groups with terms from other groups, balancing after deduplication, or otherwise changing the stratified selection algorithm.
  - Changing the upstream `keylemmas.py` results or modifying the source group TSV files.

---

## 2. Research Context & Initial Selection Size

The current upstream manifest records 1,032 ENADE texts in 42 `<year>_<chapter>` groups. A rule of thumb of five texts per variable gives:

```text
1,032 texts / 5 texts per variable = 206.4 variables
```

An initial target of approximately 210 variables is therefore reasonable to investigate. The suggested first selection settings are:

```text
--per-group 5 --max-total 220
```

With 42 groups and a maximum of five selected lemmas per group, the selector can contribute at most 210 lemma occurrences before deduplication (`42 × 5`). Consequently, `--max-total 220` is an upper safety limit and will not bind for the current 42-group, five-per-group run. It is not a request to fill 220 places or a guarantee of 210 unique lemmas.

Some groups may contain fewer than five eligible POSKW rows, and lemmas may be selected in more than one group. Both conditions reduce the number of unique lemmas; the selector must not compensate by taking extra rows from another group. Treat 42 groups and 1,032 texts as a run-specific cross-check, not fixed programme constants. Confirm them against the active upstream manifest before interpreting a run.

---

## 3. Inputs & Upstream Contract

### 3.1 Discovery and Paths

Paths are resolved relative to the phase directory `cl_st2_ph1_fernanda/`, independently of the caller's current working directory.

| Resource | Default Path | Format | Description |
|---|---|---|---|
| Key-lemma input directory | `corpus/06_enade_keylemmas` | Directory | Contains one group profile per `<year>_<chapter>`. |
| Group profile | `corpus/06_enade_keylemmas/<year>_<chapter>.tsv` | UTF-8 TSV | Ranked key-lemma rows emitted by `keylemmas.py`. |
| Upstream run manifest | `corpus/06_enade_keylemmas/keylemmas_run.json` | JSON | Provides the input run's group, document, and checksum metadata for validation/provenance. |

The selector supports `.tsv` and legacy `.txt` group files. If both extensions exist for the same stratum, `.tsv` takes precedence. Ignore hidden files, metadata files, and the consolidated `keywords` file. Discover groups by filename stem and sort their names in natural order (for example, `2009_c4`, `2009_c5`, `2010_c4`).

For an ENADE run, the expected group stem pattern is `<year>_<chapter>` (for example, `2009_c4`). The implementation should reject a missing input directory or a directory with no usable group files and should report the offending path clearly. If upstream manifest validation is implemented, it must detect missing, unexpected, or inconsistent groups without silently changing selection order.

### 3.2 TSV Schema and Ranking

The actual stage-6 header is:

```text
lemma  target_count  comparison_count  target_per_1k  comparison_per_1k  expected  LL  diff_percent  status
```

The fields are tab-separated. `lemma` is the first column and `status` is the final column. The stage-6 producer writes rows in status priority order (`POSKW`, `NEGKW`, `NOTKW`), then descending `LL`, then ascending lemma. The selector must retain the source order among rows that pass its filters; it must not calculate or apply a different ranking.

The loader skips the header, reads the first field as the lemma and the final field as the status, and accepts only exact `POSKW` statuses. The legacy whitespace-separated format remains supported for compatibility. Blank lines and malformed rows with fewer than two fields are ignored as in the existing loader. UTF-8 input is required so accented lemmas are preserved.

---

## 4. Command-Line Interface

Retain the existing option names and aliases:

| Option | ENADE default / requirement | Description |
|---|---|---|
| `--input`, `--input-dir` | `corpus/06_enade_keylemmas` | Input directory of group profiles. |
| `--output`, `--output-dir` | `corpus/07_enade_kw_selected` | Stage-7 output directory. |
| `--per-group` | Required; initially `5` | Maximum eligible POSKW lemmas taken from each group. Must be greater than zero. |
| `--max-total` | Optional; initially `220`; `0` means no cap | Maximum length of the combined list before deduplication. Must be non-negative. |
| `--dry-run` | New flag | Validate inputs and show planned counts without creating or changing files or directories. |

Initial pipeline invocation:

```shell
python select_kws_stratified.py \
    --input corpus/06_enade_keylemmas \
    --output corpus/07_enade_kw_selected \
    --per-group 5 \
    --max-total 220 \
    --dry-run
```

After reviewing the dry-run report, omit `--dry-run` to publish the outputs. Invalid numeric values must fail with a clear command-line error before any output is written.

---

## 5. Selection and Filtering Contract

The selection behavior is intentionally unchanged:

1. Discover supported group files and order group names naturally.
2. Read each group file in source order and keep only rows whose final status is exactly `POSKW`.
3. Keep lemmas that are lowercase and consist of alphabetic Unicode parts separated, optionally, by internal hyphens. A valid lemma has at least two alphabetic characters overall.
4. Reject uppercase letters, digits, punctuation other than valid internal hyphens, leading/trailing/repeated hyphens, and lemmas with fewer than two alphabetic characters.
5. For each group, select the first `--per-group` eligible rows. If fewer are available, keep all available rows; do not top up from another group.
6. Concatenate the per-group selections in natural group order.
7. If `--max-total` is positive, truncate that concatenated sequence to the cap **before deduplication**. Thus, if the cap ever binds, earlier naturally ordered groups have priority in the consolidated list.
8. Deduplicate the capped consolidated sequence by exact lemma string and sort the unique values for `keywords.txt`. Do not normalize spellings or Unicode as part of deduplication.

The per-group files contain each group's full quota selection in source ranking order. They are written before and independently of the consolidated `--max-total` truncation; the total cap does not truncate per-group files. The consolidated output is a globally unique list, not a group-balanced list after deduplication.

---

## 6. Outputs

On a successful production run, publish:

```text
corpus/07_enade_kw_selected/
├── 2009_c4.txt
├── 2009_c5.txt
├── ...
├── keywords.txt
└── select_kws_stratified_run.json
```

- `<year>_<chapter>.txt`: one selected lemma per line, preserving the group's source ranking order and containing no more than `--per-group` rows.
- `keywords.txt`: one exact-deduplicated lemma per line, sorted alphabetically by the implementation's deterministic string ordering.
- `select_kws_stratified_run.json`: provenance and count summary for the selection run.

The run report should state the resolved input and output directories, run timestamp, CLI parameters, input group names and SHA-256 checksums, eligible POSKW count and selected count per group, total selected occurrences before the cap, count after truncation, unique output count, duplicate count, and output checksums. Counts must distinguish rows/occurrences from unique lemmas. They must be generated from the files actually read rather than hard-coded to the current run's 42 groups.

---

## 7. Dry Run, Path Safety & Reruns

The new dry run must exercise discovery, parsing, filtering, quotas, deduplication, cap calculation, and output-path validation, then print a concise summary including group count, per-group availability/selection, total before and after the cap, expected unique count, and duplicate count. It must create no directories or files and must not modify existing outputs.

Before a production write:

- Resolve input and output paths against the phase directory and reject an output path that is the input directory, contains the input directory, or is contained within it. This prevents output files from being mistaken for inputs on a later run.
- Do not overwrite or partially replace existing output files. An identical rerun may verify the existing run manifest and checksums and exit without changes; conflicting parameters, inputs, checksums, or unexpected output files must stop with a diagnostic. No destructive force option is required for the initial adaptation.
- Validate all inputs and planned outputs before creating the destination, and publish atomically (for example, via a staging directory and final rename) so an error cannot leave a partial stage.
- Preserve the stage-6 inputs and all pre-existing files on every failure path.

---

## 8. Testing & Acceptance Criteria

Automated tests should use small temporary fixtures and cover at least:

1. **Actual TSV format**: header and all nine columns; first-column lemma, last-column status; UTF-8 accented lemmas and valid compounds such as `vis-à-vis` survive.
2. **Legacy input**: whitespace-separated `.txt` remains readable, and `.tsv` wins when both formats exist for the same group.
3. **Status and lexical filters**: retain exact `POSKW`; exclude `NEGKW` and `NOTKW`; reject uppercase, digits, punctuation, malformed hyphens, and too-short shapes.
4. **Ranking and quota**: selected rows preserve upstream order, selection stops at the per-group quota, and groups with fewer candidates remain below quota without top-up.
5. **Natural ordering and duplicates**: verify natural group order, exact deduplication across groups, alphabetically sorted `keywords.txt`, and source-ordered per-group files.
6. **Cap semantics**: prove truncation occurs before deduplication, that the cap can favor earlier groups, and that per-group files are unaffected by the consolidated cap. Verify `--max-total 0` means uncapped.
7. **Initial sizing arithmetic**: with 42 fixture groups and quota 5, the pre-dedup selection cannot exceed 210; `--max-total 220` does not increase that amount and may produce fewer than 210 unique lemmas.
8. **Errors and safety**: missing input directory, no usable input files, invalid/non-positive `--per-group`, negative `--max-total`, input/output overlap, and conflicting existing output all fail safely.
9. **Dry run and repeatability**: dry run creates no files or directories; a successful identical rerun is a no-op; input changes or conflicting output are reported without overwriting data.

The adaptation is accepted when the documented initial command selects up to five ranked POSKW lemmas from each discovered group, applies the cap before deduplication, emits stable per-group and consolidated files, and reports counts/checksums without modifying upstream data. No test should require exactly 210 unique lemmas: that number is an upper bound for 42 groups at quota five, not a guaranteed result.

---

## 9. Pipeline Integration & Review Note

After implementation, update section 7 of `cl_st2_ph1_fernanda_pipeline.md` to use the ENADE input and stage-7 output paths, show the recommended dry-run and production commands, and explain the selection count caveat. The pipeline should describe `corpus/07_enade_kw_selected/keywords.txt` as the consolidated output.

The current `keylemmas_run.json` records `stopword_count: 0`. Confirm that this is intentional before interpreting the selected vocabulary. Stopword configuration is an upstream review item and must not be silently corrected or compensated for by the selector.