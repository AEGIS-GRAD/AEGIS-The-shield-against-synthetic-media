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


def init_db():
    Base.metadata.create_all(bind=engine)


def log_decision(job_id, input_file, metadata, detectors_called, raw_results, aggregated_score, aggregated_verdict):
    db = SessionLocal()
    try:
        req = RequestLog(
            job_id=job_id,
            input_file=input_file,
            modality=metadata.get("modality", "unknown"),
            has_audio=metadata.get("has_audio", False),
            duration_seconds=metadata.get("duration_seconds", 0.0),
            aggregated_score=aggregated_score,
            aggregated_verdict=aggregated_verdict
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