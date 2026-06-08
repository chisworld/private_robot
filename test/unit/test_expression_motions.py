"""表情 ↔ motion3 映射（完整表演，如 shrink → Scene1）。"""

from __future__ import annotations

from pathlib import Path

from pnn.pet.gif_motions import discover_expression_motions


def test_risona_shrink_maps_to_scene1() -> None:
    model_dir = Path(__file__).resolve().parents[2] / "live2d" / "里想奈"
    if not model_dir.is_dir():
        return
    mapping = discover_expression_motions(model_dir)
    assert "shrink" in mapping
    stem, duration = mapping["shrink"]
    assert stem == "Scene1"
    assert duration >= 3.0
    assert (model_dir / "Scene1.motion3.json").is_file()
    assert mapping.get("transform shrink") == mapping.get("shrink")


def test_tap_expression_pool_varies() -> None:
    from pnn.pet.live2d_widget import Live2DWidget

    w = Live2DWidget.__new__(Live2DWidget)
    w._expression_ids = ["shrink", "skeleton", "blush", "little bear"]
    w._expr_motions = {"shrink": (0, 3.3)}
    w._wm_expr = "关闭水印"
    w._rebuild_expression_pools()
    picks = {w._pick_tap_expression() for _ in range(40)}
    assert "shrink" in picks
    assert len(picks) >= 3


def test_idle_expression_favors_light_pool() -> None:
    from pnn.pet.live2d_widget import Live2DWidget

    w = Live2DWidget.__new__(Live2DWidget)
    w._expression_ids = ["blush", "bangs", "shrink", "skeleton"]
    w._wm_expr = "关闭水印"
    w._last_idle_expr = ""
    w._rebuild_expression_pools()
    assert "shrink" in w._expr_pool_dramatic
    assert "blush" in w._expr_pool_light
    dramatic_hits = sum(
        1
        for _ in range(100)
        if w._pick_weighted_idle_expression() in w._expr_pool_dramatic
    )
    assert dramatic_hits < 50
