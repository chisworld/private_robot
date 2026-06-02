"""PySide6 OpenGL 控件：live2d-py 渲染 14酱。"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
import live2d.v3 as live2d
from live2d.v3 import StandardParams

# 头部/眼球每帧向目标靠拢的比例（越大越跟手，约 0.35–0.65）
_LOOK_BLEND = 0.52
_ANGLE_RANGE = 30.0
_EYEBALL_RANGE = 1.0

from pnn.pet.console_log import suppress_live2d_log
from pnn.pet.expressions import load_deferred_model_expressions, load_model_expressions
from pnn.pet.paths import (
    DEFAULT_EXPRESSION,
    HIDE_WATERMARK_EXPRESSION,
    MODEL_NEUTRAL_EXPRESSION,
    MODEL_CONTENT_CROP,
    MODEL_DIALOG_HIDE_VALUE,
    MODEL_DIALOG_PARAM_ID,
    MODEL_FILL_FACTOR,
    MODEL_JSON,
    MODEL_TIGHT_CROP,
    WATERMARK_HIDE_VALUE,
    WATERMARK_PARAM_ID,
)

logger = logging.getLogger(__name__)

_framework_inited = False


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
        self._model_json = Path(model_json or MODEL_JSON)
        self._model: live2d.LAppModel | None = None
        self._ready = False
        self._view_ready = False
        self._scale = 1.0
        self._scale_multiplier = max(0.5, scale_multiplier)
        self._content_crop = content_crop
        self._tight_crop = tight_crop
        self._fill_factor = MODEL_FILL_FACTOR
        self._mouth_value = 0.0
        self._transparent = True
        self._expression = MODEL_NEUTRAL_EXPRESSION
        self._expression_applied = ""
        self._expression_ids: list[str] = []
        self._extras_loaded = False
        self.setFormat(_default_gl_format())
        self.setMinimumSize(60, 80)
        self.setMaximumSize(16777215, 16777215)

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

        self._dialog_hide_timer = QTimer(self)
        self._dialog_hide_timer.setInterval(80)
        self._dialog_hide_timer.timeout.connect(self._hide_model_dialog_bubble)

        self._drag_x: float | None = None
        self._drag_y: float | None = None
        self._look_ax = 0.0
        self._look_ay = 0.0
        self._look_ex = 0.0
        self._look_ey = 0.0

    def set_mouth_open(self, value: float) -> None:
        v = max(0.0, min(1.0, value))
        if abs(v - self._mouth_value) < 0.02:
            return
        self._mouth_value = v

    def _hide_body_watermark(self) -> None:
        """隐藏身体上的「免费分享 / 禁止倒卖」等水印字。"""
        if not self._model or not self._ready:
            return
        try:
            self._model.SetParameterValue(WATERMARK_PARAM_ID, WATERMARK_HIDE_VALUE)
        except Exception:
            if HIDE_WATERMARK_EXPRESSION in self._expression_ids:
                try:
                    suppress_live2d_log()
                    self._model.SetExpression(HIDE_WATERMARK_EXPRESSION)
                except Exception as exc:
                    logger.warning("关闭水印: %s", exc)

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
        """默认「我也要死吗」；同时关闭模型 Param37 内置对话框（文案由 Qt 气泡显示）。"""
        if not self._model or not self._ready:
            return
        for face in (DEFAULT_EXPRESSION, "黑脸", "脸红", "笑嘻"):
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

    def set_expression(self, name: str) -> None:
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
        self._scale_multiplier = max(0.5, min(15.0, multiplier))
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
        print(
            f"[pet-live2d] initializeGL {self.width()}x{self.height()} "
            f"dpr={self.devicePixelRatioF():.2f}",
            flush=True,
        )
        try:
            init_live2d_framework()
            live2d.glInit()
            self._model = live2d.LAppModel()
            if not self._model_json.is_file():
                self.load_failed.emit(f"模型不存在: {self._model_json}")
                return
            old_cwd = os.getcwd()
            try:
                os.chdir(self._model_json.parent)
                self._model.LoadModelJson(str(self._model_json.resolve()))
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
                self._ready = True
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
                min(pw / crop_w, ph / crop_h) * self._fill_factor * self._scale_multiplier
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

        self._model.SetParameterValue(StandardParams.ParamMouthOpenY, self._mouth_value)
        self._hide_body_watermark()
        self._hide_model_dialog_bubble()
        self._model.Update()
        self._hide_model_dialog_bubble()
        if self._transparent:
            live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        else:
            live2d.clearBuffer(0.0588, 0.0902, 0.1647, 1.0)
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
        try:
            self._model.SetParameterValue(StandardParams.ParamAngleX, self._look_ax)
            self._model.SetParameterValue(StandardParams.ParamAngleY, self._look_ay)
            self._model.SetParameterValue(StandardParams.ParamEyeBallX, self._look_ex)
            self._model.SetParameterValue(StandardParams.ParamEyeBallY, self._look_ey)
        except Exception:
            pass

    def _on_tick(self) -> None:
        if self._ready:
            self._apply_pointer_tracking()
            self.update()

    def start_loop(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        if not self._dialog_hide_timer.isActive():
            self._dialog_hide_timer.start()

    def stop_loop(self) -> None:
        self._timer.stop()
        self._dialog_hide_timer.stop()

    def mouseMoveEvent(self, event) -> None:
        if self._model and self._ready:
            self.set_pointer_local(event.position().x(), event.position().y())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._model and self._ready:
            try:
                suppress_live2d_log()
                self._model.SetRandomExpression()
            except Exception:
                pass
        super().mousePressEvent(event)

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
        self._expression_applied = ""
        ctx = self.context()
        if ctx is None or not ctx.isValid():
            return
        self.makeCurrent()
        try:
            self.initializeGL()
        finally:
            self.doneCurrent()

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
    live2d.init()
    suppress_live2d_log()
    _framework_inited = True


def dispose_live2d_framework() -> None:
    global _framework_inited
    if not _framework_inited:
        return
    live2d.dispose()
    _framework_inited = False
