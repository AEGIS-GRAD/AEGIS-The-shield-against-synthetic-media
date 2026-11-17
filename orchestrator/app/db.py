import json
import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, ForeignKey, DateTime, inspect, text
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


class DetectorClaimOutcome(Base):
    """Per-detector claim adjudication and post-hoc ground truth confirmation."""

    __tablename__ = "detector_claim_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, index=True)
    session_id = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    detector_name = Column(String, index=True)
    model_version = Column(String, nullable=True)
    modality = Column(String, default="unknown")
    condition_tags_json = Column(String, default='["nominal"]')
    original_polarity = Column(String)
    original_confidence = Column(Float)
    accepted_confidence = Column(Float)
    weight_assigned = Column(Float)
    judge_verdict = Column(String)
    overruled_by_judge = Column(Boolean, default=False)
    discount_reason = Column(String, nullable=True)
    ground_truth_label = Column(String, nullable=True)
    detector_was_wrong = Column(Boolean, nullable=True)
    confirmed_overrule = Column(Boolean, nullable=True)
    judge_was_correct = Column(Boolean, nullable=True)
    confirmed_by = Column(String, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)


def _column_default_sql(col) -> str:
    """Builds a safe SQLite DEFAULT clause for scalar model column defaults."""
    if col.default is None or not col.default.is_scalar:
        return ""
    arg = col.default.arg
    if isinstance(arg, bool):
        return f" DEFAULT {1 if arg else 0}"
    if isinstance(arg, (int, float)):
        return f" DEFAULT {arg}"
    if isinstance(arg, str):
        escaped = arg.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def _sync_sqlite_columns(target_engine) -> None:
    """Adds missing ORM columns to pre-existing SQLite tables idempotently."""
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    with target_engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(dialect=target_engine.dialect)
                default_clause = _column_default_sql(col)
                conn.execute(
                    text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}{default_clause}')
                )


def init_db(target_engine=None):
    """Creates tables and upgrades pre-existing SQLite schemas with missing columns."""
    db_engine = target_engine or engine
    Base.metadata.create_all(bind=db_engine)
    if db_engine.dialect.name == "sqlite":
        _sync_sqlite_columns(db_engine)


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


def normalize_ground_truth_label(label: str) -> str:
    """Normalizes ground-truth labels to canonical AUTHENTIC or SYNTHETIC."""
    norm = (label or "").strip().upper()
    if norm in ("REAL", "AUTHENTIC", "HUMAN", "BONAFIDE"):
        return "AUTHENTIC"
    if norm in ("FAKE", "SYNTHETIC", "AI", "MANIPULATED", "SPOOF"):
        return "SYNTHETIC"
    raise ValueError(f"Unsupported ground_truth_label '{label}'. Expected AUTHENTIC/REAL or SYNTHETIC/FAKE.")


def _ensure_claim_outcome_table(db_session) -> None:
    DetectorClaimOutcome.__table__.create(bind=db_session.get_bind(), checkfirst=True)


def log_claim_outcomes(
    records: list[dict],
    session_factory=None,
) -> int:
    """
    Persists per-detector claim adjudication outcomes (including judge overrule flags)
    for a completed orchestration job. Returns the count of inserted rows.
    """
    if not records:
        return 0
    factory = session_factory or SessionLocal
    db = factory()
    try:
        _ensure_claim_outcome_table(db)
        inserted = 0
        for rec in records:
            conds = rec.get("condition_tags") or ["nominal"]
            cond_json = json.dumps(list(dict.fromkeys(str(c) for c in conds)))
            row = DetectorClaimOutcome(
                job_id=rec["job_id"],
                session_id=rec.get("session_id"),
                detector_name=rec["detector_name"],
                model_version=rec.get("model_version"),
                modality=rec.get("modality", "unknown"),
                condition_tags_json=cond_json,
                original_polarity=rec["original_polarity"],
                original_confidence=float(rec["original_confidence"]),
                accepted_confidence=float(rec["accepted_confidence"]),
                weight_assigned=float(rec["weight_assigned"]),
                judge_verdict=rec["judge_verdict"],
                overruled_by_judge=bool(rec.get("overruled_by_judge", False)),
                discount_reason=rec.get("discount_reason"),
            )
            db.add(row)
            inserted += 1
        db.commit()
        return inserted
    except Exception as e:
        print(f"Error logging DetectorClaimOutcome rows: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


def _apply_ground_truth_to_row(
    row: DetectorClaimOutcome,
    norm_gt: str,
    confirmed_by: str,
    now: datetime,
) -> dict:
    row.ground_truth_label = norm_gt
    row.confirmed_by = confirmed_by
    row.confirmed_at = now
    row.judge_was_correct = (row.judge_verdict == norm_gt)
    if row.original_polarity in ("AUTHENTIC", "SYNTHETIC"):
        wrong = row.original_polarity != norm_gt
        row.detector_was_wrong = wrong
        row.confirmed_overrule = bool(row.overruled_by_judge and wrong)
    else:
        row.detector_was_wrong = None
        row.confirmed_overrule = False
    return {
        "job_id": row.job_id,
        "detector_name": row.detector_name,
        "condition_tags": json.loads(row.condition_tags_json or '["nominal"]'),
        "original_polarity": row.original_polarity,
        "overruled_by_judge": bool(row.overruled_by_judge),
        "ground_truth_label": norm_gt,
        "detector_was_wrong": row.detector_was_wrong,
        "confirmed_overrule": bool(row.confirmed_overrule),
        "judge_was_correct": bool(row.judge_was_correct),
    }


def confirm_ground_truth(
    job_id: str,
    ground_truth_label: str,
    confirmed_by: str = "analyst",
    session_factory=None,
) -> list[dict]:
    """
    Records post-hoc ground truth for all detector claim rows matching `job_id`.
    Computes `detector_was_wrong`, `confirmed_overrule`, and `judge_was_correct`.
    Returns updated outcome dicts for the job.
    """
    norm_gt = normalize_ground_truth_label(ground_truth_label)
    factory = session_factory or SessionLocal
    db = factory()
    try:
        _ensure_claim_outcome_table(db)
        rows = (
            db.query(DetectorClaimOutcome)
            .filter(DetectorClaimOutcome.job_id == job_id)
            .all()
        )
        if not rows:
            return []

        now = datetime.now(timezone.utc)
        updated = [_apply_ground_truth_to_row(row, norm_gt, confirmed_by, now) for row in rows]
        db.commit()
        return updated
    except Exception as e:
        print(f"Error confirming ground truth for job '{job_id}': {e}")
        db.rollback()
        raise
    finally:
        db.close()


def confirm_ground_truth_batch(
    confirmations: list[tuple[str, str]],
    confirmed_by: str = "batch_eval",
    session_factory=None,
) -> list[dict]:
    """
    Records post-hoc ground truth for multiple `(job_id, ground_truth_label)`
    pairs inside a single DB transaction.
    """
    if not confirmations:
        return []
    gt_by_job = {
        job_id: normalize_ground_truth_label(label)
        for job_id, label in confirmations
    }
    factory = session_factory or SessionLocal
    db = factory()
    try:
        _ensure_claim_outcome_table(db)
        rows = (
            db.query(DetectorClaimOutcome)
            .filter(DetectorClaimOutcome.job_id.in_(list(gt_by_job.keys())))
            .all()
        )
        if not rows:
            return []
        now = datetime.now(timezone.utc)
        updated = [
            _apply_ground_truth_to_row(row, gt_by_job[row.job_id], confirmed_by, now)
            for row in rows
            if row.job_id in gt_by_job
        ]
        db.commit()
        return updated
    except Exception as e:
        print(f"Error confirming batch ground truth: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def fetch_confirmed_claim_outcomes(
    detector_name: str | None = None,
    limit: int | None = None,
    session_factory=None,
) -> list[dict]:
    """
    Fetches confirmed claim outcomes ordered oldest-to-newest so rolling windows
    can take the latest W observations per (detector, condition).
    """
    factory = session_factory or SessionLocal
    db = factory()
    try:
        _ensure_claim_outcome_table(db)
        q = db.query(DetectorClaimOutcome).filter(
            DetectorClaimOutcome.ground_truth_label.isnot(None)
        )
        if detector_name:
            q = q.filter(DetectorClaimOutcome.detector_name == detector_name)
        q = q.order_by(DetectorClaimOutcome.id.asc())
        if limit is not None and limit > 0:
            rows = q.all()[-limit:]
        else:
            rows = q.all()

        results: list[dict] = []
        for r in rows:
            try:
                conds = json.loads(r.condition_tags_json or '["nominal"]')
            except Exception:
                conds = ["nominal"]
            results.append({
                "id": r.id,
                "job_id": r.job_id,
                "session_id": r.session_id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "detector_name": r.detector_name,
                "model_version": r.model_version,
                "modality": r.modality,
                "condition_tags": conds or ["nominal"],
                "original_polarity": r.original_polarity,
                "original_confidence": r.original_confidence,
                "accepted_confidence": r.accepted_confidence,
                "weight_assigned": r.weight_assigned,
                "judge_verdict": r.judge_verdict,
                "overruled_by_judge": bool(r.overruled_by_judge),
                "discount_reason": r.discount_reason,
                "ground_truth_label": r.ground_truth_label,
                "detector_was_wrong": r.detector_was_wrong,
                "confirmed_overrule": bool(r.confirmed_overrule),
                "judge_was_correct": r.judge_was_correct,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
            })
        return results
    finally:
        db.close()