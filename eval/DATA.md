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
