# FaceForensics++ (FF++ C23) Legacy Baseline Checkpoints

This folder contains the original legacy EfficientNet-B0 model checkpoints trained on raw FaceForensics++ C23 video frames:

- `efficientnet_b0_ffpp_finetuned.pth` (16.3 MB): Best weights from the legacy FF++ run.
- `efficientnet_b0_ffpp_ckpt_ep10.pth` (48.6 MB): Epoch 10 full checkpoint.
- `finetune_efficientnet_log.csv`: Training and validation log.

## Purpose & Research Context
These checkpoints are preserved strictly for **ablation studies, baseline comparisons, and thesis benchmarking**.
In production, live inference, and containerized deployment, AEGIS uses the new **DF40-trained model** (`../efficientnet_b0_df40_finetuned.pth`), which was trained on aligned face crops across 27 generative deepfake methods and achieved 98.43% frame AUC, 99.75% video AUC, and 99.53% zero-shot generalization.
