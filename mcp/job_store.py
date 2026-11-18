"""
job_store.py — Asynchronous job manager for AEGIS MCP verification pipeline.
=============================================================================
Manages long-running verification jobs submitted via the MCP `verify_media` tool.
Executes the orchestrator planning -> detector dispatch -> debate arbitration -> vault sealing
pipeline in a background thread, and provides thread-safe polling via `get_report`.
Also exposes `check_stream_integrity` for verifying video hash-chains and vault ledger provenance.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── Ensure paths are set up ──────────────────────────────────────────────────
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
_ORCHESTRATOR_APP = _REPO_ROOT / "orchestrator" / "app"

for _p in [str(_REPO_ROOT), str(_THIS_DIR), str(_ORCHESTRATOR_APP)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

logger = logging.getLogger("aegis.mcp.job_store")

# ── Dynamic imports from orchestrator and security ───────────────────────────
from media_metadata import get_input_metadata
from planner import plan_detectors
from dispatch import call_all_detectors
from judge_bridge import run_judge

try:
    from security.forensics.evidence_vault import UnifiedEvidenceVault, VerificationRecord
except Exception as e:
    logger.warning("UnifiedEvidenceVault import failed: %s", e)
    UnifiedEvidenceVault = None
    VerificationRecord = None

try:
    from security.forensics.hash_chain import FrameHashChain
except Exception as e:
    logger.warning("FrameHashChain import failed: %s", e)
    FrameHashChain = None


class VerificationJobStore:
    """Thread-safe in-memory and vault-backed store for asynchronous MCP verification jobs."""

    def __init__(self, vault_dir: Optional[str] = None):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._vault_dir = vault_dir or os.environ.get("AEGIS_VAULT_DIR")
        self._vault: Optional[Any] = None

    def _get_vault(self) -> Optional[Any]:
        if self._vault is None and UnifiedEvidenceVault is not None:
            try:
                self._vault = (
                    UnifiedEvidenceVault(vault_dir=self._vault_dir)
                    if self._vault_dir
                    else UnifiedEvidenceVault()
                )
            except Exception as exc:
                logger.warning("Failed to initialize UnifiedEvidenceVault: %s", exc)
        return self._vault

    def submit_job(
        self,
        file_path: str,
        modality: Optional[str] = None,
        planner_mode: str = "rule_based",
        risk_profile: str = "standard",
        compute_budget_s: Optional[float] = None,
        job_id: Optional[str] = None,
        sync: bool = False,
        owner_principal: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submits a verification job.

        Args:
            file_path: Path to the media file on disk.
            modality: Optional explicit modality ('video', 'image', 'audio', 'text').
            planner_mode: 'rule_based' or 'llm'.
            risk_profile: 'low', 'standard', or 'high'.
            compute_budget_s: Optional budget ceiling in seconds.
            job_id: Optional predetermined job ID.
            sync: If True, execute synchronously (useful for test assertions).
            owner_principal: Authenticated principal ID owning this job.

        Returns:
            Dict containing initial status and job_id.
        """
        p = Path(file_path)
        if not p.exists():
            return {
                "status": "error",
                "job_id": None,
                "error": f"File not found: '{file_path}'",
            }

        jid = job_id or f"mcp-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        job_record: Dict[str, Any] = {
            "job_id": jid,
            "status": "pending",
            "file_path": str(p.resolve()),
            "modality": modality,
            "planner_mode": planner_mode,
            "risk_profile": risk_profile,
            "compute_budget_s": compute_budget_s,
            "submitted_at_utc": now_iso,
            "completed_at_utc": None,
            "result": None,
            "error": None,
            "evidence_bundle_ref": None,
            "evidence_bundle_path": None,
            "owner_principal": owner_principal,
        }

        with self._lock:
            self._jobs[jid] = job_record

        def _worker():
            self._execute_pipeline(
                jid,
                str(p.resolve()),
                modality,
                planner_mode,
                risk_profile,
                compute_budget_s,
            )

        if sync:
            _worker()
        else:
            t = threading.Thread(target=_worker, name=f"verify-worker-{jid}", daemon=True)
            with self._lock:
                self._threads[jid] = t
            t.start()

        return {
            "status": "pending",
            "job_id": jid,
            "message": "Verification job submitted successfully. Use get_report(job_id) to poll for results.",
            "file_path": str(p.resolve()),
        }

    def _execute_pipeline(
        self,
        job_id: str,
        file_path: str,
        modality_override: Optional[str],
        planner_mode: str,
        risk_profile: str,
        compute_budget_s: Optional[float],
    ) -> None:
        """Executes the full orchestrator verification pipeline."""
        try:
            logger.info("[%s] Extracting metadata for %s...", job_id, file_path)
            metadata = get_input_metadata(file_path)
            if modality_override:
                metadata.modality = modality_override

            effective_mode = planner_mode or "rule_based"
            logger.info("[%s] Planning detectors (mode=%s)...", job_id, effective_mode)
            planning_result = plan_detectors(
                metadata=metadata,
                mode=effective_mode,
                risk_profile=risk_profile or "standard",
                budget_s=compute_budget_s,
            )
            detectors_to_call = planning_result.detectors_to_call
            logger.info("[%s] Detectors to call: %s", job_id, detectors_to_call)

            # Dispatch async detector calls in a new event loop for this thread
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                results = loop.run_until_complete(
                    call_all_detectors(detectors_to_call, job_id, metadata.modality, file_path)
                )
            finally:
                loop.close()

            # Adjudicate via JudgeAgent
            logger.info("[%s] Adjudicating %d detector results via JudgeAgent...", job_id, len(results))
            judge_report = run_judge(results=results, metadata=metadata, job_id=job_id)
            verdict_val = judge_report.verdict.final_verdict.value
            score_val = judge_report.verdict.calibrated_score

            # Seal in UnifiedEvidenceVault if available
            bundle_ref = f"aegis://evidence-vault/{job_id}"
            bundle_path = None
            vault = self._get_vault()
            if vault is not None:
                try:
                    input_bytes = Path(file_path).read_bytes()
                    model_versions = {
                        r.detector: (r.model_version or "unknown-v0") for r in results
                    }
                    calibration_version = os.environ.get(
                        "AEGIS_CALIBRATION_VERSION",
                        judge_report.prompt_version or "aegis-calibrator-v1.0",
                    )
                    judge_transcript = {
                        "judge_mode": judge_report.judge_mode,
                        "prompt_version": judge_report.prompt_version,
                        "llm_model": judge_report.llm_model,
                        "llm_fallback_used": judge_report.llm_fallback_used,
                        "debate_transcript_hash": judge_report.debate_transcript_hash,
                        "guards_applied": judge_report.guards_applied,
                        "forensic_justification": judge_report.verdict.forensic_justification,
                        "cross_examination_findings": [
                            f.model_dump() for f in judge_report.cross_examination_findings
                        ],
                        "rounds": [r.model_dump() for r in judge_report.rounds],
                        "adjudication_latency_ms": judge_report.adjudication_latency_ms,
                    }
                    vault.store_verification(
                        job_id=job_id,
                        modality=metadata.modality,
                        input_filename=os.path.basename(file_path),
                        input_bytes=input_bytes,
                        verdict=verdict_val,
                        calibrated_score=score_val,
                        detector_outputs=[r.model_dump() for r in results],
                        model_versions=model_versions,
                        calibration_version=calibration_version,
                        judge_transcript=judge_transcript,
                        siem_alert_tier=judge_report.verdict.siem_alert_tier,
                    )
                    try:
                        exported = vault.export_signed_bundle(job_id)
                        bundle_path = str(exported)
                    except Exception as exp_err:
                        logger.warning("[%s] Failed to export signed bundle: %s", job_id, exp_err)
                except Exception as vault_err:
                    logger.warning("[%s] Failed to store in UnifiedEvidenceVault: %s", job_id, vault_err)

            report_data = {
                "job_id": job_id,
                "input_file": os.path.basename(file_path),
                "modality": metadata.modality,
                "detectors_called": detectors_to_call,
                "raw_results": [r.model_dump() for r in results],
                "aggregated_score": score_val,
                "aggregated_verdict": verdict_val,
                "judge_verdict": verdict_val,
                "judge_score": score_val,
                "judge_mode": judge_report.judge_mode,
                "siem_alert_tier": judge_report.verdict.siem_alert_tier,
                "forensic_justification": judge_report.verdict.forensic_justification,
                "debate_transcript_hash": judge_report.debate_transcript_hash,
                "debate_transcript": [r.model_dump() for r in judge_report.rounds],
            }

            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["result"] = report_data
                    self._jobs[job_id]["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
                    self._jobs[job_id]["evidence_bundle_ref"] = bundle_ref
                    self._jobs[job_id]["evidence_bundle_path"] = bundle_path

            logger.info("[%s] Pipeline completed successfully. Verdict: %s (score=%.4f)", job_id, verdict_val, score_val)

        except Exception as exc:
            logger.error("[%s] Pipeline execution failed: %s\n%s", job_id, exc, traceback.format_exc())
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "error"
                    self._jobs[job_id]["error"] = str(exc)
                    self._jobs[job_id]["completed_at_utc"] = datetime.now(timezone.utc).isoformat()

    def get_report(
        self,
        job_id: str,
        caller_principal: Optional[str] = None,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """Polls for the report of a submitted job with confused-deputy ownership checks."""
        with self._lock:
            job = self._jobs.get(job_id)

        if job is not None:
            owner = job.get("owner_principal")
            if (
                owner
                and owner not in {"local-default", "anonymous"}
                and caller_principal
                and not is_admin
                and caller_principal != owner
            ):
                return {
                    "status": "error",
                    "error_code": "CONFUSED_DEPUTY_TENANT_MISMATCH",
                    "job_id": job_id,
                    "error": (
                        f"Access denied: principal '{caller_principal}' is not authorized "
                        f"to read job '{job_id}' owned by '{owner}'."
                    ),
                    "security_flags": ["confused_deputy_blocked"],
                }
            status = job["status"]
            if status == "pending":
                return {
                    "status": "pending",
                    "job_id": job_id,
                    "submitted_at_utc": job.get("submitted_at_utc"),
                    "message": "Verification is still running. Please poll again in a few moments.",
                }
            elif status == "completed":
                res = job["result"] or {}
                return {
                    "status": "completed",
                    "job_id": job_id,
                    "verdict": res.get("aggregated_verdict"),
                    "calibrated_score": res.get("aggregated_score"),
                    "siem_alert_tier": res.get("siem_alert_tier"),
                    "forensic_justification": res.get("forensic_justification"),
                    "evidence_bundle_ref": job.get("evidence_bundle_ref"),
                    "evidence_bundle_path": job.get("evidence_bundle_path"),
                    "debate_transcript_hash": res.get("debate_transcript_hash"),
                    "report": res,
                }
            else:
                return {
                    "status": "error",
                    "job_id": job_id,
                    "error": job.get("error", "Unknown pipeline error"),
                }

        # If not in memory, check UnifiedEvidenceVault
        vault = self._get_vault()
        if vault is not None:
            try:
                rec = vault.get_verification(job_id) or vault.get_verification_by_job_id(job_id)
                if rec is not None:
                    bundle_path = None
                    try:
                        bundle_path = str(vault.export_signed_bundle(job_id))
                    except Exception:
                        pass
                    return {
                        "status": "completed",
                        "job_id": job_id,
                        "verdict": rec.verdict,
                        "calibrated_score": rec.calibrated_score,
                        "siem_alert_tier": rec.siem_alert_tier,
                        "forensic_justification": (rec.judge_transcript or {}).get("forensic_justification", ""),
                        "evidence_bundle_ref": f"aegis://evidence-vault/{job_id}",
                        "evidence_bundle_path": bundle_path,
                        "debate_transcript_hash": (rec.judge_transcript or {}).get("debate_transcript_hash", ""),
                        "report": {
                            "job_id": job_id,
                            "input_file": rec.input_filename,
                            "modality": rec.modality,
                            "raw_results": rec.detector_outputs,
                            "aggregated_score": rec.calibrated_score,
                            "aggregated_verdict": rec.verdict,
                        },
                    }
            except Exception as e:
                logger.warning("[%s] Failed checking vault: %s", job_id, e)

        return {
            "status": "error",
            "job_id": job_id,
            "error": f"Job '{job_id}' not found.",
        }

    def check_stream_integrity(
        self,
        job_id: Optional[str] = None,
        video_path: Optional[str] = None,
        manifest_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validates hash-chain integrity of a live stream or completed verification."""
        # Case A: Video file + frame hash manifest check
        if video_path and manifest_path:
            if FrameHashChain is None:
                return {
                    "status": "error",
                    "error": "FrameHashChain module is unavailable.",
                }
            try:
                fhc = FrameHashChain()
                is_intact, tampered_frame, msg = fhc.validate_stream(video_path, manifest_path)
                return {
                    "status": "ok",
                    "check_type": "stream_frame_hash_chain",
                    "stream_intact": is_intact,
                    "tampered_frame": tampered_frame,
                    "message": msg,
                    "video_path": video_path,
                    "manifest_path": manifest_path,
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Stream validation failed: {e}",
                }

        # Case B: Verification record / Vault integrity check
        if job_id:
            vault = self._get_vault()
            if vault is None:
                return {
                    "status": "error",
                    "job_id": job_id,
                    "error": "UnifiedEvidenceVault is unavailable to verify integrity.",
                }
            try:
                rec = vault.get_verification(job_id) or vault.get_verification_by_job_id(job_id)
                audit = vault.verify_vault_integrity()
                if rec is None:
                    return {
                        "status": "error",
                        "job_id": job_id,
                        "error": f"No verification record found for '{job_id}'",
                        "vault_audit": audit.summary(),
                        "vault_is_valid": audit.is_valid,
                    }
                return {
                    "status": "ok",
                    "check_type": "vault_verification_record",
                    "job_id": job_id,
                    "verification_id": rec.verification_id,
                    "record_hash": rec.record_hash,
                    "prev_record_hash": rec.prev_record_hash,
                    "signature": rec.signature,
                    "vault_is_valid": audit.is_valid,
                    "tamper_evident_ok": audit.is_valid,
                    "audit_summary": audit.summary(),
                }
            except Exception as e:
                return {
                    "status": "error",
                    "job_id": job_id,
                    "error": f"Vault integrity check failed: {e}",
                }

        return {
            "status": "error",
            "error": "Either (video_path and manifest_path) or job_id must be provided.",
        }


# Global singleton instance
_GLOBAL_JOB_STORE: Optional[VerificationJobStore] = None


def get_job_store() -> VerificationJobStore:
    global _GLOBAL_JOB_STORE
    if _GLOBAL_JOB_STORE is None:
        _GLOBAL_JOB_STORE = VerificationJobStore()
    return _GLOBAL_JOB_STORE
