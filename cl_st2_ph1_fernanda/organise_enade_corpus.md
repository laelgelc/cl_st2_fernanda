# `organise_enade_corpus.py` development specification

## Purpose and scope

Implement a repeatable, portable finalisation step for the selected ENADE chapters. The programme reads the revised page-selection manifest, source-document metadata, and denoising chapter status; validates that these inputs agree; copies each complete assembled chapter into `corpus/04_enade`; and publishes one chapter-level target-corpus manifest in NDJSON, TSV, and XLSX formats.

The NDJSON file is the canonical machine-readable manifest. The TSV and XLSX files are deterministic exports of the same rows and columns. The page-level input manifest remains unchanged. The organised chapter files are copies: never rename, move, alter, or delete files in earlier pipeline stages.

This programme establishes that chapters were selected and assembled successfully, not that they passed linguistic review. Every published row must retain the status `accepted_subject_to_audit`; review flags and notes remain visible for follow-up.

## Inputs and identity

Default input paths are relative to the phase directory (`cl_st2_ph1_fernanda/`):

| Input | Default path | Use |
| --- | --- | --- |
| Revised page-selection manifest | `corpus/enade_chapters_clean_up_revised_dataset.ndjson` | Defines selected source pages and chapter groups. |
| Source metadata | `corpus/enade_dataset.ndjson` | Supplies the authoritative year, source PDF name, mnemonic, and discipline. |
| Denoising chapter status | `corpus/03_enade_selected_chapters_denoised/chapter_status.ndjson` | Supplies completion state, selected pages, assembled output path, and audit counts. |

The selection manifest currently has one object per page, with `chapter_of_interest`, `filename_stem`, `filepath_ori`, and `chapter_page_filepath_txt`. Parse the page number from the final `_page_<number>.txt` component of the selected page filename. A group is uniquely identified by the tuple (`filepath_ori`, `filename_stem`, `chapter_of_interest`); do not group by filename stem alone.

Match each group to exactly one status record using its nested `group` tuple with the same three identity fields. Match the source metadata using `filepath_ori`. Metadata must resolve to exactly one row and provide a four-digit `year`; do not infer a year from a filename or directory name. Preserve the metadata's `filename_ori`, `mnemonic`, and `discipline` for traceability and description.

## Output layout

The default output directory is `corpus/04_enade`. Preserve the assembled chapter filename, including its existing hash suffix, and place it in a directory named `<year>_<chapter>`:

```text
corpus/04_enade/
├── 2009_c4/
│   └── enade_2009_admin_b2a0b87461.txt
├── enade_target_corpus.ndjson
├── enade_target_corpus.tsv
└── enade_target_corpus.xlsx
```

For example, `corpus/03_enade_selected_chapters_denoised/chapters/c4/enade_2009_admin_b2a0b87461.txt` is copied to `corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt`.

All paths written in the manifest must be relative to the phase directory, use `/` separators, and preserve Unicode. Do not write machine-specific absolute paths. The original source PDF is referenced in the manifest but is not copied into `04_enade`.

## Inclusion and reconciliation rules

1. Read each NDJSON input as UTF-8, one JSON object per non-blank line. Report the input path and line number for malformed JSON, missing fields, or wrong value types. Reject empty inputs.
2. Validate required identity fields as non-empty strings. Reject duplicate selected page identities (group plus page number), duplicate status identities, ambiguous source metadata matches, and invalid or non-positive page numbers.
3. Group selected pages by the full identity tuple. Sort page numbers numerically and compare sets when reconciling; input order is not meaningful, and selected pages need not be contiguous.
4. Require one corresponding status record per selected group with `status == "complete"`, `complete == true`, no failed or missing pages, and no unattempted pages. Require the status record's `selected_pages` to equal the page numbers in the selection manifest exactly. A missing, extra, or incomplete group is a validation error; do not silently omit it or publish a partial corpus.
5. Resolve the status record's `output_path` against the phase directory. Require it to be a regular readable file and use that path as the copy source; do not reconstruct the denoised filename. Verify that the path is inside the phase directory and does not resolve through a symlink outside it.
6. Resolve the source PDF path from metadata and verify that it refers to a file. It is a provenance reference only: do not copy it or include its contents in the chapter checksum.
7. Form the target directory from the validated metadata year and chapter label. Require each path component to be a single safe component (no separators, `.`/`..`, or platform-specific unsafe names); reject unsafe values instead of silently rewriting them. Preserve the chapter filename from the denoising `output_path`.
8. Detect destination collisions before copying. In addition to exact path collisions, compare destination paths after Unicode NFC normalization and case folding so a corpus built on a case-sensitive filesystem cannot collide when moved to a common case-insensitive filesystem.
9. Copy bytes without text decoding or newline conversion. Calculate SHA-256 and byte size for each assembled source, verify the destination copy has the same size and SHA-256, and record those verified values in all manifest exports. A zero-byte chapter is not by itself evidence of a failed page; report its size and follow the explicit status checks.
10. Include every selected, complete chapter exactly once. The number of manifest rows must equal the number of unique selected groups, and the number of chapter files must equal the number of rows.

Review flags, empty-success pages, and review notes do not make a completed group ineligible. Copy the chapter while retaining the flag/note counts and a path to the detailed `chapter_status.ndjson`. Do not describe the audit as complete or approved by the programme.

## Target manifest contract

Produce one row per chapter, in deterministic order by numeric year, chapter label, source path, then target path. Use this ordered set of columns in NDJSON, TSV, and XLSX:

| Column | Type / representation | Meaning |
| --- | --- | --- |
| `year` | string | Four-digit year from source metadata. |
| `chapter` | string | Chapter label, e.g. `c4`. |
| `target_subdirectory` | string | `<year>_<chapter>`, e.g. `2009_c4`. |
| `filename_stem` | string | Selection group filename stem. |
| `discipline` | string | Discipline from source metadata. |
| `mnemonic` | string | Source mnemonic from source metadata. |
| `source_pdf_filename` | string | Original PDF filename from source metadata (`filename_ori`). |
| `source_pdf_path` | string | Original PDF path from `filepath_ori`, phase-relative with `/` separators. |
| `selected_pages` | JSON array of integers | Sorted unique selected page numbers. Store as a compact JSON string in TSV and XLSX to preserve the same representation. |
| `selected_page_count` | integer | Number of selected pages in the group. |
| `denoised_source_path` | string | Phase-relative `output_path` from the matched status record. |
| `target_chapter_path` | string | Phase-relative path to the copied chapter in `corpus/04_enade`. |
| `chapter_sha256` | string | Lowercase SHA-256 hex digest of the copied chapter bytes. |
| `chapter_size_bytes` | integer | Size of the copied chapter in bytes. |
| `denoise_status` | string | `complete` for each included chapter. |
| `corpus_status` | string | `accepted_subject_to_audit`; not a linguistic approval. |
| `boundary_review_flag_count` | integer | Number of entries in the status record's `boundary_review_flags`. |
| `review_note_count` | integer | `review_note_count` from the status record. |
| `chapter_status_path` | string | Phase-relative path to `chapter_status.ndjson`, the detailed status and audit record. |
| `page_selection_manifest_path` | string | Phase-relative path to the revised page-selection input. |
| `page_selection_manifest_sha256` | string | SHA-256 of the exact input file bytes. |
| `source_metadata_manifest_path` | string | Phase-relative path to the source metadata input. |
| `source_metadata_manifest_sha256` | string | SHA-256 of the exact input file bytes. |
| `chapter_status_manifest_sha256` | string | SHA-256 of the exact `chapter_status.ndjson` bytes. |

Use the same column order in every format. NDJSON must contain only chapter objects (no header or metadata pseudo-row); serialize each object as one UTF-8 JSON line with deterministic key order and no non-standard NaN/Infinity values. TSV must have one header row, tab delimiters, UTF-8 encoding, standard CSV quoting, and `\n` record terminators. XLSX must contain a `chapters` worksheet with the same header and rows, a frozen header row, autofilter, and no formulas or macros. Preserve identifiers, paths, and page arrays as text in XLSX where spreadsheet auto-conversion could alter them.

The XLSX writer may use `openpyxl`; it is the only required third-party dependency. Check for it before any output is written and provide an actionable error if it is unavailable. NDJSON and TSV generation must use the Python standard library. Declare/document the supported Python baseline as Python 3.10 or later, matching syntax already used by the phase scripts.

## Portable command-line interface

Implement `organise_enade_corpus.py` in the phase directory, using only standard-library path, file, hashing, JSON, CSV, argument parsing, and logging facilities plus the XLSX dependency above. The script must work on Linux, macOS, and Windows with paths resolved by `pathlib`; it must not rely on the current working directory, shell-specific utilities, network access, locale defaults, or environment-specific absolute paths.

Provide CLI options for the three input paths and output directory, defaulting to the paths in this specification. Interpret relative CLI paths relative to the phase directory determined from the script location, not the caller's working directory. Support `--dry-run`, which performs all input, reconciliation, path, and collision checks and prints a concise plan and totals but creates no output directories or files. Normal mode always creates all three manifest formats; it must not offer a mode that publishes only one format.

Example invocation from the phase directory:

```shell
python organise_enade_corpus.py --dry-run
python organise_enade_corpus.py
```

Return a non-zero exit status for invalid input, missing files, collisions, copy/hash failures, or publication conflicts. Diagnostics must identify the affected file/group and explain the corrective action. Do not emit success output until the files and all three manifests have been validated.

## Safe publication and reruns

Validate the complete plan before making output changes. In normal mode, write into a uniquely named staging directory beside `corpus/04_enade` so the final rename is on the same filesystem. Copy chapters, write all three manifests, and validate the staged directory against the expected rows, paths, counts, and checksums before publishing. When `corpus/04_enade` does not exist, publish the staged directory with a single directory rename. On failure, leave the existing target untouched and report the staging location; do not automatically delete files or directories that may need diagnosis.

Never silently replace an existing target corpus or its manifests. If `corpus/04_enade` already exists, compare it with the deterministic expected output. If every expected file and manifest matches and there are no unexpected files, treat the run as an idempotent no-op after verification. If anything differs—including a manually edited manifest, review status, missing chapter, or extra file—stop with a clear conflict and preserve the existing directory. Do not add a force-overwrite option in the initial implementation; an intentional rebuild should use a separately chosen destination or be preceded by an explicit, human-managed archival action.

This rule prevents reruns from erasing human review work. Review decisions remain represented by the manifest's `corpus_status` and must not be changed by this organiser after initial publication.

## Tests and acceptance criteria

Add automated tests using temporary project trees; tests must not use the real corpus for destructive operations. Cover at least:

- Correct output folder and unchanged chapter filename, including the `2009_c4` example.
- Correct full-tuple grouping, metadata year join, and original PDF trace path.
- Numerically sorted, non-contiguous selected pages and equality checks independent of input row order.
- Duplicate page identities, duplicate status groups, ambiguous or missing metadata, missing status, incomplete status, and mismatched selected-page sets.
- Missing/unreadable source chapters, missing source PDFs, unsafe paths, symlink/path traversal outside the phase directory, and exact or case/Unicode-normalized destination collisions.
- Byte-preserving copy and SHA-256/size verification, including Unicode content and an empty assembled file with complete status.
- Equivalent row values, column order, Unicode and page-list representation across NDJSON, TSV, and XLSX; verify XLSX is readable and contains no formula cells.
- Dry run creates no files; first publication stages and publishes all expected files; a failed staged copy does not alter an existing target.
- Idempotent identical rerun; conflicting rerun leaves existing files byte-identical; extra files and manually modified manifests are detected and preserved.
- Operation with a working directory other than the phase directory and with path strings containing spaces and non-ASCII characters.

For the recorded production input, use the known run totals (30,770 selected pages and 1,032 complete chapter groups) as a one-time cross-check, not hard-coded programme constants. Investigate any discrepancy before publication. Test the algorithm on small fixtures first; do not require a live denoising service or API credentials.

## Pipeline documentation follow-up

After the programme is implemented and its acceptance tests pass, update `cl_st2_ph1_fernanda_pipeline.md` with the finalisation step after denoising: the dry-run and publication commands, required XLSX dependency, `corpus/04_enade` layout, three manifest paths, reconciliation checks, and the `accepted_subject_to_audit` interpretation. Until then, the pipeline document must not imply that this stage or its outputs already exist.