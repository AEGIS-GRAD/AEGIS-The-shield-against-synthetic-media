"""Detector target adapters and inference-time mitigation wrappers for Robustness v2."""

from __future__ import annotations

import base64
import importlib.util
import io
import math
import os
import sys
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import httpx
import numpy as np
import torch
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)


@dataclass
class TargetScore:
    """Normalized detector evaluation returned per black-box query."""

    detector_name: str
    model_version: str
    modality: str
    confidence: float
    raw_score: float
    flags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _load_module(module_name: str, file_path: Path, add_sys_dir: Optional[Path] = None):
    if module_name in sys.modules:
        return sys.modules[module_name]
    inserted = False
    if add_sys_dir is not None and str(add_sys_dir) not in sys.path:
        sys.path.insert(0, str(add_sys_dir))
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location(module_name, str(file_path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load {module_name} from {file_path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if inserted and str(add_sys_dir) in sys.path:
            sys.path.remove(str(add_sys_dir))


def _frames_to_imagenet_tensor(frames: Sequence[np.ndarray], size: Tuple[int, int] = (224, 224)) -> torch.Tensor:
    """Converts RGB uint8 frames (H, W, 3) into normalized NCHW float32 tensor."""
    batch = []
    for frame in frames:
        arr = np.asarray(frame, dtype=np.uint8)
        if arr.ndim == 2:
            arr = np.stack([arr, arr, arr], axis=-1)
        resized = cv2.resize(arr, size, interpolation=cv2.INTER_LINEAR)
        batch.append(np.transpose(resized, (2, 0, 1)).astype(np.float32) / 255.0)
    stacked = np.stack(batch, axis=0)
    normed = (stacked - _IMAGENET_MEAN) / _IMAGENET_STD
    return torch.from_numpy(normed)


def _encode_png_b64(rgb: np.ndarray) -> str:
    buf = io.BytesIO()
    Image.fromarray(np.asarray(rgb, dtype=np.uint8)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _encode_mp4_b64(frames: Sequence[np.ndarray], fps: float = 10.0) -> str:
    import tempfile

    first = np.asarray(frames[0], dtype=np.uint8)
    h, w = first.shape[:2]
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_path), fourcc, fps, (w, h))
        for frame in frames:
            bgr = cv2.cvtColor(np.asarray(frame, dtype=np.uint8), cv2.COLOR_RGB2BGR)
            writer.write(bgr)
        writer.release()
        return base64.b64encode(tmp_path.read_bytes()).decode("ascii")
    finally:
        tmp_path.unlink(missing_ok=True)


class AdaptiveTarget(ABC):
    """Unified black-box query interface counting detector queries accurately."""

    name: str
    modality: str
    model_version: str

    def __init__(self) -> None:
        self.query_count = 0

    def reset_query_count(self) -> None:
        self.query_count = 0

    def query(self, payload: Any, meta: Optional[Dict[str, Any]] = None) -> TargetScore:
        self.query_count += 1
        return self._score_impl(payload, meta or {})

    @abstractmethod
    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        """Evaluates one payload without white-box gradients."""


class HTTPDetectorTarget(AdaptiveTarget):
    """Black-box client targeting live AEGIS HTTP/HTTPS mTLS `/detect` services."""

    def __init__(
        self,
        name: str,
        modality: str,
        base_url: str,
        internal_token: Optional[str] = None,
        ssl_cert: Optional[str] = None,
        ssl_key: Optional[str] = None,
        ssl_ca: Optional[str] = None,
        timeout_s: float = 15.0,
    ) -> None:
        super().__init__()
        self.name = name
        self.modality = modality
        self.model_version = f"http:{base_url.rstrip('/')}"
        self.detect_url = f"{base_url.rstrip('/')}/detect"
        self.headers = {"x-internal-token": internal_token} if internal_token else {}
        verify: Any = ssl_ca if ssl_ca else True
        cert = (ssl_cert, ssl_key) if (ssl_cert and ssl_key) else None
        self._client = httpx.Client(verify=verify, cert=cert, timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def _encode_payload(self, payload: Any) -> str:
        if self.modality == "text":
            return base64.b64encode(str(payload).encode("utf-8")).decode("ascii")
        if self.modality == "image":
            return _encode_png_b64(payload)
        if self.modality == "video":
            seq = payload if isinstance(payload, (list, tuple)) or getattr(payload, "ndim", 0) == 4 else [payload]
            return _encode_mp4_b64(seq)
        raise ValueError(f"Unsupported modality for HTTP target: {self.modality}")

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        body = {
            "job_id": f"rv2-{uuid.uuid4().hex[:10]}",
            "modality": self.modality,
            "payload": self._encode_payload(payload),
        }
        resp = self._client.post(self.detect_url, json=body, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        evidence = data.get("evidence") or {}
        return TargetScore(
            detector_name=self.name,
            model_version=str(data.get("model_version", self.model_version)),
            modality=self.modality,
            confidence=float(data.get("confidence", 0.5)),
            raw_score=float(data.get("raw_score", data.get("confidence", 0.5))),
            flags=list(evidence.get("flags") or []),
            metadata={"status": data.get("status", "ok")},
        )


class LocalImageFrameTarget(AdaptiveTarget):
    """Local AEGIS image target combining MobileNetV3-Small FF++ CNN + FFT/EXIF checks."""

    def __init__(self, checkpoint_path: Optional[Path] = None) -> None:
        super().__init__()
        self.name = "image_mobilenetv3_forensics_v2"
        self.modality = "image"
        self.model_version = "mobilenetv3_small_ffpp+fft+exif"

        from engine.edge_model.build_edge_model import get_mobilenet_v3_small_model

        self._model = get_mobilenet_v3_small_model(checkpoint_path=checkpoint_path, device="cpu")
        self._model.eval()
        self._freq_mod = _load_module(
            "aegis_rv2_freq", REPO_ROOT / "detectors" / "image" / "evidence" / "frequency_check.py"
        )
        self._exif_mod = _load_module(
            "aegis_rv2_exif", REPO_ROOT / "detectors" / "image" / "evidence" / "exif_check.py"
        )

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        rgb = np.asarray(payload, dtype=np.uint8)
        pil_img = Image.fromarray(rgb)
        freq_res = self._freq_mod.check_frequency(pil_img)
        exif_res = self._exif_mod.check_exif(pil_img)

        tensor = _frames_to_imagenet_tensor([rgb], size=(224, 224))
        with torch.inference_mode():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)
            cnn_prob = float(probs[0, 1].item())

        fft_bump = 0.04 if freq_res.get("flag") else 0.0
        conf = float(max(0.0, min(1.0, cnn_prob + fft_bump)))
        flags: List[str] = []
        if freq_res.get("flag"):
            flags.append("frequency_anomaly")
        if exif_res.get("exif_missing"):
            flags.append("exif_missing")
        if conf >= 0.85:
            flags.append("high_confidence_synthetic")
        return TargetScore(
            detector_name=self.name,
            model_version=self.model_version,
            modality="image",
            confidence=round(conf, 4),
            raw_score=round(cnn_prob, 4),
            flags=flags,
            metadata={"peak_ratio": freq_res.get("peak_ratio"), "cnn_prob": round(cnn_prob, 4)},
        )


class LocalVideoEfficientNetTarget(AdaptiveTarget):
    """Local AEGIS video target wrapping `efficientnet_b0_ffpp_finetuned.pth`."""

    def __init__(self, checkpoint_path: Optional[Path] = None) -> None:
        super().__init__()
        self.name = "video_efficientnet_b0_v2"
        self.modality = "video"
        ckpt = checkpoint_path or (
            REPO_ROOT / "detectors" / "video-classifier" / "models" / "efficientnet_b0_ffpp_finetuned.pth"
        )
        self.model_version = f"efficientnet-b0-ffpp({ckpt.name})"
        vc_dir = REPO_ROOT / "detectors" / "video-classifier"
        self._infer_mod = _load_module("aegis_rv2_vc_infer", vc_dir / "infer.py", add_sys_dir=vc_dir)
        self._model = self._infer_mod.load_model(device="cpu", checkpoint_path=ckpt)
        self._model.eval()

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        if isinstance(payload, np.ndarray) and payload.ndim == 3:
            frames = [payload]
        else:
            frames = list(payload)
        tensor = _frames_to_imagenet_tensor(frames, size=(224, 224))
        with torch.inference_mode():
            logits = self._model(tensor)
            probs = torch.softmax(logits, dim=1)[:, 1].tolist()
        conf = float(self._infer_mod.aggregate_scores([float(p) for p in probs]))
        flags = ["high_confidence_synthetic"] if conf >= 0.85 else ([] if conf < 0.5 else ["moderate_synthetic"])
        return TargetScore(
            detector_name=self.name,
            model_version=self.model_version,
            modality="video",
            confidence=round(conf, 4),
            raw_score=round(conf, 4),
            flags=flags,
            metadata={"frame_count": len(probs), "frame_min": round(min(probs), 4), "frame_max": round(max(probs), 4)},
        )


class LocalTextForensicTarget(AdaptiveTarget):
    """Local AEGIS text target combining `ingest.py` + `stylometry.py` + repetition/uniformity profile."""

    def __init__(self, chunk_floor_defense: bool = False) -> None:
        super().__init__()
        self.name = "text_forensics_local_v2"
        self.modality = "text"
        self.model_version = "ingest+stylometry_local_v2"
        self.chunk_floor_defense = chunk_floor_defense
        td_dir = REPO_ROOT / "detectors" / "text-detector"
        self._ingest = _load_module("aegis_rv2_text_ingest", td_dir / "ingest.py", add_sys_dir=td_dir)
        self._stylo = _load_module("aegis_rv2_text_stylo", td_dir / "stylometry.py", add_sys_dir=td_dir)

    def _window_scores(self, text: str) -> List[float]:
        sentences = [s.strip() for s in self._stylo._tokenize_sentences(text) if s.strip()]
        if len(sentences) < 4:
            return [float(self._stylo.extract_stylometry_features(text)["synthetic_indication_score"])]
        scores = []
        for idx in range(len(sentences) - 2):
            win = " ".join(sentences[idx : idx + 3])
            scores.append(float(self._stylo.extract_stylometry_features(win)["synthetic_indication_score"]))
        return scores

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        raw_text = str(payload)
        ingested = self._ingest.prepare_raw_text(raw_text, max_chars=20000)
        if ingested.word_count < 40:
            return TargetScore(
                detector_name=self.name,
                model_version=self.model_version,
                modality="text",
                confidence=0.5,
                raw_score=0.0,
                flags=["text_too_short", "not_applicable"],
                metadata={"word_count": ingested.word_count},
            )

        feat = self._stylo.extract_stylometry_features(ingested.text)
        base_score = float(feat["synthetic_indication_score"])
        sent_var = feat["sentence_variation"]
        vocab = feat["vocabulary_diversity"]
        rep3 = feat["ngram_repetition"].get("3gram_repetition_rate", 0.0)
        cov = float(sent_var.get("sentence_length_cov", 0.5))
        ttr = float(vocab.get("ttr", 0.5))

        # Calibrated smooth signal so single-turn heuristic tweaks move score smoothly rather than cliff-jumping
        logit = (
            (0.45 - cov) * 2.2
            + (0.62 - ttr) * 1.4
            + max(0.0, rep3 - 0.03) * 4.5
            + (base_score - 0.5) * 1.8
        )
        conf = 1.0 / (1.0 + math.exp(-logit))
        if self.chunk_floor_defense:
            win_scores = self._window_scores(ingested.text)
            max_win = max(win_scores)
            # Robust trimmed CoV ignores short (<5-word) injected lead-ins meant to inflate sentence variance
            sent_lens = sorted(
                len(self._stylo._tokenize_words(s))
                for s in self._stylo._tokenize_sentences(ingested.text)
            )
            substantive = [w for w in sent_lens if w >= 5]
            if len(substantive) >= 3:
                mean_sub = sum(substantive) / len(substantive)
                std_sub = math.sqrt(sum((w - mean_sub) ** 2 for w in substantive) / len(substantive))
                trimmed_cov = std_sub / max(1e-6, mean_sub)
                trimmed_logit = (
                    (0.45 - trimmed_cov) * 2.4
                    + (0.65 - ttr) * 1.4
                    + max(0.0, rep3 - 0.02) * 4.5
                    + (max_win - 0.48) * 1.8
                )
                trimmed_conf = 1.0 / (1.0 + math.exp(-trimmed_logit))
                conf = max(conf, 0.55 * trimmed_conf + 0.45 * max_win)

        flags: List[str] = []
        if cov < 0.35:
            flags.append("low_burstiness")
        if ttr < 0.58:
            flags.append("low_lexical_diversity")
        if rep3 > 0.05:
            flags.append("repetitive_ngrams")
        if ingested.stripped_control_chars >= 3:
            flags.append("adversarial_unicode_stripped")
        if conf >= 0.70:
            flags.append("high_ai_probability")

        return TargetScore(
            detector_name=self.name,
            model_version=self.model_version,
            modality="text",
            confidence=round(float(max(0.0, min(1.0, conf))), 4),
            raw_score=round(base_score, 4),
            flags=flags,
            metadata={
                "word_count": ingested.word_count,
                "ttr": ttr,
                "sentence_length_cov": cov,
                "3gram_repetition_rate": rep3,
            },
        )


def _ahash_hex(rgb: np.ndarray) -> str:
    gray = cv2.resize(cv2.cvtColor(np.asarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2GRAY), (8, 8))
    bits = (gray >= float(gray.mean())).flatten()
    val = 0
    for b in bits:
        val = (val << 1) | int(b)
    return f"{val:016x}"


class QueryThrottledError(RuntimeError):
    """Raised or caught cleanly when adaptive probe burst exceeds query budget."""


class HardenedVisionDefense(AdaptiveTarget):
    """Inference-time vision mitigation: multi-view randomized smoothing, JPEG defense, and score quantization."""

    def __init__(
        self,
        base_target: AdaptiveTarget,
        num_views: int = 5,
        crop_jitter: float = 0.04,
        jpeg_quality: int = 80,
        noise_std: float = 3.5,
        confidence_quantum: float = 0.05,
        query_burst_limit: int = 1000,
        seed: int = 1337,
    ) -> None:
        super().__init__()
        self._base = base_target
        self.name = f"{base_target.name}_hardened"
        self.modality = base_target.modality
        self.model_version = f"{base_target.model_version}+defense_v2"
        self.num_views = max(1, int(num_views))
        self.crop_jitter = float(crop_jitter)
        self.jpeg_quality = int(jpeg_quality)
        self.noise_std = float(noise_std)
        self.confidence_quantum = float(confidence_quantum)
        self.query_burst_limit = int(query_burst_limit)
        self._rng = np.random.default_rng(seed)
        self._recent_hashes: Deque[str] = deque(maxlen=512)
        self._hash_counts: Dict[str, int] = {}

    def _transform_frame(self, rgb: np.ndarray, idx: int) -> np.ndarray:
        arr = np.asarray(rgb, dtype=np.uint8)
        h, w = arr.shape[:2]
        if idx > 0 and self.crop_jitter > 0.0 and min(h, w) >= 32:
            dy = int(self._rng.integers(0, max(1, int(h * self.crop_jitter) + 1)))
            dx = int(self._rng.integers(0, max(1, int(w * self.crop_jitter) + 1)))
            arr = arr[dy : h - dy if dy else h, dx : w - dx if dx else w]
            arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_AREA)

        if self.jpeg_quality > 0:
            buf = io.BytesIO()
            Image.fromarray(arr).save(buf, format="JPEG", quality=self.jpeg_quality)
            buf.seek(0)
            arr = np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)

        if idx > 0 and self.noise_std > 0.0:
            noise = self._rng.normal(0.0, self.noise_std, size=arr.shape)
            arr = np.clip(arr.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        return arr

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        is_seq = isinstance(payload, (list, tuple)) or (isinstance(payload, np.ndarray) and payload.ndim == 4)
        frames = [np.asarray(f, dtype=np.uint8) for f in (payload if is_seq else [payload])]

        key = _ahash_hex(frames[0])[:8]
        self._hash_counts[key] = self._hash_counts.get(key, 0) + 1
        throttled = self._hash_counts[key] > self.query_burst_limit

        view_scores: List[float] = []
        last_res: Optional[TargetScore] = None
        for v_idx in range(self.num_views):
            transformed = [self._transform_frame(f, v_idx) for f in frames]
            res = self._base._score_impl(transformed if is_seq else transformed[0], meta)
            view_scores.append(res.confidence)
            last_res = res

        avg_conf = float(sum(view_scores) / len(view_scores))
        q = self.confidence_quantum
        quantized = round(round(avg_conf / q) * q, 4) if q > 0 else round(avg_conf, 4)
        quantized = max(0.0, min(1.0, quantized))

        flags = list(last_res.flags if last_res else [])
        flags.append("defense_multiview_smoothing")
        if throttled:
            flags.append("query_burst_detected")
            quantized = max(quantized, 0.55)

        return TargetScore(
            detector_name=self.name,
            model_version=self.model_version,
            modality=self.modality,
            confidence=quantized,
            raw_score=round(avg_conf, 4),
            flags=sorted(set(flags)),
            metadata={
                "view_scores": [round(s, 4) for s in view_scores],
                "query_burst_count": self._hash_counts[key],
                "throttled": throttled,
            },
        )


class HardenedTextDefense(AdaptiveTarget):
    """Inference-time text hardening: chunk-window floor + NFKC canonicalization + score quantization."""

    def __init__(
        self,
        base_target: AdaptiveTarget,
        confidence_quantum: float = 0.05,
        chunk_floor_target: Optional[LocalTextForensicTarget] = None,
    ) -> None:
        super().__init__()
        self._base = base_target
        self._floor_target = chunk_floor_target or (
            LocalTextForensicTarget(chunk_floor_defense=True)
            if isinstance(base_target, LocalTextForensicTarget)
            else None
        )
        self.name = f"{base_target.name}_hardened"
        self.modality = "text"
        self.model_version = f"{base_target.model_version}+defense_v2"
        self.confidence_quantum = float(confidence_quantum)

    def _score_impl(self, payload: Any, meta: Dict[str, Any]) -> TargetScore:
        if self._floor_target is not None:
            res = self._floor_target._score_impl(payload, meta)
        else:
            res = self._base._score_impl(payload, meta)

        q = self.confidence_quantum
        quantized = round(round(res.confidence / q) * q, 4) if q > 0 else round(res.confidence, 4)
        quantized = max(0.0, min(1.0, quantized))
        flags = list(res.flags) + ["defense_chunk_floor", "defense_score_quantized"]
        return TargetScore(
            detector_name=self.name,
            model_version=self.model_version,
            modality="text",
            confidence=quantized,
            raw_score=res.raw_score,
            flags=sorted(set(flags)),
            metadata=res.metadata,
        )
