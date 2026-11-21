"""
bundle_router.py
================
Routes each BundleItem to the correct detector(s) using the existing
dispatch.py infrastructure.

Key function:
    route_bundle(bundle, job_id) → Dict[modality, List[DetectorResult]]
"""

import uuid
from typing import Dict, List

from models import DetectorResult
from dispatch import call_all_detectors   # already exists in orchestrator/app/
from bundle_parser import BundleRequest, BundleItem

# Which detector service handles each modality?
# Mirrors the logic in rules.py + dispatch.py
MODALITY_DETECTORS: Dict[str, List[str]] = {
    "image": ["detector_image"],
    "text":  ["detector_text"],
    "video": ["video-classifier", "rppg"],
    "audio": ["aasist"],
}


async def route_bundle(
    bundle: BundleRequest,
    job_id: str,
) -> Dict[str, List[DetectorResult]]:
    """
    For each modality in the bundle, dispatch to the appropriate detector(s).
    Returns a dict: modality → list of DetectorResult objects.
    """
    results: Dict[str, List[DetectorResult]] = {}

    for modality, item in bundle.items.items():
        detectors = MODALITY_DETECTORS.get(modality, [])
        if not detectors or not item.file_path:
            continue

        modality_job_id = f"{job_id}_{modality}"
        try:
            det_results = await call_all_detectors(
                detectors=detectors,
                job_id=modality_job_id,
                modality=modality,
                file_path=item.file_path,
            )
            results[modality] = det_results
        except Exception as exc:
            # Graceful degradation — record the failure, don't crash the whole bundle
            results[modality] = [
                DetectorResult(
                    detector=detectors[0] if detectors else "unknown",
                    status="failed",
                    job_id=modality_job_id,
                    error=str(exc),
                )
            ]

    return results