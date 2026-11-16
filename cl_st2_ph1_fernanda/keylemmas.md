# `keylemmas.py` Development Specification

## 1. Programme Purpose & Scope

`keylemmas.py` is a deterministic empirical corpus linguistics programme that extracts and quantifies distinctive keywords (key lemmas) across subcorpora of the ENADE dataset.

The programme processes the POS-tagged and lemmatized 3-column token files published in:
```text
corpus/05_enade_tagged/<year>_<chapter>/<filename>.txt
```
and evaluates the relative prevalence of eligible lemmas within each specific evaluation group (a target `<year>_<chapter>` pair) against a reference comparison subcorpus comprising all other groups combined.

The programme produces group-level tab-delimited key lemma profiles alongside a cryptographic run manifest:
```text
corpus/06_enade_keylemmas/<year>_<chapter>.tsv
corpus/06_enade_keylemmas/keylemmas_run.json
```

### Scope and Constraints
- **In Scope**:
  - Ingesting tagged chapter files from `corpus/05_enade_tagged/` using either manifest-driven ingestion (`enade_tagged_corpus.ndjson`) or direct directory traversal.
  - Externalizing Part-of-Speech (POS) prefix filters (`keylemmas_pos.txt`) and stopword lists (`keylemmas_stopwords.txt`) into configurable, auditable text files.
  - Computing document-presence counts, normalized prevalence rates per 1,000 files, log-likelihood ($G^2$ / $LL$) contingency statistics, effect size percentage differences ($\%DIFF$), and keyword classifications (`POSKW`, `NEGKW`, `NOTKW`).
  - Preserving mathematical invariance with the baseline analytical model.
  - Generating standard UTF-8 tab-delimited (`.tsv`) result files and a provenance manifest (`keylemmas_run.json`) with SHA-256 digests.
  - Supporting non-destructive dry-run validation (`--dry-run`), phase-directory relative path resolution, and idempotent reruns.
- **Out of Scope / Non-Goals**:
  - Retagging, lemmatizing, or altering upstream files in `corpus/05_enade_tagged/` or earlier pipeline stages.
  - Applying unadjusted multi-hypothesis corrections or arbitrary post-hoc significance cutoffs unless explicitly configured via CLI flags.
  - Training custom linguistic models or modifying underlying statistical estimators.

---

## 2. Research Context & Linguistic Methodology

In corpus linguistics and discource analysis, key word / key lemma analysis identifies lexical items that appear with statistically significant differential frequency across distinct subcorpora.

For the ENADE dataset, reports are organized into specific evaluation years (e.g., 2009, 2011, 2014, 2017, 2021) and report chapters (`c4`, `c5`, `c6`). Analyzing lexical variation at the chapter/group level reveals disciplinary norms, pedagogical framing, and temporal shifts in higher education assessment.

### 2.1 Binary Document-Presence Model
Rather than counting raw token frequencies (which can be heavily skewed by a single lengthy document repeatedly using a specific term), this analysis operates on a **binary document-presence model**:
1. For any given text document $T_i$, a lemma $L$ is either **present** ($L \in T_i$) or **absent** ($L \notin T_i$).
2. The frequency metric $a$ (or $b$) represents the total number of distinct documents in which lemma $L$ occurs at least once.
3. Normalized prevalence metrics ($perA$, $perB$) reflect the rate of occurrence per 1,000 documents.

### 2.2 Mathematical Invariance
The statistical core of `keylemmas.py` is invariant and reproduces exact numerical outputs:
- **Log-Likelihood ($G^2$)**: Standard two-way contingency table log-likelihood ratio test.
- **Effect Size ($\%DIFF$)**: Symmetrical percentage difference comparing prevalence rates.
- **Classification Status**: Direct partitioning into positive keywords (`POSKW`), negative keywords (`NEGKW`), and non-significant lemmas (`NOTKW`).

---

## 3. External Configuration Architecture

To maximize experimental auditability and maintain separation between code logic and linguistic parameterization, POS tag categories and stopword exclusions are externalized into dedicated configuration files.

### 3.1 POS Filter Configuration (`keylemmas_pos.txt`)
- **Default Path**: `keylemmas_pos.txt` (located in the phase directory `cl_st2_ph1_fernanda/`).
- **Override CLI Flag**: `--pos-config <path>`.
- **Format**: Plain text file, UTF-8 encoded, one POS tag prefix per line. Lines starting with `#` and blank lines are ignored.
- **Default Content**:
  ```text
  # Valid POS tag prefixes for key lemma extraction
  # Target major content word classes: nouns, verbs, and adjectives
  NOUN
  VERB
  ADJ
  ```

### 3.2 Stopword Exclusion Configuration (`keylemmas_stopwords.txt`)
- **Default Path**: `keylemmas_stopwords.txt` (located in the phase directory `cl_st2_ph1_fernanda/`).
- **Override CLI Flag**: `--stopwords <path>`.
- **Format**: Plain text file, UTF-8 encoded, one lowercased stopword per line. Lines starting with `#` and blank lines are ignored.
- **Default Content**: Baseline exclusion list containing roman numerals, domain-specific metadata tokens, geographic/institutional names, and function words.

### 3.3 Provenance & Parameter Auditing
During execution, `keylemmas.py` computes the SHA-256 cryptographic hash of both active configuration files and records them directly in `keylemmas_run.json`.

---

## 4. Inputs & Task Discovery

### 4.1 Default Path Conventions
Paths are resolved relative to the phase directory (`cl_st2_ph1_fernanda/`):

| Resource | Default Path | Format | Description |
|---|---|---|---|
| Tagged Corpus Base | `corpus/05_enade_tagged` | Directory | Root containing `<year>_<chapter>/` subdirectories with `.txt` 3-column files. |
| Tagged Manifest | `corpus/05_enade_tagged/enade_tagged_corpus.ndjson` | NDJSON | Upstream manifest indexing all tagged documents. |
| POS Configuration | `keylemmas_pos.txt` | Text | White-list of valid POS tag prefixes. |
| Stopword Configuration | `keylemmas_stopwords.txt` | Text | Black-list of excluded lemmas. |

### 4.2 Discovery Strategies
`keylemmas.py` supports dual discovery modes:

1. **Manifest-Driven Discovery (Primary)**:
   - When `--input-manifest` is present (or exists at default `corpus/05_enade_tagged/enade_tagged_corpus.ndjson`), `keylemmas.py` reads valid chapter entries, obtaining `year`, `chapter`, `target_subdirectory`, and `tagged_chapter_path`.
   - Ensures strict alignment with audited upstream stages.
2. **Directory Traversal Discovery (Fallback)**:
   - When traversing `--input-dir` directly, `keylemmas.py` identifies all subdirectories matching the pattern `<year>_<chapter>` (e.g., `2009_c4`, `2011_c6`, `2021_c5`).
   - Ignores top-level files (`.ndjson`, `.tsv`, `.xlsx`) and hidden directories starting with `.` or `_`.
   - Iterates through all `.txt` files within each matched subdirectory.

---

## 5. Mathematical Formulation & Filtering Pipeline

### 5.1 Token Parsing and Pre-Filtering
For every token line in a tagged `.txt` document:
1. **Split Token Line**: Parse 3 tab-separated columns: `word`, `tag`, `lemma`. If fewer than 3 columns exist, skip the line.
2. **POS Prefix Matching**: Check if `tag` starts with any prefix defined in the active POS configuration (e.g. `("NOUN", "VERB", "ADJ")`). If not, discard.
3. **Lemma Fallback**: Strip whitespace from `lemma`. If `lemma` is empty or equals `"<unknown>"`, fallback to `word.strip()`.
4. **Lowercasing**: Normalize lemma to lowercase: `lemma_lc = lemma.lower()`.
5. **Alphabetic Threshold**: Require at least 2 alphabetic characters:
   ```python
   sum(1 for ch in lemma_lc if ch.isalpha()) >= 2
   ```
6. **Stopword Exclusion**: Check if `lemma_lc` is in the active stopword set. If present, discard.
7. **Document Set Insertion**: If the candidate passes all checks and has not yet been seen in the current text document, record document membership:
   ```python
   presence[lemma_lc].add(text_label)
   ```

### 5.2 Statistical Contingency Table
For each group $G_t$ (`target`) evaluated against the comparison corpus $G_c$ (`comparison` = all documents in all other groups combined):
- $c = \text{size\_target} = |G_t|$ (Total documents in target group)
- $d = \text{size\_comp} = |G_c|$ (Total documents in comparison corpus)
- $N = c + d$ (Total documents across all groups)
- For each lemma $L$:
  - $a = \text{target\_presence}(L)$ (Number of target documents containing $L$)
  - $b = \text{comp\_presence}(L)$ (Number of comparison documents containing $L$)

### 5.3 Prevalence Rates
Normalized prevalence per 1,000 documents:
$$\text{perA} = \left( \frac{a}{c} \right) \times 1000$$
$$\text{perB} = \begin{cases} \left( \frac{b}{d} \right) \times 1000 & \text{if } d > 0 \\ 0.0 & \text{if } d = 0 \end{cases}$$

### 5.4 Expected Frequency
Expected target document count under the null hypothesis of equal prevalence:
$$E = \begin{cases} \frac{c \times (a + b)}{N} & \text{if } N > 0 \\ 0.0 & \text{if } N = 0 \end{cases}$$

### 5.5 Log-Likelihood / $G^2$ Statistic
The log-likelihood contingency test statistic is calculated as:
$$\text{LL} = 2 \left( a \ln\left(\frac{a}{E_1}\right) + b \ln\left(\frac{b}{E_2}\right) \right)$$
where:
$$E_1 = c \left( \frac{a + b}{c + d} \right), \quad E_2 = d \left( \frac{a + b}{c + d} \right)$$
*Zero-count safeguard*: If $a = 0$ or $b = 0$, $\text{LL} = 0.0$.

### 5.6 Percentage Difference ($\%DIFF$)
Symmetrical percentage difference in prevalence rate:
$$\%DIFF = \begin{cases} 0.0 & \text{if } (\text{perA} + \text{perB}) = 0 \\ 100 \times \frac{\text{perA} - \text{perB}}{\frac{\text{perA} + \text{perB}}{2}} & \text{otherwise} \end{cases}$$

### 5.7 Keyword Status Classification
Lemmas are categorized into one of three descriptive states using the critical value $\chi^2_{1, 0.05} = 3.84$:
- `POSKW` (Positive Keyword): $\text{LL} \ge 3.84$ and $\%DIFF > 0$
- `NEGKW` (Negative Keyword): $\text{LL} \ge 3.84$ and $\%DIFF \le 0$
- `NOTKW` (Not Keyword): $\text{LL} < 3.84$

### 5.8 Sorting & Ranking Hierarchy
Output rows are sorted deterministically:
1. Status priority: `POSKW` (0) $\rightarrow$ `NEGKW` (1) $\rightarrow$ `NOTKW` (2).
2. Log-likelihood statistic in descending order ($-\text{LL}$).
3. Lemma in ascending alphabetical order (tie-breaker for deterministic output).

---

## 6. Output Layout & File Contracts

### 6.1 Directory Tree
Output files are written to `corpus/06_enade_keylemmas/`:
```text
corpus/06_enade_keylemmas/
├── 2009_c4.tsv
├── 2009_c5.tsv
├── 2011_c6.tsv
├── 2021_c6.tsv
└── keylemmas_run.json
```

### 6.2 Group TSV Output Schema (`<year>_<chapter>.tsv`)
Each group file is a standard UTF-8 tab-delimited text file with a single header row and Unix line endings (`\n`).

#### TSV Column Specification

| Column Header | Format / Type | Description |
|---|---|---|
| `lemma` | string | Canonical extracted lemma (lowercased). |
| `target_count` | integer ($a$) | Number of target group documents containing the lemma. |
| `comparison_count` | integer ($b$) | Number of comparison group documents containing the lemma. |
| `target_per_1k` | float (2 dec) | Target prevalence rate per 1,000 documents ($\text{perA}$). |
| `comparison_per_1k` | float (2 dec) | Comparison prevalence rate per 1,000 documents ($\text{perB}$). |
| `expected` | float (2 dec) | Expected target presence count under null distribution ($E$). |
| `LL` | float (2 dec) | Log-likelihood ($G^2$) contingency test statistic. |
| `diff_percent` | float (2 dec) | Percentage difference in prevalence ($\%DIFF$). |
| `status` | string | Descriptive classification: `POSKW`, `NEGKW`, or `NOTKW`. |

#### Sample TSV Content
```tsv
lemma	target_count	comparison_count	target_per_1k	comparison_per_1k	expected	LL	diff_percent	status
administração	42	180	840.00	185.57	10.84	124.52	127.62	POSKW
gestão	38	210	760.00	216.49	12.11	88.34	111.32	POSKW
currículo	5	340	100.00	350.52	16.85	18.42	-111.10	NEGKW
desenvolver	30	590	600.00	608.25	30.28	0.02	-1.37	NOTKW
```

### 6.3 Run Manifest Schema (`keylemmas_run.json`)
The manifest records operational provenance, parameter state, and dataset hashes:

```json
{
  "timestamp": "2026-11-16T18:30:00Z",
  "elapsed_seconds": 4.12,
  "input_dir": "corpus/05_enade_tagged",
  "output_dir": "corpus/06_enade_keylemmas",
  "cutoff_percent": 0.0,
  "pos_config": {
    "path": "keylemmas_pos.txt",
    "sha256": "8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e9f8a7b",
    "active_prefixes": ["NOUN", "VERB", "ADJ"]
  },
  "stopwords_config": {
    "path": "keylemmas_stopwords.txt",
    "sha256": "1f2e3d4c5b6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c",
    "stopword_count": 128
  },
  "total_documents": 1032,
  "total_groups": 24,
  "groups": {
    "2009_c4": {
      "target_documents": 50,
      "comparison_documents": 982,
      "total_lemmas_evaluated": 8450,
      "poskw_count": 320,
      "negkw_count": 185,
      "notkw_count": 7945,
      "output_file": "corpus/06_enade_keylemmas/2009_c4.tsv",
      "output_sha256": "c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4",
      "output_size_bytes": 452100
    }
  }
}
```

---

## 7. Operational Features & Idempotency

### 7.1 Cutoff Parameter (`--cutoff`)
- `--cutoff <float>` specifies a minimum percentage presence requirement within the target group (default: `0.0`).
- By default (`0.0`), all eligible lemmas observed in the corpus are evaluated and reported.
- When set to a positive value (e.g. `--cutoff 3.0`), lemmas appearing in fewer than `target_texts * cutoff / 100` target documents are excluded.

### 7.2 Dry-Run Mode (`--dry-run`)
When executed with `--dry-run`:
1. Validates all input paths, manifests, and configuration files (`keylemmas_pos.txt`, `keylemmas_stopwords.txt`).
2. Discovers all group subdirectories and counts `.txt` documents.
3. Previews target/comparison document balances per group.
4. Validates that no output directory collisions or permission issues exist.
5. Prints a structured execution summary and exits cleanly with code `0` without creating directories or writing `.tsv` / `.json` files.

### 7.3 Safe Execution & Idempotent Reruns
- **Staging / Atomic Writes**: Files are written deterministically.
- **Idempotency Verification**: If `corpus/06_enade_keylemmas/` already exists, a rerun checks whether the generated data matches the existing output.
- **Conflict Prevention**: If unexpected files or mismatched checksums are detected, the programme halts with an error, preserving existing research data.

---

## 8. Command-Line Interface Specification

`keylemmas.py` provides a standard `argparse` CLI. All relative paths resolve against `PHASE_DIR = Path(__file__).resolve().parent`.

### 8.1 CLI Arguments Table

| Argument | Type | Default | Description |
|---|---|---|---|
| `--input-dir` | Path | `corpus/05_enade_tagged` | Directory containing tagged `<year>_<chapter>` subdirectories. |
| `--output-dir` | Path | `corpus/06_enade_keylemmas` | Destination directory for TSV results and run manifest. |
| `--input-manifest` | Path | `corpus/05_enade_tagged/enade_tagged_corpus.ndjson` | Path to upstream tagged corpus manifest (falls back to directory scan if absent). |
| `--pos-config` | Path | `keylemmas_pos.txt` | Path to POS tag prefix configuration file. |
| `--stopwords` | Path | `keylemmas_stopwords.txt` | Path to stopword exclusion file. |
| `--cutoff` | float | `0.0` | Minimum target group document presence percentage (0.0 to 100.0). |
| `--dry-run` | flag | `False` | Validate inputs and print execution plan without writing files. |
| `--log-file` | Path | `None` | Path to write optional detailed execution logs. |

### 8.2 Standard Invocations

#### Dry Run
```shell
python keylemmas.py --dry-run
```

#### Production Run (Default Settings)
```shell
python keylemmas.py
```

#### Custom Parameters and Cutoff Run
```shell
python keylemmas.py \
    --pos-config custom_pos.txt \
    --stopwords custom_stopwords.txt \
    --cutoff 3.0
```

### 8.3 Exit Codes
- `0`: Successful execution or dry-run completion.
- `1`: Invalid arguments, missing inputs/configuration files, empty corpus, or unhandled exceptions.

---

## 9. Testing & Acceptance Criteria

Automated tests for `keylemmas.py` must be implemented in `tests/test_keylemmas.py` using temporary directories (`tempfile.TemporaryDirectory`).

### 9.1 Unit & Statistical Test Scenarios
1. **Mathematical Invariance**:
   - Verify that `ll(a, b, c, d)` returns exact known values for standard contingency tables.
   - Verify that zero-count edge cases ($a=0$, $b=0$, $c=0$, $d=0$) safely return `0.0` without division-by-zero or math domain errors.
   - Verify that `diff_percent` correctly calculates symmetrical percentage differences.
2. **Linguistic Pre-Filtering**:
   - Verify POS prefix matching (e.g. `NC` and `NP` matched by `NOUN`, `VPI` matched by `VERB`).
   - Verify lemma fallback when lemma is `<unknown>` or empty.
   - Verify lowercase normalization and $\ge 2$ alphabetic character requirement.
   - Verify that stopwords defined in `keylemmas_stopwords.txt` are excluded.
3. **Task Discovery**:
   - Ingesting `enade_tagged_corpus.ndjson` correctly resolves all target files and group memberships.
   - Directory traversal ignores top-level `.tsv`, `.xlsx`, `.ndjson` files and hidden directories.
4. **Output Integrity**:
   - Verify that output TSV files are strictly tab-delimited with correct column headers and sorted by status priority then descending log-likelihood.
   - Verify that `keylemmas_run.json` contains valid SHA-256 digests and accurate document counts.
5. **Dry-Run & Idempotency**:
   - Verify that `--dry-run` leaves the filesystem untouched.
   - Verify that repeated runs with identical parameters produce byte-identical TSV outputs.

---

## 10. Pipeline Integration

Following the implementation and validation of `keylemmas.py`, Section 6 of `cl_st2_ph1_fernanda_pipeline.md` represents the active stage specification:
- **Input Corpus**: `corpus/05_enade_tagged/`
- **Output Corpus**: `corpus/06_enade_keylemmas/`
- **Execution Commands**: `python keylemmas.py --cutoff 3 --dry-run` and `python keylemmas.py --cutoff 3`
- **Manifest Reference**: `corpus/06_enade_keylemmas/keylemmas_run.json`
