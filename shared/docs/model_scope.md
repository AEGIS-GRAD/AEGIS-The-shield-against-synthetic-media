# AEGIS — Model Scope

This document details the 6 detector models finalized for the AEGIS project. It serves as the reference scope deliverable for Week 1 Task 1, shared across the AI, Cybersecurity, and Infrastructure tracks.

| Modality | Model | Repo/Checkpoint | Reported Metric | Source Dataset |
|---|---|---|---|---|
| Video (frame-level) | Xception (FF++ baseline) | ondyari/FaceForensics (classification folder) | | FaceForensics++ |
| Video (physiological) | rPPG (PhysNet/DeepPhys) | ubicomplab/rPPG-Toolbox | | |
| Audio-visual sync | SyncNet | joonson/syncnet_python | | |
| Audio (voice spoofing) | AASIST | clovaai/aasist | | ASVspoof 2019 LA |
| Text | Binoculars | ahans30/Binoculars | | |
| Image (GAN/diffusion) | Wang et al. CNN-Detection | peterwang512/CNNDetection | | |

### Scope Note

The original proposal suggested deprioritizing text and image to future work, but the team has since expanded Month 1-2 scope to cover all 6 modalities/models above.

### Score/Verdict Convention

All AEGIS detector microservices must adhere to the following shared response contract:

- **score**: `float` in `[0, 1]`, representing $P(\text{synthetic})$ — higher score = more likely fake.
- **verdict**: `"synthetic"` if `score > 0.5`, else `"authentic"`.
- **confidence**: distance from the 0.5 decision threshold, calculated as `abs(score - 0.5) * 2`.
