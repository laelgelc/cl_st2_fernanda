# `keylemmas.py` Programme Development Specification

## 1. Purpose and scope

Adapt `keylemmas.py` to identify lemmas whose **presence across tagged chapter files** differs between one ENADE year–chapter group and the rest of the corpus. Each group, identified by (`year`, `chapter`), is analysed once as the target; the comparison consists of all files belonging to every other group combined. A lemma contributes at most one presence to any one file, regardless of how many times it occurs there.

The programme reads the canonical tagged-corpus manifest and its referenced files, applies version-controlled POS and stopword profiles, computes descriptive prevalence and a 2×2 log-likelihood statistic, and writes deterministic per-group TSV results with run provenance. It does not modify tagged files, manifests, or earlier pipeline stages.

The first implementation is exploratory. The significance threshold, multiple-testing correction, and any inferential classification policy have not been approved; the programme must not label lemmas as statistically significant or as `POSKW`/`NEGKW` until those research decisions are made and documented.

## 2. Inputs, defaults, and paths

Resolve all default and relative CLI paths against the phase directory containing `keylemmas.py`, not against the caller's current working directory. Use `pathlib` for path handling and write only phase-relative paths to provenance.

| Resource | Default path | Contract |
| --- | --- | --- |
| Tagged-corpus manifest | `corpus/05_enade_tagged/enade_tagged_corpus.ndjson` | Canonical NDJSON input; one record per tagged chapter. |
| Tagged chapter files | Paths in `tagged_chapter_path` | UTF-8, tab-delimited token, tag, and lemma rows. |
| POS profile | `keylemmas_pos.txt` | UTF-8 base POS categories, one per line; initial values are `NOUN`, `VERB`, and `ADJ`. |
| Stopword profile | `keylemmas_stopwords.txt` | UTF-8 lemmas, one per line; start empty to preserve current behavior. |
| Output directory | `corpus/06_enade_keylemmas` | One TSV per `year_chapter` group and one run-provenance JSON file. |

The two configuration files are intended to be version controlled and created alongside the programme when it is implemented. Both formats allow blank lines and lines whose first non-whitespace character is `#` as comments. POS values are base categories, not arbitrary tag prefixes. CLI overrides may select alternate profiles, but the selected path and file hash must be recorded for every run.

The observed tagged manifest includes `year`, `chapter`, `target_subdirectory`, `filename`, `tagged_chapter_path`, `tagged_sha256`, `tagged_size_bytes`, `token_count`, `tagger_command`, and `status`, as well as source-file provenance fields. Treat `tagged_chapter_path` as relative to the phase directory, consistent with the existing pipeline manifests.

## 3. Manifest and file validation

1. Read the manifest as UTF-8 NDJSON, one JSON object per non-blank line. Reject an empty manifest, malformed JSON, non-object records, missing required values, and invalid value types; diagnostics must include the manifest path and line number.
2. Require `year` to be a four-digit string and `chapter`, `target_subdirectory`, `filename`, and `tagged_chapter_path` to be non-empty strings. Require `year`, `chapter`, and `filename` to be safe single path components (not `.`, `..`, or containing path separators); require `status == "success"`, a valid lowercase or uppercase 64-character hexadecimal SHA-256, and a non-negative integer `tagged_size_bytes`. Reject rather than silently omit any unsuccessful or malformed record.
3. Use (`year`, `chapter`) as the group identity. Multiple records per group are expected. Verify that every record for a group has the same `target_subdirectory`, and that its value is the expected `<year>_<chapter>` directory name. Do not group by filename or basename: the same filename may occur in multiple groups.
4. Reject duplicate tagged paths and duplicate output identities (`year`, `chapter`, `filename`), but do not reject repeated group identities. Resolve each tagged path against the phase directory, require a readable regular file inside `corpus/05_enade_tagged`, and reject paths that escape the tagged root (including through symlinks).
5. Recompute the tagged file's byte size and SHA-256 and require an exact match to the manifest. Do not proceed with partially validated inputs. The hash of the exact manifest bytes and every validated tagged-file path/hash/size must be available to the run-provenance record.
6. Require at least two distinct groups and at least one file in every target and comparison set. Report totals for groups, files, and any validation failure; do not use a hard-coded production file count as a programme requirement.

## 4. Configuration and lemma extraction

### POS profile

For each token row, split the POS tag at the first `.` and compare that base category exactly (after stripping whitespace and normalizing the category to uppercase) with the configured set. For example, `NOUN.Masc.Sing` matches `NOUN`; an unrelated category merely beginning with the same characters must not match. Use the actual ENADE tagged-file format, not a different tagset described in older examples.

### Stopwords and normalization

Normalize lemmas and stopword entries identically using this order: strip surrounding whitespace, apply Unicode NFC, apply Unicode `casefold()`, then apply NFC again. Ignore blank/comment-only stopword lines. Record the source configuration bytes' SHA-256 and the effective normalized POS categories and stopword values in run provenance so that changes are traceable.

Use the third tab-delimited field as the lemma. If it is empty or equals `<unknown>` after normalization, use the first field (surface token) instead. Ignore a candidate if it is empty, is a configured stopword, or contains fewer than two Unicode alphabetic characters (`str.isalpha`). These retain the prototype's fallback and short-form exclusions while making their behavior explicit.

Tagged rows are expected to contain exactly three tab-separated fields. Ignore blank lines; reject a nonblank malformed row with the tagged path and line number rather than silently changing counts. After POS, fallback, normalization, and exclusion rules, add a lemma to that file's presence set only once.

## 5. Group comparison and statistics

For each target group `g`:

- The target file set contains all validated tagged files whose (`year`, `chapter`) equals `g`.
- The reference file set contains all validated tagged files from every other group combined.
- The candidate vocabulary is the union of eligible lemmas present anywhere in the complete corpus. Do not limit candidates to lemmas present in the target: that would suppress lemmas absent from the target and prevent a complete descriptive comparison.

For each candidate lemma, construct the following 2×2 table from **file counts**:

| | Lemma present | Lemma absent |
| --- | ---: | ---: |
| Target group | `a` | `N_target - a` |
| All other groups | `c` | `N_reference - c` |

Here `a` and `c` count distinct files containing the lemma, and `N_target` and `N_reference` are the corresponding numbers of files. Compute prevalence per 1,000 files as `1000 * present_files / total_files`; these are chapter-file prevalence rates, not token frequencies.

Compute the unadjusted log-likelihood ratio `G²` from the four observed cells `O` and their independence-model expected counts `E`:

```text
G² = 2 * sum(O * ln(O / E))
```

The sum covers all four cells; a cell with `O == 0` contributes zero. Calculate `E` from the row and column margins. Handle zero cells without `log(0)`; do not return zero just because a lemma is absent from either corpus side. For a lemma present in at least one file, the table must yield a finite, non-negative `G²`; fail with a diagnostic if an invalid or non-finite result occurs. Unit tests must verify the formula against a hand-calculated table.

Report the signed prevalence difference `target_per_1000_files - comparison_per_1000_files` and a descriptive direction (`TARGET_HIGHER`, `REFERENCE_HIGHER`, or `EQUAL`). `G²` itself is non-negative and has no direction. Do not infer a p-value, significance label, or keyword status from the existing prototype's `3.84` cutoff.

### Research decisions intentionally left open

- **Significance threshold:** no threshold or significant/not-significant label is specified.
- **Multiple comparisons:** no family definition or correction (for example, across lemmas within a group or across all groups) is specified.
- **Cutoff:** export every eligible lemma in the corpus-wide vocabulary for each group. Do not carry forward the prototype's target-only `--cutoff 3` behavior. If a display or analysis cutoff is later adopted, it must be an explicit, recorded policy and must not remove rows from the complete descriptive output.
- **Dependence:** chapters from the same report may not be independent observations. Describe the results as exploratory file-prevalence comparisons and document this limitation; do not present the likelihood statistic as resolving dependence.

## 6. Output contract

Write one UTF-8 TSV per group, named `<year>_<chapter>.tsv`, under `corpus/06_enade_keylemmas/`. For example, `2009_c4.tsv` compares all files in `2009_c4` with files in every other year–chapter group. Each TSV has one header row and the following stable columns:

| Column | Meaning |
| --- | --- |
| `lemma` | Normalized candidate lemma. |
| `target_present_files` | Target files containing the lemma. |
| `target_absent_files` | Target files not containing the lemma. |
| `target_total_files` | Total validated files in the target group. |
| `target_per_1000_files` | Target prevalence per 1,000 files. |
| `comparison_present_files` | Reference files containing the lemma. |
| `comparison_absent_files` | Reference files not containing the lemma. |
| `comparison_total_files` | Total validated files in all other groups. |
| `comparison_per_1000_files` | Reference prevalence per 1,000 files. |
| `difference_per_1000_files` | Target prevalence minus reference prevalence. |
| `g2` | Unadjusted, non-negative log-likelihood statistic. |
| `direction` | Descriptive direction; not a significance classification. |

Use a real tab-delimited CSV writer with tab delimiters, standard CSV quoting, UTF-8, and `\n` record terminators. Preserve full integer counts and serialize rates and `g2` deterministically to a documented fixed precision (at least six decimal places for rates and eight for `g2`). Sort rows by descending `g2`, then descending absolute prevalence difference, then ascending normalized lemma; use the same deterministic group ordering (numeric year, then chapter) for logs and provenance. Do not emit NaN or infinity.

Write a deterministic `keylemmas_run.json` alongside the group TSVs. It must include a schema/algorithm version, the input manifest path and SHA-256, POS and stopword paths and SHA-256 values, effective normalized POS categories and stopword values, effective group definitions, target/reference file totals, candidate and output-row counts, a sorted list of each validated tagged-file path/hash/size, per-group TSV paths and SHA-256 values, the fixed method description, and a clear statement that significance thresholding and multiple-testing correction are not applied. Paths must be phase-relative with `/` separators; do not include machine-specific absolute paths. Avoid volatile fields that would make identical reruns produce different provenance bytes.

## 7. Command-line interface and publication safety

Implement `keylemmas.py` for Python 3.10 or later using the standard library only. Provide:

- `--input-manifest`, defaulting to `corpus/05_enade_tagged/enade_tagged_corpus.ndjson`;
- `--output`, defaulting to `corpus/06_enade_keylemmas`;
- `--pos-config`, defaulting to `keylemmas_pos.txt`;
- `--stopwords`, defaulting to `keylemmas_stopwords.txt`;
- `--dry-run`, which performs all manifest, file, hash, configuration, grouping, and analysis validation and prints totals without creating or changing any output path.

Relative CLI paths are resolved from the phase directory. Do not retain the old default `corpus/07_tagged`, old output `corpus/08_keylemmas`, or the misleading space-separated `.txt` output. Remove the old target-only `--cutoff` option until a research cutoff policy is approved.

Validate the complete run before publication. In normal mode, write all TSVs and the provenance JSON into a uniquely named staging directory beside the requested output, validate the staged files and checksums, and publish the complete directory atomically when the destination does not exist. Never overwrite an existing destination silently: if it exactly matches the deterministic expected output, report a verified no-op; if any expected file is missing or differs, or any unexpected file exists, stop and preserve the existing directory. On publication failure, report the staging location for diagnosis. Return a non-zero exit status for invalid input, hash mismatch, malformed tagged data, output conflict, or write/verification failure; diagnostics must identify the affected path or group and corrective action.

Example invocation from the phase directory:

```shell
python keylemmas.py --dry-run
python keylemmas.py
```

## 8. Tests and acceptance criteria

Add automated tests using temporary project trees; never use the production corpus for destructive or publication tests. Cover at least:

- Manifest parsing, required fields and types, duplicate paths/output identities, multiple files in one group, unsuccessful status, path traversal/symlink escape, missing files, incorrect size/hash, and deterministic group identity independent of input order.
- Multiple groups where each target is compared with all other groups; duplicate lemma occurrences in one file count once; same basename in different groups remains distinct; files containing no eligible lemmas still count in denominators.
- POS base-category matching (including `NOUN.Masc.Sing`), configured POS changes, normalized stopword matching, Unicode NFC/casefold equivalence, `<unknown>` and empty-lemma fallback, short-form exclusion, blank lines, and malformed tagged rows with line diagnostics.
- Lemmas absent from the target remain in its result; zero-presence target and reference cells are handled; no target-only cutoff is applied; prevalence denominators are file counts.
- Hand-calculated 2×2 log-likelihood values, including zero cells, equal rates, a lemma present in every file, and finite/non-negative results. For example, observed counts `[[3, 1], [1, 5]]` must produce `G²` approximately `3.5548`.
- TSV delimiter/quoting, header order, stable sorting/precision, UTF-8, row values, and reproducible provenance hashes across identical fixture runs.
- Dry run creates no files; first publication writes all expected outputs; identical rerun is a no-op; conflicting or extra files are detected and preserved; failed staged publication leaves the existing destination unchanged.
- Operation from a working directory other than the phase directory, including phase paths with spaces and non-ASCII characters.

## 9. Pipeline documentation follow-up

After the programme, configuration files, and acceptance tests are implemented, update section 6 of `cl_st2_ph1_fernanda_pipeline.md` to document the finalized input manifest, POS/stopword profiles, dry-run and production commands, `corpus/06_enade_keylemmas` layout, output columns, provenance, and exploratory interpretation. Until implementation is complete, the pipeline must not imply that these outputs exist or that the results have a settled significance policy.