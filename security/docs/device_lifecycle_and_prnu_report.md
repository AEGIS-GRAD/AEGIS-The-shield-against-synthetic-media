# Camera Device Lifecycle & Real-Camera PRNU — Test Report

**Task:** Week 11 Cybersecurity Task 6 · **Date:** 2026-11-16
**Tests:** `security/tests/test_device_lifecycle.py` (17 tests, real mTLS against two live ingestion-gateway processes)
**PRNU evaluation:** `eval/scripts/prnu_real_camera_eval.py` · proxy results `eval/reports/prnu_proxy_sample_videos_eval.md`
**Depends on:** Week 10 Task 4 (RTSP ingestion bridge), which is merged.

## 1. Summary

| Area | Before this task | After this task |
|---|---|---|
| Certificate issuance | One shared `client.crt` (`camera-001`), RSA, 365-day validity | Per-camera ECDSA P-256 certs, CN = camera id, 30-day default, registry of serials (`device_lifecycle.py`) |
| Rotation | Not supported | `renew_camera()` issues a new key/cert with an overlap window; old serial revoked as `superseded` |
| Revocation | **Not enforced.** Gateway loads only the CA, so a stolen camera key works until expiry | CRL issued by the CA; gateway enforces `VERIFY_CRL_CHECK_LEAF`, hot-reloads the CRL (2 s poll), and **closes live sessions** of newly revoked certs |
| Cross-session replay | **Replay succeeds.** Constant chain genesis, sequence restarts at 1, relative timestamps | `AEGIS_SESSION_BINDING=enforce`: per-session nonce → bound genesis; replay fails at frame 1 |
| Clock skew | **Not checked.** A camera 10 min off is accepted | In bound sessions every frame's absolute timestamp is checked (±2 s default) → `CLOCK_SKEW`, `INTEGRITY_UNKNOWN`, severed in prod |
| PRNU on real footage | Validated only on simulated splices | Evaluated on real (web-compressed) footage. **It separates sources, but by scene content, not sensor noise** (§4). Physical two-camera test still outstanding |

## 2. Lifecycle test results (all against the real gateway, prod profile)

| # | Scenario | Expected | Result | Test |
|---|---|---|---|---|
| 1 | Enrolled camera, valid cert | accepted | 10/10 frames VALID | `test_enrolled_camera_is_accepted` |
| 2 | Cert from a rogue CA | rejected | 0 frames | `test_camera_from_rogue_ca_is_rejected` |
| 3 | Expired cert | rejected | 0 frames | `test_expired_camera_certificate_is_rejected` |
| 4 | Cert not yet valid (provisioning clock 1 day fast) | rejected | 0 frames | `test_not_yet_valid_certificate_is_rejected` |
| 5a | Revoked cert, **no CRL published** (pre-Week-11 behaviour) | — | **accepted: 5/5 frames** | `test_revocation_is_enforced_once_crl_published` |
| 5b | Same cert after CRL published (no restart) | rejected | 0 frames; unrelated camera still 5/5 | same |
| 6 | Revoke a camera **mid-stream** | session cut | cut within ~1–2 s of CRL publication | `test_revocation_severs_an_already_open_session` |
| 7 | Rotation: old + new cert during overlap, then supersede old | both valid → old rejected, new valid | as expected | `test_rotation_overlap_then_supersede` |
| 8 | Record session 1, replay verbatim in session 2 (legacy protocol) | — | **replay accepted: 10/10 frames** | `test_cross_session_replay_succeeds_on_legacy_protocol` |
| 9 | Same replay with session binding | rejected | 0 frames (chain break at frame 1, severed) | `test_cross_session_replay_rejected_with_session_binding` |
| 10 | Legacy client against a binding-enforcing gateway | rejected | 0 frames (migration requirement) | `test_legacy_client_is_refused_by_bound_gateway` |
| 11 | RTSP bridge negotiates binding | bound genesis | yes | `test_rtsp_bridge_negotiates_binding` |
| 12 | Clock skew +0.4 s / −1.5 s (bound) | accepted | 6/6 | `test_clock_skew_handling_with_session_binding` |
| 13 | Clock skew +10 min / −30 s (bound) | rejected + `CLOCK_SKEW` event | 0 frames, event logged | same |
| 14 | Clock skew +10 min on legacy protocol | — | **accepted: 6/6** (skew invisible) | `test_clock_skew_invisible_on_legacy_protocol` |
| 15 | Expired CRL | fail closed | handshake refused ("CRL has expired") | `test_crl_expiry_fails_closed` |

## 3. Operational notes

* **CRL freshness is now a liveness dependency.** The CRL is fail-closed: if `nextUpdate` passes, every camera is refused.
  Re-issue it at least daily (`python -m security.transport.device_lifecycle crl`, default validity 7 days) and alert
  when less than 48 h remain.
* **Session binding is opt-in** (`AEGIS_SESSION_BINDING=off` by default) so the existing harnesses, pen-test scripts and
  the Month 2 load test keep working. The RTSP bridge already supports it (it reads the hello if one arrives, so it works
  with either setting). Enable `enforce` in production once every camera client is updated; the load test, the
  `security/tests/run_*_pentest.py` scripts and `live_pipeline` clients still use the legacy genesis.
* Bound sessions require cameras to send **absolute** epoch-ms timestamps (the RTSP bridge already does) and NTP-synchronised clocks.
* Camera private keys are written unencrypted next to the cert (devices cannot type a passphrase); on real hardware they
  belong in the camera's secure element / TPM.

## 4. Real-camera PRNU: what we could and could not establish

**No physical cameras were available, so PRNU has not been validated on physical-camera footage.** All earlier results
(unit tests, surveillance pen-test) used simulated splices, so they do not show that the check works on real cameras.

What we did instead, on real (but web-compressed) footage, the three sample feeds in `web/public/sample_videos/`
(different, unknown source devices, 480x600 common crop, 40 enrolment frames each):

| Statistic | Same-source median | Cross-source median | Same-source accepted @PCE 50 | Foreign accepted @PCE 50 | AUC |
|---|:-:|:-:|:-:|:-:|:-:|
| Gateway PCE | 40,581 | 20.0 | 100% | 0% | 1.000 |
| Zero-shift PCE | 2,161 | 3.3 | 100% | 0% | 1.000 |

Separation looks perfect, **but a control experiment shows it is driven by scene content, not the sensor:**

| Probe against the `authentic_feed` baseline | Median gateway PCE | Accepted as same camera |
|---|:-:|:-:|
| Genuine later frames of the same video | 147,989 | 100% |
| **Same frames, sensor noise removed and replaced by a different synthetic sensor pattern** | **1,282** | **100%** |
| Frames from a different video | 18 | 0% |

Frames that share the scene but carry a *different* noise pattern pass at 25x the threshold. The residual extractor
(`PRNUExtractor`, single-frame wavelet filter, level 2) leaves scene edges in the residual. The baseline is bootstrapped
from the stream's first frames of a static scene, and the gateway takes the correlation peak at any shift. So the gateway's
"PRNU" check behaves as a **scene-consistency check**. It catches splices of footage from a *different scene* (the
simulated-splice tests), but it would accept a face-swap deepfake rendered on the camera's own background, or the same
view re-filmed by a different camera.

Consequences:

1. Until the two-camera protocol below passes, reports must describe PRNU results as "scene/sensor consistency" and must
   not present them as sensor identification. The admissibility checklist already says this.
2. The fusion layer should not let a PRNU pass raise confidence that content is authentic.

How to close it (ready to run): film with two phones (`flat` wall/sky clip for enrolment, a **shared** scene filmed by both
phones, and one private scene each) and run
`python eval/scripts/prnu_real_camera_eval.py --camera phoneA=footage/phoneA --camera phoneB=footage/phoneB`.
Pass criterion: on the shared scene, cross-camera PCE stays below threshold (foreign accept ≤ 1%) while same-camera PCE on
the private scenes stays above it. Expected algorithm fixes if it fails: enrol from flat-field frames, zero-mean and
Wiener-filter the fingerprint in the Fourier domain, use zero-shift PCE, and replace the single-pass wavelet filter with a
proper Mihcak/BM3D denoiser.

## 5. Changed files

* `security/transport/device_lifecycle.py` (new): DeviceCA issue / renew / revoke / CRL + CLI
* `security/transport/session_binding.py` (new): nonce-bound genesis, client hello helpers, clock check
* `security/gateway/ingestion/server.py`: CRL enforcement with hot reload and live-session severing; opt-in session binding; absolute clock-skew check
* `security/gateway/rtsp_bridge/bridge.py`: negotiates session binding when offered
* `eval/scripts/prnu_real_camera_eval.py` (new): real-camera PRNU protocol and metrics

Pre-existing issue observed: `security/tests/test_prnu.py::test_continuous_prnu_stream_monitoring_e2e` fails on a clean
checkout because `security/fixtures/tampered_streams/*/stream.mkv` is not in the repository. It needs
`security/attacks/generate_attack_streams.py` to be run first. This is unrelated to this task.
