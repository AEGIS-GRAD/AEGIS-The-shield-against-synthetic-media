import os
import datetime
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import NameOID
from cryptography import x509

def generate_cert(name, is_ca=False, issuer_name=None, issuer_key=None):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"EG"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Cairo"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Cairo"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"AEGIS"),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])
    
    issuer = issuer_name if issuer_name else subject
    signing_key = issuer_key if issuer_key else private_key
    
    builder = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
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
            x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True, data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True
        )
    else:
        builder = builder.add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False
        )
        builder = builder.add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False
        )
        builder = builder.add_extension(
            x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True, data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True
        )
        
    certificate = builder.sign(
        private_key=signing_key, algorithm=hashes.SHA256()
    )
    
    return private_key, certificate, subject

def save_cert(cert_dir, prefix, key, cert):
    with open(os.path.join(cert_dir, f"{prefix}.key"), "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    with open(os.path.join(cert_dir, f"{prefix}.crt"), "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

if __name__ == "__main__":
    cert_dir = os.path.join(os.path.dirname(__file__), "certs")
    os.makedirs(cert_dir, exist_ok=True)
    
    print("1. Generating Root CA...")
    ca_key, ca_cert, ca_subject = generate_cert(u"AEGIS Root CA", is_ca=True)
    save_cert(cert_dir, "ca", ca_key, ca_cert)
    
    print("2. Generating Server Certificate (Ingestion Node)...")
    server_key, server_cert, _ = generate_cert(u"localhost", issuer_name=ca_subject, issuer_key=ca_key)
    save_cert(cert_dir, "server", server_key, server_cert)
    
    print("3. Generating Client Certificate (Edge Camera)...")
    client_key, client_cert, _ = generate_cert(u"camera-001", issuer_name=ca_subject, issuer_key=ca_key)
    save_cert(cert_dir, "client", client_key, client_cert)
    
    print(f"Certificates generated successfully in {cert_dir}")
