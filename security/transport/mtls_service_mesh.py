"""
🛡️ AEGIS Zero Trust Inter-Service mTLS Mesh Module
===================================================
Provides cryptographic mutual authentication (mTLS 1.3 / 1.2), role-based
service identity validation, and encrypted inter-service RPC for all AEGIS
subsystems (Ingestion Gateway, Feed Fusion, Alert Router, Downstream SIEM).

Complies with:
  - NIST SP 800-207 (Zero Trust Architecture)
  - RFC 8446 (The Transport Layer Security (TLS) Protocol Version 1.3)
  - RFC 5280 (X.509 PKI and CRL Profile)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("aegis.transport.mesh")

DEFAULT_CERTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "certs"))


def get_service_cert_paths(service_name: str, certs_dir: Optional[str] = None) -> Dict[str, str]:
    """
    Resolves standard certificate paths for a given service:
    Valid service_name options: 'gateway', 'fusion', 'alert_router', 'client', 'siem'.
    """
    base = certs_dir or DEFAULT_CERTS_DIR
    return {
        "ca_cert": os.path.join(base, "ca.crt"),
        "cert_file": os.path.join(base, f"{service_name}.crt"),
        "key_file": os.path.join(base, f"{service_name}.key"),
    }


def create_mtls_server_context(
    cert_file: str,
    key_file: str,
    ca_file: str,
    require_client_cert: bool = True,
) -> ssl.SSLContext:
    """
    Constructs an SSLContext for an mTLS server endpoint.
    Strictly requires and validates client certificates signed by our Root CA.
    """
    if not os.path.exists(cert_file) or not os.path.exists(key_file) or not os.path.exists(ca_file):
        raise FileNotFoundError(
            f"Missing mTLS certificates. Ensure cert_file ({cert_file}), "
            f"key_file ({key_file}), and ca_file ({ca_file}) exist."
        )

    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.verify_mode = ssl.CERT_REQUIRED if require_client_cert else ssl.CERT_OPTIONAL
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    context.load_verify_locations(cafile=ca_file)

    # Enforce TLS 1.2 minimum, preference for TLS 1.3
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def create_mtls_client_context(
    cert_file: str,
    key_file: str,
    ca_file: str,
    check_hostname: bool = False,
) -> ssl.SSLContext:
    """
    Constructs an SSLContext for an mTLS client.
    Presents client certificate and validates server certificate against Root CA.
    """
    if not os.path.exists(cert_file) or not os.path.exists(key_file) or not os.path.exists(ca_file):
        raise FileNotFoundError(
            f"Missing mTLS certificates. Ensure cert_file ({cert_file}), "
            f"key_file ({key_file}), and ca_file ({ca_file}) exist."
        )

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    context.load_cert_chain(certfile=cert_file, keyfile=key_file)
    context.check_hostname = check_hostname
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def extract_peer_identity(cert: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extracts validated identity attributes from an SSL peer certificate:
    - common_name: Common Name (CN)
    - organization: Organization Name (O)
    - sans: Subject Alternative Names
    """
    if not cert:
        return {"common_name": "Anonymous", "organization": "None", "sans": []}

    subject_dict = dict(x[0] for x in cert.get("subject", []))
    common_name = subject_dict.get("commonName", "Unknown")
    organization = subject_dict.get("organizationName", "Unknown")

    sans = []
    for san_type, san_val in cert.get("subjectAltName", []):
        sans.append(f"{san_type}:{san_val}")

    return {
        "common_name": common_name,
        "organization": organization,
        "sans": sans,
    }


def verify_peer_authorization(
    cert: Optional[Dict[str, Any]],
    allowed_common_names: Optional[Set[str]] = None,
) -> Tuple[bool, str]:
    """
    Verifies that the peer certificate belongs to an authorized service role.
    Prevents cross-service impersonation (e.g., an edge camera cannot call internal alert router).
    """
    if not cert:
        return False, "NO_CERTIFICATE_PRESENTED"

    identity = extract_peer_identity(cert)
    cn = identity["common_name"]

    if allowed_common_names and cn not in allowed_common_names:
        return False, f"UNAUTHORIZED_SERVICE_ROLE: '{cn}' is not in allowed roles {allowed_common_names}"

    return True, f"AUTHORIZED: {cn}"


class MTLSServiceServer:
    """
    Lightweight, high-performance asynchronous mTLS server for inter-service communication.
    Features:
      - Mandatory mutual TLS handshake with Root CA validation
      - Role-Based Access Control (RBAC) on client Common Names
      - Line-delimited JSON RPC message handling
    """

    def __init__(
        self,
        service_name: str,
        host: str = "127.0.0.1",
        port: int = 8445,
        allowed_client_cns: Optional[Set[str]] = None,
        certs_dir: Optional[str] = None,
        request_handler: Optional[Callable[[Dict[str, Any], str], Dict[str, Any]]] = None,
    ):
        self.service_name = service_name
        self.host = host
        self.port = port
        self.allowed_client_cns = allowed_client_cns
        self.certs_dir = certs_dir or DEFAULT_CERTS_DIR
        self.request_handler = request_handler
        self.server: Optional[asyncio.Server] = None
        self._is_running = False

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer_cert = writer.get_extra_info("peercert")
        peer_info = writer.get_extra_info("peername")
        client_ip = peer_info[0] if peer_info else "unknown"

        # Step 1: Zero Trust Authorization Check on Client Identity
        authorized, reason = verify_peer_authorization(peer_cert, self.allowed_client_cns)
        identity = extract_peer_identity(peer_cert)
        client_cn = identity["common_name"]

        if not authorized:
            logger.warning(
                f"[{self.service_name.upper()}] mTLS REJECTION: Unauthorized peer from {client_ip} -> {reason}"
            )
            try:
                err_resp = json.dumps({"status": "REJECTED", "error": reason}) + "\n"
                writer.write(err_resp.encode("utf-8"))
                await writer.drain()
            except Exception:
                pass
            writer.close()
            await writer.wait_closed()
            return

        logger.info(
            f"[{self.service_name.upper()}] SECURE mTLS SESSION: Authenticated peer '{client_cn}' ({client_ip})"
        )

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                try:
                    payload = json.loads(line.decode("utf-8"))
                except Exception as parse_err:
                    err_msg = json.dumps({"status": "ERROR", "detail": f"Malformed JSON: {parse_err}"}) + "\n"
                    writer.write(err_msg.encode("utf-8"))
                    await writer.drain()
                    continue

                # Process payload with registered handler
                if self.request_handler:
                    try:
                        response_data = self.request_handler(payload, client_cn)
                    except Exception as handler_err:
                        response_data = {"status": "ERROR", "detail": str(handler_err)}
                else:
                    response_data = {"status": "OK", "ack": True, "service": self.service_name}

                resp_bytes = (json.dumps(response_data) + "\n").encode("utf-8")
                writer.write(resp_bytes)
                await writer.drain()
        except Exception as e:
            logger.debug(f"[{self.service_name}] Session closed with {client_cn}: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        paths = get_service_cert_paths(self.service_name, self.certs_dir)
        context = create_mtls_server_context(
            cert_file=paths["cert_file"],
            key_file=paths["key_file"],
            ca_file=paths["ca_cert"],
            require_client_cert=True,
        )

        self.server = await asyncio.start_server(
            self._handle_connection, self.host, self.port, ssl=context
        )
        self._is_running = True
        logger.info(
            f"[{self.service_name.upper()}] mTLS Mesh Service listening on {self.host}:{self.port} (Allowed: {self.allowed_client_cns or 'ALL_CA_SIGNED'})"
        )

    def start_background(self) -> threading.Thread:
        """Starts the mTLS server in a dedicated background daemon thread with its own event loop."""
        self._loop = asyncio.new_event_loop()
        ready_event = threading.Event()

        def _runner():
            asyncio.set_event_loop(self._loop)

            async def _main():
                await self.start()
                ready_event.set()
                try:
                    await self.server.serve_forever()
                except (asyncio.CancelledError, Exception):
                    pass

            try:
                self._loop.run_until_complete(_main())
            except Exception:
                pass
            finally:
                try:
                    pending = asyncio.all_tasks(self._loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    self._loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=_runner, daemon=True)
        self._thread.start()
        ready_event.wait(timeout=2.0)
        return self._thread

    def stop_background(self):
        """Stops the background mTLS server and closes its event loop cleanly."""
        if hasattr(self, "_loop") and self._loop and self._loop.is_running():
            if self.server:
                self._loop.call_soon_threadsafe(self.server.close)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if hasattr(self, "_thread") and self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._is_running = False
        logger.info(f"[{self.service_name.upper()}] mTLS Mesh Service stopped.")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self._is_running = False
            logger.info(f"[{self.service_name.upper()}] mTLS Mesh Service stopped.")


class MTLSServiceClient:
    """
    Synchronous / Asynchronous mTLS client for calling internal mesh services.
    Presents its own client certificate and verifies server identity against Root CA.
    """

    def __init__(
        self,
        calling_service_name: str,
        certs_dir: Optional[str] = None,
        timeout: float = 3.0,
    ):
        self.calling_service_name = calling_service_name
        self.certs_dir = certs_dir or DEFAULT_CERTS_DIR
        self.timeout = timeout
        self.paths = get_service_cert_paths(calling_service_name, self.certs_dir)

    def send_request(
        self,
        host: str,
        port: int,
        payload: Dict[str, Any],
        expected_server_cn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sends an mTLS request to a target service and returns the response.
        """
        context = create_mtls_client_context(
            cert_file=self.paths["cert_file"],
            key_file=self.paths["key_file"],
            ca_file=self.paths["ca_cert"],
            check_hostname=False,
        )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        conn = context.wrap_socket(sock, server_hostname=host)

        try:
            conn.connect((host, port))

            # Validate server certificate Common Name
            if expected_server_cn:
                peer_cert = conn.getpeercert()
                identity = extract_peer_identity(peer_cert)
                server_cn = identity["common_name"]
                if server_cn != expected_server_cn:
                    raise ssl.CertificateError(
                        f"Expected server CN '{expected_server_cn}', got '{server_cn}'"
                    )

            msg = (json.dumps(payload) + "\n").encode("utf-8")
            conn.sendall(msg)

            data = conn.recv(65536)
            if not data:
                return {"status": "ERROR", "detail": "Empty response from server"}
            return json.loads(data.decode("utf-8"))
        finally:
            try:
                conn.close()
            except Exception:
                pass
