from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pnn.core.paths import CONFIG_DIR

MEMORY_CONFIG_PATH = CONFIG_DIR / "memory.json"


@dataclass
class MemoryConfig:
    enabled: bool = True
    top_k: int = 5
    extraction_enabled: bool = True
    extraction_max_tokens: int = 400
    core_card: str = ""
    decay_per_day: float = 0.02
    min_score: float = 0.15
    reinforce_boost: float = 0.25
    diary_enabled: bool = True
    affection_initial: int = 80
    affection_min: int = 0
    affection_max: int = 100
    merge_similar_with_llm: bool = True


def load_memory_config() -> MemoryConfig:
    d = MemoryConfig()
    if not MEMORY_CONFIG_PATH.is_file():
        return d
    try:
        raw = json.loads(MEMORY_CONFIG_PATH.read_text(encoding="utf-8"))
        return MemoryConfig(
            enabled=bool(raw.get("enabled", d.enabled)),
            top_k=max(1, min(20, int(raw.get("top_k", d.top_k)))),
            extraction_enabled=bool(raw.get("extraction_enabled", d.extraction_enabled)),
            extraction_max_tokens=max(
                128, min(1024, int(raw.get("extraction_max_tokens", d.extraction_max_tokens)))
            ),
            core_card=str(raw.get("core_card", d.core_card)),
            decay_per_day=max(0.0, min(0.5, float(raw.get("decay_per_day", d.decay_per_day)))),
            min_score=max(0.01, min(1.0, float(raw.get("min_score", d.min_score)))),
            reinforce_boost=max(0.05, min(1.0, float(raw.get("reinforce_boost", d.reinforce_boost)))),
            diary_enabled=bool(raw.get("diary_enabled", d.diary_enabled)),
            affection_initial=max(0, min(100, int(raw.get("affection_initial", d.affection_initial)))),
            affection_min=max(0, int(raw.get("affection_min", d.affection_min))),
            affection_max=max(1, int(raw.get("affection_max", d.affection_max))),
            merge_similar_with_llm=bool(
                raw.get("merge_similar_with_llm", d.merge_similar_with_llm)
            ),
        )
    except (json.JSONDecodeError, TypeError, ValueError):
        return MemoryConfig()


def save_memory_config(config: MemoryConfig) -> None:
    MEMORY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_CONFIG_PATH.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
