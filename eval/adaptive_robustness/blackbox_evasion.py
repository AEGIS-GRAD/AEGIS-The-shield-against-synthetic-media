"""Score-based black-box query evasion attacks for AEGIS image & video detectors."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from eval.adaptive_robustness.detectors import AdaptiveTarget

DEFAULT_QUERY_CHECKPOINTS = (1, 10, 25, 50, 75, 100, 150)


@dataclass
class VisionEvasionTrace:
    """Complete query-by-query evasion outcome for one image or video sample."""

    sample_id: str
    modality: str
    detector_name: str
    attack_method: str
    clean_confidence: float
    final_confidence: float
    score_drop: float
    flipped: bool
    queries_used: int
    flip_query: Optional[int]
    linf_norm: float
    l2_norm: float
    psnr_db: float
    trajectory: Dict[int, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvasionCurveRow:
    """Single point on an evasion success-rate (ASR vs budget) curve."""

    modality: str
    detector_name: str
    attack_method: str
    budget_unit: str
    budget_value: int
    total_detected_clean: int
    evaded_count: int
    asr: float
    mean_confidence: float
    mean_score_drop: float


def _as_batch(clean: Any) -> Tuple[np.ndarray, bool]:
    arr = np.asarray(clean, dtype=np.uint8)
    if arr.ndim == 3:
        return arr[np.newaxis, ...], False
    if arr.ndim == 4:
        return arr, True
    raise ValueError(f"Expected 3D image or 4D video frames, got shape {arr.shape}")


def _unwrap(batch: np.ndarray, is_video: bool) -> Any:
    return [batch[i] for i in range(batch.shape[0])] if is_video else batch[0]


def _distortion_metrics(clean_u8: np.ndarray, adv_u8: np.ndarray) -> Tuple[float, float, float]:
    diff = adv_u8.astype(np.float32) - clean_u8.astype(np.float32)
    linf = float(np.max(np.abs(diff)) / 255.0)
    l2 = float(np.sqrt(np.mean(diff ** 2)) / 255.0)
    mse = float(np.mean(diff ** 2))
    psnr = 99.0 if mse < 1e-10 else float(10.0 * math.log10((255.0 ** 2) / mse))
    return round(linf, 4), round(l2, 4), round(psnr, 2)


def _square_fraction(step_frac: float, p_init: float) -> float:
    """Exponential decay schedule from Andriushchenko et al. Square Attack."""
    if step_frac < 0.005:
        return p_init
    if step_frac < 0.02:
        return p_init * 0.5
    if step_frac < 0.05:
        return p_init * 0.25
    if step_frac < 0.15:
        return p_init * 0.125
    if step_frac < 0.4:
        return p_init * 0.0625
    return max(0.015, p_init * 0.03)


def run_square_attack(
    sample_id: str,
    clean_input: Any,
    target: AdaptiveTarget,
    threshold: float = 0.5,
    eps: float = 16.0 / 255.0,
    max_queries: int = 150,
    p_init: float = 0.30,
    checkpoints: Sequence[int] = DEFAULT_QUERY_CHECKPOINTS,
    seed: int = 42,
) -> Tuple[VisionEvasionTrace, np.ndarray]:
    """Runs L_inf score-based black-box Square Attack against an image or video target."""
    clean_batch, is_video = _as_batch(clean_input)
    modality = "video" if is_video else "image"
    t_steps, height, width, channels = clean_batch.shape
    eps_u8 = max(1, int(round(eps * 255.0)))
    rng = np.random.default_rng(seed)

    # Query 1: clean baseline score
    res0 = target.query(_unwrap(clean_batch, is_video))
    clean_conf = float(res0.confidence)
    trajectory: Dict[int, float] = {1: clean_conf}
    best_adv = clean_batch.copy()
    best_conf = clean_conf
    flip_query: Optional[int] = 1 if clean_conf < threshold else None
    queries_used = 1

    if flip_query is not None or max_queries <= 1:
        for cp in checkpoints:
            trajectory.setdefault(cp, best_conf)
        linf, l2, psnr = _distortion_metrics(clean_batch, best_adv)
        return (
            VisionEvasionTrace(
                sample_id=sample_id,
                modality=modality,
                detector_name=target.name,
                attack_method="square_linf",
                clean_confidence=clean_conf,
                final_confidence=best_conf,
                score_drop=round(clean_conf - best_conf, 4),
                flipped=best_conf < threshold,
                queries_used=queries_used,
                flip_query=flip_query,
                linf_norm=linf,
                l2_norm=l2,
                psnr_db=psnr,
                trajectory=trajectory,
                metadata={"eps": round(eps, 4), "max_queries": max_queries},
            ),
            best_adv[0] if not is_video else best_adv,
        )

    # Query 2: Vertical-stripe sign initialization (temporally shared across frames for video)
    stripe = rng.choice([-eps_u8, eps_u8], size=(1, 1, width, channels)).astype(np.int16)
    init_adv = np.clip(clean_batch.astype(np.int16) + stripe, 0, 255).astype(np.uint8)
    cand_score = float(target.query(_unwrap(init_adv, is_video)).confidence)
    queries_used += 1
    if cand_score < best_conf:
        best_conf = cand_score
        best_adv = init_adv
        if best_conf < threshold and flip_query is None:
            flip_query = queries_used

    delta = best_adv.astype(np.int16) - clean_batch.astype(np.int16)
    for cp in checkpoints:
        if cp <= queries_used:
            trajectory[cp] = best_conf

    while queries_used < max_queries and best_conf >= threshold:
        step_frac = queries_used / float(max_queries)
        s_frac = _square_fraction(step_frac, p_init=p_init)
        sq = max(4, min(min(height, width), int(round(math.sqrt(s_frac * height * width)))))
        y0 = int(rng.integers(0, max(1, height - sq + 1)))
        x0 = int(rng.integers(0, max(1, width - sq + 1)))

        cand_delta = delta.copy()
        patch_sign = rng.choice([-eps_u8, eps_u8], size=(1, 1, 1, channels)).astype(np.int16)
        cand_delta[:, y0 : y0 + sq, x0 : x0 + sq, :] = np.broadcast_to(
            patch_sign, (t_steps, sq, sq, channels)
        )
        cand_adv = np.clip(clean_batch.astype(np.int16) + cand_delta, 0, 255).astype(np.uint8)

        cand_score = float(target.query(_unwrap(cand_adv, is_video)).confidence)
        queries_used += 1

        if cand_score < best_conf:
            best_conf = cand_score
            best_adv = cand_adv
            delta = cand_adv.astype(np.int16) - clean_batch.astype(np.int16)
            if best_conf < threshold and flip_query is None:
                flip_query = queries_used

        for cp in checkpoints:
            if cp >= queries_used and cp not in trajectory:
                pass
            if queries_used == cp:
                trajectory[cp] = best_conf

    for cp in checkpoints:
        trajectory.setdefault(cp, best_conf)

    linf, l2, psnr = _distortion_metrics(clean_batch, best_adv)
    return (
        VisionEvasionTrace(
            sample_id=sample_id,
            modality=modality,
            detector_name=target.name,
            attack_method="square_linf",
            clean_confidence=clean_conf,
            final_confidence=best_conf,
            score_drop=round(clean_conf - best_conf, 4),
            flipped=best_conf < threshold,
            queries_used=queries_used,
            flip_query=flip_query,
            linf_norm=linf,
            l2_norm=l2,
            psnr_db=psnr,
            trajectory=dict(sorted(trajectory.items())),
            metadata={"eps": round(eps, 4), "max_queries": max_queries},
        ),
        best_adv[0] if not is_video else best_adv,
    )


def _apply_media_transform(
    frame_u8: np.ndarray,
    jpeg_quality: int,
    scale: float,
    blur_sigma: float,
    gamma: float,
    noise_sigma: float,
    rng: np.random.Generator,
) -> np.ndarray:
    h, w = frame_u8.shape[:2]
    arr = frame_u8.astype(np.float32)
    if abs(gamma - 1.0) > 1e-3:
        arr = np.power(np.clip(arr / 255.0, 0.0, 1.0), gamma) * 255.0
    if blur_sigma > 0.1:
        k = max(3, int(round(blur_sigma * 3.0)) | 1)
        arr = cv2.GaussianBlur(arr, (k, k), sigmaX=blur_sigma)
    if noise_sigma > 0.1:
        arr = arr + rng.normal(0.0, noise_sigma, size=arr.shape)
    out = np.clip(arr, 0, 255).astype(np.uint8)
    if scale < 0.99:
        nh, nw = max(16, int(round(h * scale))), max(16, int(round(w * scale)))
        out = cv2.resize(out, (nw, nh), interpolation=cv2.INTER_AREA)
        out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
    if jpeg_quality < 98:
        buf = io.BytesIO()
        Image.fromarray(out).save(buf, format="JPEG", quality=int(jpeg_quality))
        buf.seek(0)
        out = np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)
    return out


def run_adaptive_transform_attack(
    sample_id: str,
    clean_input: Any,
    target: AdaptiveTarget,
    threshold: float = 0.5,
    max_queries: int = 60,
    min_psnr_db: float = 20.0,
    checkpoints: Sequence[int] = (1, 10, 25, 40, 60),
    seed: int = 42,
) -> Tuple[VisionEvasionTrace, np.ndarray]:
    """Adaptive evolutionary search over realistic media transforms (JPEG, scale, blur, gamma, noise)."""
    clean_batch, is_video = _as_batch(clean_input)
    modality = "video" if is_video else "image"
    rng = np.random.default_rng(seed)

    res0 = target.query(_unwrap(clean_batch, is_video))
    clean_conf = float(res0.confidence)
    best_conf = clean_conf
    best_adv = clean_batch.copy()
    best_params = {"jpeg_quality": 95, "scale": 1.0, "blur_sigma": 0.0, "gamma": 1.0, "noise_sigma": 0.0}
    flip_query: Optional[int] = 1 if clean_conf < threshold else None
    queries_used = 1
    attempts = 0
    trajectory: Dict[int, float] = {1: clean_conf}

    while queries_used < max_queries and best_conf >= threshold and attempts < max_queries * 4:
        attempts += 1
        cand_params = {
            "jpeg_quality": int(np.clip(best_params["jpeg_quality"] + int(rng.integers(-22, 16)), 25, 95)),
            "scale": float(np.clip(best_params["scale"] + float(rng.uniform(-0.20, 0.15)), 0.45, 1.0)),
            "blur_sigma": float(np.clip(best_params["blur_sigma"] + float(rng.uniform(-0.4, 0.7)), 0.0, 2.2)),
            "gamma": float(np.clip(best_params["gamma"] + float(rng.uniform(-0.15, 0.15)), 0.75, 1.30)),
            "noise_sigma": float(np.clip(best_params["noise_sigma"] + float(rng.uniform(-2.0, 4.0)), 0.0, 14.0)),
        }
        cand_batch = np.stack(
            [_apply_media_transform(clean_batch[i], rng=rng, **cand_params) for i in range(clean_batch.shape[0])],
            axis=0,
        )
        _, _, cand_psnr = _distortion_metrics(clean_batch, cand_batch)
        if cand_psnr < min_psnr_db:
            continue

        cand_score = float(target.query(_unwrap(cand_batch, is_video)).confidence)
        queries_used += 1
        if cand_score < best_conf:
            best_conf = cand_score
            best_adv = cand_batch
            best_params = cand_params
            if best_conf < threshold and flip_query is None:
                flip_query = queries_used

        if queries_used in checkpoints:
            trajectory[queries_used] = best_conf

    for cp in checkpoints:
        trajectory.setdefault(cp, best_conf)

    linf, l2, psnr = _distortion_metrics(clean_batch, best_adv)
    return (
        VisionEvasionTrace(
            sample_id=sample_id,
            modality=modality,
            detector_name=target.name,
            attack_method="adaptive_transform_search",
            clean_confidence=clean_conf,
            final_confidence=best_conf,
            score_drop=round(clean_conf - best_conf, 4),
            flipped=best_conf < threshold,
            queries_used=queries_used,
            flip_query=flip_query,
            linf_norm=linf,
            l2_norm=l2,
            psnr_db=psnr,
            trajectory=dict(sorted(trajectory.items())),
            metadata={"best_params": best_params, "min_psnr_db": min_psnr_db},
        ),
        best_adv[0] if not is_video else best_adv,
    )


def summarize_vision_curves(
    traces: Iterable[VisionEvasionTrace],
    threshold: float = 0.5,
    checkpoints: Sequence[int] = DEFAULT_QUERY_CHECKPOINTS,
) -> List[EvasionCurveRow]:
    """Aggregates Attack Success Rate (ASR) curves vs. query budget across samples."""
    grouped: Dict[Tuple[str, str, str], List[VisionEvasionTrace]] = {}
    for t in traces:
        if t.clean_confidence >= threshold:
            grouped.setdefault((t.modality, t.detector_name, t.attack_method), []).append(t)

    rows: List[EvasionCurveRow] = []
    for (modality, det_name, method), items in sorted(grouped.items()):
        n = len(items)
        all_cps = sorted({k for item in items for k in item.trajectory.keys()} | set(checkpoints))
        for q in all_cps:
            evaded = sum(1 for item in items if item.flip_query is not None and item.flip_query <= q)
            confs = [item.trajectory.get(q, item.final_confidence) for item in items]
            drops = [item.clean_confidence - item.trajectory.get(q, item.final_confidence) for item in items]
            rows.append(
                EvasionCurveRow(
                    modality=modality,
                    detector_name=det_name,
                    attack_method=method,
                    budget_unit="queries",
                    budget_value=int(q),
                    total_detected_clean=n,
                    evaded_count=evaded,
                    asr=round(evaded / n, 4),
                    mean_confidence=round(sum(confs) / n, 4),
                    mean_score_drop=round(sum(drops) / n, 4),
                )
            )
    return rows
