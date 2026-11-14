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

