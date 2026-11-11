"""
AEGIS Full-Mesh mTLS Connection Audit Script & Verifier (Month 3, Week 10 Task 1).

Verifies two orthogonal layers of Zero Trust transport enforcement:
  1. Static Compose / Proxy / Telemetry Audit (`audit_static_configuration`):
       * Ensures detector host ports (8001-8004) and Prometheus host port (9090)
         are closed (`ports: []`) in strict overlay (`docker-compose.mtls.yml`).
       * Ensures all active detector services and gateway_validator run with
         uvicorn `--ssl-cert-reqs=2` and `/mesh/mesh_ca.crt`.
       * Ensures shared `INTERNAL_API_KEY` HTTP fallback is stripped from internal
         detectors and `AEGIS_MESH_STRICT=1` is active across internal callers.
       * Ensures all internal URLs (`DETECTOR_*_URL`, `VIDEO_DETECTOR_URL`,
         `AUDIO_DETECTOR_URL`, `PROMETHEUS_URL`) require `https://`.
       * Ensures Prometheus scrape targets use `scheme: https` + `tls_config` and
         Nginx upstream `gateway_validator` uses `proxy_pass https://...` + `proxy_ssl_verify on`.
  2. Live Network / Socket & Handshake Audit (`audit_endpoint_mtls`, `audit_closed_port`):
       * Probes closed legacy plaintext ports (proves connection refused).
       * Probes every mesh service endpoint against:
           (a) plaintext HTTP (must reject),
           (b) TLS with no client certificate (must reject),
           (c) TLS with main-CA camera certificate (must reject),
           (d) valid mesh-CA client certificate (must succeed on TLSv1.2+).

Usage examples:
  python security/transport/audit_mesh_connections.py --self-test --markdown-out security/docs/mtls_mesh_audit_report.md
  python security/transport/audit_mesh_connections.py --config-only
  python security/transport/audit_mesh_connections.py --probe detector_rppg=127.0.0.1:9443
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import socket
import ssl
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _ComposeLoader(yaml.SafeLoader):
    """YAML loader supporting Docker Compose v2 `!reset` tags."""


def _reset_constructor(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_ComposeLoader.add_constructor("!reset", _reset_constructor)

LEGACY_DETECTOR_PORTS = (8001, 8002, 8003, 8004)
DEFAULT_MESH_AUDIT_SERVICES = (
    ("video-classifier", "mesh_detector_video_classifier"),
    ("aasist", "mesh_detector_aasist"),
    ("rppg", "mesh_detector_rppg"),
    ("syncnet", "mesh_detector_syncnet"),
    ("image", "mesh_detector_image"),
    ("text", "mesh_detector_text"),
    ("gateway-validator", "mesh_gateway_validator"),
    ("judge", "mesh_judge"),
    ("llm-bridge", "mesh_llm_bridge"),
)


@dataclass
class AuditCheck:
    category: str
    target: str
    check: str
    passed: bool
    detail: str


@dataclass
class AuditReport:
    generated_at: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    checks: List[AuditCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def add(self, category: str, target: str, check: str, passed: bool, detail: str) -> None:
        self.checks.append(AuditCheck(category=category, target=target, check=check, passed=passed, detail=detail))

    def to_markdown(self) -> str:
        status_label = "PASS (Zero Plaintext Inter-Service Traffic)" if self.passed else "FAIL (Violations Detected)"
        lines = [
            "# AEGIS Full-Mesh mTLS Connection Audit Report",
            "",
            f"- **Generated At (UTC):** `{self.generated_at}`",
            f"- **Overall Result:** **{status_label}** ({self.passed_count}/{self.total} checks passed)",
            "",
            "## Audit Summary Table",
            "",
            "| Category | Service / Target | Check | Result | Detail |",
            "| :--- | :--- | :--- | :---: | :--- |",
        ]
        for item in self.checks:
            badge = "PASS" if item.passed else "FAIL"
            safe_detail = item.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{item.category}` | `{item.target}` | {item.check} | **{badge}** | {safe_detail} |")
        lines.append("")
        return "\n".join(lines)


def _env_list_to_dict(env_spec: Any) -> Dict[str, str]:
    """Converts Compose environment list (`KEY=VAL`) or dict (`{KEY: VAL}`) into a normalized dict."""
    result: Dict[str, str] = {}
    if isinstance(env_spec, dict):
        for k, v in env_spec.items():
            result[str(k)] = "" if v is None else str(v)
    elif isinstance(env_spec, list):
        for entry in env_spec:
            text = str(entry)
            if "=" in text:
                k, v = text.split("=", 1)
                result[k] = v
            else:
                result[text] = ""
    return result


def _merge_compose_files(base_path: Path, overlay_path: Path) -> Dict[str, Any]:
    base = yaml.load(base_path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
    overlay = yaml.load(overlay_path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}

    merged_services: Dict[str, Any] = {}
    base_services = base.get("services") or {}
    overlay_services = overlay.get("services") or {}

    for svc_name, base_cfg in base_services.items():
        cfg = dict(base_cfg or {})
        ov_cfg = dict(overlay_services.get(svc_name) or {})
        merged_env = _env_list_to_dict(cfg.get("environment"))
        merged_env.update(_env_list_to_dict(ov_cfg.get("environment")))

        for key, val in ov_cfg.items():
            if key == "environment":
                continue
            cfg[key] = val
        cfg["environment"] = merged_env
        merged_services[svc_name] = cfg

    return {"services": merged_services}


def _check_ssl_command_flags(cmd: Any) -> Tuple[bool, str]:
    tokens = [str(t) for t in cmd] if isinstance(cmd, list) else str(cmd or "").split()
    joined = " ".join(tokens)
    required = ("--ssl-cert-reqs=2", "--ssl-ca-certs=/mesh/mesh_ca.crt", "--ssl-certfile=", "--ssl-keyfile=")
    missing = [flag for flag in required if flag not in joined]
    if missing:
        return False, f"missing uvicorn TLS flags: {missing}"
    return True, "uvicorn mTLS flags enforced (--ssl-cert-reqs=2, mesh_ca.crt)"


def audit_static_configuration(report: AuditReport, repo_root: Path = REPO_ROOT) -> None:
    """Audits merged Compose overlay, Prometheus configs, and Nginx mTLS proxy template."""
    compose_base = repo_root / "docker-compose.yml"
    compose_mtls = repo_root / "docker-compose.mtls.yml"

    merged = _merge_compose_files(compose_base, compose_mtls)
    services = merged["services"]

    # 1. All active detector containers & prometheus must expose ZERO host ports and run strict mTLS
    detector_services = ("detector_video_classifier", "detector_aasist", "detector_rppg", "detector_syncnet")
    for svc in detector_services:
        cfg = services.get(svc, {})
        ports = cfg.get("ports") or []
        report.add(
            "compose",
            svc,
            "Host ports closed",
            len(ports) == 0,
            "0 host ports published" if not ports else f"exposed host ports remain: {ports}",
        )
        ok_tls, tls_detail = _check_ssl_command_flags(cfg.get("command"))
        report.add("compose", svc, "mTLS listener enforced", ok_tls, tls_detail)

        env = cfg.get("environment", {})
        shared_key_cleared = env.get("INTERNAL_API_KEY", "__UNSET__") == ""
        strict_flag = env.get("AEGIS_MESH_STRICT") == "1"
        report.add(
            "compose",
            svc,
            "Shared INTERNAL_API_KEY fallback removed",
            shared_key_cleared and strict_flag,
            f"INTERNAL_API_KEY={env.get('INTERNAL_API_KEY')!r}, AEGIS_MESH_STRICT={env.get('AEGIS_MESH_STRICT')!r}",
        )

    # 2. gateway_validator listener & upstream URL enforcement
    gw_cfg = services.get("gateway_validator", {})
    ok_gw_tls, gw_tls_detail = _check_ssl_command_flags(gw_cfg.get("command"))
    report.add("compose", "gateway_validator", "mTLS listener enforced", ok_gw_tls, gw_tls_detail)
    gw_env = gw_cfg.get("environment", {})
    for url_var in ("VIDEO_DETECTOR_URL", "AUDIO_DETECTOR_URL"):
        val = gw_env.get(url_var, "")
        report.add(
            "compose",
            "gateway_validator",
            f"HTTPS enforced for {url_var}",
            val.startswith("https://"),
            val or "<unset>",
        )

    # 3. orchestrator strict mesh URLs
    orch_env = services.get("orchestrator", {}).get("environment", {})
    report.add(
        "compose",
        "orchestrator",
        "Strict mesh mode active",
        orch_env.get("AEGIS_MESH_STRICT") == "1",
        f"AEGIS_MESH_STRICT={orch_env.get('AEGIS_MESH_STRICT')!r}",
    )
    for url_var in (
        "DETECTOR_VIDEO_CLASSIFIER_URL",
        "DETECTOR_AASIST_URL",
        "DETECTOR_RPPG_URL",
        "DETECTOR_SYNCNET_URL",
        "DETECTOR_IMAGE_URL",
        "DETECTOR_TEXT_URL",
        "PROMETHEUS_URL",
    ):
        val = orch_env.get(url_var, "")
        report.add(
            "compose",
            "orchestrator",
            f"HTTPS enforced for {url_var}",
            val.startswith("https://"),
            val or "<unset>",
        )

    # 4. Prometheus port closure + web mTLS + https scrape targets
    prom_cfg = services.get("prometheus", {})
    prom_ports = prom_cfg.get("ports") or []
    report.add(
        "compose",
        "prometheus",
        "Host port 9090 closed",
        len(prom_ports) == 0,
        "0 host ports published" if not prom_ports else f"exposed host ports: {prom_ports}",
    )

    prom_scrape = yaml.safe_load((repo_root / "security" / "telemetry" / "prometheus.mtls.yml").read_text(encoding="utf-8"))
    for job in prom_scrape.get("scrape_configs", []):
        job_name = job.get("job_name", "unknown")
        is_https = job.get("scheme") == "https" and bool(job.get("tls_config"))
        report.add(
            "prometheus",
            job_name,
            "HTTPS mutual-TLS scraping configured",
            is_https,
            f"scheme={job.get('scheme')}, cert_file={job.get('tls_config', {}).get('cert_file')}",
        )

    web_cfg = yaml.safe_load((repo_root / "security" / "telemetry" / "web-config.mtls.yml").read_text(encoding="utf-8"))
    tls_srv = web_cfg.get("tls_server_config", {})
    report.add(
        "prometheus",
        "web_server",
        "RequireAndVerifyClientCert configured",
        tls_srv.get("client_auth_type") == "RequireAndVerifyClientCert",
        f"client_auth_type={tls_srv.get('client_auth_type')}",
    )

    # 5. Nginx api_gateway mTLS proxy check
    nginx_tpl = (repo_root / "security" / "gateway" / "nginx.mtls.conf.template").read_text(encoding="utf-8")
    nginx_ok = (
        "proxy_pass https://aegis_gateway_validator:8080/" in nginx_tpl
        and "proxy_ssl_verify on;" in nginx_tpl
        and "proxy_ssl_certificate /mesh/mesh_api_gateway.crt;" in nginx_tpl
    )
    report.add(
        "nginx",
        "api_gateway",
        "Upstream mTLS to gateway_validator enforced",
        nginx_ok,
        "proxy_pass https:// + proxy_ssl_verify on + mesh_api_gateway cert" if nginx_ok else "missing proxy_ssl directives",
    )


def audit_closed_port(host: str, port: int, timeout: float = 0.5) -> Tuple[bool, str]:
    """Returns (True, detail) if TCP port is closed / unreachable on host."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return False, f"port {host}:{port} accepted TCP connection (expected closed)"
    except (ConnectionRefusedError, TimeoutError, OSError):
        return True, f"port {host}:{port} unreachable / refused"


def audit_endpoint_mtls(
    report: AuditReport,
    service_name: str,
    host: str,
    port: int,
    certs_dir: Path,
    server_hostname: Optional[str] = None,
) -> None:
    """Executes active negative and positive transport probes against a live service endpoint."""
    url_host = server_hostname or host
    sni_host = server_hostname or host

    # Probe 1: Plaintext HTTP must NOT succeed
    plain_ok = False
    plain_detail = "rejected"
    try:
        r = httpx.get(f"http://{url_host}:{port}/health", timeout=1.5)
        plain_detail = f"unexpected HTTP response status={r.status_code}"
    except (httpx.TransportError, ssl.SSLError, OSError) as exc:
        plain_ok = True
        plain_detail = f"plaintext HTTP rejected ({type(exc).__name__})"
    report.add("live_probe", service_name, f"Plaintext HTTP rejected (:{port})", plain_ok, plain_detail)

    # Probe 2: TLS without client certificate must fail handshake
    no_cert_ok = False
    no_cert_detail = "rejected"
    ctx_no_cert = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(certs_dir / "mesh_ca.crt"))
    try:
        with httpx.Client(verify=ctx_no_cert, timeout=1.5) as client:
            r = client.get(f"https://{url_host}:{port}/health")
            no_cert_detail = f"unexpected response without client cert: {r.status_code}"
    except (httpx.TransportError, ssl.SSLError, OSError) as exc:
        no_cert_ok = True
        no_cert_detail = f"unauthenticated TLS rejected ({type(exc).__name__})"
    report.add("live_probe", service_name, f"TLS without client cert rejected (:{port})", no_cert_ok, no_cert_detail)

    # Probe 3: Main-CA camera certificate must be rejected by mesh_ca trust store
    cam_cert = certs_dir / "client.crt"
    cam_key = certs_dir / "client.key"
    if cam_cert.exists() and cam_key.exists():
        cam_ok = False
        cam_detail = "rejected"
        ctx_cam = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(certs_dir / "mesh_ca.crt"))
        ctx_cam.load_cert_chain(str(cam_cert), str(cam_key))
        try:
            with httpx.Client(verify=ctx_cam, timeout=1.5) as client:
                r = client.get(f"https://{url_host}:{port}/health")
                cam_detail = f"unexpected response for main-CA camera cert: {r.status_code}"
        except (httpx.TransportError, ssl.SSLError, OSError) as exc:
            cam_ok = True
            cam_detail = f"wrong-CA camera cert rejected ({type(exc).__name__})"
        report.add("live_probe", service_name, f"Non-mesh CA cert rejected (:{port})", cam_ok, cam_detail)

    # Probe 4: Valid mesh_orchestrator client cert must connect on TLS 1.2+ and succeed
    orch_ok = False
    orch_detail = "failed"
    ctx_mesh = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(certs_dir / "mesh_ca.crt"))
    ctx_mesh.load_cert_chain(str(certs_dir / "mesh_orchestrator.crt"), str(certs_dir / "mesh_orchestrator.key"))
    try:
        with socket.create_connection((host, port), timeout=1.5) as raw:
            with ctx_mesh.wrap_socket(raw, server_hostname=sni_host) as tls:
                tls_ver = tls.version()
        with httpx.Client(verify=ctx_mesh, timeout=1.5) as client:
            r = client.get(f"https://{url_host}:{port}/health")
            if r.status_code == 200:
                orch_ok = True
                orch_detail = f"mTLS verified ({tls_ver}, HTTP 200)"
            else:
                orch_detail = f"HTTP {r.status_code} over {tls_ver}"
    except Exception as exc:
        orch_detail = f"mTLS handshake failed: {exc}"
    report.add("live_probe", service_name, f"Authorized mesh mTLS accepted (:{port})", orch_ok, orch_detail)


def run_self_test_mesh_audit(report: AuditReport, closed_ports: Sequence[int] = LEGACY_DETECTOR_PORTS) -> None:
    """Boots ephemeral mTLS uvicorn nodes for every mesh role and audits every port & handshake."""
    from security.tests.mesh_test_utils import TLSDetectorServer, make_pki

    for port in closed_ports:
        closed, detail = audit_closed_port("127.0.0.1", port)
        report.add("port_closure", f"127.0.0.1:{port}", "Legacy plaintext detector port closed", closed, detail)

    with tempfile.TemporaryDirectory(prefix="aegis_mesh_audit_") as tmp_dir:
        certs_dir = Path(make_pki(tmp_dir))
        for role_name, cert_prefix in DEFAULT_MESH_AUDIT_SERVICES:
            with TLSDetectorServer(str(certs_dir), service_prefix=cert_prefix) as srv:
                audit_endpoint_mtls(
                    report=report,
                    service_name=role_name,
                    host="127.0.0.1",
                    port=srv.port,
                    certs_dir=certs_dir,
                )


def _parse_probe_arg(spec: str) -> Tuple[str, str, int]:
    if "=" not in spec or ":" not in spec:
        raise ValueError(f"Expected name=host:port, got {spec!r}")
    name, addr = spec.split("=", 1)
    host, port_s = addr.rsplit(":", 1)
    return name.strip(), host.strip(), int(port_s)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AEGIS Full-Mesh mTLS Connection Audit Tool")
    parser.add_argument("--config-only", action="store_true", help="Run static compose/nginx/prometheus config audit only.")
    parser.add_argument("--self-test", action="store_true", help="Boot ephemeral mTLS nodes for every service and run live probes.")
    parser.add_argument("--certs-dir", default=str(REPO_ROOT / "security" / "transport" / "certs"), help="PKI directory for live --probe checks.")
    parser.add_argument("--probe", action="append", default=[], help="Live endpoint target in name=host:port format.")
    parser.add_argument("--check-closed-port", action="append", type=int, default=[], help="Assert legacy host TCP port is unreachable.")
    parser.add_argument("--markdown-out", default="", help="Write Markdown audit report to path.")
    parser.add_argument("--json-out", default="", help="Write JSON audit report to path.")
    args = parser.parse_args(argv)

    report = AuditReport()
    audit_static_configuration(report)

    if not args.config_only:
        if args.self_test:
            closed = tuple(args.check_closed_port) if args.check_closed_port else LEGACY_DETECTOR_PORTS
            run_self_test_mesh_audit(report, closed_ports=closed)
        else:
            for port in args.check_closed_port:
                closed, detail = audit_closed_port("127.0.0.1", port)
                report.add("port_closure", f"127.0.0.1:{port}", "Plaintext port closed", closed, detail)
            certs_dir = Path(args.certs_dir)
            for spec in args.probe:
                name, host, port = _parse_probe_arg(spec)
                audit_endpoint_mtls(report, name, host, port, certs_dir)

    md = report.to_markdown()
    if args.markdown_out:
        out_p = Path(args.markdown_out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
    if args.json_out:
        out_j = Path(args.json_out)
        out_j.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": report.generated_at,
            "passed": report.passed,
            "total": report.total,
            "passed_count": report.passed_count,
            "failed_count": report.failed_count,
            "checks": [asdict(c) for c in report.checks],
        }
        out_j.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[AUDIT] {report.passed_count}/{report.total} checks passed.")
    for chk in report.checks:
        tag = "PASS" if chk.passed else "FAIL"
        print(f"  [{tag}] {chk.category}:{chk.target} - {chk.check} :: {chk.detail}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

