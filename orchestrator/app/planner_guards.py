"""
Planner poisoning guards — Week 11 Cybersecurity Task 2
=======================================================

Red-team findings (``security/docs/poisoning_redteam_log.md``): the planner trusts
Prometheus telemetry on its own, so a spoofed ``up=0`` or a spoofed 60 s p95
latency removes the primary visual detector from the plan, and the poisoned plan
is cached and reused after telemetry recovers. Cheap mitigations:

  PL1 primary protection: a modality's primary detector is never removed on
      Prometheus evidence alone; only first-hand circuit-breaker evidence counts
  PL2 mass-exclusion sanity: if telemetry would remove half or more of the
      eligible detectors at once, telemetry is treated as untrusted
  PL3 no cache poisoning: telemetry-driven exclusions are part of the cache key
      and plans shaped by them are not cached
  PL4 mandatory primary: latency budgeting may not drop the primary detector

Disabled with ``AEGIS_POISONING_GUARDS=0``.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

PRIMARY_BY_MODALITY = {
    "video": "video-classifier",
    "image": "detector_image",
    "text": "detector_text",
    "audio": "aasist",
}
FIRST_HAND_SOURCES = {"circuit_breaker"}


def guards_enabled() -> bool:
    return os.environ.get("AEGIS_POISONING_GUARDS", "1") != "0"


def _source(tel) -> Optional[str]:
    if tel is None:
        return None
    return getattr(tel, "source", None) or (tel.get("source") if isinstance(tel, dict) else None)


def reinstate_unconfirmed(
    modality: str,
    eligible_before: List[dict],
    eligible_after: List[dict],
    excluded_after: List[dict],
    telemetry: Optional[Dict],
) -> Tuple[List[dict], List[dict], List[str], List[str]]:
    """Returns (eligible, excluded, notes, telemetry_excluded_names)."""
    before = {m["detector_name"]: m for m in eligible_before}
    after_names = {m["detector_name"] for m in eligible_after}
    removed = [n for n in before if n not in after_names]
    if not removed:
        return eligible_after, excluded_after, [], []

    notes: List[str] = []
    reinstate = set()
    if len(before) >= 2 and len(removed) * 2 >= len(before):  # PL2
        reinstate = set(removed)
        notes.append(f"PL2: telemetry would remove {len(removed)}/{len(before)} eligible detectors at once "
                     f"({sorted(removed)}); treated as untrusted (mass outage or spoofed metrics).")
    primary = PRIMARY_BY_MODALITY.get((modality or "").lower())
    if primary in removed and _source((telemetry or {}).get(primary)) not in FIRST_HAND_SOURCES:  # PL1
        reinstate.add(primary)
        notes.append(f"PL1: primary detector '{primary}' reported down by Prometheus only; kept in the plan "
                     "(the circuit breaker will fail it fast if it really is down).")

    eligible = list(eligible_after) + [before[n] for n in removed if n in reinstate]
    excluded = [e for e in excluded_after if e.get("detector_name") not in reinstate]
    still_excluded = [n for n in removed if n not in reinstate]
    return eligible, excluded, notes, still_excluded


def ensure_primary(modality: str, detectors: List[str], eligible_ids) -> Tuple[List[str], List[str]]:
    """PL4: latency budgeting must not drop the modality's primary detector."""
    primary = PRIMARY_BY_MODALITY.get((modality or "").lower())
    if primary and primary in eligible_ids and primary not in detectors:
        return detectors + [primary], [f"PL4: primary detector '{primary}' re-added after budget deprioritisation."]
    return detectors, []
