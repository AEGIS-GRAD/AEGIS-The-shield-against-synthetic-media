# FaceForensics++ (c23) Dataset Staging & Management

This document describes the setup, acquisition, external storage guidelines, and staging workflow for the **FaceForensics++ (c23)** deepfake video dataset used within the AEGIS evaluation suite.

---

## 1. Dataset Source

- **Primary Working Source**: Kaggle dataset mirror [`xdxd003/ff-c23`](https://www.kaggle.com/datasets/xdxd003/ff-c23/data).
- **Official Academic Dataset**: The official FaceForensics++ dataset is hosted by the Technical University of Munich (TUM). For canonical publication or formal research evaluation, the official academic access request form should be submitted in parallel.

---

## 2. Manual Download & Extraction Instructions

> [!NOTE]
> Do **not** write or run automated script downloads inside this repository. Raw data is downloaded manually.

1. Log into your Kaggle account.
2. Navigate to the dataset page: `https://www.kaggle.com/datasets/xdxd003/ff-c23/data`.
3. Download the raw dataset archive.
4. Extract the dataset onto a local storage location outside this repository (e.g., an external drive or dedicated dataset directory like `D:\archive\FaceForensics++_C23`).

---

## 3. Storage Policy (Raw Data vs. Local Subset)

> [!IMPORTANT]
> **Raw extracted data MUST live OUTSIDE the repository.**
> The full dataset is tens of gigabytes in size and must **never** be copied or committed into `eval/data/` or any other git-tracked directory.

### Directory Mapping
The raw extracted data directory contains subfolders organized by manipulation algorithm:
- **Real Videos**:
  - `original/`
- **Fake Videos**:
  - `Deepfakes/`
  - `Face2Face/`
  - `FaceShifter/`
  - `FaceSwap/`
  - `NeuralTextures/`
  - `DeepFakeDetection/`

---

## 4. Configuring Data Paths (`eval/config/data_paths.yaml`)

The repository references the raw data location through a central configuration file at `eval/config/data_paths.yaml`:

```yaml
raw_data_root: "D:/archive/FaceForensics++_C23"

categories:
  real:
    - original
  fake:
    - Deepfakes
    - Face2Face
    - FaceShifter
    - FaceSwap
    - NeuralTextures
    - DeepFakeDetection
```

### Updating paths for different systems/teammates
If a teammate stores the raw data on a different drive letter or directory (e.g., `C:/Datasets/ff_c23` or `/mnt/data/FaceForensics++_C23`), update the `raw_data_root` value in `eval/config/data_paths.yaml` accordingly.

---

## 5. Stratified Subset Generation (`eval/scripts/make_subset.py`)

To allow fast local evaluation without copying tens of GBs, `eval/scripts/make_subset.py` creates a balanced, stratified subset under `eval/data/video_subset/`.

> [!NOTE]
> Videos staged into `eval/data/` are automatically ignored by Git (configured via `.gitignore`) to prevent accidental commits of media assets.

### How the Script Works
1. Reads `raw_data_root` and subfolder mappings from `eval/config/data_paths.yaml`.
2. Samples $N_{\text{real}}$ videos from `original/`.
3. Samples $N_{\text{fake}}$ videos evenly across all 6 fake subfolders ($N_{\text{fake}} / 6$ per subfolder).
4. Copies (via `shutil.copy2`) the selected files into:
   - `eval/data/video_subset/real/`
   - `eval/data/video_subset/fake/` (fake filenames are prefixed with their algorithm name, e.g., `Face2Face_000_003.mp4`, to prevent naming collisions).

### Command Usage & Changing $N$

Default run ($150$ real, $150$ fake evenly split across 6 fake algorithms):
```bash
python eval/scripts/make_subset.py
```

Changing sample counts $N$ (e.g., $300$ real, $300$ fake):
```bash
python eval/scripts/make_subset.py --n-real 300 --n-fake 300
```

Using custom random seed or cleaning output directory:
```bash
python eval/scripts/make_subset.py --n-real 100 --n-fake 100 --seed 123 --clean
```

### CLI Arguments Summary
| Argument | Description | Default |
| :--- | :--- | :--- |
| `--config` | Path to `data_paths.yaml` configuration file | `eval/config/data_paths.yaml` |
| `--output-dir` | Directory where staged video subset will be saved | `eval/data/video_subset` |
| `--n-real` | Total number of real videos to sample | `150` |
| `--n-fake` | Total number of fake videos to sample (split evenly across 6 algorithms) | `150` |
| `--seed` | Random seed for sampling reproducibility | `42` |
| `--clean` | Remove existing output directory before building subset | `False` |

---

---

# Audio Dataset — ASVspoof 2019 Logical Access (LA)

This section describes the staging workflow for the **ASVspoof 2019 Logical Access (LA)** audio dataset used for evaluating the **AASIST** voice-spoofing (countermeasure) detector within the AEGIS evaluation suite.

> [!IMPORTANT]
> Only the **Logical Access (LA)** partition is used.  The Physical Access (PA) partition covers a different attack category (replay attacks in physical environments) and is **not** used by AASIST.  Do not mix up the two partitions.

---

## 1. Dataset Source

- **Official source**: [datashare.ed.ac.uk](https://datashare.ed.ac.uk/handle/10283/3336) — University of Edinburgh DataShare.
- **Direct item link**: `https://datashare.ed.ac.uk/items/31074a11-b6f6-4e92-a4ad-07093f8c0c45`
- **Challenge context**: ASVspoof 2019 (anti-spoofing challenge), used as the standard benchmark for speaker liveness / voice anti-spoofing research.

---

## 2. Manual Download & Extraction Instructions

> [!NOTE]
> Do **not** write or run automated script downloads inside this repository.  Raw data is downloaded manually.

1. Navigate to the dataset item page:
   `https://datashare.ed.ac.uk/items/31074a11-b6f6-4e92-a4ad-07093f8c0c45`
2. Download **`LA.zip` only** — this is the Logical Access partition.
   - Do **not** download `PA.zip` (Physical Access) — it is a different attack category not used here.
3. Extract `LA.zip` to a location **outside** the repository (e.g., `D:\LA\`).
   The extracted structure will be `D:/LA/LA/` with the subdirectories listed below.

---

## 3. Storage Policy (Raw Data vs. Local Subset)

> [!IMPORTANT]
> **Raw extracted data MUST live OUTSIDE the repository.**
> The full LA dataset is several GB in size and must **never** be copied or committed into `eval/data/` or any other git-tracked directory.

`eval/data/` is already covered by `.gitignore` — no additional configuration is needed.

---

## 4. Folder Structure (as staged at `D:/LA/LA/`)

```
D:/LA/LA/
  ASVspoof2019_LA_train/
    flac/              ← training utterances (.flac files)
    LICENSE.txt
  ASVspoof2019_LA_dev/
    flac/              ← development utterances
    LICENSE.txt
  ASVspoof2019_LA_eval/
    flac/              ← evaluation utterances  ← used for subset sampling
    LICENSE.txt
  ASVspoof2019_LA_cm_protocols/   ← CM (countermeasure) protocol files — USED
    ASVspoof2019.LA.cm.train.trn.txt
    ASVspoof2019.LA.cm.dev.trl.txt
    ASVspoof2019.LA.cm.eval.trl.txt
  ASVspoof2019_LA_asv_protocols/  ← ASV (speaker verification) — IGNORED
  ASVspoof2019_LA_asv_scores/     ← ASV scores — IGNORED
  README.LA.txt
```

### CM vs. ASV protocols — why only CM is used

| Protocol type | Task | Files used here? |
|:---|:---|:---|
| **CM** (countermeasure) | Spoof/bonafide detection — is the speaker real? | ✅ Yes |
| **ASV** (speaker verification) | Is this the right speaker? | ❌ No — different task |

AASIST is a countermeasure model trained to classify utterances as **bonafide** (genuine human speech) or **spoof** (synthesised / voice-converted).  Only the CM protocol files are needed.

### Protocol file format

Each CM protocol file is whitespace-separated with 5 columns:

```
<speaker_id>  <filename>  -  <attack_type>  <label>
```

| Column | Example | Notes |
|:---|:---|:---|
| `speaker_id` | `LA_0039` | Speaker identifier |
| `filename` | `LA_E_2834763` | Bare filename stem (no extension) |
| `-` | `-` | Fixed placeholder |
| `attack_type` | `A11`, `A14`, … or `-` | Synthesis/VC system ID; `-` for bonafide |
| `label` | `spoof` / `bonafide` | Ground-truth CM label |

The corresponding audio file lives at:
`{split_dir}/flac/{filename}.flac`

---

## 5. Configuring Data Paths (`eval/config/data_paths.yaml`)

The `audio:` section in `eval/config/data_paths.yaml` references the raw data location:

```yaml
audio:
  raw_data_root: "D:/LA/LA"
  protocol_dir: "ASVspoof2019_LA_cm_protocols"
  audio_subdir: "flac"
  splits:
    train: "ASVspoof2019_LA_train"
    dev:   "ASVspoof2019_LA_dev"
    eval:  "ASVspoof2019_LA_eval"
  protocol_files:
    train: "ASVspoof2019.LA.cm.train.trn.txt"
    dev:   "ASVspoof2019.LA.cm.dev.trl.txt"
    eval:  "ASVspoof2019.LA.cm.eval.trl.txt"
```

If the raw data is on a different path (different machine or drive), update `raw_data_root` accordingly — no other changes are needed.

---

## 6. Stratified Subset Generation (`eval/scripts/make_audio_subset.py`)

To allow fast local evaluation without requiring access to the full dataset,
`eval/scripts/make_audio_subset.py` creates a balanced subset under `eval/data/audio_subset/`.

> [!NOTE]
> Files staged into `eval/data/` are automatically ignored by Git to prevent accidental commits.

### How the Script Works

1. Reads the `audio:` config block from `eval/config/data_paths.yaml`.
2. Parses the selected split's CM protocol file to get `filename → label` mappings.
3. Performs **stratified random sampling**: $N_{\text{real}}$ bonafide + $N_{\text{fake}}$ spoof utterances.
4. Copies (via `shutil.copy2`) selected `.flac` files into:
   - `eval/data/audio_subset/real/`  ← bonafide
   - `eval/data/audio_subset/fake/`  ← spoof

### Command Usage & Changing $N$

Default run — 150 bonafide + 150 spoof from the **eval** split:
```bash
python eval/scripts/make_audio_subset.py
```

Use the **dev** split instead:
```bash
python eval/scripts/make_audio_subset.py --split dev
```

Change sample counts (e.g., 300 real + 300 fake):
```bash
python eval/scripts/make_audio_subset.py --n-real 300 --n-fake 300
```

Custom seed and clean rebuild:
```bash
python eval/scripts/make_audio_subset.py --n-real 100 --n-fake 100 --seed 123 --clean
```

### CLI Arguments Summary

| Argument | Description | Default |
|:---|:---|:---|
| `--config` | Path to `data_paths.yaml` configuration file | `eval/config/data_paths.yaml` |
| `--output-dir` | Directory where staged audio subset will be saved | `eval/data/audio_subset` |
| `--split` | Dataset split to sample from (`train`, `dev`, `eval`) | `eval` |
| `--n-real` | Number of bonafide utterances to include | `150` |
| `--n-fake` | Number of spoof utterances to include | `150` |
| `--seed` | Random seed for sampling reproducibility | `42` |
| `--clean` | Remove existing output directory before building subset | `False` |

