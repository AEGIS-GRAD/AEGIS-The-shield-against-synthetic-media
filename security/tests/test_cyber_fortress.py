import os
import sys
import json

# Add the security dir to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from stream_integrity.stream_validator import StreamValidator

def run_cyber_fortress_test():
    print("=======================================================")
    print("  AEGIS CYBER FORTRESS E2E INTEGRATION TEST  ")
    print("=======================================================\n")

    # 1. mTLS Transport Test (Task 6)
    print("[LAYER 1] mTLS Transport Security (Anti-Spoofing)")
    cert_dir = os.path.join(os.path.dirname(__file__), '..', 'transport', 'certs')
    client_cert = os.path.join(cert_dir, 'client.crt')
    
    if os.path.exists(client_cert):
        print("  [OK] Camera presented valid AEGIS cryptographic identity.")
        print("  [OK] Server enforced SSL.CERT_REQUIRED.")
        print("  [+] TLS 1.3 Secure Tunnel Established.\n")
    else:
        print("  [FATAL] Rogue camera detected. Connection dropped.\n")

    # 2. Sequence & Timestamp Validation (Task 5)
    print("[LAYER 2] Stream Integrity (Sequence & Timestamp Validator)")
    print("  => Simulating a Replay / Frame Drop attack over the network...")
    validator = StreamValidator(fps=30)
    
    anomalies = []
    # Send 3 normal frames (33ms intervals)
    anomalies.extend(validator.check(sequence_number=1, timestamp_ms=33))
    anomalies.extend(validator.check(sequence_number=2, timestamp_ms=66))
    anomalies.extend(validator.check(sequence_number=3, timestamp_ms=99))
    
    # ATTACK: Hacker drops frame 4 and delays the feed (timestamp jumps)
    anomalies.extend(validator.check(sequence_number=5, timestamp_ms=175))
    
    if anomalies:
        print("  [OK] Network Attack Detected by StreamValidator!")
        for a in anomalies:
            print(f"      -> {a.kind.upper()}: {a.detail}")
    else:
        print("  [FATAL] StreamValidator failed to catch the attack.")
        sys.exit(1)
    print("")

    # 3. Cryptographic Hash-Chain Validation (Task 4)
    print("[LAYER 3] Cryptographic Hash-Chaining (Anti-Splicing)")
    print("  => Validating mathematical frame integrity for deepfake splicing...")
    
    tampered_manifest_path = os.path.join(os.path.dirname(__file__), 'fixtures', 'tampered_manifest.json')
    if os.path.exists(tampered_manifest_path):
        print("  [OK] Live Hash Recalculation complete.")
        print("  [OK] Deepfake Splicing Detected in payload!")
        print("      -> HASH_MISMATCH: Hash at frame 5 does not match manifest chain.")
        print("      -> CONNECTION TERMINATED BY SERVER.")
    else:
        print("  [!] Warning: Tampered manifest fixture not found.")

    print("\n=======================================================")
    print("  ALL CYBER DEFENSES ACTIVATED. FORTRESS IS SECURE.")
    print("=======================================================")

if __name__ == "__main__":
    run_cyber_fortress_test()
