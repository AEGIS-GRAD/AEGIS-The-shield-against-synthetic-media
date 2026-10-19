"""
Smoke-test: verify that judge_bridge.run_judge() integrates cleanly with main.py's
data shapes WITHOUT needing a live HTTP server.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from models import DetectorResult, DetectorEvidence, InputMetadata
from judge_bridge import run_judge

def test_judge_full_pipeline_smoke():
    results = [
        DetectorResult(detector="video-classifier", status="ok", job_id="smoke-001",
                       confidence=0.88, raw_score=0.88, latency_ms=120,
                       model_version="efficientnet-b0-v1.0",
                       evidence=DetectorEvidence(claim="High synthetic probability in 8/10 frames.", flags=[])),
        DetectorResult(detector="rppg", status="ok", job_id="smoke-001",
                       confidence=0.76, raw_score=0.76, latency_ms=300,
                       model_version="rppg-chrom-v1.0",
                       evidence=DetectorEvidence(claim="BVP signal flat — no cardiac activity.", flags=[])),
    ]
    meta = InputMetadata(filename="test_deepfake.mp4", modality="video",
                         has_audio=False, duration_seconds=8.0)
    
    report = run_judge(results, meta, "smoke-001")
    
    assert report.verdict.final_verdict.value in ("SYNTHETIC", "INTEGRITY_UNKNOWN", "AUTHENTIC")
    assert len(report.rounds) == 3
    assert report.debate_transcript_hash  # non-empty hash
    assert report.verdict.forensic_justification
    print("PASSED:", report.verdict.final_verdict.value,
          f"score={report.verdict.calibrated_score:.3f}",
          f"rounds={len(report.rounds)}")

if __name__ == "__main__":
    test_judge_full_pipeline_smoke()
