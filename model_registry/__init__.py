"""
AEGIS Model Registry & Promotion Gate
=====================================
Versioned registry for detector checkpoints and calibration artifacts with an
automatic fail-closed promotion gate (integrity, contract/schema tests,
staged evaluation regression check, latency & memory budgets, and atomic
capability manifest updates with rollback support).
"""

from model_registry.gate import GateCheckResult, GateResult, PromotionGate
from model_registry.registry import (
    ModelRegistry,
    PromotionBlockedError,
    RegistryError,
    RegistryValidationError,
)
from model_registry.schema import ENTRY_SCHEMA, REGISTRY_SCHEMA, validate_registry_data

__all__ = [
    "ENTRY_SCHEMA",
    "GateCheckResult",
    "GateResult",
    "ModelRegistry",
    "PromotionBlockedError",
    "PromotionGate",
    "REGISTRY_SCHEMA",
    "RegistryError",
    "RegistryValidationError",
    "validate_registry_data",
]
