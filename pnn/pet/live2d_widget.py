"""PySide6 OpenGL 控件：live2d-py 渲染 Live2D 模型。"""

from __future__ import annotations

import logging
import math
import os
import random
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from pnn.pet.actions import BODY_ACTION_NAMES, HEAD_ACTION_NAMES, ActionPlayer
from pnn.pet.idle_gestures import build_idle_gesture_pool
from pnn.pet.model_params import discover_parameter_ids, discover_parameter_names
from pnn.pet.ui_constants import clamp_character_scale

if TYPE_CHECKING:
    import live2d.v3 as live2d

_live2d_mod: Any = None


def _ld():
    global _live2d_mod
    if _live2d_mod is None:
        import live2d.v3 as live2d

        _live2d_mod = live2d
    return _live2d_mod

# 头部/眼球每帧向目标靠拢的比例（越大越跟手，约 0.35–0.65）
_LOOK_BLEND = 0.52
_ANGLE_RANGE = 30.0
_EYEBALL_RANGE = 1.0

from pnn.pet.console_log import suppress_live2d_log
from pnn.pet.expressions import load_deferred_model_expressions, load_model_expressions
from pnn.pet.paths import (
    MODEL_CONTENT_CROP,
    MODEL_DIALOG_HIDE_VALUE,
    MODEL_DIALOG_PARAM_ID,
    MODEL_FILL_FACTOR,
    MODEL_TIGHT_CROP,
    _discover_watermark_settings,
)

logger = logging.getLogger(__name__)

_framework_inited = False


class _NoRepeatPicker:
    """从池子里随机抽取，用尽一轮后再洗牌，避免连续重复。"""

    def __init__(self) -> None:
        self._source: list[str] = []
        self._pool: list[str] = []

    def reset(self, items: list[str]) -> None:
        uniq: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = (item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(key)
        self._source = uniq
        self._pool = []

    def pick(self) -> str:
        if not self._source:
            return ""
        if not self._pool:
            self._pool = list(self._source)
            random.shuffle(self._pool)
        return self._pool.pop()


def _default_gl_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
    fmt.setAlphaBufferSize(8)
    fmt.setDepthBufferSize(24)
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    return fmt


def configure_opengl_app() -> None:
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if sys.platform == "win32":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    QSurfaceFormat.setDefaultFormat(_default_gl_format())


class Live2DWidget(QOpenGLWidget):
    load_failed = Signal(str)
    load_succeeded = Signal()

    def __init__(
        self,
        model_json: Path | None = None,
        *,
        scale_multiplier: float = 1.0,
        content_crop: tuple[float, float, float, float] = MODEL_CONTENT_CROP,
        tight_crop: tuple[float, float, float, float] = MODEL_TIGHT_CROP,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._model_json = Path(model_json) if model_json else None
        self._model: Any = None
        self._ready = False
        self._view_ready = False
        self._scale = 1.0
        self._scale_multiplier = clamp_character_scale(scale_multiplier)
        self._content_crop = content_crop
        self._tight_crop = tight_crop
        self._fill_factor = MODEL_FILL_FACTOR
        self._mouth_value = 0.0
        self._transparent = True
        self._expression = ""
        self._expression_applied = ""
        self._expression_ids: list[str] = []
        self._extras_loaded = False
        self._wm_param_id = "CheekPuff2"
        self._wm_expr = "关闭水印"
        self._wm_value = 1.0
        self._wm_expr_applied = False
        self._assets_ready = False
        self.setFormat(_default_gl_format())
        self.setMinimumSize(60, 80)
        self.setMaximumSize(16777215, 16777215)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)

        self._idle_action_timer = QTimer(self)
        self._idle_action_timer.setInterval(random.randint(18000, 32000))
        self._idle_action_timer.timeout.connect(self._on_idle_action)

        self._body_action_timer = QTimer(self)
        self._body_action_timer.setInterval(random.randint(28000, 48000))
        self._body_action_timer.timeout.connect(self._on_body_idle_action)

        self._idle_gesture_timer = QTimer(self)
        self._idle_gesture_timer.setInterval(random.randint(14000, 26000))
        self._idle_gesture_timer.timeout.connect(self._on_idle_gesture)

        self._idle_motion_timer = QTimer(self)
        self._idle_motion_timer.setInterval(random.randint(120000, 210000))
        self._idle_motion_timer.timeout.connect(self._on_idle_motion)

        # 自然待机表情循环：每隔 25~55s 随机切换一个装饰性表情 2~4s 再还原
        self._idle_expression_timer = QTimer(self)
        self._idle_expression_timer.setInterval(random.randint(35000, 70000))
        self._idle_expression_timer.timeout.connect(self._on_idle_expression)

        # 表情还原定时器（单次）
        self._idle_expr_release_timer = QTimer(self)
        self._idle_expr_release_timer.setSingleShot(True)
        self._idle_expr_release_timer.timeout.connect(self._release_idle_expression)

        # 当前由 idle 表情暂用的表达式名
        self._idle_expr_name: str = ""

        self._dialog_hide_timer = QTimer(self)
        self._dialog_hide_timer.setInterval(500)
        self._dialog_hide_timer.timeout.connect(self._hide_model_dialog_bubble)

        self._drag_x: float | None = None
        self._drag_y: float | None = None
        self._look_ax = 0.0
        self._look_ay = 0.0
        self._look_ex = 0.0
        self._look_ey = 0.0
        self._idle_start = time.time()
        self._playing_speech = False
        self._idle_amplitude = 1.0
        self._action_player = ActionPlayer(self._set_action_param)
        self._motion_active = False
        self._motion_until = 0.0
        self._performance_hold = False
        self._expr_motions: dict[str, tuple[int, float]] = {}
        self._performance_expr = ""
        self._performance_expr_timer = QTimer(self)
        self._performance_expr_timer.setSingleShot(True)
        self._performance_expr_timer.timeout.connect(self._apply_performance_expression)
        self._idle_gesture_pool: list[str] = []
        self._gesture_frames: dict[str, list] = {}
        self._tap_pending = False
        self._expr_pool_light: list[str] = []
        self._expr_pool_dramatic: list[str] = []
        self._expr_pool_tap: list[str] = []
        self._last_idle_expr = ""
        self._tap_expr_picker = _NoRepeatPicker()
        self._tap_action_picker = _NoRepeatPicker()
        self._body_idle_rr: list[str] = []

    # 待机/点击：轻量装饰 vs 变身/道具类（后者降低随机权重）
    _EXPR_DRAMATIC_HINTS: tuple[str, ...] = (
        "shrink",
        "transform shrink",
        "skeleton",
        "sickle",
        "scythe",
        "black",
        "hold the",
        "take a",
        "take the",
        "chest eyes",
    )

    def _rebuild_expression_pools(self) -> None:
        """按模型实际 .exp3 划分轻量/表演表情，避免只剩 shrink 被反复抽到。"""
        from pnn.pet.paths import DEFAULT_EXPRESSION, MODEL_NEUTRAL_EXPRESSION

        exclude = {
            self._wm_expr,
            DEFAULT_EXPRESSION,
            MODEL_NEUTRAL_EXPRESSION,
            "watermark",
            "关闭水印",
        }
        light: list[str] = []
        dramatic: list[str] = []
        for name in self._expression_ids:
            if name in exclude:
                continue
            low = name.lower()
            if any(h in low for h in self._EXPR_DRAMATIC_HINTS):
                dramatic.append(name)
            else:
                light.append(name)
        if not light and not dramatic:
            light = [n for n in self._expression_ids if n not in exclude]
        self._expr_pool_light = light
        self._expr_pool_dramatic = dramatic
        self._expr_pool_tap = light + dramatic
        self._tap_expr_picker.reset(self._expr_pool_tap)
        action_pool = list(BODY_ACTION_NAMES)
        for name in self._idle_gesture_pool:
            if name not in action_pool:
                action_pool.append(name)
        self._tap_action_picker.reset(action_pool)

    def _pick_weighted_idle_expression(self) -> str:
        light = self._expr_pool_light
        dramatic = self._expr_pool_dramatic
        if not light and not dramatic:
            return ""
        pool = dramatic if dramatic and random.random() < 0.2 else (light or dramatic)
        choices = [e for e in pool if e != self._last_idle_expr] or pool
        name = random.choice(choices)
        self._last_idle_expr = name
        return name

    def _pick_tap_expression(self) -> str:
        pool = self._expr_pool_tap
        if not pool:
            pool = [e for e in self._expression_ids if e != self._wm_expr]
        if not pool:
            return ""
        return random.choice(pool)

    def _apply_idle_expression(self, name: str, *, hold_ms: int) -> None:
        """待机随机表情：有 motion3 的走完整表演并保持终态。"""
        if not name or not self._model or not self._ready:
            return
        self._idle_expr_name = name
        if name in self._expr_motions:
            if self.play_expression_performance(
                name, hold_ms=hold_ms, min_total_ms=hold_ms, hold_pose=True
            ):
                return
        try:
            suppress_live2d_log()
            self._model.SetExpression(name)
        except Exception:
            self._idle_expr_name = ""
            return
        self._idle_expr_release_timer.start(hold_ms)

    def _ensure_model_assets(self) -> None:
        if self._assets_ready:
            return
        from pnn.pet.paths import (
            DEFAULT_EXPRESSION,
            HIDE_WATERMARK_EXPRESSION,
            MODEL_JSON,
            MODEL_NEUTRAL_EXPRESSION,
            WATERMARK_HIDE_VALUE,
            WATERMARK_PARAM_ID,
        )

        if self._model_json is None:
            self._model_json = Path(MODEL_JSON)
        if not self._expression:
            self._expression = MODEL_NEUTRAL_EXPRESSION
        self._wm_param_id = WATERMARK_PARAM_ID
        self._wm_expr = HIDE_WATERMARK_EXPRESSION
        self._wm_value = WATERMARK_HIDE_VALUE
        self._assets_ready = True

    def set_mouth_open(self, value: float) -> None:
        v = max(0.0, min(1.0, value))
        if abs(v - self._mouth_value) < 0.02:
            return
        self._mouth_value = v

    def _hide_body_watermark(self) -> None:
        """隐藏身体上的水印字（只改参数；SetExpression 会冲掉当前表情）。"""
        if not self._model or not self._ready:
            return
        try:
            self._model.SetParameterValue(self._wm_param_id, self._wm_value)
        except Exception:
            pass

    def _hide_model_dialog_bubble(self) -> None:
        """关闭模型内置对话框（带尖角；AI 文案仅由独立 Qt 气泡窗显示）。"""
        if not self._model or not self._ready:
            return
        try:
            self._model.SetParameterValue(MODEL_DIALOG_PARAM_ID, MODEL_DIALOG_HIDE_VALUE)
        except Exception:
            pass

    def hide_model_dialog(self) -> None:
        self._hide_model_dialog_bubble()

    def _apply_default_expression(self) -> None:
        """应用默认表情；若无匹配则依序尝试任何已加载的表情。"""
        if not self._model or not self._ready:
            return
        from pnn.pet.paths import DEFAULT_EXPRESSION, MODEL_NEUTRAL_EXPRESSION

        # 优先用模型默认表情名
        for face in (DEFAULT_EXPRESSION, MODEL_NEUTRAL_EXPRESSION):
            if face not in self._expression_ids:
                continue
            try:
                suppress_live2d_log()
                self._model.SetExpression(face)
                self._expression = face
                self._expression_applied = face
                self._hide_body_watermark()
                self._hide_model_dialog_bubble()
                return
            except Exception:
                continue
        # 模型没有同名表情时尝试任意已加载表情
        for face in self._expression_ids:
            try:
                suppress_live2d_log()
                self._model.SetExpression(face)
                self._expression = face
                self._expression_applied = face
                self._hide_body_watermark()
                self._hide_model_dialog_bubble()
                return
            except Exception:
                continue
        # 连表情都没有，就用模型默认姿态
        self._hide_body_watermark()
        self._hide_model_dialog_bubble()

    def play_expression_performance(
        self,
        expression: str,
        *,
        hold_ms: int = 6000,
        min_total_ms: int | None = None,
        hold_pose: bool = False,
    ) -> bool:
        """播放表情 motion3；hold_pose 为 True 时暂禁待机晃身（不阻断视线跟踪）。"""
        if not self._model or not self._ready:
            return False
        name = (expression or "").strip()
        if not name:
            return False

        self._idle_expr_release_timer.stop()
        self._performance_expr_timer.stop()
        mapping = self._expr_motions.get(name)
        motion_ms = 0
        if mapping is not None:
            idx, duration = mapping
            motion_ms = int(max(0.1, duration) * 1000)
            try:
                self._action_player.stop()
                suppress_live2d_log()
                self._model.StopAllMotions()
                self._model.StartMotion(
                    "ExprMotion",
                    idx,
                    _ld().MotionPriority.NORMAL,
                )
            except Exception as exc:
                logger.warning("StartMotion(ExprMotion,%s): %s", name, exc)
                mapping = None

        if mapping is None:
            self.set_expression(name)
            tail_ms = max(hold_ms, min_total_ms or 0, 3000)
            self._motion_active = True
            self._performance_hold = hold_pose
            self._performance_expr = name if hold_pose else ""
            self._motion_until = time.time() + tail_ms / 1000.0
            if hold_pose:
                self._pause_competing_idle_timers()
                self._idle_expr_release_timer.start(tail_ms)
            return False

        tail_ms = max(hold_ms, 2000)
        if min_total_ms is not None:
            tail_ms = max(tail_ms, min_total_ms - motion_ms)
        total_ms = motion_ms + tail_ms
        self._motion_active = True
        self._performance_hold = hold_pose
        self._performance_expr = name if hold_pose else ""
        self._motion_until = time.time() + total_ms / 1000.0
        if hold_pose:
            self._pause_competing_idle_timers()
        self._performance_expr_timer.start(motion_ms)
        if hold_pose:
            self._idle_expr_release_timer.start(total_ms)
        return True

    def _apply_performance_expression(self) -> None:
        expr = self._performance_expr
        if not expr or not self._performance_hold:
            return
        if self._model and self._ready:
            try:
                suppress_live2d_log()
                self._model.StopAllMotions()
            except Exception:
                pass
        self.set_expression(expr)

    def release_expression_performance(self) -> None:
        """结束当前表情表演（motion3 + 保持），回到默认表情。"""
        self._release_performance()

    def _pause_competing_idle_timers(self) -> None:
        self._idle_action_timer.stop()
        self._body_action_timer.stop()
        self._idle_gesture_timer.stop()
        self._idle_motion_timer.stop()
        self._idle_expression_timer.stop()

    def _resume_competing_idle_timers(self) -> None:
        self._sync_competing_idle_timers()

    def _sync_competing_idle_timers(self) -> None:
        """表演定姿期间暂停随机待机；其余时刻补启被误停的 companion 定时器。"""
        if not self._timer.isActive():
            return
        timers = (
            self._idle_action_timer,
            self._body_action_timer,
            self._idle_gesture_timer,
            self._idle_motion_timer,
            self._idle_expression_timer,
        )
        if self._performance_hold:
            for timer in timers:
                if timer.isActive():
                    timer.stop()
        else:
            for timer in timers:
                if not timer.isActive():
                    timer.start()

    def _heal_stale_performance_state(self) -> None:
        """定姿/release 定时器被意外取消时，避免长期冻结呼吸与随机待机。"""
        if not self._performance_hold:
            return
        if self._idle_expr_release_timer.isActive() or self._performance_expr_timer.isActive():
            return
        if self._motion_until > 0 and time.time() < self._motion_until:
            return
        logger.debug("表演状态过期但未释放，强制还原默认表情")
        self._release_performance()

    def _release_performance(self) -> None:
        self._performance_expr_timer.stop()
        self._idle_expr_release_timer.stop()
        self._performance_expr = ""
        self._performance_hold = False
        self._motion_active = False
        self._motion_until = 0.0
        if self._model and self._ready:
            try:
                suppress_live2d_log()
                self._model.StopAllMotions()
            except Exception:
                pass
        self._apply_default_expression()
        self._resume_competing_idle_timers()

    def set_expression(self, name: str) -> None:
        from pnn.pet.paths import MODEL_NEUTRAL_EXPRESSION

        name = (name or MODEL_NEUTRAL_EXPRESSION).strip()
        if name == self._expression_applied:
            self._hide_body_watermark()
            self._hide_model_dialog_bubble()
            return
        self._expression = name
        if self._model and self._ready:
            try:
                suppress_live2d_log()
                self._model.SetExpression(name)
                self._expression_applied = name
                self._hide_body_watermark()
                self._hide_model_dialog_bubble()
                self._model.Update()
                self._hide_model_dialog_bubble()
            except Exception as exc:
                logger.warning("SetExpression(%s): %s", name, exc)

    def play_gif_motion(self, gif_name: str, expression: str = "") -> None:
        """根据 GIF 名称触发对应的 Live2D 表情或动作。"""
        if not self._model or not self._ready:
            return

        if not expression:
            self._apply_default_expression()
            return

        # 内置动作（bow, nod, shake_head, tilt_head, surprise）
        from pnn.pet.actions import ACTIONS
        if expression in ACTIONS:
            self._action_player.play(expression, min_duration_ms=1800)
            return

        # idle: 回到中性并播放 Idle 动画
        if expression == "idle":
            self._apply_default_expression()
            try:
                motions = self._model.GetMotions()
                idle_list = motions.get("Idle", [])
                if idle_list:
                    import time
                    self._motion_active = True
                    self._motion_until = time.time() + 6.0
            except Exception:
                pass
            return

        # 普通 Live2D 表情（优先完整 motion3 + 保持终态）
        if expression in self._expression_ids:
            if not self.play_expression_performance(
                expression, hold_ms=8000, hold_pose=True
            ):
                self.set_expression(expression)
                self._idle_expr_release_timer.start(8000)
        elif self._action_player.play(expression):
            # 尝试作为内置/注册动作播放
            pass
        else:
            logger.debug("GIF 动作 %s → 未知: %s", gif_name, expression)

    def expression_names(self) -> list[str]:
        return list(self._expression_ids)

    def apply_render_prefs(
        self,
        *,
        fill_percent: float = 135.0,
        crop_shrink_percent: float = 22.0,
    ) -> None:
        from pnn.pet.crop_config import crops_from_prefs, fill_factor_from_prefs

        self._content_crop, self._tight_crop = crops_from_prefs(
            crop_shrink_percent=crop_shrink_percent
        )
        self._fill_factor = fill_factor_from_prefs(fill_percent)
        pw, ph = self._pixel_size()
        if self._model and self._ready and pw >= 8 and ph >= 8:
            self._fit_scale(pw, ph)
            self.update()

    def set_scale_multiplier(self, multiplier: float) -> None:
        self._scale_multiplier = clamp_character_scale(multiplier)
        pw, ph = self._pixel_size()
        if self._model and self._ready and pw >= 8 and ph >= 8:
            self._fit_scale(pw, ph)

    def scale_multiplier(self) -> float:
        return self._scale_multiplier

    def content_crop_fractions(self) -> tuple[float, float, float, float]:
        return self._content_crop

    def canvas_pixel_size(self) -> tuple[float, float]:
        if self._model and self._ready:
            return self._model.GetCanvasSizePixel()
        return 0.0, 0.0

    def content_pixel_size(self) -> tuple[float, float]:
        """全身区域宽高（像素），用于窗口比例。"""
        cw, ch = self.canvas_pixel_size()
        if cw <= 0 or ch <= 0:
            return 0.0, 0.0
        l, t, r, b = self._content_crop
        return cw * (r - l), ch * (b - t)

    def content_aspect(self) -> float:
        """全身区域高/宽，窗口按此比例可避免上下或左右留白。"""
        cw, ch = self.content_pixel_size()
        if cw <= 0:
            return 1.45
        return ch / cw

    def tight_crop_rect_local(self) -> QRect:
        """人物本体在控件内的近似区域（用于命中与描边）。"""
        w, h = self.width(), self.height()
        if w < 4 or h < 4:
            return QRect(0, 0, max(0, w), max(0, h))
        l, t, r, b = self._tight_crop
        return QRect(
            int(w * l),
            int(h * t),
            max(1, int(w * (r - l))),
            max(1, int(h * (b - t))),
        )

    def _pixel_size(self) -> tuple[int, int]:
        dpr = self.devicePixelRatioF()
        return max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr))

    def initializeGL(self) -> None:
        suppress_live2d_log()
        self._ensure_model_assets()
        if self._model is not None:
            try:
                self._model.DestroyRenderer()
            except Exception:
                pass
            self._model = None
        self._ready = False
        self._view_ready = False
        self._expression_ids = []
        self._extras_loaded = False
        self._expression_applied = ""
        print(
            f"[pet-live2d] initializeGL {self.width()}x{self.height()} "
            f"dpr={self.devicePixelRatioF():.2f}",
            flush=True,
        )
        try:
            init_live2d_framework()
            live2d = _ld()
            live2d.glInit()
            self._model = live2d.LAppModel()
            if not self._model_json.is_file():
                self.load_failed.emit(f"模型不存在: {self._model_json}")
                return
            old_cwd = os.getcwd()
            try:
                os.chdir(self._model_json.parent)
                self._model.LoadModelJson(str(self._model_json.resolve()))
                wm_param, wm_expr, wm_val = _discover_watermark_settings(
                    self._model_json.parent
                )
                self._wm_param_id = wm_param
                self._wm_expr = wm_expr
                self._wm_value = wm_val
                suppress_live2d_log()
                self._hide_body_watermark()
                self._hide_model_dialog_bubble()
                loaded = load_model_expressions(
                    self._model, self._model_json.parent, priority_only=True
                )
                self._expression_ids = loaded or []
                self._extras_loaded = False
                QTimer.singleShot(0, self._load_deferred_expressions)
                self._apply_default_expression()
                self._model.SetAutoBlinkEnable(True)
                self._model.SetAutoBreathEnable(True)
                self._ready = True
                self._load_idle_motions()
                self._load_expression_motions()
                self._rebuild_expression_pools()
                self._configure_idle_gestures()
                pw, ph = self._pixel_size()
                if pw >= 8 and ph >= 8:
                    self._model.Resize(pw, ph)
                    self._fit_scale(pw, ph)
                    self._view_ready = True
                cw, ch = self._model.GetCanvasSizePixel()
                cw0, ch0 = self.content_pixel_size()
                print(
                    f"[pet-live2d] 模型已加载 canvas={cw}x{ch} content≈{cw0:.0f}x{ch0:.0f} "
                    f"表情={len(self._expression_ids)} 路径={self._model_json.parent}",
                    flush=True,
                )
                self.load_succeeded.emit()
                self.update()
            finally:
                os.chdir(old_cwd)
        except Exception as exc:
            logger.exception("Live2D 加载失败")
            print(f"[pet-live2d] 加载失败: {exc}", flush=True)
            self.load_failed.emit(str(exc))

    def _fit_scale(self, pw: int, ph: int) -> None:
        if not self._model:
            return
        cw, ch = self._model.GetCanvasSizePixel()
        l, t, r, b = self._tight_crop
        crop_w = cw * (r - l)
        crop_h = ch * (b - t)
        if crop_w > 0 and crop_h > 0:
            self._scale = (
                min(pw / crop_w, ph / crop_h)
                * self._fill_factor
                * self._scale_multiplier
            )
        elif cw > 0 and ch > 0:
            self._scale = min(pw / cw, ph / ch) * self._scale_multiplier
        else:
            self._scale = 1.0 * self._scale_multiplier
        self._model.SetScale(self._scale)

        try:
            ppu = float(self._model.GetPixelsPerUnit())
        except Exception:
            ppu = 1.0
        if ppu <= 0:
            ppu = 1.0
        tl, tt, tr, tb = self._tight_crop
        crop_cx = cw * (tl + tr) * 0.5
        crop_cy = ch * (tt + tb) * 0.5
        off_x = (cw * 0.5 - crop_cx) / ppu
        off_y = (ch * 0.5 - crop_cy) / ppu
        self._model.SetOffset(off_x, off_y)

    def resizeGL(self, w: int, h: int) -> None:
        if not self._model or not self._ready:
            return
        pw, ph = self._pixel_size()
        if pw < 8 or ph < 8:
            return
        self._model.Resize(pw, ph)
        self._fit_scale(pw, ph)
        self._view_ready = True
        self.update()

    def paintGL(self) -> None:
        if not self._model or not self._ready:
            return
        if not self._view_ready:
            pw, ph = self._pixel_size()
            if pw >= 8 and ph >= 8:
                self._model.Resize(pw, ph)
                self._fit_scale(pw, ph)
                self._view_ready = True

        self._model.SetParameterValue(_ld().StandardParams.ParamMouthOpenY, self._mouth_value)
        self._hide_body_watermark()
        self._hide_model_dialog_bubble()
        self._model.Update()
        # 物理 Update 会改写 BodyAngle；关键帧动作须在 Update 之后重写入才可见
        if self._action_player.is_active():
            self._action_player.reapply()
        if self._transparent:
            _ld().clearBuffer(0.0, 0.0, 0.0, 0.0)
        else:
            _ld().clearBuffer(0.0588, 0.0902, 0.1647, 1.0)
        self._model.Draw()

    def set_pointer_local(self, x: float, y: float, *, clamp: bool = True) -> None:
        """Live2D 控件内坐标（逻辑像素），与渲染帧同步驱动 Drag。"""
        dpr = self.devicePixelRatioF()
        pw = max(1, self.width())
        ph = max(1, self.height())
        if clamp:
            x = max(0.0, min(float(pw), x))
            y = max(0.0, min(float(ph), y))
        self._drag_x = x * dpr
        self._drag_y = y * dpr

    def set_pointer_global(self, global_pos: QPoint) -> None:
        """屏幕全局坐标；窗外观鼠时也可转头（映射到控件外会自动夹到最大角度）。"""
        g = global_pos if isinstance(global_pos, QPoint) else QPoint(global_pos)
        local = self.mapFromGlobal(g)
        self.set_pointer_local(local.x(), local.y(), clamp=False)

    def clear_pointer(self) -> None:
        self._drag_x = None
        self._drag_y = None

    def _pointer_targets(self) -> tuple[float, float, float, float]:
        if self._drag_x is None or self._drag_y is None:
            return 0.0, 0.0, 0.0, 0.0
        pw, ph = self._pixel_size()
        if pw < 8 or ph < 8:
            return 0.0, 0.0, 0.0, 0.0
        nx = (self._drag_x / pw - 0.5) * 2.0
        ny = (self._drag_y / ph - 0.5) * 2.0
        nx = max(-1.0, min(1.0, nx))
        ny = max(-1.0, min(1.0, ny))
        return (
            nx * _ANGLE_RANGE,
            -ny * _ANGLE_RANGE,
            nx * _EYEBALL_RANGE,
            -ny * _EYEBALL_RANGE,
        )

    def _apply_pointer_tracking(self) -> None:
        if not self._model or not self._ready:
            return
        if self._drag_x is not None and self._drag_y is not None:
            self._model.Drag(self._drag_x, self._drag_y)
            tax, tay, tex, tey = self._pointer_targets()
            b = _LOOK_BLEND
            self._look_ax += (tax - self._look_ax) * b
            self._look_ay += (tay - self._look_ay) * b
            self._look_ex += (tex - self._look_ex) * b
            self._look_ey += (tey - self._look_ey) * b
        else:
            b = _LOOK_BLEND * 0.65
            self._look_ax *= 1.0 - b
            self._look_ay *= 1.0 - b
            self._look_ex *= 1.0 - b
            self._look_ey *= 1.0 - b
        overridden = self._action_player.active_param_set()
        try:
            if "ParamAngleX" not in overridden:
                self._model.SetParameterValue(_ld().StandardParams.ParamAngleX, self._look_ax)
            if "ParamAngleY" not in overridden:
                self._model.SetParameterValue(_ld().StandardParams.ParamAngleY, self._look_ay)
            self._model.SetParameterValue(_ld().StandardParams.ParamEyeBallX, self._look_ex)
            self._model.SetParameterValue(_ld().StandardParams.ParamEyeBallY, self._look_ey)
        except Exception:
            pass

    def _apply_idle_motion(self) -> None:
        if not self._model or not self._ready:
            return
        if self._motion_active or self._action_player.is_active() or self._performance_hold:
            return
        amp = self._idle_amplitude
        if amp <= 0.01:
            return
        overridden = self._action_player.active_param_set()
        t = time.time() - self._idle_start
        body_x = (
            math.sin(t * 0.45 + 1.2) * 16.0
            + math.sin(t * 1.3 + 2.7) * 3.0
        ) * amp
        body_z = (
            math.sin(t * 0.55 + 3.5) * 5.0
            + math.sin(t * 1.6 + 0.9) * 1.5
        ) * amp
        body_y = math.sin(t * 0.38 + 5.1) * 2.0 * amp
        quiver_x = math.sin(t * 1.7 + 0.3) * 1.2 * amp
        quiver_y = math.sin(t * 1.9 + 2.1) * 0.9 * amp
        try:
            if "ParamBodyAngleX" not in overridden:
                self._model.SetParameterValue("ParamBodyAngleX", body_x)
            if "ParamBodyAngleZ" not in overridden:
                self._model.SetParameterValue("ParamBodyAngleZ", body_z)
            if "ParamBodyAngleY" not in overridden:
                self._model.SetParameterValue("ParamBodyAngleY", body_y)
            if "ParamAngleX" not in overridden:
                self._model.SetParameterValue(
                    _ld().StandardParams.ParamAngleX, self._look_ax + quiver_x
                )
            if "ParamAngleY" not in overridden:
                self._model.SetParameterValue(
                    _ld().StandardParams.ParamAngleY, self._look_ay + quiver_y
                )
        except Exception:
            pass

    def _load_idle_motions(self) -> None:
        """加载模型目录下待机 .motion3.json（跳过表情专用 motion）。"""
        model_dir = self._model_json.parent
        exclude: set[str] = set()
        try:
            from pnn.pet.gif_motions import discover_expression_motions

            for _expr, (stem, _dur) in discover_expression_motions(model_dir).items():
                exclude.add(stem)
        except Exception:
            pass
        loaded = 0
        for mf in sorted(model_dir.glob("*.motion3.json")):
            if mf.stem in exclude:
                continue
            try:
                self._model.LoadExtraMotion("Idle", str(mf.resolve()))
                loaded += 1
            except Exception:
                logger.warning("无法加载动作文件: %s", mf.name)
        if loaded:
            logger.debug("已加载 %s 个待机 motion3", loaded)

    def _load_expression_motions(self) -> None:
        """为带 motion3 的表情注册 ExprMotion 组（如 shrink → Scene1）。"""
        self._expr_motions = {}
        if not self._model or not self._model_json:
            return
        from pnn.pet.gif_motions import discover_expression_motions

        model_dir = self._model_json.parent
        for expr, (stem, duration) in discover_expression_motions(model_dir).items():
            path = model_dir / f"{stem}.motion3.json"
            if not path.is_file():
                continue
            try:
                idx = self._model.LoadExtraMotion("ExprMotion", str(path.resolve()))
                self._expr_motions[expr] = (idx, duration)
            except Exception:
                logger.warning("无法加载表情动作: %s", path.name)
        if self._expr_motions:
            names = "、".join(sorted(self._expr_motions))
            print(f"[pet-live2d] 表情 motion3: {names}", flush=True)
            logger.debug("表情 motion3 映射: %s", names)

    def _configure_idle_gestures(self) -> None:
        """按当前模型 cdi3 参数注册待机随机动作（前倾/晃身/胸口等）。"""
        if not self._model_json:
            self._idle_gesture_pool = []
            self._action_player.register_actions({})
            return
        available = discover_parameter_ids(self._model_json.parent)
        names = discover_parameter_names(self._model_json.parent)
        pool, gestures = build_idle_gesture_pool(available)
        from pnn.pet.body_actions import build_adaptive_body_actions

        adaptive = build_adaptive_body_actions(available, names)
        merged = {**gestures, **adaptive}
        self._idle_gesture_pool = pool
        self._gesture_frames = gestures
        self._action_player.register_actions(merged)
        names = "、".join(pool) if pool else "无"
        logger.debug("待机随机动作池: %s", names)

    def _schedule_idle_gesture_timer(self) -> None:
        self._idle_gesture_timer.setInterval(random.randint(14000, 26000))

    def _schedule_idle_motion_timer(self) -> None:
        self._idle_motion_timer.setInterval(random.randint(120000, 210000))

    def _on_idle_gesture(self) -> None:
        """每隔约 14~26 秒随机播放一次参数关键帧动作。"""
        self._schedule_idle_gesture_timer()
        if not self._model or not self._ready:
            return
        if (
            self._playing_speech
            or self._action_player.is_active()
            or self._motion_active
            or self._performance_hold
            or self._idle_amplitude <= 0.01
            or not self._idle_gesture_pool
        ):
            return
        name = random.choice(self._idle_gesture_pool)
        if self._action_player.play(name, amplitude=self._idle_amplitude):
            logger.debug("待机动作: %s", name)

    def _on_idle_motion(self) -> None:
        """每隔约 2~3.5 分钟随机播放模型自带 .motion3 待机动作。"""
        self._schedule_idle_motion_timer()
        if not self._model or not self._ready:
            return
        if self._playing_speech or self._action_player.is_active() or self._performance_hold:
            return
        try:
            suppress_live2d_log()
            motions = self._model.GetMotions()
            idle_motions = motions.get("Idle", [])
            if not idle_motions:
                return
            self._model.StopAllMotions()
            self._model.StartRandomMotion("Idle", _ld().MotionPriority.IDLE)
            self._motion_active = True
            self._motion_until = time.time() + 6.0
        except Exception:
            self._motion_active = False
            self._motion_until = 0.0

    def _tick_motion_active(self) -> None:
        if not self._motion_active or self._motion_until <= 0:
            return
        if time.time() < self._motion_until:
            return
        if self._performance_hold:
            self._release_performance()
        else:
            self._motion_active = False
            self._motion_until = 0.0
            self._resume_competing_idle_timers()

    def _can_play_idle_motion(self) -> bool:
        if not self._model or not self._ready:
            return False
        if self._playing_speech or self._motion_active or self._action_player.is_active():
            return False
        if self._performance_hold:
            return False
        return True

    def _play_body_action(self, name: str) -> bool:
        if not self._can_play_idle_motion():
            return False
        return self._action_player.play(name, amplitude=self._idle_amplitude)

    def _pick_body_idle_action(self) -> str:
        """整身待机轮播 sit/bow 等，不与 gesture 混池稀释概率。"""
        if not self._body_idle_rr:
            self._body_idle_rr = list(BODY_ACTION_NAMES)
            random.shuffle(self._body_idle_rr)
        name = self._body_idle_rr.pop()
        if not self._body_idle_rr:
            self._body_idle_rr = list(BODY_ACTION_NAMES)
            random.shuffle(self._body_idle_rr)
        return name

    def _on_body_idle_action(self) -> None:
        """每隔 28~48 秒随机整身动作：晃、鞠躬等。"""
        self._body_action_timer.setInterval(random.randint(28000, 48000))
        if not self._can_play_idle_motion():
            return
        name = self._pick_body_idle_action()
        if self._action_player.play(name, amplitude=self._idle_amplitude):
            logger.debug("整身待机动作: %s", name)

    def _on_idle_action(self) -> None:
        """每隔 22~38 秒随机头部/轻量动作。"""
        self._idle_action_timer.setInterval(random.randint(22000, 38000))
        if not self._can_play_idle_motion():
            return
        if random.random() >= 0.45:
            return
        pool = list(HEAD_ACTION_NAMES) + ["stretch"]
        name = random.choice(pool)
        if self._action_player.play(name, amplitude=self._idle_amplitude):
            logger.debug("待机动作: %s", name)

    def play_random_body_action(self) -> bool:
        """外部触发：随机播放一次整身动作（晃、鞠躬等）。"""
        pool = list(BODY_ACTION_NAMES)
        if not pool:
            return False
        return self._play_body_action(random.choice(pool))

    def _on_idle_expression(self) -> None:
        """每隔 35~70s 随机装饰/变身类表情，表演类走 motion3。"""
        self._idle_expression_timer.setInterval(random.randint(35000, 70000))
        if not self._model or not self._ready:
            return
        if self._playing_speech or self._motion_active or self._action_player.is_active():
            return
        if self._performance_hold:
            return
        name = self._pick_weighted_idle_expression()
        if not name:
            return
        hold_ms = random.randint(4000, 8000)
        if name in self._expr_motions:
            hold_ms = random.randint(10000, 16000)
        self._apply_idle_expression(name, hold_ms=hold_ms)

    def _pick_tap_body_action(self) -> str:
        pool = list(BODY_ACTION_NAMES)
        for name in self._idle_gesture_pool:
            if name not in pool:
                pool.append(name)
        return random.choice(pool) if pool else ""

    def play_tap_reaction(self) -> None:
        """点击人物：随机切换表情（含变身 motion3）+ 整身动作，各自不重复轮换。"""
        if not self._model or not self._ready or self._playing_speech:
            return
        self._idle_expr_release_timer.stop()
        self._performance_expr_timer.stop()

        expr = self._tap_expr_picker.pick()
        if not expr:
            expr = self._pick_tap_expression()

        action = self._tap_action_picker.pick()
        if not action:
            action = self._pick_tap_body_action()

        played_action = False
        if action:
            played_action = self._play_tap_body_action(action)

        if expr:
            hold_ms = random.randint(10000, 16000)
            if expr in self._expr_motions:
                hold_ms = random.randint(12000, 20000)
            use_motion3 = expr in self._expr_motions and not played_action
            if use_motion3 and self.play_expression_performance(
                expr,
                hold_ms=hold_ms,
                min_total_ms=hold_ms,
                hold_pose=True,
            ):
                logger.debug("点击表情: %s", expr)
                if played_action:
                    logger.debug("点击动作: %s", action)
                return
            self.set_expression(expr)
            self._performance_hold = True
            self._motion_active = True
            self._performance_expr = expr
            self._motion_until = time.time() + hold_ms / 1000.0
            self._pause_competing_idle_timers()
            self._idle_expr_release_timer.start(hold_ms)
            logger.debug("点击表情(静态): %s", expr)
        elif played_action:
            logger.debug("点击动作: %s", action)

    def _play_tap_body_action(self, name: str) -> bool:
        if not self._model or not self._ready or self._playing_speech:
            return False
        if self._motion_active and self._performance_hold:
            try:
                self._model.StopAllMotions()
            except Exception:
                pass
            self._motion_active = False
            self._performance_hold = False
            self._performance_expr = ""
            self._resume_competing_idle_timers()
        return self._action_player.play(
            name,
            amplitude=max(1.0, self._idle_amplitude),
        )

    def _release_idle_expression(self) -> None:
        """还原空闲表情到中性。"""
        self._idle_expr_name = ""
        if self._performance_hold:
            self._release_performance()
        else:
            self._apply_default_expression()

    def _set_action_param(self, param: str, value: float) -> None:
        try:
            if self._model:
                self._model.SetParameterValue(param, value)
        except Exception:
            pass

    def perform_action(self, name: str, *, min_duration_ms: int | None = None) -> None:
        self._performance_expr_timer.stop()
        self._idle_expr_release_timer.stop()
        self._performance_expr = ""
        self._performance_hold = False
        try:
            if self._model:
                self._model.StopAllMotions()
                self._motion_active = False
                self._motion_until = 0.0
        except Exception:
            pass
        from pnn.pet.actions import resolve_action_min_duration_ms

        self._action_player.play(
            name,
            amplitude=self._idle_amplitude,
            min_duration_ms=resolve_action_min_duration_ms(
                name,
                override=min_duration_ms,
            ),
        )
        self._sync_competing_idle_timers()

    def set_idle_amplitude(self, value: float) -> None:
        self._idle_amplitude = max(0.0, min(3.0, float(value)))

    def set_playing_speech(self, playing: bool) -> None:
        self._playing_speech = bool(playing)
        if playing:
            if self._timer.interval() != 16:
                self._timer.setInterval(16)
        elif self._timer.interval() != 33:
            self._timer.setInterval(33)
        if not playing:
            self._idle_action_timer.setInterval(random.randint(22000, 38000))
            self._body_action_timer.setInterval(random.randint(28000, 48000))

    def _on_tick(self) -> None:
        if self._ready:
            self._tick_motion_active()
            self._heal_stale_performance_state()
            self._action_player.tick()
            active = self._action_player.is_active()
            target_iv = 16 if (active or self._playing_speech) else 33
            if self._timer.interval() != target_iv:
                self._timer.setInterval(target_iv)
            self._apply_pointer_tracking()
            self._apply_idle_motion()
            self._sync_competing_idle_timers()
            self.update()

    def start_loop(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        if not self._dialog_hide_timer.isActive():
            self._dialog_hide_timer.start()
        if not self._idle_action_timer.isActive():
            self._idle_action_timer.start()
        if not self._body_action_timer.isActive():
            self._body_action_timer.start()
        if not self._idle_gesture_timer.isActive():
            self._idle_gesture_timer.start()
        if not self._idle_motion_timer.isActive():
            self._idle_motion_timer.start()
        if not self._idle_expression_timer.isActive():
            self._idle_expression_timer.start()

    def stop_loop(self) -> None:
        self._timer.stop()
        self._dialog_hide_timer.stop()
        self._idle_action_timer.stop()
        self._body_action_timer.stop()
        self._idle_gesture_timer.stop()
        self._idle_motion_timer.stop()
        self._idle_expression_timer.stop()

    def _character_parent(self):
        p = self.parentWidget()
        if p is not None and hasattr(p, "_character_hit_global"):
            return p
        return None

    def mouseMoveEvent(self, event) -> None:
        parent = self._character_parent()
        if parent is not None and getattr(parent, "_drag_start", None) is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                gpos = event.globalPosition().toPoint()
                if hasattr(parent, "_apply_drag"):
                    parent._apply_drag(gpos)
                event.accept()
                return
        if self._model and self._ready:
            self.set_pointer_local(event.position().x(), event.position().y())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            parent = self._character_parent()
            if parent is not None:
                gpos = event.globalPosition().toPoint()
                plocal = parent.mapFromGlobal(gpos)
                if hasattr(parent, "_try_begin_drag"):
                    parent._try_begin_drag(gpos, plocal)
            self._tap_pending = bool(self._model and self._ready)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        parent = self._character_parent()
        was_drag = False
        if parent is not None:
            was_drag = getattr(parent, "_drag_active", False)
            if hasattr(parent, "_end_drag"):
                parent._end_drag()
        if (
            event.button() == Qt.MouseButton.LeftButton
            and getattr(self, "_tap_pending", False)
            and not was_drag
        ):
            self.play_tap_reaction()
        self._tap_pending = False
        super().mouseReleaseEvent(event)

    def _load_deferred_expressions(self) -> None:
        if self._extras_loaded or not self._model or not self._ready:
            return
        try:
            more = load_deferred_model_expressions(self._model, self._model_json.parent)
            seen = set(self._expression_ids)
            for name in more:
                if name not in seen:
                    self._expression_ids.append(name)
                    seen.add(name)
            self._extras_loaded = True
            self._rebuild_expression_pools()
            if more:
                print(
                    f"[pet-live2d] 延后表情 +{len(more)}，共 {len(self._expression_ids)} 个",
                    flush=True,
                )
        except Exception as exc:
            logger.warning("延后表情加载失败: %s", exc)
            self._extras_loaded = True

    def reload_model(self, model_json: Path | None = None) -> None:
        """切换角色包后重新加载 Live2D（需已有 OpenGL 上下文）。"""
        if model_json is not None:
            self._model_json = Path(model_json)
        self.shutdown()
        self._ready = False
        self._view_ready = False
        self._expression_ids = []
        self._extras_loaded = False
        self._expr_pool_light = []
        self._expr_pool_dramatic = []
        self._expr_pool_tap = []
        self._last_idle_expr = ""
        self._tap_expr_picker.reset([])
        self._tap_action_picker.reset([])
        self._body_idle_rr = []
        self._expression_applied = ""
        self._idle_gesture_pool = []
        self._gesture_frames = {}
        self._wm_expr_applied = False
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            return
        self.makeCurrent()
        try:
            self.initializeGL()
        finally:
            self.doneCurrent()

    def _drop_parent(self):
        return self._character_parent()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        parent = self._drop_parent()
        if parent is not None:
            parent.dragEnterEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        parent = self._drop_parent()
        if parent is not None:
            parent.dragMoveEvent(event)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        parent = self._drop_parent()
        if parent is not None:
            parent.dragLeaveEvent(event)
        else:
            super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        parent = self._drop_parent()
        if parent is not None:
            parent.dropEvent(event)
        else:
            event.ignore()

    def shutdown(self) -> None:
        self.stop_loop()
        if self._model:
            try:
                self._model.DestroyRenderer()
            except Exception:
                pass
            self._model = None


def init_live2d_framework() -> None:
    global _framework_inited
    if _framework_inited:
        return
    suppress_live2d_log()
    _ld().init()
    suppress_live2d_log()
    _framework_inited = True


def dispose_live2d_framework() -> None:
    global _framework_inited
    if not _framework_inited:
        return
    _ld().dispose()
    _framework_inited = False
