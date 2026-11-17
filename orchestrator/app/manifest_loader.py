"""
manifest_loader.py — Capability-manifest consumption layer (Task 1)
=====================================================================
Single canonical source for loading and validating the per-detector
capability manifests into the orchestrator's planning context.

Responsibilities
----------------
1. Load every capability_manifests/*.json file by detector name.
2. Validate each manifest against the shared JSON-Schema defined in
   capability_manifests/Schema.py. Raise ManifestValidationError
   on any structural violation so nothing silently enters the planner.
3. Render each manifest (or the full registry) into a plain-text
   summary that the planning LLM can reason over. prompt_builder.py
   owns the full prompt assembly; this module owns the per-manifest text
   representation.

Public API
----------
load_all_manifests()        -> list[dict]
load_manifest(name)         -> dict
validate_manifest(data)     -> None  (raises on failure)
render_manifest_text(m)     -> str
render_registry_text(ms)    -> str

All functions are pure / side-effect-free except the two loaders, which
read the filesystem once.  Results are not cached so that tests can swap
the manifests directory freely.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Schema import — resolve the path so this module works whether it is
# imported from inside the orchestrator container (PYTHONPATH=/app) or run
# from the repo root in a test environment.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # orchestrator/app/<file> -> repo root
_MANIFESTS_DIR_DEFAULT = _REPO_ROOT / "capability_manifests"

# Try to import the shared schema. Support both the package name used
# when capability_manifests/ is on sys.path, and the fallback of inserting
# the dir ourselves so tests work without any extra setup.
try:
    from capability_manifests.Schema import DETECTOR_MANIFEST_SCHEMA  # type: ignore[import]
except Exception:
    try:
        _schema_dir = str(_MANIFESTS_DIR_DEFAULT)
        if _schema_dir not in sys.path:
            sys.path.insert(0, _schema_dir)
        from Schema import DETECTOR_MANIFEST_SCHEMA  # type: ignore[import]
    except Exception:
        # Fallback embedded schema ensures module import never fails regardless of working directory
        _obs_entry_schema = {
            "type": "object",
            "required": ["sample_count", "rolling_reliability", "status"],
            "properties": {
                "sample_count": {"type": "integer", "minimum": 0},
                "correct_count": {"type": "integer", "minimum": 0},
                "wrong_count": {"type": "integer", "minimum": 0},
                "overruled_count": {"type": "integer", "minimum": 0},
                "confirmed_overrule_count": {"type": "integer", "minimum": 0},
                "raw_accuracy": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
                "rolling_reliability": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "confirmed_overrule_rate": {"type": ["number", "null"], "minimum": 0.0, "maximum": 1.0},
                "status": {
                    "type": "string",
                    "enum": ["reliable", "caution", "deprioritize", "insufficient_data"],
                },
                "last_updated": {"type": ["string", "null"]},
            },
        }
        DETECTOR_MANIFEST_SCHEMA = {
            "type": "object",
            "required": [
                "detector_name", "modality", "version", "description",
                "input_constraints", "performance", "known_failure_modes",
                "reliability_notes"
            ],
            "properties": {
                "detector_name": {"type": "string"},
                "modality": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["video", "audio", "image", "text"]}
                },
                "version": {"type": "string"},
                "description": {"type": "string"},
                "input_constraints": {
                    "type": "object",
                    "required": ["requires_audio", "min_duration_seconds", "supported_formats"],
                    "properties": {
                        "requires_audio": {"type": "boolean"},
                        "min_duration_seconds": {"type": "number"},
                        "max_duration_seconds": {"type": ["number", "null"]},
                        "supported_formats": {"type": "array", "items": {"type": "string"}}
                    }
                },
                "performance": {
                    "type": "object",
                    "required": ["avg_latency_ms", "measured_on"],
                    "properties": {
                        "avg_latency_ms": {"type": ["number", "null"]},
                        "p95_latency_ms": {"type": ["number", "null"]},
                        "avg_ram_usage_mb": {"type": ["number", "null"]},
                        "avg_vram_usage_mb": {"type": ["number", "null"]},
                        "measured_on": {"type": "string"}
                    }
                },
                "known_failure_modes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["condition", "effect", "source"],
                        "properties": {
                            "condition": {"type": "string"},
                            "effect": {"type": "string"},
                            "source": {"type": "string"}
                        }
                    }
                },
                "reliability_notes": {"type": "string"},
                "observed_reliability": {
                    "type": "object",
                    "properties": {
                        "updated_at": {"type": ["string", "null"]},
                        "window_size": {"type": "integer", "minimum": 1},
                        "revision": {"type": "integer", "minimum": 0},
                        "overall": _obs_entry_schema,
                        "by_condition": {
                            "type": "object",
                            "additionalProperties": _obs_entry_schema,
                        },
                    },
                },
            }
        }

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "jsonschema is required by manifest_loader — add it to "
        "orchestrator/requirements.txt: jsonschema>=4.0.0"
    ) from exc


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ManifestError(Exception):
    """Base class for all manifest errors."""


class ManifestNotFoundError(ManifestError):
    """Raised when a manifest file cannot be located."""


class ManifestValidationError(ManifestError):
    """Raised when a manifest file fails JSON-Schema validation."""

    def __init__(self, detector_name: str, message: str) -> None:
        self.detector_name = detector_name
        super().__init__(f"[{detector_name}] {message}")


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _manifests_dir() -> Path:
    """Return the capability_manifests directory (env-overridable for tests)."""
    override = os.environ.get("AEGIS_MANIFESTS_DIR")
    if override:
        return Path(override)
    if _MANIFESTS_DIR_DEFAULT.is_dir():
        return _MANIFESTS_DIR_DEFAULT
    for candidate in [
        _REPO_ROOT / "capability_manifests",
        Path(__file__).resolve().parent.parent.parent / "capability_manifests",
        Path("/capability_manifests"),
        Path("/app/capability_manifests"),
    ]:
        if candidate.is_dir():
            return candidate
    return _MANIFESTS_DIR_DEFAULT


def validate_manifest(data: dict) -> None:
    """
    Validate *data* against DETECTOR_MANIFEST_SCHEMA.

    Raises
    ------
    ManifestValidationError
        If the manifest violates the schema.
    """
    try:
        jsonschema.validate(instance=data, schema=DETECTOR_MANIFEST_SCHEMA)
    except jsonschema.exceptions.ValidationError as exc:
        detector = data.get("detector_name", "<unknown>")
        raise ManifestValidationError(detector, exc.message) from exc


def _reliability_overlay_dir(create: bool = False) -> Optional[Path]:
    """
    Optional writable overlay dir for `observed_reliability` when the primary
    manifests directory is mounted read-only (e.g. Docker `:ro` volume).
    """
    override = os.environ.get("AEGIS_RELIABILITY_OVERLAY_DIR")
    if override:
        p = Path(override)
        if create:
            p.mkdir(parents=True, exist_ok=True)
        return p

    for candidate in (Path("/app/reliability_overlay"),):
        if candidate.is_dir():
            return candidate
        if create and candidate.parent.is_dir() and os.access(candidate.parent, os.W_OK):
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate

    if create:
        import tempfile
        p = Path(tempfile.gettempdir()) / "aegis_reliability_overlay"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return None


def _load_single_file(path: Path) -> dict:
    """Load, parse, and validate one manifest file.  Returns the dict."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Malformed JSON in {path}: {exc}") from exc

    overlay_dir = _reliability_overlay_dir()
    if overlay_dir is not None:
        overlay_path = overlay_dir / path.name
        if overlay_path.is_file():
            try:
                with open(overlay_path, "r", encoding="utf-8") as ofh:
                    overlay_data = json.load(ofh)
                if isinstance(overlay_data, dict) and "observed_reliability" in overlay_data:
                    base_rev = int((data.get("observed_reliability") or {}).get("revision", 0))
                    ov_rev = int((overlay_data.get("observed_reliability") or {}).get("revision", 0))
                    if ov_rev >= base_rev:
                        data["observed_reliability"] = overlay_data["observed_reliability"]
            except Exception:
                pass

    validate_manifest(data)
    return data


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_all_manifests(manifests_dir: Optional[Path] = None) -> list[dict]:
    """
    Load and validate every *.json file in manifests_dir.

    Parameters
    ----------
    manifests_dir:
        Override the default capability_manifests/ directory.
        Useful in tests; normally leave as None.

    Returns
    -------
    list[dict]
        Validated manifest dicts, sorted by detector_name for
        deterministic ordering.

    Raises
    ------
    ManifestError
        If no manifests are found.
    ManifestValidationError
        If any manifest fails schema validation.
    """
    directory = manifests_dir or _manifests_dir()
    json_files = sorted(directory.glob("*.json"))

    if not json_files:
        raise ManifestError(f"No manifest JSON files found in {directory}")

    manifests: list[dict] = []
    for path in json_files:
        manifests.append(_load_single_file(path))

    # Sort by detector_name so the order is stable regardless of filesystem
    manifests.sort(key=lambda m: m["detector_name"])
    return manifests


def load_manifest(detector_name: str, manifests_dir: Optional[Path] = None) -> dict:
    """
    Load and validate the manifest for a single detector by name.

    Parameters
    ----------
    detector_name:
        The detector_name field value, e.g. "rppg" or "video-classifier".
        This must match the filename stem (rppg.json, video-classifier.json).
    manifests_dir:
        Override the default directory (useful in tests).

    Raises
    ------
    ManifestNotFoundError
        If the file does not exist.
    ManifestValidationError
        If the file fails schema validation.
    """
    directory = manifests_dir or _manifests_dir()
    path = directory / f"{detector_name}.json"

    if not path.exists():
        raise ManifestNotFoundError(
            f"No manifest file found for detector '{detector_name}' at {path}"
        )

    return _load_single_file(path)


# ---------------------------------------------------------------------------
# Text rendering (LLM-facing)
# ---------------------------------------------------------------------------

def _render_failure_modes(modes: list[dict]) -> str:
    """Format the known_failure_modes list as a bullet-point string."""
    if not modes:
        return "  (none documented)"
    lines = []
    for m in modes:
        condition = m.get("condition", "?")
        effect = m.get("effect", "?")
        source = m.get("source", "")
        source_note = f" [source: {source}]" if source else ""
        lines.append(f"  * IF {condition} -> {effect}{source_note}")
    return "\n".join(lines)


def _render_performance(perf: dict) -> str:
    """Render performance fields, substituting placeholder text for nulls."""
    avg = perf.get("avg_latency_ms")
    p95 = perf.get("p95_latency_ms")
    ram = perf.get("avg_ram_usage_mb")
    vram = perf.get("avg_vram_usage_mb")
    measured_on = perf.get("measured_on", "unknown")

    avg_str = f"{avg/1000:.1f}s" if avg is not None else "pending"
    p95_str = f"{p95/1000:.1f}s" if p95 is not None else "pending"
    ram_str = f"{ram:.0f} MB" if ram is not None else "pending"
    vram_str = f"{vram:.0f} MB" if vram is not None else "pending"

    return (
        f"avg latency: {avg_str}, p95 latency: {p95_str}, "
        f"RAM: {ram_str}, VRAM: {vram_str} "
        f"(measured on: {measured_on})"
    )


def _render_observed_reliability(obs: Optional[dict]) -> str:
    """Format rolling condition-level reliability stats if present on the manifest."""
    if not isinstance(obs, dict):
        return ""
    by_cond = obs.get("by_condition") or {}
    if not by_cond:
        return ""
    parts = []
    for cond in sorted(by_cond.keys()):
        entry = by_cond[cond]
        rel = entry.get("rolling_reliability")
        n = entry.get("sample_count", 0)
        status = entry.get("status", "unknown")
        overruled = entry.get("confirmed_overrule_count", 0)
        rel_str = f"{rel:.2f}" if isinstance(rel, (int, float)) else "?"
        parts.append(f"{cond}={rel_str} [{status}, n={n}, conf_overruled={overruled}]")
    return "  observed_rel    : " + "; ".join(parts)


def render_manifest_text(manifest: dict) -> str:
    """
    Convert one validated manifest dict into a plain-text block that a
    planning LLM can reason over.

    Covers every field the planner needs:
    - What the detector does and which modalities it handles
    - Hard input constraints (format, duration, audio requirement)
    - Observed performance figures (or "pending" where null)
    - All known failure modes with their conditions and effects
    - The reliability notes summary
    - Rolling observed per-condition reliability (when populated by feedback loop)

    Parameters
    ----------
    manifest:
        A validated manifest dict as returned by load_all_manifests()
        or load_manifest().

    Returns
    -------
    str
        Multi-line plain-text block, suitable for direct inclusion in a
        planning prompt.
    """
    name = manifest["detector_name"]
    version = manifest.get("version", "?")
    modalities = ", ".join(manifest.get("modality", []))
    description = manifest.get("description", "")

    constraints = manifest.get("input_constraints", {})
    requires_audio = constraints.get("requires_audio", False)
    min_dur = constraints.get("min_duration_seconds")
    max_dur = constraints.get("max_duration_seconds")
    formats = ", ".join(constraints.get("supported_formats", []))

    dur_str = f">= {min_dur}s" if min_dur is not None else "no minimum"
    if max_dur is not None:
        dur_str += f", <= {max_dur}s"

    perf_str = _render_performance(manifest.get("performance", {}))
    failure_modes_str = _render_failure_modes(manifest.get("known_failure_modes", []))
    reliability_notes = manifest.get("reliability_notes", "")
    observed_line = _render_observed_reliability(manifest.get("observed_reliability"))

    text = (
        f"[{name} v{version}]\n"
        f"  modalities      : {modalities}\n"
        f"  description     : {description}\n"
        f"  requires_audio  : {requires_audio}\n"
        f"  duration        : {dur_str}\n"
        f"  formats         : {formats}\n"
        f"  performance     : {perf_str}\n"
        f"  failure_modes:\n{failure_modes_str}\n"
        f"  reliability     : {reliability_notes}"
    )
    if observed_line:
        text += f"\n{observed_line}"
    return text


def render_registry_text(manifests: list[dict]) -> str:
    """
    Render the full list of manifests as a single text block for the LLM.

    Each manifest is separated by a blank line. The block is prefixed with
    a one-line header so the LLM knows what it is looking at.

    Parameters
    ----------
    manifests:
        List of validated manifest dicts (typically from load_all_manifests()).

    Returns
    -------
    str
        Ready-to-embed text block.
    """
    if not manifests:
        return "No capability manifests loaded."

    header = f"Detector registry — {len(manifests)} detector(s) available:\n"
    body = "\n\n".join(render_manifest_text(m) for m in manifests)
    return header + "\n" + body
