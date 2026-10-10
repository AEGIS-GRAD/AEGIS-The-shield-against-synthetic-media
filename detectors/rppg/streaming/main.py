"""
rppg streaming service variant.  Run:  uvicorn app.main:app --port 8002
Keeps one StreamingRPPG per session id so several live feeds can be scored at once.
"""
import threading, time
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
try:
    from .streaming import StreamingRPPG
except ImportError:
    from streaming import StreamingRPPG

app = FastAPI(title="AEGIS rPPG (streaming)")
_sessions: Dict[str, StreamingRPPG] = {}
_last_seen: Dict[str, float] = {}
_lock = threading.Lock()
SESSION_TTL = 300.0


class Sample(BaseModel):
    t: float = Field(..., description="frame timestamp in seconds")
    rgb: Optional[List[float]] = Field(None, min_length=3, max_length=3,
                                       description="mean R,G,B of the face ROI; omit if no face")


def _get(sid: str, fps: float = 10.0) -> StreamingRPPG:
    with _lock:
        now = time.time()
        for k in [k for k, v in _last_seen.items() if now - v > SESSION_TTL]:
            _sessions.pop(k, None); _last_seen.pop(k, None)
        if sid not in _sessions:
            _sessions[sid] = StreamingRPPG(fps=fps)
        _last_seen[sid] = now
        return _sessions[sid]


@app.get("/health")
def health():
    return {"status": "healthy", "service": "rppg", "mode": "streaming",
            "sessions": len(_sessions)}


@app.post("/stream/{sid}/sample")
def sample(sid: str, s: Sample, fps: float = 10.0):
    det = _get(sid, fps)
    if s.rgb is None:
        det.notify_no_face(s.t); return det.last.to_dict()
    return det.push(s.t, s.rgb).to_dict()


@app.get("/stream/{sid}/score")
def score(sid: str):
    if sid not in _sessions:
        raise HTTPException(404, "unknown session")
    return _sessions[sid].last.to_dict()


@app.delete("/stream/{sid}")
def reset(sid: str):
    with _lock:
        _sessions.pop(sid, None); _last_seen.pop(sid, None)
    return {"status": "closed"}
