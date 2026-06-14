"""设置页：模型下载链接块（可点击打开浏览器）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pnn.core.model_downloads import ModelDownloadEntry, list_model_downloads


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_model_download_widget(
    category: str,
    *,
    title: str = "模型下载",
    hint: str = "",
) -> QWidget:
    """按 category（asr / tts / llm_local）生成可点击外链的说明块。"""
    wrap = QWidget()
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)

    head = QLabel(title)
    head.setObjectName("sectionHint")
    layout.addWidget(head)

    if hint:
        tip = QLabel(hint)
        tip.setObjectName("sectionHint")
        tip.setWordWrap(True)
        layout.addWidget(tip)

    entries = list_model_downloads(category=category)
    if not entries:
        empty = QLabel("（暂无登记下载地址）")
        empty.setObjectName("sectionHint")
        layout.addWidget(empty)
        return wrap

    for entry in entries:
        layout.addWidget(_entry_label(entry))

    mirror = QLabel(
        f"镜像站可在 .env 设置 HF_ENDPOINT（当前登记页使用 { _escape_html(_hf_hint()) }）。"
    )
    mirror.setObjectName("sectionHint")
    mirror.setWordWrap(True)
    layout.addWidget(mirror)
    return wrap


def _hf_hint() -> str:
    from pnn.core.model_downloads import hf_endpoint

    return hf_endpoint()


def _entry_label(entry: ModelDownloadEntry) -> QLabel:
    parts: list[str] = [
        f"<b>{_escape_html(entry.name)}</b><br/>"
        f"<span style='color:#636366;'>安装路径：{_escape_html(entry.install_path)}</span>"
    ]
    if entry.description:
        parts.append(
            f"<span style='color:#636366;'>{_escape_html(entry.description)}</span>"
        )
    link_bits = [
        f"<a href='{_escape_html(link.url)}'>{_escape_html(link.label)}</a>"
        for link in entry.links
    ]
    if link_bits:
        parts.append(" · ".join(link_bits))
    label = QLabel("<br/>".join(parts))
    label.setObjectName("downloadLinks")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextBrowserInteraction
    )
    return label
