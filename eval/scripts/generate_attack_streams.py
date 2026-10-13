"""Backward-compatible proxy for the SecDevOps Red-Team Attack Harness.

The canonical implementation has been relocated to security/attacks/generate_attack_streams.py.
This script forwards execution to ensure existing CLI scripts and imports continue working without friction.
"""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SECURITY_ATTACKS_DIR = os.path.join(REPO_ROOT, "security", "attacks")

if SECURITY_ATTACKS_DIR not in sys.path:
    sys.path.insert(0, SECURITY_ATTACKS_DIR)

from generate_attack_streams import *  # noqa: F401, F403
import generate_attack_streams as _canonical

if __name__ == "__main__":
    _canonical.main()
