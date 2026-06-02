"""根据用户设置计算 Live2D 裁剪与贴边缩放。"""

from __future__ import annotations

from pnn.pet.paths import MODEL_CONTENT_CROP, MODEL_TIGHT_CROP


def _shrink_crop(
    crop: tuple[float, float, float, float],
    percent: float,
) -> tuple[float, float, float, float]:
    """从四边按比例收紧裁剪框。percent=20 表示每边再收 10% 跨度。"""
    p = max(0.0, min(90.0, percent)) / 100.0
    l, t, r, b = crop
    w, h = r - l, b - t
    if w <= 0 or h <= 0:
        return crop
    dl, dt = w * p * 0.5, h * p * 0.5
    return (
        min(max(0.0, l + dl), 0.49),
        min(max(0.0, t + dt), 0.49),
        max(min(1.0, r - dl), 0.51),
        max(min(1.0, b - dt), 0.51),
    )


def crops_from_prefs(
    *,
    crop_shrink_percent: float = 20.0,
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    content = _shrink_crop(MODEL_CONTENT_CROP, crop_shrink_percent * 0.35)
    tight = _shrink_crop(MODEL_TIGHT_CROP, crop_shrink_percent)
    return content, tight


def fill_factor_from_prefs(fill_percent: float = 135.0) -> float:
    return max(1.0, min(1.65, fill_percent / 100.0))
