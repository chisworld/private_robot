"""待机随机动作：按模型参数启用前倾/晃身/胸口晃。"""

from __future__ import annotations

import json
from pathlib import Path

from pnn.pet.idle_gestures import build_idle_gesture_pool
from pnn.pet.model_params import chest_parameter_ids, discover_parameter_ids


def test_build_pool_standard_body(tmp_path: Path) -> None:
    cdi = tmp_path / "test.cdi3.json"
    cdi.write_text(
        json.dumps(
            {
                "Parameters": [
                    {"Id": "ParamBodyAngleX"},
                    {"Id": "ParamBodyAngleZ"},
                ]
            }
        ),
        encoding="utf-8",
    )
    available = discover_parameter_ids(tmp_path)
    pool, gestures = build_idle_gesture_pool(available)
    assert "lean_forward" in pool
    assert "body_sway" in pool
    assert "lean_forward" in gestures
    assert gestures["lean_forward"][1][1] == "ParamBodyAngleZ"


def test_chest_bounce_when_breast_param(tmp_path: Path) -> None:
    available = {"ParamBodyAngleX", "ParamBreastY"}
    chest = chest_parameter_ids(available)
    assert chest == ["ParamBreastY"]
    pool, gestures = build_idle_gesture_pool(available)
    assert "chest_bounce" in pool
    assert gestures["chest_bounce"][0][1] == "ParamBreastY"


def test_no_chest_without_param() -> None:
    pool, _ = build_idle_gesture_pool({"ParamBodyAngleX", "ParamBodyAngleZ"})
    assert "chest_bounce" not in pool
