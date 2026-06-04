"""Exit 0 if API is ready for pet startup (used by launch/start_pet.bat)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pnn.core.api_health import is_api_ready_for_pet

raise SystemExit(0 if is_api_ready_for_pet(timeout=0.8) else 1)
