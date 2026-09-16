from typing import List
from models import InputMetadata


def decide_detectors_to_call(metadata: InputMetadata) -> List[str]:
    detectors: List[str] = []

    if metadata.modality in ("video", "image"):
        detectors.append("video-classifier")

    if metadata.modality == "video":
        detectors.append("rppg")

    if metadata.has_audio:
        detectors.append("aasist")
        if metadata.modality == "video":
            detectors.append("syncnet")

    return detectors