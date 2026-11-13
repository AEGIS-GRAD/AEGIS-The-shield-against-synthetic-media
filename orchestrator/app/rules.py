from typing import List
from models import InputMetadata


def decide_detectors_to_call(metadata: InputMetadata) -> List[str]:
    detectors: List[str] = []

    if metadata.modality == "video":
        detectors.append("video-classifier")
        detectors.append("rppg")
        if metadata.has_audio:
            detectors.append("syncnet")

    elif metadata.modality == "image":
        detectors.append("detector_image")

    elif metadata.modality == "text":
        detectors.append("detector_text")

    if metadata.has_audio:
        detectors.append("aasist")

    return detectors
