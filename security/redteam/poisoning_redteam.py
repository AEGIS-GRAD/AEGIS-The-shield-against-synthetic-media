"""
AEGIS Poisoning Red-Team — judge and planner (Week 11 Cybersecurity Task 2)
==========================================================================

Crafts poisoned / miscalibrated detector outputs, spoofed operating conditions,
self-serving flags, spoofed telemetry and spoofed metadata, runs them through the
real ``JudgeAgent`` (deterministic mode, the production default) and the real
orchestrator planner, and records which attacks change the outcome.

Each scenario is run with the poisoning guards OFF (Week 10 behaviour) and ON
(``debate/poisoning_guards.py``), so the log shows the effect of each mitigation.

    python security/redteam/poisoning_redteam.py            # writes security/docs/poisoning_redteam_log.{md,json}
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO), str(REPO / "orchestrator" / "app"), str(REPO / "orchestrator")):
    if p not in sys.path:
        sys.path.insert(0, p)

from debate.judge_agent import JudgeAgent  # noqa: E402
from debate.schemas import ForensicClaim, OperatingConditions  # noqa: E402

DOMAINS = {
    "video-classifier": "spatial_pixel", "rppg": "physiological_bvp", "syncnet": "audiovisual_sync",
    "aasist": "audio_acoustic", "detector_image": "image_forensic", "detector_text": "text_forensic",
}


def C(det: str, pol: str, conf: float, **kw) -> Dict[str, Any]:
    c = {"job_id": "redteam", "detector_id": det, "model_version": "v1", "domain": DOMAINS[det],
         "polarity": pol, "confidence": conf, "raw_score": conf, "claim": f"{det} reports {pol.lower()}"}
    c.update(kw)
    return c


# Honest evidence for a face-swap deepfake with the donor's real voice (ground truth SYNTHETIC).
DEEPFAKE = [C("video-classifier", "SYNTHETIC", 0.86), C("syncnet", "SYNTHETIC", 0.74),
            C("rppg", "SYNTHETIC", 0.68), C("aasist", "AUTHENTIC", 0.22)]
# Honest evidence for a genuine clip (ground truth AUTHENTIC).
GENUINE = [C("video-classifier", "AUTHENTIC", 0.14), C("syncnet", "AUTHENTIC", 0.22),
           C("rppg", "AUTHENTIC", 0.25), C("aasist", "AUTHENTIC", 0.12)]
GOOD_CONDITIONS = {"duration_seconds": 12.0, "mean_luminance": 120.0, "face_detected": True, "audio_present": True,
                   "video_bitrate_kbps": 2500.0}


def replace(claims: List[Dict[str, Any]], det: str, **kw) -> List[Dict[str, Any]]:
    out = copy.deepcopy(claims)
    for c in out:
        if c["detector_id"] == det:
            c.update(kw)
    return out


@dataclass
class Scenario:
    sid: str
    category: str
    description: str
    ground_truth: str
    attacker_goal: str  # verdict the attacker wants
    claims: List[Dict[str, Any]]
    conditions: Dict[str, Any] = field(default_factory=lambda: dict(GOOD_CONDITIONS))


JUDGE_SCENARIOS: List[Scenario] = [
    Scenario("J0a", "control", "Honest deepfake evidence", "SYNTHETIC", "-", DEEPFAKE),
    Scenario("J0b", "control", "Honest genuine evidence", "AUTHENTIC", "-", GENUINE),
    Scenario("J1", "single compromised detector", "Hide a deepfake: video-classifier reports AUTHENTIC at 0.01",
             "SYNTHETIC", "AUTHENTIC", replace(DEEPFAKE, "video-classifier", polarity="AUTHENTIC", confidence=0.01, raw_score=0.01)),
    Scenario("J2", "single compromised detector", "Frame a genuine clip: video-classifier reports SYNTHETIC at 0.99",
             "AUTHENTIC", "SYNTHETIC", replace(GENUINE, "video-classifier", polarity="SYNTHETIC", confidence=0.99, raw_score=0.99)),
    Scenario("J3", "two colluding detectors", "Hide a deepfake: video-classifier and syncnet both report AUTHENTIC",
             "SYNTHETIC", "AUTHENTIC",
             replace(replace(DEEPFAKE, "video-classifier", polarity="AUTHENTIC", confidence=0.03),
                     "syncnet", polarity="AUTHENTIC", confidence=0.05)),
    Scenario("J4", "miscalibration", "Frame a genuine clip: the secondary audio detector reports SYNTHETIC at 0.999",
             "AUTHENTIC", "SYNTHETIC", replace(GENUINE, "aasist", polarity="SYNTHETIC", confidence=0.999, raw_score=0.999)),
    Scenario("J5", "polarity/confidence inconsistency", "video-classifier says AUTHENTIC but confidence P(synthetic)=0.97",
             "SYNTHETIC", "AUTHENTIC", replace(DEEPFAKE, "video-classifier", polarity="AUTHENTIC", confidence=0.97)),
    Scenario("J6", "self-serving flags", "Hide a deepfake: rPPG flags itself low_light and syncnet flags silent_video, video-classifier compromised",
             "SYNTHETIC", "AUTHENTIC",
             replace(replace(replace(DEEPFAKE, "video-classifier", polarity="AUTHENTIC", confidence=0.04),
                             "rppg", flags=["low_light_attenuation"]), "syncnet", flags=["silent_video"])),
    Scenario("J7", "spoofed operating conditions", "Hide a deepfake: conditions claim darkness, no face, 1.5 s clip; video-classifier compromised",
             "SYNTHETIC", "AUTHENTIC", replace(DEEPFAKE, "video-classifier", polarity="AUTHENTIC", confidence=0.04),
             {"duration_seconds": 1.5, "mean_luminance": 8.0, "face_detected": False, "audio_present": False,
              "video_bitrate_kbps": 2500.0}),
    Scenario("J8", "domain spoofing", "Hide a deepfake: video-classifier claims the physiological domain",
             "SYNTHETIC", "AUTHENTIC", replace(DEEPFAKE, "video-classifier", polarity="AUTHENTIC", confidence=0.02,
                                                domain="physiological_bvp")),
    Scenario("J9", "sybil / duplicate claims", "Hide a deepfake: five duplicate AUTHENTIC claims from one compromised detector",
             "SYNTHETIC", "AUTHENTIC",
             [C("video-classifier", "AUTHENTIC", 0.02, claim_id=f"dup{i}") for i in range(5)] + DEEPFAKE[1:]),
    Scenario("J10", "self-reported attenuation", "Frame a genuine clip: honest detectors' claims carry attenuation 0.0 (poisoned wrapper), one compromised SYNTHETIC",
             "AUTHENTIC", "SYNTHETIC",
             [dict(c, attenuation_factors={"luminance_factor": 0.0}) for c in GENUINE[1:]]
             + [C("video-classifier", "SYNTHETIC", 0.95)]),
    Scenario("J11", "abstention", "Hide a deepfake: compromised video-classifier abstains, rPPG fooled by donor pulse",
             "SYNTHETIC", "AUTHENTIC",
             [C("video-classifier", "INCONCLUSIVE", 0.5), C("rppg", "AUTHENTIC", 0.10), C("aasist", "AUTHENTIC", 0.2)]),
]


def run_judge(s: Scenario, guards: bool) -> Dict[str, Any]:
    os.environ["AEGIS_POISONING_GUARDS"] = "1" if guards else "0"
    judge = JudgeAgent(mode="deterministic", manifests_dir=REPO / "capability_manifests")
    try:
        claims = [ForensicClaim(**c) for c in s.claims]
        report = judge.judge_claims(claims, conditions=OperatingConditions(**s.conditions), job_id=f"rt-{s.sid}")
        verdict = report.verdict.final_verdict.value
        guard_notes = [g for g in report.guards_applied if "POISON" in g.upper()]
        return {"verdict": verdict, "score": round(report.verdict.calibrated_score, 3), "guards": guard_notes}
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "REJECTED", "score": None, "guards": [f"input rejected: {str(exc)[:120]}"]}


def attack_succeeded(s: Scenario, verdict: str) -> Optional[bool]:
    if s.attacker_goal == "-":
        return None
    return verdict == s.attacker_goal


# ─────────────────────────────────────────────────────────────────────────────
# Planner scenarios
# ─────────────────────────────────────────────────────────────────────────────
def run_planner_scenarios(guards: bool) -> List[Dict[str, Any]]:
    os.environ["AEGIS_POISONING_GUARDS"] = "1" if guards else "0"
    os.environ.setdefault("AEGIS_PLANNER_MODE", "llm")
    import importlib

    import planner as planner_mod
    from models import InputMetadata
    from telemetry_client import DetectorTelemetry

    importlib.reload(planner_mod)

    def tel(name, status, up=True, p95=None, source="live_prometheus"):
        return DetectorTelemetry(detector_name=name, status=status, p95_latency_ms=p95, avg_latency_ms=p95,
                                 ram_usage_mb=None, vram_usage_mb=None, calls_count=100, source=source,
                                 degradation_ratio=None, up=up, last_updated=0.0)

    video = InputMetadata(filename="clip.mp4", modality="video", has_audio=True, duration_seconds=12.0,
                          resolution=[1280, 720], mean_luminance=120.0, face_detected=True)
    healthy = {n: tel(n, "healthy") for n in ("video-classifier", "rppg", "syncnet", "aasist")}

    def plan(meta, snapshot):
        planner_mod.get_telemetry_snapshot = lambda *a, **k: snapshot
        res = planner_mod.plan_detectors(meta, mode="llm", mock_llm=True)
        return sorted(res.detectors_to_call), res

    out = []
    planner_mod.clear_plan_cache()
    base, _ = plan(video, healthy)
    out.append({"id": "P0", "category": "control", "description": "Healthy telemetry, video with audio",
                "detectors": base, "attack_succeeded": None})

    planner_mod.clear_plan_cache()
    spoof = dict(healthy, **{"video-classifier": tel("video-classifier", "down", up=False)})
    sel, _ = plan(video, spoof)
    out.append({"id": "P1", "category": "telemetry spoofing", "description": "Spoofed Prometheus series marks video-classifier down",
                "detectors": sel, "attack_succeeded": "video-classifier" not in sel})

    planner_mod.clear_plan_cache()
    spoof_all = {n: tel(n, "down", up=False) for n in ("video-classifier", "syncnet", "aasist")}
    spoof_all["rppg"] = tel("rppg", "healthy")
    sel, res = plan(video, spoof_all)
    out.append({"id": "P2", "category": "telemetry spoofing", "description": "Everything but rPPG (fooled by donor pulse) marked down",
                "detectors": sel, "attack_succeeded": "video-classifier" not in sel})

    planner_mod.clear_plan_cache()
    plan(video, spoof)  # poisoned plan computed and cached
    sel, res = plan(video, healthy)  # telemetry has recovered
    out.append({"id": "P3", "category": "cache persistence", "description": "Plan made under spoofed 'down' telemetry reused after recovery",
                "detectors": sel, "attack_succeeded": "video-classifier" not in sel})

    planner_mod.clear_plan_cache()
    stripped = video.model_copy(update={"has_audio": False})
    sel, _ = plan(stripped, healthy)
    out.append({"id": "P4", "category": "metadata spoofing", "description": "Audio track hidden from ffprobe (has_audio=False) on a voice-cloned clip",
                "detectors": sel, "attack_succeeded": bool(set(base) - set(sel)) or not any(d in base for d in ("aasist", "syncnet")),
                "note": "aasist/syncnet are not scheduled even with audio under the default 3 s budget, so hiding the "
                        "audio track changes nothing the attacker needs; audio coverage is already missing (see log)."})

    planner_mod.clear_plan_cache()
    slow = dict(healthy, **{"video-classifier": tel("video-classifier", "degraded", p95=60_000.0)})
    sel, _ = plan(video, slow)
    out.append({"id": "P5", "category": "telemetry spoofing", "description": "Spoofed 60 s p95 latency makes the planner drop video-classifier to save budget",
                "detectors": sel, "attack_succeeded": "video-classifier" not in sel})
    return out


def main() -> None:
    results: Dict[str, Any] = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "judge": [], "planner": {}}
    for s in JUDGE_SCENARIOS:
        off, on = run_judge(s, False), run_judge(s, True)
        results["judge"].append({
            "id": s.sid, "category": s.category, "description": s.description, "ground_truth": s.ground_truth,
            "attacker_goal": s.attacker_goal, "guards_off": off, "guards_on": on,
            "succeeded_off": attack_succeeded(s, off["verdict"]), "succeeded_on": attack_succeeded(s, on["verdict"]),
        })
    try:
        results["planner"]["guards_off"] = run_planner_scenarios(False)
        results["planner"]["guards_on"] = run_planner_scenarios(True)
    except Exception as exc:  # noqa: BLE001
        results["planner"]["error"] = repr(exc)

    out_json = REPO / "security" / "docs" / "poisoning_redteam_results.json"
    out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"{'ID':4} {'Category':34} {'Goal':10} {'Guards OFF':22} {'Guards ON':22}")
    for r in results["judge"]:
        f = lambda v, ok: f"{v['verdict']}{' (WIN)' if ok else ''}"
        print(f"{r['id']:4} {r['category'][:34]:34} {r['attacker_goal']:10} {f(r['guards_off'], r['succeeded_off']):22} {f(r['guards_on'], r['succeeded_on']):22}")
    for mode in ("guards_off", "guards_on"):
        for r in results["planner"].get(mode, []):
            print(f"{mode:10} {r['id']:4} {r['description'][:60]:60} -> {r['detectors']} {'(WIN)' if r['attack_succeeded'] else ''}")
    if "error" in results["planner"]:
        print("planner error:", results["planner"]["error"])
    print(f"\nResults -> {out_json}")


if __name__ == "__main__":
    main()
