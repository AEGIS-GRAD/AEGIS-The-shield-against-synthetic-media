# AEGIS — Model Scope

This document details the 6 detector models finalized for the AEGIS project. It serves as the reference scope deliverable for Week 1 Task 1, shared across the AI, Cybersecurity, and Infrastructure tracks.

| Modality | Model | Repo/Checkpoint | Reported Metric | Source Dataset |
|---|---|---|---|---|
| Video (frame-level) | EfficientNet-B0 (FF++ c23) | Xicor9/efficientnet-b0-ffpp-c23 | | FaceForensics++ (c23) |
| Video (physiological) | rPPG (PhysNet/DeepPhys) | ubicomplab/rPPG-Toolbox | | |
| Audio-visual sync | SyncNet | joonson/syncnet_python | | |
| Audio (voice spoofing) | AASIST | clovaai/aasist | | ASVspoof 2019 LA (Logical Access, CM task only) |
| Text | Binoculars | ahans30/Binoculars | | |
| Image (GAN/diffusion) | Wang et al. CNN-Detection | peterwang512/CNNDetection | | |

### Scope Note

The original proposal suggested deprioritizing text and image to future work, but the team has since expanded Month 1-2 scope to cover all 6 modalities/models above.

### Dataset Staging Status

Both primary evaluation datasets are now extracted and staged locally:

- **FaceForensics++ (c23)** — raw data at `D:/archive/FaceForensics++_C23/`; eval subset staged at `eval/data/video_subset/{real,fake}/` via `eval/scripts/make_subset.py`.
- **ASVspoof 2019 LA** — raw data at `D:/LA/LA/`; eval subset staged at `eval/data/audio_subset/{real,fake}/` via `eval/scripts/make_audio_subset.py`. Only the CM (countermeasure) protocol files are used; ASV protocol/score files are a different task and are ignored.

See `eval/DATA.md` for full download, extraction, and subset-generation instructions for both datasets.

