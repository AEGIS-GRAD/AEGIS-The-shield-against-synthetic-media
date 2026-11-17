"""Model weight SHA-256 verification and safe checkpoint loading utilities."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().with_name("weights_sha256.json")


class ModelIntegrityError(RuntimeError):
    """Raised when a model checkpoint fails SHA-256 verification or safe deserialization."""


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Computes lowercase hex SHA-256 digest of a file using streaming reads."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ModelIntegrityError(f"Weight artifact not found: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def load_weights_manifest(manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    """Loads the canonical model weight SHA-256 registry."""
    target = Path(manifest_path) if manifest_path is not None else DEFAULT_MANIFEST_PATH
    if not target.is_file():
        raise ModelIntegrityError(f"Weights manifest not found: {target}")
    data = json.loads(target.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ModelIntegrityError(f"Invalid weights manifest structure in {target}")
    return artifacts


def verify_file_sha256(path: Path, expected_sha256: str) -> str:
    """Verifies a file's SHA-256 matches `expected_sha256`; raises ModelIntegrityError on mismatch."""
    expected = expected_sha256.strip().lower()
    if len(expected) != 64:
        raise ModelIntegrityError(f"Invalid SHA-256 digest format: {expected_sha256!r}")
    actual = compute_sha256(path)
    if actual != expected:
        raise ModelIntegrityError(
            f"SHA-256 mismatch for {path}: expected {expected}, got {actual}"
        )
    return actual


def verify_registered_artifact(
    artifact_key: str,
    file_path: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    require_exists: bool = True,
) -> Optional[str]:
    """Verifies a local file against its registered digest in `weights_sha256.json`."""
    artifacts = load_weights_manifest(manifest_path)
    if artifact_key not in artifacts:
        raise ModelIntegrityError(f"Artifact {artifact_key!r} is not registered in weights manifest")
    entry = artifacts[artifact_key]
    target = Path(file_path) if file_path is not None else (REPO_ROOT / artifact_key)
    if not target.exists():
        if require_exists:
            raise ModelIntegrityError(f"Registered artifact missing on disk: {target}")
        return None
    return verify_file_sha256(target, entry["sha256"])


def safe_torch_load(
    path: Path,
    map_location: Any = "cpu",
    expected_sha256: Optional[str] = None,
    allowed_globals: Optional[Sequence[Any]] = None,
) -> Any:
    """Loads a PyTorch checkpoint strictly with `weights_only=True` and optional SHA-256 check."""
    import torch

    target = Path(path)
    if expected_sha256:
        verify_file_sha256(target, expected_sha256)

    ctx = (
        torch.serialization.safe_globals(list(allowed_globals))
        if allowed_globals and hasattr(torch.serialization, "safe_globals")
        else nullcontext()
    )
    try:
        with ctx:
            return torch.load(str(target), map_location=map_location, weights_only=True)
    except Exception as exc:
        raise ModelIntegrityError(
            f"Unsafe or corrupt checkpoint rejected under weights_only=True at {target}: {exc}"
        ) from exc


def get_expected_sha256(artifact_key: str, env_override: Optional[str] = None) -> Optional[str]:
    """Returns env override digest or manifest digest when `AEGIS_STRICT_WEIGHT_HASH` allows."""
    if env_override:
        val = os.getenv(env_override, "").strip().lower()
        if val:
            return val
    try:
        artifacts = load_weights_manifest()
        entry = artifacts.get(artifact_key)
        return entry.get("sha256") if isinstance(entry, dict) else None
    except Exception:
        return None
