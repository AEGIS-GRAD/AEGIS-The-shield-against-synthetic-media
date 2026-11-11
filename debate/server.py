"""
AEGIS Debate & Arbitration Microservice (Week 10 Task 1).

Exposes JudgeAgent over FastAPI so orchestrator <-> judge traffic runs as an
independent mTLS-authenticated node in the service mesh when deployed separately:
  - GET  /health : Readiness / liveness probe (scraped over mTLS in strict mode)
  - POST /judge  : Accepts raw detector responses + operating conditions and
                   returns a validated JudgeReport JSON payload.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    from debate.judge_agent import JudgeAgent
    from debate.schemas import JudgeReport, OperatingConditions
except ImportError:
    from judge_agent import JudgeAgent
    from schemas import JudgeReport, OperatingConditions

_JUDGE_MODE = os.environ.get("AEGIS_JUDGE_MODE", "deterministic")
_judge: Optional[JudgeAgent] = None


def _get_judge() -> JudgeAgent:
    global _judge
    if _judge is None:
        _judge = JudgeAgent(mode=os.environ.get("AEGIS_JUDGE_MODE", _JUDGE_MODE))
    return _judge


class JudgeRequest(BaseModel):
    raw_responses: Dict[str, Optional[Dict[str, Any]]]
    conditions: Optional[OperatingConditions] = None
    job_id: Optional[str] = Field(default=None)


app = FastAPI(
    title="AEGIS Judge Arbitration Service",
    description="Multi-round evidentiary arbitration service over mTLS.",
    version="1.0.0",
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy", "service": "aegis-judge"}


@app.post("/judge", response_model=JudgeReport)
def judge(req: JudgeRequest) -> JudgeReport:
    return _get_judge().judge_file(
        raw_responses=req.raw_responses,
        conditions=req.conditions,
        job_id=req.job_id,
    )

