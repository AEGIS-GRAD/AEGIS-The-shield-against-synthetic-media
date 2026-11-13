"""FastAPI microservice entrypoint for AEGIS detector_text."""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional

import psutil
import torch
from fastapi import FastAPI, Header, HTTPException, Request

from binoculars_small import BinocularsMetrics, BinocularsSmallScorer
from chunking import apply_length_gating
from config import TextDetectorConfig, load_signal_thresholds
from desklib_runner import DesklibRunner
from evidence import build_forensic_evidence, build_not_applicable_evidence
from ingest import IngestionError, IngestedText, ingest_payload, prepare_raw_text
from perplexity import PerplexityMetrics, PerplexityScorer
from schemas import DetectionEvidence, DetectionRequest, DetectionResponse, LegacyTextRequest
from stylometry import extract_stylometry_features
from telemetry import metrics_app, track_inference

logger = logging.getLogger("detector_text")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

_PROCESS = psutil.Process(os.getpid())


@dataclass
class ServiceRuntime:
    """Holds live detector components so tests can swap runners cleanly."""

    config: TextDetectorConfig
    desklib: DesklibRunner
    perplexity: Optional[PerplexityScorer]
    binoculars: Optional[BinocularsSmallScorer]


def create_default_runtime(config: Optional[TextDetectorConfig] = None) -> ServiceRuntime:
    """Instantiate production runners from environment configuration."""
    cfg = config or TextDetectorConfig()
    thresholds = load_signal_thresholds(cfg)
    desklib = DesklibRunner(
        model_dir=cfg.model_dir,
        model_name=cfg.model_name,
        lora_dir=cfg.lora_dir,
        use_fp16=cfg.use_fp16,
        batch_size=cfg.chunk_batch_size,
    )
    ppl = (
        PerplexityScorer(
            model_dir=cfg.ppl_model_dir,
            model_id=cfg.ppl_model_id,
            use_fp16=cfg.use_fp16,
            max_sentences=cfg.max_ppl_sentences,
        )
        if cfg.enable_ppl
        else None
    )
    bino = (
        BinocularsSmallScorer(
            performer_id=cfg.binoculars_performer_id,
            observer_id=cfg.binoculars_observer_id,
            threshold=thresholds.binoculars_threshold,
            use_fp16=cfg.use_fp16,
        )
        if cfg.enable_binoculars
        else None
    )
    return ServiceRuntime(config=cfg, desklib=desklib, perplexity=ppl, binoculars=bino)


def _memory_snapshot_mb() -> tuple[float, Optional[float]]:
    ram_mb = round(_PROCESS.memory_info().rss / (1024.0 * 1024.0), 2)
    if torch.cuda.is_available():
        vram_mb = round(torch.cuda.memory_allocated() / (1024.0 * 1024.0), 2)
        return ram_mb, vram_mb
    return ram_mb, None


def _verify_internal_auth(x_internal_token: Optional[str], config: TextDetectorConfig) -> None:
    """Enforce X-Internal-Token in non-mTLS mode (identical contract to other AEGIS detectors)."""
    expected = config.internal_api_key
    if expected and not config.mesh_strict and x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Token.")


def _run_perplexity_safe(
    scorer: Optional[PerplexityScorer], text: str, cfg: TextDetectorConfig
) -> PerplexityMetrics:
    if scorer is None:
        return PerplexityMetrics(
            enabled=False, available=False, model_id=cfg.ppl_model_id
        )
    try:
        return scorer.score(text)
    except Exception as exc:
        logger.warning("Perplexity scorer degraded cleanly: %s", exc)
        return PerplexityMetrics(
            enabled=True,
            available=False,
            model_id=cfg.ppl_model_id,
            error=str(exc)[:120],
        )


def _run_binoculars_safe(
    scorer: Optional[BinocularsSmallScorer], text: str, cfg: TextDetectorConfig, threshold: float
) -> BinocularsMetrics:
    if scorer is None:
        return BinocularsMetrics(
            enabled=False,
            available=False,
            performer_id=cfg.binoculars_performer_id,
            observer_id=cfg.binoculars_observer_id,
            threshold=threshold,
        )
    try:
        return scorer.score(text)
    except Exception as exc:
        logger.warning("Binoculars-small scorer degraded cleanly: %s", exc)
        return BinocularsMetrics(
            enabled=True,
            available=False,
            performer_id=cfg.binoculars_performer_id,
            observer_id=cfg.binoculars_observer_id,
            threshold=threshold,
            error=str(exc)[:120],
        )


def _score_ingested_text(
    job_id: str,
    ingested: IngestedText,
    runtime: ServiceRuntime,
    started_at: float,
) -> DetectionResponse:
    cfg = runtime.config
    thresholds = load_signal_thresholds(cfg)
    ram_mb, vram_mb = _memory_snapshot_mb()

    if ingested.word_count < cfg.min_words:
        evidence = build_not_applicable_evidence(ingested, min_words=cfg.min_words)
        latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        return DetectionResponse(
            job_id=job_id,
            status="not_applicable",
            modality="text",
            confidence=0.5,
            raw_score=0.0,
            latency_ms=latency_ms,
            ram_usage_mb=ram_mb,
            vram_usage_mb=vram_mb,
            model_version=cfg.effective_model_version,
            evidence=DetectionEvidence(**evidence.to_dict()),
            signals={
                "input_stats": {
                    "word_count": ingested.word_count,
                    "char_count": ingested.char_count,
                    "source_kind": ingested.source_kind,
                    "stripped_control_chars": ingested.stripped_control_chars,
                }
            },
        )

    chunk_result = runtime.desklib.score_text(
        ingested.text,
        chunk_tokens=cfg.chunk_tokens,
        overlap=cfg.chunk_overlap,
        max_chunks=cfg.max_chunks,
        spread_threshold=cfg.chunk_disagreement_spread,
    )
    gating = apply_length_gating(
        raw_probability=chunk_result.raw_probability,
        word_count=ingested.word_count,
        min_words=cfg.min_words,
        reliable_words=cfg.reliable_words,
    )
    stylo = extract_stylometry_features(ingested.text)
    ppl_metrics = _run_perplexity_safe(runtime.perplexity, ingested.text, cfg)
    bino_metrics = _run_binoculars_safe(
        runtime.binoculars, ingested.text, cfg, thresholds.binoculars_threshold
    )
    evidence = build_forensic_evidence(
        ingested=ingested,
        chunk_result=chunk_result,
        gating=gating,
        perplexity=ppl_metrics,
        stylometry=stylo,
        thresholds=thresholds,
        binoculars=bino_metrics,
    )

    ram_mb, vram_mb = _memory_snapshot_mb()
    latency_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    return DetectionResponse(
        job_id=job_id,
        status=gating.status,
        modality="text",
        confidence=gating.confidence,
        raw_score=chunk_result.raw_probability,
        latency_ms=latency_ms,
        ram_usage_mb=ram_mb,
        vram_usage_mb=vram_mb,
        model_version=cfg.effective_model_version,
        evidence=DetectionEvidence(**evidence.to_dict()),
        signals={
            "chunk_aggregation": {
                "chunk_count": chunk_result.chunk_count,
                "sampled_from_chunks": chunk_result.sampled_from_chunks,
                "total_tokens": chunk_result.total_tokens,
                "chunk_scores": list(chunk_result.chunk_scores),
                "chunk_spread": chunk_result.chunk_spread,
                "disagreement": chunk_result.disagreement,
                "mean_logit": chunk_result.mean_logit,
            },
            "length_gating": {
                "attenuated": gating.attenuated,
                "attenuation_factor": gating.attenuation_factor,
                "min_words": cfg.min_words,
                "reliable_words": cfg.reliable_words,
            },
            "perplexity": ppl_metrics.to_dict(),
            "binoculars_small": bino_metrics.to_dict(),
            "stylometry": stylo,
            "input_stats": {
                "word_count": ingested.word_count,
                "char_count": ingested.char_count,
                "line_count": ingested.line_count,
                "paragraph_count": ingested.paragraph_count,
                "source_kind": ingested.source_kind,
                "stripped_control_chars": ingested.stripped_control_chars,
            },
        },
    )


def _get_runtime(request: Request) -> ServiceRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:
        runtime = create_default_runtime()
        request.app.state.runtime = runtime
    return runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = TextDetectorConfig()
    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        runtime = create_default_runtime(cfg)
        app.state.runtime = runtime

    if cfg.preload_models:
        if not runtime.desklib.is_loaded():
            runtime.desklib.load()
        if runtime.perplexity is not None and not runtime.perplexity.is_loaded():
            try:
                runtime.perplexity.load()
            except Exception as exc:
                logger.warning("Preloading GPT-2 perplexity scorer failed (will retry lazily): %s", exc)
        if runtime.binoculars is not None and not runtime.binoculars.is_loaded():
            try:
                runtime.binoculars.load()
            except Exception as exc:
                logger.warning("Preloading Binoculars-small failed (will retry lazily): %s", exc)
    yield


def create_app(runtime: Optional[ServiceRuntime] = None) -> FastAPI:
    """Application factory enabling isolated test wiring as well as Uvicorn ASGI launch."""
    application = FastAPI(
        title="AEGIS Text Authenticity Detector",
        version="2.0.0",
        lifespan=lifespan,
    )
    if runtime is not None:
        application.state.runtime = runtime

    application.mount("/metrics", metrics_app)

    @application.get("/health")
    def health(request: Request) -> Dict[str, Any]:
        rt = _get_runtime(request)
        ram_mb, vram_mb = _memory_snapshot_mb()
        return {
            "status": "ok",
            "service": rt.config.service_name,
            "model": rt.config.model_name,
            "model_version": rt.config.effective_model_version,
            "model_loaded": rt.desklib.is_loaded(),
            "device": str(rt.desklib.device),
            "perplexity_enabled": rt.config.enable_ppl,
            "perplexity_loaded": rt.perplexity.is_loaded() if rt.perplexity else False,
            "binoculars_enabled": rt.config.enable_binoculars,
            "binoculars_loaded": rt.binoculars.is_loaded() if rt.binoculars else False,
            "ram_usage_mb": ram_mb,
            "vram_usage_mb": vram_mb,
        }

    @application.post(
        "/detect",
        response_model=DetectionResponse,
        response_model_exclude_none=True,
    )
    @track_inference("text")
    async def detect(
        payload_req: DetectionRequest,
        request: Request,
        x_internal_token: Optional[str] = Header(default=None),
    ) -> DetectionResponse:
        started_at = time.perf_counter()
        rt = _get_runtime(request)
        _verify_internal_auth(x_internal_token, rt.config)

        if payload_req.modality != "text":
            raise HTTPException(
                status_code=400,
                detail=f"detector_text only accepts modality='text', got '{payload_req.modality}'.",
            )

        try:
            ingested = ingest_payload(
                payload_req.payload,
                shared_root=rt.config.shared_volume_root,
                max_chars=rt.config.max_chars,
            )
        except IngestionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        return _score_ingested_text(
            job_id=payload_req.job_id,
            ingested=ingested,
            runtime=rt,
            started_at=started_at,
        )

    @application.post(
        "/analyze",
        response_model=DetectionResponse,
        response_model_exclude_none=True,
        deprecated=True,
    )
    @track_inference("text")
    async def analyze_legacy(
        payload_req: LegacyTextRequest,
        request: Request,
        x_internal_token: Optional[str] = Header(default=None),
    ) -> DetectionResponse:
        """Deprecated raw-text endpoint kept solely for Task 3 script compatibility."""
        started_at = time.perf_counter()
        rt = _get_runtime(request)
        _verify_internal_auth(x_internal_token, rt.config)
        try:
            ingested = prepare_raw_text(
                payload_req.text, source_kind="legacy_raw", max_chars=rt.config.max_chars
            )
        except IngestionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

        return _score_ingested_text(
            job_id="legacy-analyze",
            ingested=ingested,
            runtime=rt,
            started_at=started_at,
        )

    return application


app = create_app()
