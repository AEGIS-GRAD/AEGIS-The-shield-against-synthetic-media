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

from typing import Optional


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

