# PRNU Source-Separation Evaluation — proxy: 3 web-compressed sample videos (NOT physical cameras)

**Date:** 2026-11-16 19:21 UTC · **Script:** `eval/scripts/prnu_real_camera_eval.py`
**Sources:** authentic, deepfake, manipulated · **Common centre crop:** 480x600 (no resampling) · **Enrolment frames / source:** 40
**Probe frames:** 360 · **DWT level:** 2 · **Gateway threshold:** PCE 50

| Statistic | Same-source median | Cross-source median | Same-source accepted @50 | Foreign accepted @50 | ROC AUC | EER |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Gateway PCE (peak at any shift) | 40580.7 | 20.0 | 100.0% | 0.0% | 1.000 | 0.0% |
| Classic zero-shift PCE | 2161.3 | 3.3 | 100.0% | 0.0% | 1.000 | 0.0% |

Median gateway PCE, probe source (row) against enrolled baseline (column):

| probe \ enrolled | authentic | deepfake | manipulated |
|---|---|---|---|
| **authentic** | 147786.7 | 18.1 | 19.9 |
| **deepfake** | 20.2 | 5435.1 | 20.1 |
| **manipulated** | 21.7 | 19.7 | 40469.8 |

