# AEGIS Model Registry & Promotion Gate — Desklib Promotion & Rollback Demo

**Registry File:** `D:\Grad Projectt eccuuuuu\model_registry\registry.json`  
**Target Detector:** `detector_text`  
**Staged Evaluation Subset:** `eval/data/text/text_eval_manifest.jsonl` ($N = 16$ stratified samples)  
**Execution Device:** `CUDA`

---

## 1. Pre-Promotion Baseline State

- **Active Entry:** `detector_text@1.0.0-asis`
- **Manifest `version`:** `desklib-ai-text-detector-v1.01-fp16`
- **Calibration Checkpoint:** `eval/calibration/checkpoints/detector_text_platt_calibrator.json`

---

## 2. Automatic Promotion Gate Checks (`detector_text@1.1.0-lora-finetuned`)

| Gate Check | Status | Summary |
| :--- | :---: | :--- |
| `integrity_and_calibration` | **PASS** | All checkpoint, adapter, and calibration hashes verified. |
| `schema_and_contract_tests` | **PASS** | Manifest schema and API contract checks passed. |
| `staged_eval_regression` | **PASS** | Staged eval passed (N=16, AUROC=1.0000, Acc=0.9375, ECE=0.0589). |
| `latency_and_memory_budget` | **PASS** | Budget check passed (cuda: avg=147.2ms <= 500ms, p95=274.6ms <= 1000ms, RAM=1372.2MB <= 6144MB). |
| `manifest_update_validation` | **PASS** | Prepared schema-valid manifest update for version=desklib-v1.01-lora-finetuned-fp16. |

### Staged Subset Regression & Resource Comparison

| Metric | As-Is Baseline (`1.0.0-asis`) | Fine-Tuned LoRA (`1.1.0-lora-finetuned`) | Delta |
| :--- | :---: | :---: | :---: |
| **ROC-AUC** | 1.0 | **1.0** | +0.0000 |
| **Accuracy @ 0.5** | 0.9375 | **0.9375** | +0.0000 |
| **F1 @ 0.5** | 0.9412 | **0.9412** | +0.0000 |
| **TPR @ 1% FPR** | 1.0 | **1.0** | +0.0000 |
| **Calibrated ECE (10-bin)** | 0.061 | **0.0589** | -0.0021 |
| **Avg Latency (ms)** | 116.79 | **147.2** | +30.41 |
| **P95 Latency (ms)** | 265.72 | **274.64** | +8.92 |
| **Peak RAM (MB)** | 1350.23 | **1372.23** | — |

---

## 3. Promoted State (Post-Gate Activation)

- **Active Entry:** `detector_text@1.1.0-lora-finetuned` (previous `detector_text@1.0.0-asis` → `archived`)
- **Updated Manifest `version`:** `desklib-v1.01-lora-finetuned-fp16`
- **Updated Manifest `registry_entry_id`:** `detector_text@1.1.0-lora-finetuned`
- **Updated `performance.measured_on`:** `PromotionGate (CUDA) on eval/data/text/text_eval_manifest.jsonl (N=16, AUROC=1.0)`

---

## 4. Rollback State (Restored to As-Is Baseline)

- **Active Entry:** `detector_text@1.0.0-asis` (rolled back `detector_text@1.1.0-lora-finetuned` → `rolled_back`)
- **Restored Manifest `version`:** `desklib-ai-text-detector-v1.01-fp16`
- **Restored Calibration Checkpoint:** `eval/calibration/checkpoints/detector_text_platt_calibrator.json`
- **Manifest Schema Valid:** `True`
