"""
Deterministic eligibility filter — v2 (matches real manifest schema)
=======================================================================
Revised after reading the actual capability_manifests/*.json files
(detector_name, input_constraints, known_failure_modes, reliability_notes —
not the id/input_requirements/cost shape the original design doc sketched).

Important shift from v1: the real manifests do NOT give numeric thresholds
for face visibility or lighting (no min_face_visibility, no min_luminance
field exists anywhere). Those conditions are only described as free text in
`known_failure_modes`. So THIS filter only enforces what the manifests
actually make possible to enforce mechanically:
  - modality match
  - requires_audio vs. has_audio
  - duration bounds
  - file format

Soft conditions (lighting, occlusion, compression) are NOT hard-excluded
here — they are passed to the LLM as `known_failure_modes` /
`reliability_notes` text in the prompt, and the LLM reasons over them.
This matches orchestrator_design.md's own distinction between "eligibility"
(hard/deterministic) and "selection reasoning" (soft/LLM judgment) — the
real manifests just push more of the soft signals into free text than the
original design doc assumed.

Special case: SyncNet's own manifest documents that it already returns
`not_applicable` internally for silent/short/dark/occluded input rather
than erroring. For those conditions we still exclude it in advance (no
point spending a call to get a known not_applicable back), but we quote
the manifest's own wording as the reason, not an invented one.
"""

from typing import Any, Dict, List, Optional

try:
    from reliability_feedback import extract_condition_tags_from_input
except ImportError:  # pragma: no cover
    from orchestrator.app.reliability_feedback import extract_condition_tags_from_input


def check_eligibility(manifest: dict, metadata: dict) -> tuple[bool, Optional[str]]:
    constraints = manifest.get("input_constraints", {})

    # --- modality check ---
    if metadata["modality"] not in manifest.get("modality", []):
        return False, f"modality '{metadata['modality']}' not supported by this detector"

    # --- audio requirement (hard, structural) ---
    if constraints.get("requires_audio") and not metadata.get("has_audio", False):
        return False, "requires_audio=true in manifest; input has no audio track"

    # --- duration bounds (hard, structural) ---
    duration = metadata.get("duration_seconds")
    if duration is not None:
        min_dur = constraints.get("min_duration_seconds")
        if min_dur is not None and duration < min_dur:
            return False, f"clip is {duration}s, manifest requires min_duration_seconds={min_dur}"
        max_dur = constraints.get("max_duration_seconds")
        if max_dur is not None and duration > max_dur:
            return False, f"clip is {duration}s, manifest caps max_duration_seconds={max_dur}"

    # --- format (hard, structural) ---
    supported = constraints.get("supported_formats")
    ext = metadata.get("file_extension")
    if supported and ext is not None:
        if ext not in supported:
            return False, f"format '{ext}' not in supported_formats {supported}"

    # --- severe prerequisite failures documented with fatal_if_violated ---
    cond_rel = manifest.get("condition_reliability") or {}
    severe_dark = cond_rel.get("severe_dark_or_face_lost")
    if isinstance(severe_dark, dict) and severe_dark.get("fatal_if_violated"):
        min_lum = severe_dark.get("min_luminance")
        lum = metadata.get("mean_luminance")
        if min_lum is not None and lum is not None and float(lum) < float(min_lum):
            return False, (
                f"mean_luminance={lum} < {min_lum} (severe_dark_or_face_lost in manifest; "
                "returns not_applicable)"
            )
        if metadata.get("face_detected") is False:
            return False, "face_detected=false (severe_dark_or_face_lost in manifest; returns not_applicable)"

    return True, None


def filter_detectors(manifests: list[dict], metadata: dict) -> tuple[list[dict], list[dict]]:
    """
    Splits manifests into (eligible, excluded).
    excluded entries: {"detector_name": ..., "reason": ...}
    """
    eligible, excluded = [], []
    for manifest in manifests:
        ok, reason = check_eligibility(manifest, metadata)
        if ok:
            eligible.append(manifest)
        else:
            excluded.append({"detector_name": manifest["detector_name"], "reason": reason})
    return eligible, excluded


def apply_telemetry_constraints(
    eligible: list[dict],
    excluded: list[dict],
    telemetry: Optional[dict] = None,
) -> tuple[list[dict], list[dict]]:
    """
    Filters out detectors that are hard-down according to live telemetry
    (e.g., Prometheus reported up=0 or circuit-breaker is OPEN).
    Degraded detectors are KEPT eligible so the LLM planner can reason over
    the latency/cost trade-off.
    """
    if not telemetry:
        return eligible, excluded

    new_eligible = []
    new_excluded = list(excluded)

    for m in eligible:
        name = m["detector_name"]
        tel = telemetry.get(name)
        if tel:
            # tel can be DetectorTelemetry object or dict
            status = getattr(tel, "status", None) or (tel.get("status") if isinstance(tel, dict) else None)
            is_up = getattr(tel, "up", True) if not isinstance(tel, dict) else tel.get("up", True)

            if status == "down" or not is_up:
                new_excluded.append({
                    "detector_name": name,
                    "reason": f"live telemetry: detector is offline/down (up={is_up}, status={status})",
                })
                continue

        new_eligible.append(m)

    return new_eligible, new_excluded


_STATUS_SEVERITY = {
    "deprioritize": 3,
    "caution": 2,
    "reliable": 1,
    "insufficient_data": 0,
    "no_history": 0,
}


def extract_input_condition_tags(metadata: Any) -> List[str]:
    """Returns canonical operating condition tags for an input metadata dict or model."""
    return extract_condition_tags_from_input(metadata)


def assess_manifest_condition_reliability(
    manifest: Dict[str, Any],
    active_conditions: List[str],
) -> Dict[str, Any]:
    """
    Inspects a manifest's `observed_reliability.by_condition` for the current
    input's active operating conditions and returns the most severe status found.
    """
    obs = manifest.get("observed_reliability")
    if not isinstance(obs, dict):
        return {
            "status": "no_history",
            "condition": None,
            "rolling_reliability": None,
            "sample_count": 0,
            "confirmed_overrule_count": 0,
            "revision": 0,
        }

    by_cond = obs.get("by_condition") or {}
    revision = int(obs.get("revision", 0) or 0)
    best_match: Optional[Dict[str, Any]] = None
    best_rank = (-1, 1.0)  # (severity desc, reliability asc)

    for cond in active_conditions:
        entry = by_cond.get(cond)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "insufficient_data"))
        sev = _STATUS_SEVERITY.get(status, 0)
        rel = float(entry.get("rolling_reliability", 1.0))
        rank = (sev, -rel)
        if rank > best_rank:
            best_rank = rank
            best_match = {
                "status": status,
                "condition": cond,
                "rolling_reliability": rel,
                "sample_count": int(entry.get("sample_count", 0)),
                "confirmed_overrule_count": int(entry.get("confirmed_overrule_count", 0)),
                "wrong_count": int(entry.get("wrong_count", 0)),
                "revision": revision,
            }

    if best_match is None:
        return {
            "status": "no_history",
            "condition": None,
            "rolling_reliability": None,
            "sample_count": 0,
            "confirmed_overrule_count": 0,
            "revision": revision,
        }
    return best_match


_CANONICAL_AUTHORITY_TIERS: Dict[str, str] = {
    "video-classifier": "primary",
    "syncnet": "primary",
    "aasist": "primary",
    "detector_image": "primary",
    "image": "primary",
    "detector_text": "primary",
    "rppg": "secondary_proxy",
    "streaming-rppg": "secondary_proxy",
    "fusion": "secondary_proxy",
}


def compute_deprioritization_map(
    eligible: List[Dict[str, Any]],
    active_conditions: List[str],
    require_primary_quorum: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """
    Computes per-detector feedback reliability assessment and whether the detector
    should be deprioritized under `active_conditions`.

    Safety invariant: a detector marked `deprioritize` is ONLY flagged for skipping
    when at least one other eligible detector sharing its modality is NOT
    marked `deprioritize` (so modality coverage never collapses to zero).
    When `require_primary_quorum=True`, decisive spatial/primary detectors
    (`video-classifier`, `detector_image`, `detector_text`, `aasist`) cannot be
    deprioritized based on secondary proxies OR non-spatial cross-modal helpers
    like `syncnet`.
    """
    _NON_SUBSTITUTABLE_PRIMARY = {
        "video-classifier",
        "detector_image",
        "image",
        "detector_text",
        "aasist",
    }
    assessments: Dict[str, Dict[str, Any]] = {}
    for m in eligible:
        name = m["detector_name"]
        info = assess_manifest_condition_reliability(m, active_conditions)
        info["modalities"] = set(m.get("modality", []))
        info["authority_tier"] = str(
            m.get("authority_tier") or _CANONICAL_AUTHORITY_TIERS.get(name, "secondary_proxy")
        )
        info["should_deprioritize"] = False
        assessments[name] = info

    for m in eligible:
        name = m["detector_name"]
        info = assessments[name]
        if info["status"] != "deprioritize":
            continue
        if require_primary_quorum and name in _NON_SUBSTITUTABLE_PRIMARY:
            # Look only for another true non-proxy primary in the same core modality
            # (never substitute video-classifier with secondary rppg or audio-sync syncnet).
            has_peer_primary = any(
                other_name != name
                and assessments[other_name]["status"] != "deprioritize"
                and assessments[other_name]["authority_tier"] == "primary"
                and other_name != "syncnet"
                and bool(info["modalities"] & assessments[other_name]["modalities"])
                for other_name in assessments
            )
            if not has_peer_primary:
                info["quorum_protected"] = True
                continue
        my_mods = info["modalities"]
        my_tier = info["authority_tier"]
        has_reliable_alt = any(
            other_name != name
            and assessments[other_name]["status"] != "deprioritize"
            and bool(my_mods & assessments[other_name]["modalities"])
            and (
                not require_primary_quorum
                or my_tier != "primary"
                or assessments[other_name]["authority_tier"] == "primary"
            )
            for other_name in assessments
        )
        if has_reliable_alt:
            info["should_deprioritize"] = True
        elif require_primary_quorum and my_tier == "primary":
            info["quorum_protected"] = True

    return assessments


def reliability_signature(
    eligible: List[Dict[str, Any]],
    active_conditions: List[str],
) -> str:
    """
    Returns a compact signature of manifest reliability revisions & active statuses
    so planner decision cache invalidates cleanly when manifests update.
    """
    parts = []
    for m in sorted(eligible, key=lambda x: x["detector_name"]):
        info = assess_manifest_condition_reliability(m, active_conditions)
        rev = info.get("revision", 0)
        status = info.get("status", "no_history")
        if rev or status != "no_history":
            parts.append(f"{m['detector_name']}:r{rev}:{status}")
    return "|".join(parts)


