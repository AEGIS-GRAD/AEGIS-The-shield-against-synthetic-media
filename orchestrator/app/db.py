import json
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Pin to the directory this file lives in so the DB is always found at the
# same absolute path regardless of where uvicorn is launched from.
_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_HERE, "flight_recorder.db")

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class RequestLog(Base):
    __tablename__ = "requests"
    
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    input_file = Column(String)
    modality = Column(String)
    has_audio = Column(Boolean)
    duration_seconds = Column(Float)
    aggregated_score = Column(Float, nullable=True)
    aggregated_verdict = Column(String)
    planner_mode = Column(String, default="rule_based")
    plan_json = Column(String, nullable=True)
    rationale = Column(String, nullable=True)
    fallback = Column(Boolean, default=False)
    fallback_reason = Column(String, nullable=True)

    decisions = relationship("OrchestratorDecision", back_populates="request")
    telemetry = relationship("DetectorTelemetry", back_populates="request")

class OrchestratorDecision(Base):
    __tablename__ = "orchestrator_decisions"
    
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"))
    planned_detector = Column(String)

    request = relationship("RequestLog", back_populates="decisions")

class DetectorTelemetry(Base):
    __tablename__ = "detector_telemetry"
    
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("requests.id"))
    detector_name = Column(String)
    status = Column(String)
    latency_ms = Column(Integer, nullable=True)
    confidence_score = Column(Float, nullable=True)
    error = Column(String, nullable=True)

    request = relationship("RequestLog", back_populates="telemetry")


class JudgeAuditLog(Base):
    __tablename__ = "judge_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True)
    judge_verdict = Column(String)           # SYNTHETIC | AUTHENTIC | INTEGRITY_UNKNOWN
    judge_score = Column(Float)
    judge_mode = Column(String)              # expert_deterministic_judge | llm_agentic_judge
    siem_alert_tier = Column(String)         # P1_CRITICAL | P2_ELEVATED | P4_INFORMATIONAL
    debate_transcript_hash = Column(String)  # tamper-evident SHA-256 over all 3 rounds
    forensic_justification = Column(String)
    guards_applied_count = Column(Integer, default=0)
    cross_exam_findings_count = Column(Integer, default=0)
    adjudication_latency_ms = Column(Float)
    debate_transcript_json = Column(String)  # full JSON of all 3 DebateRound objects


def init_db():
    Base.metadata.create_all(bind=engine)


def log_judge_report(job_id: str, report) -> None:
    """Persists a JudgeReport to the judge_audit_log table for tamper-evident audit trail."""
    import json
    db = SessionLocal()
    try:
        row = JudgeAuditLog(
            job_id=job_id,
            judge_verdict=report.verdict.final_verdict.value,
            judge_score=report.verdict.calibrated_score,
            judge_mode=report.judge_mode,
            siem_alert_tier=report.verdict.siem_alert_tier,
            debate_transcript_hash=report.debate_transcript_hash,
            forensic_justification=report.verdict.forensic_justification,
            guards_applied_count=len(report.guards_applied),
            cross_exam_findings_count=len(report.cross_examination_findings),
            adjudication_latency_ms=report.adjudication_latency_ms,
            debate_transcript_json=json.dumps(
                [r.model_dump() for r in report.rounds], default=str
            ),
        )
        db.add(row)
        db.commit()
    except Exception as e:
        print(f"Error persisting JudgeReport to DB: {e}")
        db.rollback()
    finally:
        db.close()


def log_decision(
    job_id,
    input_file,
    metadata,
    detectors_called,
    raw_results,
    aggregated_score,
    aggregated_verdict,
    planner_mode="rule_based",
    plan=None,
    rationale=None,
    fallback=False,
    fallback_reason=None,
):
    db = SessionLocal()
    try:
        plan_str = json.dumps(plan) if plan is not None and not isinstance(plan, str) else plan
        req = RequestLog(
            job_id=job_id,
            input_file=input_file,
            modality=metadata.get("modality", "unknown"),
            has_audio=metadata.get("has_audio", False),
            duration_seconds=metadata.get("duration_seconds", 0.0),
            aggregated_score=aggregated_score,
            aggregated_verdict=aggregated_verdict,
            planner_mode=planner_mode,
            plan_json=plan_str,
            rationale=rationale,
            fallback=fallback,
            fallback_reason=fallback_reason,
        )
        db.add(req)
        db.commit()
        db.refresh(req)

        for det in detectors_called:
            dec = OrchestratorDecision(request_id=req.id, planned_detector=det)
            db.add(dec)
        
        for res in raw_results:
            tel = DetectorTelemetry(
                request_id=req.id,
                detector_name=res.get("detector"),
                status=res.get("status"),
                latency_ms=res.get("latency_ms"),
                confidence_score=res.get("confidence"),
                error=res.get("error")
            )
            db.add(tel)
        
        db.commit()
    except Exception as e:
        print(f"Error logging to DB: {e}")
        db.rollback()
    finally:
        db.close()