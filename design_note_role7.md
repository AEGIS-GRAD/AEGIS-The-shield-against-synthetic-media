# Design Note — Role 7: Verify Bundles of Related Media

## 1. Problem Overview
Individual detectors evaluate single modalities in isolation (e.g., image-only, audio-only, text-only). Real-world synthetic media often arrives as bundled packages—such as a deepfake image paired with a human-authored journalistic caption, or a real video paired with an AI-dubbed voice track or an AI-generated transcript. A system inspecting only one channel fails to detect partial manipulations or inconsistencies across channels. Bundle verification addresses this gap by accepting multi-item bundles in a single request, routing each piece of media to its appropriate detectors, and fusing the outcomes into a consolidated bundle verdict alongside an explicit cross-modal agreement analysis.

## 2. Architecture & Components
The bundle verification pipeline integrates into `orchestrator/app/` using the following components:

- **`bundle_parser.py` (`parse_bundle`)**:
  Parses incoming `multipart/form-data` requests. Extracts file uploads (`image`, `video`, `audio`) and text payloads (`text`, `caption`, `transcript`). Saves transient files to an isolated temporary directory and wraps the inputs into a structured `BundleRequest`.

- **`bundle_router.py` (`route_bundle`)**:
  Inspects the modalities present in `BundleRequest` and maps them to their respective detector microservices (`detector_image`, `detector_text`, `video-classifier`, `rppg`, `aasist`). Reuses the existing asynchronous HTTP/mTLS dispatch mechanism (`call_all_detectors`) from `dispatch.py`. Handles individual detector failures gracefully without aborting the remaining pipeline.

- **`bundle_fusion.py` (`fuse_bundle`)**:
  Applies weighted confidence fusion across the evaluated modalities. Computes modality-level verdicts using the established baseline thresholds (`SYNTHETIC >= 0.65`, `AUTHENTIC <= 0.35`, else `UNCERTAIN`). Produces an overall `bundle_score` and `bundle_verdict`.
  - Modality weights: Video (1.5), Image (1.2), Audio (1.0), Text (0.8).

- **`bundle_agreement.py` (`compute_agreement`)**:
  Analyzes cross-modal alignment across valid detector results.
  - States:
    - `agree_synthetic`: All modalities indicate synthetic media.
    - `agree_authentic`: All modalities indicate authentic media.
    - `partial`: Majority agreement (>= 75%), identifying minority conflicting modalities (e.g., authentic caption on synthetic image).
    - `disagree`: Significant split/disagreement between modalities; explicitly flagged for human analyst review.
    - `single`: Degenerate bundle containing only a single modality.
    - `insufficient`: All detectors failed or returned no results.

- **Endpoint (`POST /orchestrate/bundle`) in `main.py`**:
  Exposes the bundle orchestration interface accepting multipart requests, coordinating parser, router, fusion, and agreement analysis, returning a structured JSON response.

## 3. Disagreement & Failure Handling
1. **Explicit Disagreements**: When modalities conflict (e.g., fake video + authentic audio), the overall verdict falls back to `UNCERTAIN` or flags partial manipulation, and `cross_modal_agreement.state` is set to `"disagree"`. Conflicting modalities are enumerated under `conflicting_modalities`.
2. **Graceful Fault Tolerance**: If a detector fails (e.g. connection timeout, service outage), it is excluded from skewing the weighted score rather than defaulting to an arbitrary probability. If all detectors fail, the state reports `insufficient` with `NO_RESULTS`.

## 4. Test Suite (`eval/tests/test_role7_bundles.py`)
The implementation is verified across 12 distinct scenario classes comprising >= 20 unit and integration tests:
- Case 1: Image + Text both synthetic (`agree_synthetic`).
- Case 2: Image + Text both authentic (`agree_authentic`).
- Case 3: Synthetic image + Authentic caption (**Disagreement** flagged).
- Case 4: Authentic image + Synthetic caption (**Disagreement** flagged).
- Case 5: Deepfake video + Synthetic transcript + Synthetic audio (Tri-modal agreement).
- Case 6: Authentic video + Dubbed synthetic audio (**Disagreement** flagged).
- Case 7: Degenerate single-modality bundle.
- Case 8: Comprehensive failure handling across detectors.
- Case 9: Multi-modal high-confidence synthetic detection.
- Case 10: Inconclusive/borderline scores.
- Case 11: 3-vs-1 partial agreement with outlier attribution.
- Case 12: Video-only deepfake with authentic audio track (**Disagreement** flagged).
