# Sample Forensic Evidence Bundles (Genuine & Tampered)

Verify all bundles offline with zero dependencies using:
```bash
python tools/evidence_verifier/aegis_verify.py tools/evidence_verifier/sample_bundles/ --verbose
```

| Bundle File | Expected | Modality | Scenario / Attack Demonstrated |
|---|---|---|---|
| `genuine_video_bundle.zip` | **PASS** | `video` | Genuine signed video bundle (SYNTHETIC, score=0.91). |
| `genuine_audio_bundle.zip` | **PASS** | `audio` | Genuine signed audio bundle (SYNTHETIC, score=0.88). |
| `genuine_image_bundle.zip` | **PASS** | `image` | Genuine signed image bundle (AUTHENTIC, score=0.12). |
| `genuine_text_bundle.zip` | **PASS** | `text` | Genuine signed text bundle (SYNTHETIC, score=0.86). |
| `genuine_multimodal_bundle.zip` | **PASS** | `multimodal` | Genuine signed multimodal bundle (SYNTHETIC, score=0.93). |
| `genuine_live_alert_bundle.zip` | **PASS** | `live_surveillance` | Genuine signed live surveillance HASH_CHAIN_BREAK incident bundle. |
| `tampered_verdict_flip.zip` | **FAIL** | `video` | evidence.json modified (`SYNTHETIC` -> `AUTHENTIC`) without valid hashes/signatures. |
| `tampered_payload_swap.zip` | **FAIL** | `video` | Raw media file inside payload/ mutated by 5 bytes. |
| `tampered_report_markdown.zip` | **FAIL** | `video` | Human-readable report.md altered while JSON & payload remain untouched. |
| `tampered_forged_signature.zip` | **FAIL** | `video` | evidence.json + hashes.sha256 recomputed, but bundle_signature.sig signed with attacker key. |
| `tampered_missing_signature.zip` | **FAIL** | `video` | Required cryptographic signature file `bundle_signature.sig` removed. |
