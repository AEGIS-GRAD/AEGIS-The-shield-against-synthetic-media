import os
import datetime
import ipaddress
from typing import List, Optional
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography import x509


def generate_cert(
    name: str,
    is_ca: bool = False,
    issuer_name: Optional[x509.Name] = None,
    issuer_key: Optional[rsa.RSAPrivateKey] = None,
    san_dns_names: Optional[List[str]] = None,
    san_ips: Optional[List[str]] = None,
):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "EG"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Cairo"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Cairo"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AEGIS"),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])

    issuer = issuer_name if issuer_name else subject
    signing_key = issuer_key if issuer_key else private_key

    now = datetime.datetime.now(datetime.timezone.utc)
    builder = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        now
    ).not_valid_after(
        now + datetime.timedelta(days=365)
    )

    if is_ca:
        builder = builder.add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False
        )
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(private_key.public_key()), critical=False
        )
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
    else:
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False
        )
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False
        )
        builder = builder.add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        # Enable both Server & Client Auth for inter-service mTLS
        builder = builder.add_extension(
            x509.ExtendedKeyUsage([
                ExtendedKeyUsageOID.SERVER_AUTH,
                ExtendedKeyUsageOID.CLIENT_AUTH,
            ]),
            critical=False,
        )

        # Subject Alternative Names (SANs) for modern RFC 5280 / TLS verification
        san_elements = []
        if san_dns_names:
            for dns in san_dns_names:
                san_elements.append(x509.DNSName(dns))
        if san_ips:
            for ip_str in san_ips:
                san_elements.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        if san_elements:
            builder = builder.add_extension(
                x509.SubjectAlternativeName(san_elements), critical=False
            )

    certificate = builder.sign(
        private_key=signing_key, algorithm=hashes.SHA256()
    )

    return private_key, certificate, subject


def save_cert(cert_dir: str, prefix: str, key, cert):
    os.makedirs(cert_dir, exist_ok=True)
    with open(os.path.join(cert_dir, f"{prefix}.key"), "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with open(os.path.join(cert_dir, f"{prefix}.crt"), "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def generate_all_service_certs(cert_dir: Optional[str] = None):
    """
    Generates Root CA and all service certificates required for AEGIS
    Zero Trust Inter-Service mTLS Mesh:
      - ca: AEGIS Root Certificate Authority
      - server / gateway: Live Ingestion Gateway (Port 8443)
      - client: Edge Camera (camera-001)
      - fusion: Feed Fusion Engine (Port 8445)
      - alert_router: Incident Response & Alert Router (Port 8446)
      - siem: Downstream SOC / SIEM Endpoint Receiver
    """
    if cert_dir is None:
        cert_dir = os.path.join(os.path.dirname(__file__), "certs")
    os.makedirs(cert_dir, exist_ok=True)

    print("1. Generating AEGIS Root CA...")
    ca_key, ca_cert, ca_subject = generate_cert("AEGIS Root CA", is_ca=True)
    save_cert(cert_dir, "ca", ca_key, ca_cert)

    standard_sans = ["localhost", "127.0.0.1"]

    print("2. Generating Ingestion Gateway Certificate...")
    gw_key, gw_cert, _ = generate_cert(
        "aegis-gateway",
        issuer_name=ca_subject,
        issuer_key=ca_key,
        san_dns_names=["localhost", "gateway", "aegis-gateway"],
        san_ips=["127.0.0.1"],
    )
    save_cert(cert_dir, "server", gw_key, gw_cert)
    save_cert(cert_dir, "gateway", gw_key, gw_cert)

    print("3. Generating Edge Camera Certificate...")
    cam_key, cam_cert, _ = generate_cert(
        "camera-001",
        issuer_name=ca_subject,
        issuer_key=ca_key,
        san_dns_names=["camera-001", "localhost"],
        san_ips=["127.0.0.1"],
    )
    save_cert(cert_dir, "client", cam_key, cam_cert)

    print("4. Generating Feed Fusion Service Certificate...")
    fusion_key, fusion_cert, _ = generate_cert(
        "aegis-fusion",
        issuer_name=ca_subject,
        issuer_key=ca_key,
        san_dns_names=["localhost", "fusion", "aegis-fusion"],
        san_ips=["127.0.0.1"],
    )
    save_cert(cert_dir, "fusion", fusion_key, fusion_cert)

    print("5. Generating Alert Router Service Certificate...")
    ar_key, ar_cert, _ = generate_cert(
        "aegis-alert-router",
        issuer_name=ca_subject,
        issuer_key=ca_key,
        san_dns_names=["localhost", "alert-router", "aegis-alert-router"],
        san_ips=["127.0.0.1"],
    )
    save_cert(cert_dir, "alert_router", ar_key, ar_cert)

    print("6. Generating Downstream SOC / SIEM Mock Certificate...")
    siem_key, siem_cert, _ = generate_cert(
        "aegis-siem",
        issuer_name=ca_subject,
        issuer_key=ca_key,
        san_dns_names=["localhost", "siem", "aegis-siem"],
        san_ips=["127.0.0.1"],
    )
    save_cert(cert_dir, "siem", siem_key, siem_cert)

    print(f"All 6 service certificates generated successfully in {cert_dir}")


if __name__ == "__main__":
    generate_all_service_certs()

