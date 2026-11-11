"""
Week 10 Task 1 - Gate 1 (DFS): Full-mesh mTLS across all AEGIS services.

Exercises real uvicorn mTLS servers (`--ssl-cert-reqs=2 --ssl-ca-certs=<mesh_ca>`) across:
  * Remaining active + planned detectors (rppg, syncnet, image, text) + X-Internal-Token removal
  * Orchestrator -> Judge microservice (`debate.server:app`) over mTLS
  * Orchestrator planner & Judge -> LLM-bridge over mTLS + plaintext downgrade rejection
  * Orchestrator -> Prometheus telemetry queries over mTLS
  * Connection-audit script positive & negative (regression-catching) checks
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import socket
import ssl
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List

import httpx
import pytest
import uvicorn
from cryptography import x509
from fastapi import FastAPI, Request

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ORCH_APP = REPO_ROOT / "orchestrator" / "app"
for p in (str(REPO_ROOT), str(ORCH_APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

from security.tests.mesh_test_utils import TLSDetectorServer, free_port, make_pki
from security.transport.audit_mesh_connections import (
    AuditReport,
    audit_closed_port,
    audit_endpoint_mtls,
    audit_static_configuration,
)
from security.transport.generate_certs import MESH_SERVICES, generate_cert, save_cert


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch_tls = _load(ORCH_APP / "mesh_tls.py", "mesh_tls_w10")
gw_tls = _load(REPO_ROOT / "security" / "gateway" / "validator" / "app" / "mesh_tls.py", "gw_mesh_tls_w10")


class _ThreadUvicorn:
    """Runs an arbitrary ASGI FastAPI app under TLS or plain HTTP for real-socket tests."""

    def __init__(self, app: FastAPI, *, certs_dir: str | None = None, service_prefix: str | None = None):
        self.port = free_port()
        cfg_kwargs = dict(host="127.0.0.1", port=self.port, log_level="error")
        if certs_dir and service_prefix:
            cfg_kwargs.update(
                ssl_keyfile=str(Path(certs_dir) / f"{service_prefix}.key"),
                ssl_certfile=str(Path(certs_dir) / f"{service_prefix}.crt"),
                ssl_ca_certs=str(Path(certs_dir) / "mesh_ca.crt"),
                ssl_cert_reqs=ssl.CERT_REQUIRED,
            )
        self.server = uvicorn.Server(uvicorn.Config(app, **cfg_kwargs))
        self.thread: threading.Thread | None = None

    @property
    def scheme(self) -> str:
        return "https" if self.server.config.ssl_certfile else "http"

    @property
    def base_url(self) -> str:
        return f"{self.scheme}://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started and time.time() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            raise RuntimeError("Test uvicorn server failed to start")
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)


def _strict_env(certs_dir: str, prefix: str = "mesh_orchestrator") -> Dict[str, str]:
    return {
        "AEGIS_MESH_STRICT": "1",
        "AEGIS_MESH_CA": str(Path(certs_dir) / "mesh_ca.crt"),
        "AEGIS_MESH_CERT": str(Path(certs_dir) / f"{prefix}.crt"),
        "AEGIS_MESH_KEY": str(Path(certs_dir) / f"{prefix}.key"),
        "AEGIS_MESH_DETECTORS": "video-classifier,aasist,rppg,syncnet,image,text,judge,prometheus",
    }


@pytest.fixture(scope="module")
def full_pki(tmp_path_factory):
    return make_pki(tmp_path_factory.mktemp("full_mesh_pki"))


# ── 1. Expanded Mesh PKI ─────────────────────────────────────────────────────
class TestFullMeshPKI:
    def test_all_13_mesh_services_issued_by_mesh_ca(self, full_pki):
        expected = {
            "aegis-orchestrator",
            "aegis-gateway-validator",
            "aegis-api-gateway",
            "aegis-prometheus",
            "aegis-detector-video-classifier",
            "aegis-detector-aasist",
            "aegis-detector-rppg",
            "aegis-detector-syncnet",
            "aegis-detector-image",
            "aegis-detector-text",
            "aegis-judge",
            "aegis-llm-bridge",
            "aegis-web",
        }
        assert set(MESH_SERVICES.keys()) == expected
        mesh_ca = x509.load_pem_x509_certificate((Path(full_pki) / "mesh_ca.crt").read_bytes())

        for cn, (prefix, dns_names) in MESH_SERVICES.items():
            cert = x509.load_pem_x509_certificate((Path(full_pki) / f"{prefix}.crt").read_bytes())
            assert cert.issuer == mesh_ca.subject
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            dns_got = set(san.get_values_for_type(x509.DNSName))
            for name in dns_names:
                assert name in dns_got, f"{cn} missing SAN {name}"
            eku = list(cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
            assert len(eku) == 2


# ── 2. All Detectors mTLS & X-Internal-Token Removal ─────────────────────────
class TestAllDetectorsMesh:
    @pytest.mark.parametrize(
        "detector,prefix",
        [
            ("rppg", "mesh_detector_rppg"),
            ("syncnet", "mesh_detector_syncnet"),
            ("image", "mesh_detector_image"),
            ("text", "mesh_detector_text"),
        ],
    )
    def test_orchestrator_dispatches_to_detector_without_internal_token_header(
        self, full_pki, monkeypatch, detector, prefix
    ):
        captured_headers: List[Dict[str, str]] = []

        app = FastAPI()

        @app.post("/detect")
        async def detect(request: Request):
            captured_headers.append({k.lower(): v for k, v in request.headers.items()})
            body = await request.json()
            return {
                "job_id": body["job_id"],
                "confidence": 0.15,
                "raw_score": 0.15,
                "latency_ms": 4,
                "model_version": "mtls-test-1.0",
                "evidence": {"claim": "authentic", "flags": []},
            }

        env = _strict_env(full_pki, "mesh_orchestrator")
        with _ThreadUvicorn(app, certs_dir=full_pki, service_prefix=prefix) as srv:
            env_var = f"DETECTOR_{detector.upper().replace('-', '_')}_URL"
            for k, v in env.items():
                monkeypatch.setenv(k, v)
            monkeypatch.setenv("INTERNAL_API_TOKEN", "should_never_be_sent")
            monkeypatch.setenv(env_var, srv.base_url)

            from orchestrator.app.dispatch import call_all_detectors

            results = asyncio.run(call_all_detectors([detector], "job-mtls-1", "video", "/tmp/x.mp4"))

        assert len(results) == 1
        assert results[0].status == "ok"
        assert results[0].detector == detector
        assert len(captured_headers) == 1
        assert "x-internal-token" not in captured_headers[0], "Shared X-Internal-Token leaked in strict mTLS mode!"

    def test_strict_mesh_blocks_plaintext_downgrade_on_all_detectors(self, full_pki, monkeypatch):
        env = _strict_env(full_pki, "mesh_orchestrator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        for det in ("video-classifier", "aasist", "rppg", "syncnet", "image", "text"):
            monkeypatch.setenv(f"DETECTOR_{det.upper().replace('-', '_')}_URL", f"http://detector_{det}:8000")

        from orchestrator.app.dispatch import call_all_detectors

        results = asyncio.run(
            call_all_detectors(["rppg", "syncnet", "image", "text"], "job-down", "video", "/tmp/x.mp4")
        )
        assert len(results) == 4
        for r in results:
            assert r.status == "failed"
            assert "not https" in (r.error or "")


# ── 3. Orchestrator <-> Judge Service over mTLS ──────────────────────────────
class TestOrchestratorToJudgeMTLS:
    def test_remote_judge_service_over_mtls_succeeds(self, full_pki, monkeypatch):
        from debate.server import app as judge_app
        from orchestrator.app.judge_bridge import run_judge
        from orchestrator.app.models import DetectorEvidence, DetectorResult, InputMetadata

        env = _strict_env(full_pki, "mesh_orchestrator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        results = [
            DetectorResult(
                detector="video-classifier", status="ok", job_id="j-mtls",
                confidence=0.9, raw_score=0.9, latency_ms=10, model_version="v1",
                evidence=DetectorEvidence(claim="Synthetic artifacts detected.", flags=["spatial"]),
            ),
            DetectorResult(
                detector="rppg", status="ok", job_id="j-mtls",
                confidence=0.85, raw_score=0.85, latency_ms=12, model_version="v1",
                evidence=DetectorEvidence(claim="No biological pulse.", flags=[]),
            ),
        ]
        meta = InputMetadata(filename="clip.mp4", modality="video", has_audio=True, duration_seconds=5.0)

        with _ThreadUvicorn(judge_app, certs_dir=full_pki, service_prefix="mesh_judge") as srv:
            monkeypatch.setenv("AEGIS_JUDGE_URL", srv.base_url)
            report = run_judge(results, meta, "j-mtls")

            # Verify unauthenticated HTTP or client without mesh cert is rejected by the Judge service
            with pytest.raises((httpx.TransportError, ssl.SSLError, OSError)):
                ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(Path(full_pki) / "mesh_ca.crt"))
                with httpx.Client(verify=ctx, timeout=2.0) as bad_client:
                    bad_client.get(f"{srv.base_url}/health")

        assert len(report.rounds) == 3
        assert report.verdict.calibrated_score > 0.5

    def test_remote_judge_plaintext_downgrade_refused(self, full_pki, monkeypatch):
        from orchestrator.app import judge_bridge
        from orchestrator.app.models import InputMetadata

        env = _strict_env(full_pki, "mesh_orchestrator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("AEGIS_JUDGE_URL", "http://127.0.0.1:19999")

        meta = InputMetadata(filename="clip.mp4", modality="video", has_audio=False, duration_seconds=4.0)
        with pytest.raises(judge_bridge.MeshTLSConfigError, match="not https"):
            judge_bridge.run_judge([], meta, "j-downgrade")


# ── 4. Orchestrator Planner & Debate Judge <-> LLM Bridge TLS / mTLS ─────────
class TestLLMBridgeMTLS:
    def _mock_llm_bridge_app(self, content_obj: dict) -> FastAPI:
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(_req: Request):
            return {"choices": [{"message": {"content": json.dumps(content_obj)}}]}

        return app

    def test_planner_call_llm_uses_mtls_and_blocks_http_downgrade(self, full_pki, monkeypatch):
        from orchestrator.app.planner import call_llm

        env = _strict_env(full_pki, "mesh_orchestrator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("AEGIS_MOCK_LLM", raising=False)

        valid_plan = {
            "plan_version": "3",
            "stages": [{"stage": 1, "run": ["video-classifier"], "mode": "parallel"}],
            "skipped": [],
            "coverage_warnings": [],
            "estimated_latency_s": 5.0,
            "rationale": "mTLS planner response",
        }
        bridge_app = self._mock_llm_bridge_app(valid_plan)

        with _ThreadUvicorn(bridge_app, certs_dir=full_pki, service_prefix="mesh_llm_bridge") as srv:
            monkeypatch.setenv("AEGIS_LLM_BRIDGE_URL", f"{srv.base_url}/v1/chat/completions")
            parsed, model, _ = call_llm("select detectors", mock=False)
            assert parsed == valid_plan
            assert model != "ALL_MODELS_FAILED"

        # Downgrade attack: plain http:// URL in strict mode must be blocked BEFORE network I/O
        monkeypatch.setenv("AEGIS_LLM_BRIDGE_URL", "http://127.0.0.1:19998/v1/chat/completions")
        parsed_bad, reason, _ = call_llm("select detectors", mock=False)
        assert parsed_bad is None
        assert reason.startswith("TLS_POLICY_VIOLATION:")

    def test_judge_llm_client_uses_mtls_and_blocks_http_downgrade(self, full_pki, monkeypatch):
        from debate.llm_client import call_judge_llm

        env = _strict_env(full_pki, "mesh_orchestrator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.delenv("AEGIS_MOCK_LLM", raising=False)

        narrative = {
            "forensic_justification": (
                "Video-classifier and rppg detectors corroborate synthetic artifacts across frames."
            ),
            "adjudication_summary": "Verified mTLS Judge LLM output.",
        }
        bridge_app = self._mock_llm_bridge_app(narrative)

        with _ThreadUvicorn(bridge_app, certs_dir=full_pki, service_prefix="mesh_llm_bridge") as srv:
            monkeypatch.setenv("AEGIS_LLM_BRIDGE_URL", f"{srv.base_url}/v1/chat/completions")
            parsed, _, _, err = call_judge_llm(
                "justify verdict", ["video-classifier", "rppg"], "SYNTHETIC", 0.91
            )
            assert err is None
            assert parsed == narrative

        # Downgrade attack must refuse and safely emit TLS_POLICY_VIOLATION fallback reason
        monkeypatch.setenv("AEGIS_LLM_BRIDGE_URL", "http://127.0.0.1:19998/v1/chat/completions")
        fallback_out, _, _, err_msg = call_judge_llm(
            "justify verdict", ["video-classifier"], "SYNTHETIC", 0.91
        )
        assert fallback_out is not None
        assert err_msg and err_msg.startswith("TLS_POLICY_VIOLATION:")

    def test_untrusted_llm_server_cert_is_rejected(self, full_pki, tmp_path, monkeypatch):
        from orchestrator.app.planner import call_llm

        rogue_key, _, rogue_sub = generate_cert("Rogue LLM CA", is_ca=True)
        k, c, _ = generate_cert(
            "rogue-llm", issuer_name=rogue_sub, issuer_key=rogue_key, san_dns_names=["localhost"], san_ips=["127.0.0.1"]
        )
        save_cert(str(tmp_path), "rogue_llm", k, c)

        app = self._mock_llm_bridge_app({"plan_version": "3"})
        srv = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=free_port(),
                ssl_keyfile=str(tmp_path / "rogue_llm.key"),
                ssl_certfile=str(tmp_path / "rogue_llm.crt"),
                log_level="error",
            )
        )
        t = threading.Thread(target=srv.run, daemon=True)
        t.start()
        deadline = time.time() + 10
        while not srv.started and time.time() < deadline:
            time.sleep(0.05)

        try:
            env = _strict_env(full_pki, "mesh_orchestrator")
            for key, val in env.items():
                monkeypatch.setenv(key, val)
            monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
            monkeypatch.delenv("AEGIS_MOCK_LLM", raising=False)
            monkeypatch.setenv("AEGIS_LLM_BRIDGE_URL", f"https://127.0.0.1:{srv.config.port}/v1/chat/completions")
            monkeypatch.setenv("AEGIS_LLM_MTLS", "1")

            parsed, reason, _ = call_llm("select", mock=False)
            assert parsed is None
            assert reason == "ALL_MODELS_FAILED"
        finally:
            srv.should_exit = True
            t.join(timeout=5)


# ── 5. Orchestrator -> Prometheus Telemetry mTLS ─────────────────────────────
class TestPrometheusTelemetryMTLS:
    def test_prometheus_client_queries_over_mtls_and_refuses_http_in_strict(self, full_pki, monkeypatch):
        from orchestrator.app.telemetry_client import PrometheusTelemetryClient

        prom_app = FastAPI()

        @prom_app.get("/api/v1/query")
        def query(query: str):
            if "up{" in query:
                return {"status": "success", "data": {"result": [{"metric": {"job": "aegis_detector_rppg"}, "value": [1, "1"]}]}}
            if "histogram_quantile" in query:
                return {"status": "success", "data": {"result": [{"metric": {"model_name": "rppg"}, "value": [1, "4.2"]}]}}
            return {"status": "success", "data": {"result": []}}

        env = _strict_env(full_pki, "mesh_orchestrator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        with _ThreadUvicorn(prom_app, certs_dir=full_pki, service_prefix="mesh_prometheus") as srv:
            client = PrometheusTelemetryClient(prometheus_url=srv.base_url, timeout_s=2.0)
            snap = client.get_telemetry_snapshot(["rppg"])
            assert snap["rppg"].source == "live_prometheus"
            assert snap["rppg"].p95_latency_ms == 4200.0

            # Plain HTTP Prometheus URL in strict mode must refuse cleartext and fall back cleanly
            plain_client = PrometheusTelemetryClient(prometheus_url=f"http://127.0.0.1:{srv.port}", timeout_s=1.0)
            plain_snap = plain_client.get_telemetry_snapshot(["rppg"])
            assert plain_snap["rppg"].source == "baseline_fallback"


# ── 6. Strict Policy & Connection-Audit Script ───────────────────────────────
class TestStrictMeshAndAuditScript:
    def test_strict_flag_enforces_https_for_all_services_and_fails_closed(self, full_pki):
        strict_env = _strict_env(full_pki, "mesh_orchestrator")
        assert orch_tls.url_allowed("future-detector", "http://future:8000", strict_env) is False
        assert orch_tls.url_allowed("judge", "http://judge:8000", strict_env) is False
        assert orch_tls.url_allowed("future-detector", "https://future:8000", strict_env) is True
        assert gw_tls.url_allowed("rppg", "http://detector_rppg:8000", strict_env) is False

        with pytest.raises(orch_tls.MeshTLSConfigError):
            orch_tls.client_tls_kwargs({"AEGIS_MESH_STRICT": "1"})

    def test_audit_static_configuration_passes_zero_findings(self):
        report = AuditReport()
        audit_static_configuration(report, REPO_ROOT)
        assert report.passed, [c for c in report.checks if not c.passed]

    def test_audit_script_catches_plaintext_regression_and_open_port(self, full_pki):
        # Spin up an intentionally INSECURE plaintext HTTP server to prove the audit catches it!
        insecure_app = FastAPI()

        @insecure_app.get("/health")
        def health():
            return {"status": "insecure"}

        with _ThreadUvicorn(insecure_app) as plain_srv:
            # Open TCP port check must fail because port IS open
            closed, _ = audit_closed_port("127.0.0.1", plain_srv.port)
            assert closed is False

            # Live endpoint audit must FAIL (because plaintext HTTP succeeded!)
            bad_report = AuditReport()
            audit_endpoint_mtls(bad_report, "rogue-plain-service", "127.0.0.1", plain_srv.port, Path(full_pki))
            assert bad_report.passed is False
            assert any(c.check.startswith("Plaintext HTTP rejected") and not c.passed for c in bad_report.checks)

        # Now audit a real compliant mTLS endpoint and verify 100% pass
        with TLSDetectorServer(full_pki, service_prefix="mesh_detector_rppg") as mtls_srv:
            ok_report = AuditReport()
            audit_endpoint_mtls(ok_report, "rppg", "127.0.0.1", mtls_srv.port, Path(full_pki))
            assert ok_report.passed is True

    def test_gateway_validator_mtls_forwarding_and_downgrade_refusal(self, full_pki, monkeypatch):
        import base64
        from fastapi.testclient import TestClient

        validator_root = str(REPO_ROOT / "security" / "gateway" / "validator")
        if validator_root not in sys.path:
            sys.path.insert(0, validator_root)
        from app import config as gw_config
        from app.main import app as gw_app

        env = _strict_env(full_pki, "mesh_gateway_validator")
        for k, v in env.items():
            monkeypatch.setenv(k, v)

        wav_b64 = base64.b64encode(b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE" + b"\x00" * 20).decode()
        payload = {"job_id": "gw-mtls-1", "modality": "audio", "payload": wav_b64}
        gw_client = TestClient(gw_app)

        with TLSDetectorServer(full_pki, service_prefix="mesh_detector_aasist") as aasist_srv:
            monkeypatch.setattr(gw_config, "AUDIO_DETECTOR_URL", f"{aasist_srv.base_url}/detect")
            resp = gw_client.post("/validate/audio", json=payload)
            assert resp.status_code == 200
            assert resp.json()["job_id"] == "gw-mtls-1"

            # Plaintext http:// upstream must be blocked by gateway validator in strict mode
            monkeypatch.setattr(gw_config, "AUDIO_DETECTOR_URL", f"http://127.0.0.1:{aasist_srv.port}/detect")
            bad = gw_client.post("/validate/audio", json=payload)
            assert bad.status_code == 502
            assert "not https" in bad.json()["error"]


