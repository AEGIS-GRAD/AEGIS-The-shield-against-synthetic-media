import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_APP_DIR = _REPO_ROOT / "orchestrator" / "app"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_MANIFESTS_DIR = _REPO_ROOT / "capability_manifests"
if str(_MANIFESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_MANIFESTS_DIR))
