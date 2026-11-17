"""Built-in benchmark dataset loaders for Robustness v2 evaluation."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Sequence, Tuple

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class VisionSample:
    sample_id: str
    modality: str
    payload: Any  # np.ndarray (H,W,3) for image; List[np.ndarray] (T,H,W,3) for video
    source_path: str


@dataclass
class TextSample:
    sample_id: str
    domain: str
    text: str


def _load_video_preprocessor():
    vc_dir = REPO_ROOT / "detectors" / "video-classifier"
    inserted = False
    if str(vc_dir) not in sys.path:
        sys.path.insert(0, str(vc_dir))
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location("aegis_rv2_vp", vc_dir / "preprocess.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.VideoPreprocessor(target_size=(224, 224), device="cpu")
    finally:
        if inserted and str(vc_dir) in sys.path:
            sys.path.remove(str(vc_dir))


def load_vision_benchmark_samples(
    max_video_clips: int = 8,
    max_images: int = 8,
    frames_per_clip: int = 4,
) -> Tuple[List[VisionSample], List[VisionSample]]:
    """Extracts RGB face crops & multi-frame clips from tracked AEGIS synthetic video fixtures."""
    vp = _load_video_preprocessor()
    candidate_relpaths = [
        "web/public/sample_videos/deepfake_feed.mp4",
        "web/public/sample_videos/manipulated_feed.mp4",
        "eval/fixtures/edge_cases/clean_baseline.mp4",
        "eval/fixtures/edge_cases/dim_light.mp4",
        "eval/fixtures/edge_cases/poorly_lit.mp4",
        "eval/fixtures/edge_cases/occluded_face.mp4",
        "eval/fixtures/edge_cases/borderline_short.mp4",
        "eval/fixtures/edge_cases/marginal_short.mp4",
        "eval/fixtures/edge_cases/short_clip.mp4",
        "eval/fixtures/edge_cases/silent_video.mp4",
    ]
    video_samples: List[VisionSample] = []
    image_samples: List[VisionSample] = []

    for rel in candidate_relpaths:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        raw_frames = vp.extract_frames(path, sample_n=15)
        if not raw_frames:
            cap = cv2.VideoCapture(str(path))
            ok, bgr = cap.read()
            cap.release()
            if ok:
                raw_frames = [cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)]
        if not raw_frames:
            continue

        crops: List[np.ndarray] = []
        for frame in raw_frames[:frames_per_clip]:
            face = vp.crop_face(frame)
            face_224 = cv2.resize(face, (224, 224), interpolation=cv2.INTER_LINEAR)
            crops.append(face_224.astype(np.uint8))

        while len(crops) < frames_per_clip:
            crops.append(crops[-1].copy())

        stem = path.stem
        if len(video_samples) < max_video_clips:
            video_samples.append(VisionSample(sample_id=f"vid_{stem}", modality="video", payload=crops, source_path=rel))
        if len(image_samples) < max_images:
            image_samples.append(VisionSample(sample_id=f"img_{stem}", modality="image", payload=crops[0].copy(), source_path=rel))

    return image_samples, video_samples


def load_text_benchmark_samples(limit: Optional[int] = None) -> List[TextSample]:
    """Held-out synthetic-style prose passages spanning diverse domains (>=75 words each)."""
    samples = [
        TextSample(
            sample_id="txt_ai_cyber_01",
            domain="cybersecurity",
            text=(
                "Organizations frequently implement layered authentication controls to mitigate unauthorized network access. "
                "Furthermore, continuous monitoring frameworks demonstrate consistent improvements in threat detection accuracy across distributed environments. "
                "Additionally, security teams must evaluate configuration baselines routinely to maintain strict compliance posture. "
                "Therefore, adopting automated verification pipelines remains essential for safeguarding critical infrastructure systems. "
                "Consequently, consistent audit procedures facilitate rapid incident response and strengthen overall resilience across modern enterprise deployments."
            ),
        ),
        TextSample(
            sample_id="txt_ai_policy_02",
            domain="policy",
            text=(
                "Comprehensive regulatory frameworks play an essential role in ensuring accountable artificial intelligence deployment across public sectors. "
                "Moreover, transparent documentation standards enable independent auditors to evaluate algorithmic fairness and operational reliability consistently. "
                "Furthermore, policymakers should balance innovation incentives with clear safeguards against synthetic misinformation risks. "
                "Therefore, cross-sector collaboration remains essential to establish durable governance norms. "
                "Consequently, standardized compliance reporting demonstrates measurable progress toward trustworthy digital ecosystems."
            ),
        ),
        TextSample(
            sample_id="txt_ai_finance_03",
            domain="finance",
            text=(
                "Modern financial institutions utilize predictive risk modeling to evaluate portfolio exposure under shifting macroeconomic conditions. "
                "Additionally, automated compliance monitoring demonstrates significant efficiency gains compared to manual transaction review workflows. "
                "However, legacy settlement architectures frequently create operational bottlenecks during peak clearing windows. "
                "Therefore, engineering leaders prioritize modular ledger upgrades while maintaining strict auditability controls. "
                "Consequently, balanced capital allocation depends on accurate forecasting and disciplined governance."
            ),
        ),
        TextSample(
            sample_id="txt_ai_health_04",
            domain="healthcare",
            text=(
                "Clinical decision support platforms demonstrate promising accuracy when assisting radiologists with early anomaly screening. "
                "Furthermore, standardized data pipelines facilitate consistent model validation across diverse hospital populations. "
                "However, practitioners must evaluate algorithmic uncertainty carefully before integrating automated alerts into critical care pathways. "
                "Additionally, strict privacy safeguards protect patient records throughout model training and inference cycles. "
                "Therefore, rigorous clinical trials remain essential for trustworthy medical adoption."
            ),
        ),
        TextSample(
            sample_id="txt_ai_edu_05",
            domain="education",
            text=(
                "Adaptive learning platforms utilize formative assessment metrics to personalize instructional pacing for individual students. "
                "Moreover, structured feedback loops demonstrate measurable improvements in conceptual retention across STEM curricula. "
                "Nevertheless, educators frequently emphasize that digital tools supplement rather than replace collaborative classroom discussion. "
                "Therefore, academic institutions evaluate software vendors carefully to ensure equitable accessibility across districts. "
                "Consequently, thoughtful integration strategies enhance instructional outcomes without overwhelming faculty workloads."
            ),
        ),
        TextSample(
            sample_id="txt_ai_climate_06",
            domain="energy",
            text=(
                "Grid operators increasingly utilize real-time telemetry analytics to balance renewable generation across regional transmission networks. "
                "Furthermore, utility-scale battery storage systems mitigate frequency volatility during rapid cloud-cover transitions. "
                "Additionally, standardized interconnection protocols facilitate smoother integration of distributed solar installations. "
                "However, aging substation transformers frequently constrain peak transfer capacity along rural corridors. "
                "Therefore, coordinated infrastructure investment remains essential for reliable decarbonization targets."
            ),
        ),
        TextSample(
            sample_id="txt_ai_supply_07",
            domain="logistics",
            text=(
                "Global manufacturing networks utilize multi-tier inventory tracking to mitigate sudden component shortages across regional hubs. "
                "Additionally, predictive demand forecasting demonstrates substantial cost reductions compared to static buffer stocking policies. "
                "Furthermore, automated port scheduling systems facilitate faster container turnaround during seasonal volume surges. "
                "However, fragmented carrier data standards frequently complicate end-to-end shipment visibility across borders. "
                "Therefore, harmonized electronic manifests remain essential for resilient supply chains."
            ),
        ),
        TextSample(
            sample_id="txt_ai_legal_08",
            domain="forensics",
            text=(
                "Digital provenance verification establishes verifiable cryptographic custody from sensor capture through courtroom presentation. "
                "Moreover, continuous hash chaining demonstrates immediate tamper sensitivity whenever intermediate video frames undergo alteration. "
                "Additionally, automated metadata inspection flags stripped camera signatures and anomalous encoding histories reliably. "
                "Nevertheless, forensic analysts evaluate multiple independent detectors before issuing formal evidentiary findings. "
                "Consequently, transparent audit trails enhance judicial confidence in synthetic media attribution."
            ),
        ),
    ]
    return samples[:limit] if limit is not None else samples
