"""
Detector adapters for the robustness harness.

In-process adapters reuse each service's own loader, preprocessing and scoring
code (so results match the containers) but run fp32 on CPU; the services use
fp16 on GPU. ``HttpDetectorAdapter`` targets a running stack instead.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import os
import sys
import uuid
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[2]


class ImageCommForAdapter:
    """``detectors/image`` — Community Forensics ViT-S/16 @ 384, P(AI-generated)."""

    name = "detector_image"
    model_version = "commfor-model-384 (fp32 CPU)"

    def __init__(self, batch_size: int = 8):
        import torch
        import torchvision.transforms as T

        spec = importlib.util.spec_from_file_location("aegis_image_loader", REPO / "detectors" / "image" / "models" / "loader.py")
        loader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loader)
        model, device = loader.load_model(str(REPO / "detectors" / "image" / "weights"))
        self.model = model.float().eval()  # service casts to fp16 for 8 GB GPUs; fp32 on CPU
        self.device = device
        self.torch = torch
        # Identical to detectors/image/app.py::TRANSFORM
        self.transform = T.Compose([T.Resize((384, 384)), T.ToTensor(),
                                    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])])
        self.batch_size = batch_size

    def score_many(self, images: List) -> List[float]:
        out: List[float] = []
        for i in range(0, len(images), self.batch_size):
            batch = self.torch.stack([self.transform(im.convert("RGB")) for im in images[i:i + self.batch_size]]).to(self.device)
            with self.torch.no_grad():
                logits = self.model(batch).reshape(-1)
            out.extend(self.torch.sigmoid(logits).tolist())
        return out


class TextDesklibAdapter:
    """``detectors/text-detector`` — desklib v1.01 + team LoRA, through the service's ingest."""

    name = "detector_text"

    def __init__(self, max_chunks: int = 2):
        svc = str(REPO / "detectors" / "text-detector")
        if svc not in sys.path:
            sys.path.insert(0, svc)
        from config import TextDetectorConfig  # noqa: E402  (service-local modules)
        from desklib_runner import DesklibRunner
        from ingest import prepare_raw_text

        cfg = TextDetectorConfig()
        self.model_version = cfg.effective_model_version.replace("fp16", "fp32")
        self.prepare = prepare_raw_text
        self.runner = DesklibRunner(model_dir=cfg.model_dir, model_name=cfg.model_name, lora_dir=cfg.lora_dir,
                                    use_finetuned=cfg.use_finetuned, use_fp16=False, batch_size=4)
        self.runner.load(device="cpu")
        self.max_chunks = max_chunks

    def score(self, text: str) -> float:
        ingested = self.prepare(text)  # NFKC + zero-width / control stripping, as in /detect
        return float(self.runner.score_text(ingested.text, max_chunks=self.max_chunks).raw_probability)

    def score_many(self, texts: List[str]) -> List[float]:
        return [self.score(t) for t in texts]


class HttpDetectorAdapter:
    """Any AEGIS detector's ``POST /detect`` (schema in shared/json-api-contracts-schema/SCHEMA.md)."""

    def __init__(self, url: str, modality: str, token: Optional[str] = None, verify=True, cert=None, timeout: float = 120.0):
        import httpx

        self.name = f"http:{url}"
        self.model_version = "remote"
        self.modality = modality
        self.client = httpx.Client(timeout=timeout, verify=verify, cert=cert)
        self.url = url.rstrip("/") + "/detect"
        self.headers = {"X-Internal-Token": token or os.environ.get("INTERNAL_API_KEY", "")}

    def _post(self, payload: bytes) -> float:
        r = self.client.post(self.url, headers=self.headers, json={
            "job_id": f"robustness-{uuid.uuid4().hex[:12]}", "modality": self.modality,
            "payload": base64.b64encode(payload).decode()})
        r.raise_for_status()
        return float(r.json()["confidence"])

    def score_many(self, items: List) -> List[float]:
        out = []
        for it in items:
            if isinstance(it, str):
                out.append(self._post(it.encode("utf-8")))
            else:
                buf = io.BytesIO()
                it.convert("RGB").save(buf, format="PNG")  # lossless transport: perturbation is the only change
                out.append(self._post(buf.getvalue()))
        return out
