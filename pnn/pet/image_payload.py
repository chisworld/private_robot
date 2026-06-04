"""截图 → base64 载荷（供识图 / Agent 使用）。"""

from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QIODevice, Qt, QMimeData
from PySide6.QtGui import QImage


def qimage_to_payload(img: QImage, *, max_side: int = 1600) -> tuple[str, str]:
    if img.isNull():
        return "", ""
    work = img.convertToFormat(QImage.Format.Format_RGBA8888)
    if max(work.width(), work.height()) > max_side:
        work = work.scaled(
            max_side,
            max_side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not work.save(buf, "PNG"):
        return "", ""
    b64 = base64.b64encode(bytes(buf.data())).decode("ascii")
    return b64, "image/png"


def _image_from_mime_data(mime: QMimeData) -> QImage | None:
    if mime.hasImage():
        data = mime.imageData()
        if isinstance(data, QImage) and not data.isNull():
            return data
        for fmt in (
            "image/png",
            "image/bmp",
            "image/jpeg",
            "image/webp",
            "application/x-qt-image",
        ):
            raw = mime.data(fmt)
            if raw is not None and not raw.isEmpty():
                img = QImage.fromData(raw)
                if not img.isNull():
                    return img
    if mime.hasUrls():
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            img = QImage(url.toLocalFile())
            if not img.isNull():
                return img
    return None


def image_from_clipboard() -> QImage | None:
    from PySide6.QtWidgets import QApplication

    cb = QApplication.clipboard()
    img = cb.image()
    if not img.isNull():
        return img
    return _image_from_mime_data(cb.mimeData())


def image_from_mime(mime: QMimeData) -> QImage | None:
    return _image_from_mime_data(mime)


def mime_has_image(mime: QMimeData) -> bool:
    if mime.hasImage():
        return True
    if mime.hasUrls():
        for url in mime.urls():
            if url.isLocalFile():
                path = url.toLocalFile().lower()
                if path.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
                    return True
    return False
