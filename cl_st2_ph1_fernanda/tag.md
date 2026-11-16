# `tag.py` Development Specification

## 1. Programme Purpose & Scope

`tag.py` is a deterministic, high-throughput Part-of-Speech (POS) tagging and lemmatization pipeline programme for the ENADE corpus linguistics research project.

The programme processes the assembled, audited plain-text chapters published in:
```text
corpus/04_enade/<year>_<chapter>/<filename>.txt
```
and executes TreeTagger with Portuguese language parameter files to produce a verified, standardized 3-column POS-tagged token corpus in:
```text
corpus/05_enade_tagged/<year>_<chapter>/<filename>.txt
```
alongside auditable machine-readable and human-inspectable provenance manifests:
```text
corpus/05_enade_tagged/enade_tagged_corpus.ndjson
corpus/05_enade_tagged/enade_tagged_corpus.tsv
corpus/05_enade_tagged/enade_tagged_corpus.xlsx
corpus/05_enade_tagged/tagging_failures.ndjson
```

### Scope and Constraints
- **In Scope**:
  - Processing all 1,032 finalized ENADE target chapters across years (2009–2021) and chapter groups (`c4`, `c5`, `c6`).
  - Dual task discovery: manifest-driven ingestion via `enade_target_corpus.ndjson` or recursive directory traversal of `corpus/04_enade/`.
  - Text normalization and XML/SGML tag bracket escaping to safeguard TreeTagger tokenization.
  - Multi-process parallel batch tagging with isolated error containment and recovery logging.
  - Idempotent resumability (`--resume`), dry-run validation (`--dry-run`), and phase-relative CLI execution.
  - Comprehensive cryptographic provenance recording input/output SHA-256 digests, byte sizes, token metrics, and execution times.
- **Out of Scope / Non-Goals**:
  - Text rewriting, OCR denoising, or structural content modifications (handled upstream in `llm_denoise.py`).
  - Modification, movement, or deletion of source files in `corpus/04_enade` or earlier stages (all upstream data is immutable).
  - Training or modifying TreeTagger acoustic/lexical parameter models.

---

## 2. Research Context & Linguistic Architecture

The ENADE corpus serves empirical corpus linguistics research evaluating Brazilian higher education evaluation reports. Computational linguistics workflows rely on accurate POS distribution metrics, lemma frequency counts, and multi-word token parsing to assess disciplinary syntactic and lexical variations.

TreeTagger is a probabilistic tagger utilizing decision trees based on transition probabilities. In the Portuguese parameter configuration (`tree-tagger-portuguese2` / Portuguese TreeTagger model), each token is tagged with its grammatical category and canonical dictionary lemma.

To maximize downstream utility and ensure research reproducibility:
1. Every input token must be cleanly mapped to its 3-column representation (`token\tPOS\tlemma\n`).
2. Structural markup or OCR-introduced angle brackets must not induce TreeTagger to silently drop sentences as SGML tags.
3. Every tagged output must be traceable back to its exact `04_enade` source hash and metadata.

---

## 3. Inputs & Task Discovery

### 3.1 Default Path Conventions
Default paths are resolved relative to the phase directory (`cl_st2_ph1_fernanda/`):

| Input Resource | Default Path | Format | Description |
|---|---|---|---|
| Target Corpus Base | `corpus/04_enade` | Directory | Root containing `<year>_<chapter>/` subdirectories with `.txt` chapter files. |
| Target Manifest (Optional Input) | `corpus/04_enade/enade_target_corpus.ndjson` | NDJSON | Official stage-4 manifest indexing all 1,032 validated chapters. |

### 3.2 Input Corpus Layout
`corpus/04_enade` contains chapter subdirectories organized by `<year>_<chapter>` as well as top-level stage manifests:
```text
corpus/04_enade/
├── 2009_c4/
│   └── enade_2009_admin_b2a0b87461.txt
├── 2009_c5/
│   └── enade_2009_admin_c9f28d104a.txt
├── 2011_c6/
│   └── enade_2011_biomed_e473b1892f.txt
├── enade_target_corpus.ndjson
├── enade_target_corpus.tsv
└── enade_target_corpus.xlsx
```

### 3.3 Task Discovery Strategies
`tag.py` must support two complementary discovery mechanisms to maximize flexibility across testing and batch environments:

1. **Manifest-Driven Discovery (Primary / Recommended)**:
   - When `--input-manifest` is provided (or exists by default at `corpus/04_enade/enade_target_corpus.ndjson`), `tag.py` parses each JSON record to extract `target_chapter_path`, `target_subdirectory`, `year`, `chapter`, and `filename_stem`.
   - Manifest parsing guarantees 100% alignment with the official target dataset and avoids scanning untracked filesystem artefacts.
2. **Directory Traversal Discovery (Fallback / Direct)**:
   - When discovering from `--input-dir` without a manifest, `tag.py` iterates over immediate subdirectories of `corpus/04_enade`.
   - Criteria for valid corpus subdirectories:
     - Must be a directory (`path.is_dir()`).
     - Must match the `<year>_<chapter>` naming convention (e.g. `re.match(r"^\d{4}_c\d+$", path.name)`).
     - Must ignore top-level files (such as `enade_target_corpus.ndjson`, `.tsv`, `.xlsx`) and hidden folders starting with `.` or `_`.
   - Within each matched subdirectory, all files ending in `.txt` (case-insensitive) are collected as input tasks.

---

## 4. Text Preprocessing & TreeTagger Contract

### 4.1 Legacy Markdown Stripping Removal
The previous prototype used `clean_text_for_treetagger(text)`:
```python
# Legacy logic to be REMOVED:
text.translate(str.maketrans("", "", "*#"))
```
In this pipeline, Markdown characters (`*`, `#`) were already eliminated during upstream text extraction and LLM denoising (`llm_denoise.py`). Removing these characters in `tag.py` is unnecessary and risks altering legitimate mathematical or punctuation tokens.

### 4.2 XML / SGML Bracket Escaping
TreeTagger natively interprets `<tag>` and `</tag>` constructs as SGML/XML structural tags, omitting them from token tagging output. If raw text contains OCR artifacts or mathematical symbols such as `< 0.05` or `<A>`, TreeTagger may misinterpret entire paragraphs between `<` and `>` as SGML markup and discard them.

To preserve complete textual fidelity:
1. All angle brackets in the input text must be escaped prior to passing text to TreeTagger:
   - `<` becomes `&lt;`
   - `>` becomes `&gt;`
2. TreeTagger processes `&lt;` and `&gt;` as literal tokens rather than SGML delimiters.

### 4.3 Whitespace and Encoding Normalization
- All files must be read and written strictly as UTF-8.
- Linebreaks must be normalized to standard Unix newlines (`\n`).
- Leading/trailing null bytes or unusual control characters (e.g., `\x00`, `\x1a`) should be sanitized to avoid premature EOF termination in subprocess pipes.

---

## 5. TreeTagger Invocation & Binary Resolution

### 5.1 Command Execution
TreeTagger is executed as a non-interactive subprocess:
```python
subprocess.run(
    tagger_cmd,
    input=escaped_text,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    check=True,
    timeout=600,  # Bounded execution per chapter
)
```

### 5.2 Executable Resolution Order
To ensure seamless portability across local development machines, continuous integration (CI) environments, and Amazon EC2 production instances:
1. **Explicit CLI Flag**: `--tagger-cmd <path_or_command>` takes highest precedence.
2. **Environment Variable**: `TREETAGGER_CMD` or binary inside `TREETAGGER_HOME/cmd/` (e.g., `$TREETAGGER_HOME/cmd/tree-tagger-portuguese2`).
3. **System PATH Lookup**:
   - `tree-tagger-portuguese2` (preferred Portuguese UTF-8 wrapper)
   - `tree-tagger-portuguese` (standard wrapper)
   - `tree-tagger` (fallback with explicit Portuguese parameter arguments).

### 5.3 Startup Preflight Check
Before spawning the multi-processing worker pool, `tag.py` must perform a fast preflight check by running the resolved tagger command on a dummy string (e.g., `"O ENADE avalia o ensino superior.\n"`). If the tagger fails, is missing, or exits with an error code, the programme aborts immediately with an actionable diagnostic message, preventing wasted compute cycles.

---

## 6. Output Layout & Token Format

### 6.1 Output Directory Structure
Tagged outputs preserve the input subdirectory grouping:
```text
corpus/05_enade_tagged/
├── 2009_c4/
│   └── enade_2009_admin_b2a0b87461.txt
├── 2009_c5/
│   └── enade_2009_admin_c9f28d104a.txt
├── 2021_c6/
│   └── enade_2021_med_f1a2b3c4d5.txt
├── enade_tagged_corpus.ndjson
├── enade_tagged_corpus.tsv
├── enade_tagged_corpus.xlsx
└── tagging_failures.ndjson
```

### 6.2 Three-Column TSV Format
Each output file is a tab-delimited file (`.txt`) where each line represents one token in 3 columns:
```text
token	POS	lemma
```
Example output:
```text
O	ART	o
ENADE	NP	ENADE
avalia	VPI	avaliar
os	ART	o
cursos	NC	curso
superiores	ADJ	superior
.	SENT	.
```

Column specifications:
1. `token`: The lexical token extracted from the input text.
2. `POS`: The Part-of-Speech tag assigned by TreeTagger (e.g., `NC` for common noun, `VPI` for present indicative verb, `ADJ` for adjective).
3. `lemma`: The canonical base form (lemma) of the word. Unknown lemmas are tagged as `<unknown>` by TreeTagger.

---

## 7. Concurrency, Fault Isolation & Checkpointing

### 7.1 Multi-Process Execution Architecture
To maximize CPU utilization across multi-core systems and cloud instances (e.g., AWS EC2), tagging operations are distributed across a pool of worker processes via `concurrent.futures.ProcessPoolExecutor`.

- Default worker pool size: `max(1, multiprocessing.cpu_count() - 1)` to prevent CPU exhaustion on host systems.
- Configurable worker limit via CLI: `--workers <int>` (constrained to `1`–`64`).
- Progress tracking via `tqdm` with real-time ETA, file throughput rates, and summary metrics.

### 7.2 Worker-Level Fault Isolation
In legacy versions, an unhandled exception in `subprocess.run(..., check=True)` caused immediate batch termination, forfeiting work across all concurrent workers. 

Under this specification:
1. Each worker wraps tagger execution in a defensive `try...except Exception` block.
2. If TreeTagger times out, crashes, or returns a non-zero exit code:
   - The worker records the failure details (`error_type`, `error_message`, `stderr`).
   - The partial/corrupted output file is safely removed if present.
   - The failure is appended to `tagging_failures.ndjson`.
   - Remaining tasks continue processing without interruption.
3. Upon batch completion, `tag.py` summarizes total successes and failures, exiting with code `1` if any file failed.

### 7.3 Resumability & Checkpointing (`--resume`)
Processing 1,032 full chapters requires significant CPU time. To prevent redundant compute on aborted or staged runs:
- When `--resume` is supplied, `tag.py` evaluates each candidate task:
  - If the target file exists, is non-empty (`stat().st_size > 0`), and is verified to contain valid 3-column tagged data, the task is skipped.
  - Manifest metrics for skipped files are retrieved from an existing `enade_tagged_corpus.ndjson` if available, or quickly recalculated from the existing output file.
- If `--resume` is omitted, existing outputs are re-tagged and overwritten.

### 7.4 Dry-Run Mode (`--dry-run`)
`--dry-run` enables pre-execution validation of pipeline parameters without mutating filesystem state:
- Resolves all input paths and verifies source file readability.
- Validates the TreeTagger executable via startup preflight probe.
- Evaluates existing output files against `--resume` criteria.
- Prints a detailed summary of discovered chapters, target paths, worker count, and planned actions.
- Exits cleanly with status `0` without creating directories or writing manifest/tagged files.

---

## 8. Tagged Corpus Manifest & Error Contracts

### 8.1 Canonical Output Manifest (`enade_tagged_corpus.ndjson`)
The primary provenance record is `corpus/05_enade_tagged/enade_tagged_corpus.ndjson`. Each line is a valid UTF-8 JSON object formatted deterministically:

```json
{
  "year": "2009",
  "chapter": "c4",
  "target_subdirectory": "2009_c4",
  "filename": "enade_2009_admin_b2a0b87461.txt",
  "source_chapter_path": "corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
  "source_sha256": "b2a0b87461320ef45768e1ab3091dfa299100fa1b6e4e58b9cfc9d0901e12a45",
  "source_size_bytes": 14250,
  "tagged_chapter_path": "corpus/05_enade_tagged/2009_c4/enade_2009_admin_b2a0b87461.txt",
  "tagged_sha256": "4c8f09d84e1b782c9e67d26451e089201cb29845fef109b8e1a7894561234abc",
  "tagged_size_bytes": 31200,
  "token_count": 3840,
  "tagger_command": "tree-tagger-portuguese2",
  "status": "success",
  "elapsed_seconds": 0.38,
  "timestamp": "2026-11-16T15:45:00Z"
}
```

### 8.2 Field Definitions

| Field | Type | Description |
|---|---|---|
| `year` | string | Four-digit ENADE report year (e.g. `"2009"`). |
| `chapter` | string | Chapter group identifier (e.g. `"c4"`, `"c5"`, `"c6"`). |
| `target_subdirectory` | string | Normalized subfolder name (`<year>_<chapter>`). |
| `filename` | string | Chapter filename (e.g. `enade_2009_admin_b2a0b87461.txt`). |
| `source_chapter_path` | string | Phase-relative path to the source chapter in `corpus/04_enade`. |
| `source_sha256` | string | Lowercase hex SHA-256 digest of source `.txt` bytes. |
| `source_size_bytes` | integer | Byte size of the source input chapter. |
| `tagged_chapter_path` | string | Phase-relative path to the tagged output in `corpus/05_enade_tagged`. |
| `tagged_sha256` | string | Lowercase hex SHA-256 digest of tagged 3-column TSV output. |
| `tagged_size_bytes` | integer | Byte size of the tagged output file. |
| `token_count` | integer | Total line/token count in the tagged TSV file. |
| `tagger_command` | string | Executable name or command string invoked for tagging. |
| `status` | string | Status outcome: `"success"` or `"skipped"`. |
| `elapsed_seconds` | float | Wall-clock execution duration in seconds for tagging this chapter. |
| `timestamp` | string | ISO-8601 UTC timestamp of task completion (`YYYY-MM-DDTHH:MM:SSZ`). |

### 8.3 Secondary Export Formats (`.tsv` and `.xlsx`)
- **TSV (`enade_tagged_corpus.tsv`)**: Tab-delimited UTF-8 table with identical columns in identical order.
- **XLSX (`enade_tagged_corpus.xlsx`)**: Excel spreadsheet generated using `openpyxl` with a frozen header row, autofilter enabled, and text formatted cleanly.

### 8.4 Failure Manifest (`tagging_failures.ndjson`)
When tagging fails for any document, a structured error record is appended to `corpus/05_enade_tagged/tagging_failures.ndjson`:

```json
{
  "year": "2009",
  "chapter": "c4",
  "filename": "enade_2009_admin_b2a0b87461.txt",
  "source_chapter_path": "corpus/04_enade/2009_c4/enade_2009_admin_b2a0b87461.txt",
  "error_type": "TreeTaggerSubprocessError",
  "error_message": "Command 'tree-tagger-portuguese2' returned non-zero exit status 1: invalid token stream",
  "timestamp": "2026-11-16T15:45:10Z"
}
```

---

## 9. Command-Line Interface Specification

`tag.py` must use standard `argparse` with phase-directory relative path resolution (`PHASE_DIR = Path(__file__).resolve().parent`).

### 9.1 CLI Options Table

| Argument | Type | Default | Description |
|---|---|---|---|
| `--input-dir` | Path | `corpus/04_enade` | Base directory containing assembled ENADE chapters. |
| `--output-dir` | Path | `corpus/05_enade_tagged` | Destination directory for tagged outputs and manifests. |
| `--input-manifest` | Path | `corpus/04_enade/enade_target_corpus.ndjson` | Path to stage-4 target manifest (if omitted, falls back to directory traversal). |
| `--workers` | int | `max(1, cpu_count - 1)` | Number of parallel worker processes (1–64). |
| `--tagger-cmd` | str | `tree-tagger-portuguese2` | Custom TreeTagger command path or binary name. |
| `--dry-run` | flag | `False` | Validate inputs, tagger probe, and print plan without writing files. |
| `--resume` | flag | `False` | Skip tagging for valid existing output files. |
| `--log-file` | Path | `None` | Optional file path for detailed execution logging. |

### 9.2 Exit Codes
- `0`: All tasks completed successfully, or dry-run finished without validation errors.
- `1`: Validation error, missing prerequisite, tagger preflight failure, or one or more document tagging failures.

---

## 10. Testing, Fixtures & Acceptance Criteria

### 10.1 Automated Unit & Integration Tests
Automated tests for `tag.py` must be implemented in `tests/test_tag.py` using isolated temporary test directories (`tempfile.TemporaryDirectory`).

Key test scenarios:
1. **XML Bracket Escaping**:
   - Verify that strings containing `< 0.05` and `<div>` are escaped to `&lt; 0.05` and `&lt;div&gt;` prior to subprocess invocation.
2. **Task Discovery**:
   - Ingesting `enade_target_corpus.ndjson` discovers exact matching files.
   - Directory traversal correctly discovers `<year>_<chapter>/*.txt` and ignores `.ndjson`, `.tsv`, `.xlsx`, and hidden directories.
3. **Mock Subprocess Tagging**:
   - Verify that worker process feeds text into subprocess stdin and writes stdout correctly formatted to 3 columns.
4. **Resumability & Checkpointing**:
   - Verify that running with `--resume` skips files with existing non-zero output, while rerun without `--resume` overwrites them.
5. **Worker Error Isolation**:
   - Verify that simulated tagger failures (e.g., throwing `CalledProcessError`) log to `tagging_failures.ndjson` and do not kill the parent process.
6. **Manifest Equivalence**:
   - Verify that `enade_tagged_corpus.ndjson`, `.tsv`, and `.xlsx` contain identical rows, columns, SHA-256 digests, and token counts.
7. **Path Resolution & CLI Flags**:
   - Verify execution when invoked from both project root and phase directory with various CLI overrides (`--workers`, `--dry-run`, `--tagger-cmd`).

### 10.2 Acceptance Criteria Checklist
- [ ] No hardcoded working directory dependencies (`Path.cwd()`).
- [ ] Legacy Markdown strip logic removed; TreeTagger XML escaping implemented.
- [ ] 100% of 1,032 ENADE target chapters processed and mapped to `corpus/05_enade_tagged/<year>_<chapter>/`.
- [ ] Full provenance manifests (`.ndjson`, `.tsv`, `.xlsx`) and failure manifest (`tagging_failures.ndjson`) produced.
- [ ] Dry-run and resumable batch execution supported.

---

## 11. Pipeline Documentation Follow-up

Upon completing the implementation and passing all unit tests, update `cl_st2_ph1_fernanda/cl_st2_ph1_fernanda_pipeline.md` (Section 5) as follows:

```markdown
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
```
