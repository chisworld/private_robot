"""启动原生 Live2D 桌宠（不依赖 WebEngine / Pixi）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pnn.pet.window import main

if __name__ == "__main__":
    main()
