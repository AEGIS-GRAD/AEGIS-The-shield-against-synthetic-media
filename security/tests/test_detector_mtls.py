"""
Week 9 Task 6 - Gate 1 (DFS): orchestrator -> detector mTLS, attacked in isolation.

Every test talks to a real uvicorn server started with the production TLS flags
(--ssl-ca-certs=<mesh_ca> --ssl-cert-reqs=2). Covers the positive path plus the
attacks a pentester would try: no cert, wrong CA, camera cert, expired cert, plain HTTP,
server impersonation, and plaintext downgrade.
"""

import importlib.util
import ssl
import sys
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security.tests.mesh_test_utils import TLSDetectorServer, make_pki, mesh_env
from security.transport.generate_certs import MESH_SERVICES, generate_cert, save_cert


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch_tls = _load(REPO_ROOT / "orchestrator" / "app" / "mesh_tls.py", "orch_mesh_tls")
gw_tls = _load(REPO_ROOT / "security" / "gateway" / "validator" / "app" / "mesh_tls.py", "gw_mesh_tls")

TRANSPORT_ERRORS = (httpx.TransportError, ssl.SSLError, OSError)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    return make_pki(tmp_path_factory.mktemp("mesh_pki"))


@pytest.fixture(scope="module")
def server(pki):
    with TLSDetectorServer(pki) as s:
        yield s


def _client(**kwargs):
    return httpx.Client(timeout=5.0, **kwargs)


def _ctx_with(ca_file, cert_file=None, key_file=None):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    if cert_file:
        ctx.load_cert_chain(cert_file, key_file)
    return ctx


# ── PKI ──────────────────────────────────────────────────────────────────────
class TestMeshPKI:
    def test_all_mesh_certs_exist_with_docker_sans_and_dual_eku(self, pki):
        assert (Path(pki) / "mesh_ca.crt").exists()
        for cn, (prefix, dns_names) in MESH_SERVICES.items():
            cert = x509.load_pem_x509_certificate((Path(pki) / f"{prefix}.crt").read_bytes())
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            got = san.get_values_for_type(x509.DNSName)
            for name in dns_names:
                assert name in got, f"{cn} missing SAN {name}"
            eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            assert len(list(eku)) == 2  # serverAuth + clientAuth

    def test_mesh_ca_is_separate_from_main_ca(self, pki):
        mesh = x509.load_pem_x509_certificate((Path(pki) / "mesh_ca.crt").read_bytes())
        main = x509.load_pem_x509_certificate((Path(pki) / "ca.crt").read_bytes())
        assert mesh.subject != main.subject
        assert mesh.public_key().public_numbers() != main.public_key().public_numbers()


# ── Positive path ────────────────────────────────────────────────────────────
class TestAuthorizedCallers:
    def test_orchestrator_cert_is_accepted(self, server, pki):
        kw = orch_tls.client_tls_kwargs(mesh_env(pki, "mesh_orchestrator"))
        with _client(**kw) as c:
            r = c.post(f"{server.base_url}/detect", json={"job_id": "j1"})
        assert r.status_code == 200 and r.json()["job_id"] == "j1"

    def test_gateway_validator_cert_is_accepted(self, server, pki):
        kw = gw_tls.client_tls_kwargs(mesh_env(pki, "mesh_gateway_validator"))
        with _client(**kw) as c:
            assert c.get(f"{server.base_url}/health").status_code == 200

    def test_prometheus_cert_can_scrape_metrics(self, server, pki):
        kw = orch_tls.client_tls_kwargs(mesh_env(pki, "mesh_prometheus"))
        with _client(**kw) as c:
            assert c.get(f"{server.base_url}/metrics").status_code == 200

    def test_negotiated_protocol_is_tls12_or_newer(self, server, pki):
        ctx = _ctx_with(
            str(Path(pki) / "mesh_ca.crt"),
            str(Path(pki) / "mesh_orchestrator.crt"),
            str(Path(pki) / "mesh_orchestrator.key"),
        )
        import socket

        with socket.create_connection(("127.0.0.1", server.port), timeout=5) as raw:
            with ctx.wrap_socket(raw, server_hostname="localhost") as tls:
                assert tls.version() in ("TLSv1.2", "TLSv1.3")


# ── Attacks that MUST fail ───────────────────────────────────────────────────
class TestRejectedCallers:
    def test_no_client_certificate_is_rejected(self, server, pki):
        ctx = _ctx_with(str(Path(pki) / "mesh_ca.crt"))  # trusts server, presents nothing
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(verify=ctx) as c:
                c.get(f"{server.base_url}/health")

    def test_camera_certificate_from_main_ca_is_rejected(self, server, pki):
        """A legitimately issued camera cert must NOT be able to call detectors."""
        ctx = _ctx_with(
            str(Path(pki) / "mesh_ca.crt"),
            str(Path(pki) / "client.crt"),
            str(Path(pki) / "client.key"),
        )
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(verify=ctx) as c:
                c.get(f"{server.base_url}/health")

    def test_main_ca_gateway_cert_is_rejected(self, server, pki):
        ctx = _ctx_with(
            str(Path(pki) / "mesh_ca.crt"),
            str(Path(pki) / "gateway.crt"),
            str(Path(pki) / "gateway.key"),
        )
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(verify=ctx) as c:
                c.get(f"{server.base_url}/health")

    def test_rogue_ca_cert_claiming_orchestrator_identity_is_rejected(self, server, pki, tmp_path):
        rogue_key, rogue_ca, rogue_subject = generate_cert("Rogue CA", is_ca=True)
        k, c, _ = generate_cert(
            "aegis-orchestrator", issuer_name=rogue_subject, issuer_key=rogue_key,
            san_dns_names=["orchestrator"],
        )
        save_cert(str(tmp_path), "rogue", k, c)
        ctx = _ctx_with(
            str(Path(pki) / "mesh_ca.crt"),
            str(tmp_path / "rogue.crt"),
            str(tmp_path / "rogue.key"),
        )
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(verify=ctx) as cl:
                cl.get(f"{server.base_url}/health")

    def test_expired_mesh_certificate_is_rejected(self, server, pki, tmp_path):
        ca_key = serialization.load_pem_private_key((Path(pki) / "mesh_ca.key").read_bytes(), None)
        ca_cert = x509.load_pem_x509_certificate((Path(pki) / "mesh_ca.crt").read_bytes())
        k, c, _ = generate_cert(
            "aegis-orchestrator", issuer_name=ca_cert.subject, issuer_key=ca_key,
            san_dns_names=["orchestrator"], valid_days=1, backdate_days=5,
        )
        save_cert(str(tmp_path), "expired", k, c)
        ctx = _ctx_with(
            str(Path(pki) / "mesh_ca.crt"),
            str(tmp_path / "expired.crt"),
            str(tmp_path / "expired.key"),
        )
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(verify=ctx) as cl:
                cl.get(f"{server.base_url}/health")

    def test_plain_http_to_tls_port_fails(self, server):
        with pytest.raises(TRANSPORT_ERRORS):
            httpx.get(f"http://localhost:{server.port}/health", timeout=3.0)

    def test_client_refuses_server_not_signed_by_mesh_ca(self, server, pki):
        """Server impersonation: client that only trusts the main CA must refuse the detector."""
        ctx = _ctx_with(
            str(Path(pki) / "ca.crt"),
            str(Path(pki) / "mesh_orchestrator.crt"),
            str(Path(pki) / "mesh_orchestrator.key"),
        )
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(verify=ctx) as c:
                c.get(f"{server.base_url}/health")

    def test_hostname_not_in_san_is_rejected(self, server, pki):
        kw = orch_tls.client_tls_kwargs(mesh_env(pki, "mesh_orchestrator"))
        with pytest.raises(TRANSPORT_ERRORS):
            with _client(**kw) as c:
                c.get(f"https://localhost.evil.invalid:{server.port}/health")


# ── Client helper behaviour (relaxed / strict / fail-closed) ─────────────────
class TestClientHelper:
    @pytest.mark.parametrize("mod", [orch_tls, gw_tls])
    def test_relaxed_mode_returns_no_tls_kwargs(self, mod):
        assert mod.client_tls_kwargs({}) == {}
        assert mod.mesh_enabled({}) is False

    @pytest.mark.parametrize("mod", [orch_tls, gw_tls])
    def test_partial_configuration_stays_relaxed(self, mod):
        assert mod.client_tls_kwargs({"AEGIS_MESH_CA": "/x"}) == {}

    @pytest.mark.parametrize("mod", [orch_tls, gw_tls])
    def test_strict_with_missing_files_fails_closed(self, mod, pki):
        env = mesh_env(pki, "mesh_orchestrator")
        env["AEGIS_MESH_KEY"] = str(Path(pki) / "does_not_exist.key")
        with pytest.raises(mod.MeshTLSConfigError):
            mod.client_tls_kwargs(env)

    def test_strict_returns_ssl_context(self, pki):
        kw = orch_tls.client_tls_kwargs(mesh_env(pki, "mesh_orchestrator"))
        assert isinstance(kw["verify"], ssl.SSLContext)
        assert kw["verify"].verify_mode == ssl.CERT_REQUIRED
        assert kw["verify"].check_hostname is True

    def test_downgrade_protection_only_for_mesh_detectors(self, pki):
        env = mesh_env(pki, "mesh_orchestrator")
        assert orch_tls.url_allowed("aasist", "http://detector_aasist:8000", env) is False
        assert orch_tls.url_allowed("video-classifier", "HTTP://x:8000", env) is False
        assert orch_tls.url_allowed("aasist", "https://detector_aasist:8000", env) is True
        assert orch_tls.url_allowed("rppg", "http://detector_rppg:8000", env) is True  # Week 10
        assert orch_tls.url_allowed("aasist", "http://detector_aasist:8000", {}) is True  # relaxed

