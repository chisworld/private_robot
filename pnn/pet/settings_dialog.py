"""桌宠设置：ASR / TTS / LLM / 界面。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from dataclasses import replace

from PySide6.QtCore import QDateTime, QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QDateTimeEdit,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pnn.core.env import upsert_env
from pnn.pet.api_client import PetApiClient
from pnn.pet.asr_session import AsrSession
from pnn.pet.color_picker_widget import ColorPickerRow
from pnn.pet.preferences import PetUiPreferences, load_preferences, save_preferences
from pnn.pet.presence.config import PresenceConfig, load_presence_config, save_presence_config
from pnn.pet.ui_constants import (
    CHARACTER_SCALE_MAX,
    CHARACTER_SCALE_MIN,
    CHARACTER_SCALE_SPIN_STEP_PERCENT,
)
from pnn.pet.settings_local import (
    list_character_packs_local,
    list_characters_local,
    list_memories_local,
    load_asr_config_local,
    load_chat_config_local,
    load_mcp_config_local,
    load_mcp_status_local,
    load_memory_config_local,
    load_settings_payload_local,
    load_translate_config_local,
    load_tts_config_local,
)
from pnn.pet.volume_meter_widget import VolumeMeterWidget
from pnn.pet.settings_styles import SETTINGS_DIALOG_QSS
from pnn.llm.vision_client import DASHSCOPE_VL_MODELS

logger = logging.getLogger(__name__)

LLM_PROVIDER_PRESETS: list[tuple[str, str, str]] = [
    ("DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("自定义", "", ""),
]

# DeepSeek 模型 ID 快捷选项（模型 ID 框仍可直接输入其它 ID）
DEEPSEEK_MODEL_PRESETS: list[tuple[str, str]] = [
    ("deepseek-chat", "默认对话"),
    ("deepseek-v4-pro", "V4 Pro"),
    ("deepseek-v4-flash", "V4 Flash"),
]


class _RemoteConfigLoader(QThread):
    """在后台拉取 LLM/TTS/ASR 配置，避免阻塞设置窗主线程。"""

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, api: PetApiClient, parent=None) -> None:
        super().__init__(parent)
        self._api = api

    def run(self) -> None:
        from pnn.pet.api_client import SETTINGS_LOAD_TIMEOUT
        from pnn.pet.api_guard import is_api_responsive

        to = SETTINGS_LOAD_TIMEOUT
        if not is_api_responsive(timeout=3.0):
            try:
                self.finished_ok.emit(load_settings_payload_local())
                return
            except Exception as exc:
                self.failed.emit(
                    f"本地 API (8765) 无响应，且本地配置读取失败: {exc}"
                )
                return

        warnings: list[str] = []

        def _load(
            label: str,
            fn,
            *,
            local_fn=None,
            required: bool = False,
            default=None,
        ):
            try:
                return fn()
            except Exception as exc:
                if local_fn is not None:
                    try:
                        logger.info("设置页 %s API 不可用，改用本地 JSON", label)
                        return local_fn()
                    except Exception as local_exc:
                        msg = f"{label}: {exc}（本地读取失败: {local_exc}）"
                else:
                    msg = f"{label}: {exc}"
                logger.warning("设置页远程配置 %s", msg)
                warnings.append(msg)
                if required:
                    raise
                return default

        try:
            chat = _load(
                "LLM",
                lambda: self._api.get_chat_config(timeout=to),
                local_fn=load_chat_config_local,
                required=True,
            )
            packs = _load(
                "角色包",
                lambda: self._api.list_character_packs(timeout=to),
                local_fn=list_character_packs_local,
                default=[],
            )
            if not packs:
                packs = _load(
                    "角色",
                    lambda: self._api.list_characters(timeout=to),
                    local_fn=list_characters_local,
                    default=[],
                )
            payload = {
                "chat": chat,
                "characters": packs,
                "packs": packs,
                "memory": _load(
                    "记忆",
                    lambda: self._api.get_memory_config(timeout=to),
                    local_fn=load_memory_config_local,
                    default={},
                ),
                "memories": _load(
                    "记忆列表",
                    lambda: self._api.list_memories(80, timeout=to),
                    local_fn=lambda: list_memories_local(80),
                    default=[],
                ),
                "translate": _load(
                    "翻译",
                    lambda: self._api.get_translate_config(timeout=to),
                    local_fn=load_translate_config_local,
                    default={},
                ),
                "tts": _load(
                    "TTS",
                    lambda: self._api.get_tts_config(
                        fresh=False, probe=False, timeout=to
                    ),
                    local_fn=load_tts_config_local,
                    default={},
                ),
                "asr": _load(
                    "ASR",
                    lambda: self._api.get_asr_config(timeout=to),
                    local_fn=load_asr_config_local,
                    default={},
                ),
                "mcp": {},
            }
            mcp_cfg = _load(
                "MCP 配置",
                lambda: self._api.get_mcp_config(timeout=to),
                local_fn=load_mcp_config_local,
                default={},
            )
            mcp_st = _load(
                "MCP 状态",
                lambda: self._api.get_mcp_status(timeout=to),
                local_fn=load_mcp_status_local,
                default={},
            )
            payload["mcp"] = {**mcp_cfg, **mcp_st}
            if warnings:
                payload["_load_warnings"] = warnings
            self.finished_ok.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))


class _SaveSettingsWorker(QThread):
    """后台执行保存相关的 HTTP 请求，避免阻塞设置窗主线程。"""

    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, api: PetApiClient, snapshot: dict, parent=None) -> None:
        super().__init__(parent)
        self._api = api
        self._snapshot = snapshot

    def run(self) -> None:
        from pnn.pet.api_client import SETTINGS_SAVE_TIMEOUT

        save_to = SETTINGS_SAVE_TIMEOUT
        snap = self._snapshot
        mcp_note = snap.get("mcp_note")
        mcp_fields = snap.get("mcp_fields")
        mcp_skip = bool(snap.get("mcp_skip"))
        batch_body: dict = {
            "char_id": snap.get("char_id") or "",
            "mcp_skip": mcp_skip,
            "llm": snap["llm"],
            "asr": snap["asr"],
            "memory": snap["memory"],
            "translate": snap["translate"],
        }
        if mcp_fields and not mcp_skip:
            batch_body["mcp"] = mcp_fields
        pack = snap.get("pack")
        char_id = str(snap.get("char_id") or "")
        if pack and char_id:
            batch_body["pack"] = pack
        else:
            batch_body["tts"] = snap["tts"]
        try:
            try:
                result = self._api.save_settings_batch(batch_body, timeout=save_to)
            except RuntimeError as exc:
                if "404" not in str(exc) and "Not Found" not in str(exc):
                    raise
                result = SettingsDialog._save_settings_legacy(
                    self._api, snap, mcp_fields, mcp_note, timeout=save_to
                )
            llm_cfg = result.get("llm") or {}
            if mcp_fields and not mcp_skip and not result.get("mcp_synced"):
                mcp_note = SettingsDialog._sync_mcp_config_to_api(
                    self._api, mcp_fields, mcp_note, timeout=save_to
                )
            done = "设置已保存并生效"
        except Exception as api_exc:
            try:
                from pnn.settings.batch_save import apply_settings_batch

                result = apply_settings_batch(batch_body)
                llm_cfg = result.get("llm") or {}
                done = (
                    "API 保存超时或不可用，已写入本地配置并生效。"
                    f"\n（{SettingsDialog._format_save_error(api_exc)}）"
                )
            except Exception as local_exc:
                self.failed.emit(SettingsDialog._format_save_error(local_exc))
                return
        if mcp_note:
            done += f"\n\n⚠ {mcp_note}"
        if not llm_cfg.get("configured"):
            done += (
                "\n\n提示：尚未配置 LLM API Key，对话会失败。"
                "请在「LLM」页填写 Key，或在项目根 .env 设置 DEEPSEEK_API_KEY。"
            )
        self.finished_ok.emit(done)


class _McpToolsLoader(QThread):
    """后台连接 MCP 并拉取工具列表。"""

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, api: PetApiClient, *, connect: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._api = api
        self._connect = connect

    def run(self) -> None:
        try:
            status = self._api.get_mcp_status()
            tools_data = self._api.list_mcp_tools(connect=self._connect)
            self.finished_ok.emit({"status": status, "tools": tools_data})
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(
        self,
        api: PetApiClient,
        *,
        on_ui_saved: Callable[[PetUiPreferences], None] | None = None,
        on_character_applied: Callable[[], None] | None = None,
        on_presence_saved: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._on_ui_saved = on_ui_saved
        self._on_character_applied = on_character_applied
        self._on_presence_saved = on_presence_saved
        self._active_pack_id = ""
        self._save_worker: _SaveSettingsWorker | None = None
        self._save_btn: QPushButton | None = None
        self.setWindowTitle("桌宠设置")
        self.setMinimumSize(440, 520)
        self.resize(480, 580)
        self.setStyleSheet(SETTINGS_DIALOG_QSS)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint,
        )

        title = QLabel("桌宠设置")
        title.setObjectName("dialogTitle")
        self._fullscreen_btn = QPushButton("全屏")
        self._fullscreen_btn.setObjectName("ghostBtn")
        self._fullscreen_btn.setToolTip("最大化设置窗口（再次点击还原）")
        self._fullscreen_btn.clicked.connect(self._toggle_settings_fullscreen)
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._fullscreen_btn)

        tabs = QTabWidget()
        tabs.addTab(self._build_ui_tab(), "界面")
        tabs.addTab(self._build_character_tab(), "角色")
        tabs.addTab(self._build_memory_tab(), "记忆")
        tabs.addTab(self._build_presence_tab(), "日程与提醒")
        tabs.addTab(self._build_llm_tab(), "LLM")
        tabs.addTab(self._build_mcp_tab(), "MCP")
        tabs.addTab(self._build_tts_tab(), "TTS")
        tabs.addTab(self._build_asr_tab(), "ASR")
        self._tabs = tabs
        tabs.currentChanged.connect(self._on_tab_changed)

        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primaryBtn")
        self._save_btn = save_btn
        save_btn.clicked.connect(self._save_all)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryBtn")
        close_btn.setToolTip("关闭并自动保存「界面」页的对话窗/气泡设置")
        close_btn.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close_btn)
        footer.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        self._load_status = QLabel("")
        self._load_status.setObjectName("sectionHint")
        self._load_status.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(self._load_status)
        layout.addWidget(tabs, stretch=1)
        layout.addLayout(footer)

        self._remote_loader: _RemoteConfigLoader | None = None
        self._mcp_tools_loader: _McpToolsLoader | None = None
        self._mcp_server_checks: dict[str, QCheckBox] = {}
        self._mcp_save_baseline: dict | None = None
        self._asr_probe = AsrSession(self._api, parent=self)
        self._asr_probe.level_changed.connect(self._on_probe_level)
        self._asr_probe.error_occurred.connect(self._on_probe_error)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_fullscreen_button()
        self._reload_ui_from_disk()
        self._load_presence_fields()
        self._schedule_remote_load()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_fullscreen_button()

    def _sync_fullscreen_button(self) -> None:
        if not hasattr(self, "_fullscreen_btn"):
            return
        self._fullscreen_btn.setText("还原" if self.isMaximized() else "全屏")

    def _reload_ui_from_disk(self) -> None:
        """再次打开设置时从本地 JSON 刷新界面项（对话框/气泡颜色等）。"""
        if not hasattr(self, "_chat_color"):
            return
        ui = load_preferences()
        char_id = self._pack_combo.currentData() if hasattr(self, "_pack_combo") else None
        if char_id:
            ui = ui.get_for_character(str(char_id))
        self._chat_color.set_hex_color(ui.chat_text_color)
        self._chat_bg_color.set_hex_color(ui.chat_bg_color)
        self._chat_bg_transparency.setValue(ui.chat_bg_transparency_percent)
        self._page_interval.setValue(max(1, ui.page_interval_ms // 1000))
        self._bubble_font_size.setValue(ui.bubble_font_size)
        self._bubble_color.set_hex_color(ui.bubble_text_color)
        self._bubble_bg_color.set_hex_color(ui.bubble_bg_color)
        self._bubble_bg_transparency.setValue(ui.bubble_bg_transparency_percent)
        self._stream_bubble.setChecked(ui.stream_bubble_output)
        self._char_scale.setValue(int(ui.character_scale * 100))
        self._fill_percent.setValue(int(ui.fill_percent))
        self._crop_shrink.setValue(int(ui.crop_shrink_percent))
        self._idle_amplitude.setValue(ui.idle_motion_amplitude)
        if hasattr(self, "_tts_voice_on"):
            self._tts_voice_on.setChecked(ui.voice_output_enabled)

    def _schedule_remote_load(self) -> None:
        if self._remote_loader is not None and self._remote_loader.isRunning():
            return
        self._load_status.setText("正在从 API 加载配置…")
        worker = _RemoteConfigLoader(self._api, parent=self)
        worker.finished_ok.connect(self._apply_remote_config)
        worker.failed.connect(self._on_remote_load_failed)
        worker.finished.connect(worker.deleteLater)
        self._remote_loader = worker
        worker.start()

    def _on_remote_load_failed(self, err: str) -> None:
        self._remote_loader = None
        try:
            data = load_settings_payload_local()
            data["_load_warnings"] = [
                f"API 不可用，已改用本地配置：{err}",
            ]
            self._apply_remote_config(data)
            self._load_status.setText(
                f"API 不可用，已加载本地配置。\n{err}"
            )
        except Exception as local_exc:
            self._load_status.setText(
                f"远程配置加载失败：{err}\n本地回退也失败：{local_exc}"
            )

    def closeEvent(self, event) -> None:
        self._stop_asr_test()
        if self._mcp_tools_loader is not None and self._mcp_tools_loader.isRunning():
            self._mcp_tools_loader.wait(3000)
        self._mcp_tools_loader = None
        if self._remote_loader is not None and self._remote_loader.isRunning():
            self._remote_loader.wait(3000)
        self._remote_loader = None
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_asr_test()
        super().reject()

    def accept(self) -> None:
        self._stop_asr_test()
        try:
            self._save_ui_preferences(apply_callback=True)
        except Exception:
            pass
        super().accept()

    def _scroll_tab(self, inner: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    def _form_group(self, title: str, hint: str = "") -> tuple[QGroupBox, QFormLayout]:
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        lay.setSpacing(8)
        if hint:
            tip = QLabel(hint)
            tip.setObjectName("sectionHint")
            tip.setWordWrap(True)
            lay.addWidget(tip)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        lay.addLayout(form)
        return box, form

    def _build_ui_tab(self) -> QWidget:
        ui = load_preferences()
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        g_chat, form_chat = self._form_group(
            "对话窗",
            "可调整文字、背景颜色与背景透明度（0 不透明，100 全透明）。识别文字在输入框。",
        )
        self._chat_color = ColorPickerRow(ui.chat_text_color)
        form_chat.addRow("文字颜色", self._chat_color)
        self._chat_bg_color = ColorPickerRow(ui.chat_bg_color)
        form_chat.addRow("背景颜色", self._chat_bg_color)
        self._chat_bg_transparency = QSpinBox()
        self._chat_bg_transparency.setRange(0, 100)
        self._chat_bg_transparency.setValue(ui.chat_bg_transparency_percent)
        self._chat_bg_transparency.setSuffix(" %")
        self._chat_bg_transparency.setToolTip("0 = 不透明，100 = 完全透明")
        form_chat.addRow("背景透明度", self._chat_bg_transparency)
        self._page_interval = QSpinBox()
        self._page_interval.setRange(1, 15)
        self._page_interval.setValue(max(1, ui.page_interval_ms // 1000))
        self._page_interval.setSuffix(" 秒")
        form_chat.addRow("识别区翻页", self._page_interval)
        outer.addWidget(g_chat)

        g_bubble, form_bubble = self._form_group(
            "AI 气泡窗",
            "可设背景颜色与透明度；建议深灰底 (#333) + 白字。保存后立即生效。",
        )
        self._bubble_font_size = QSpinBox()
        self._bubble_font_size.setRange(10, 36)
        self._bubble_font_size.setValue(ui.bubble_font_size)
        self._bubble_font_size.setSuffix(" px")
        form_bubble.addRow("字号", self._bubble_font_size)
        self._bubble_color = ColorPickerRow(ui.bubble_text_color)
        form_bubble.addRow("文字颜色", self._bubble_color)
        self._bubble_bg_color = ColorPickerRow(ui.bubble_bg_color)
        form_bubble.addRow("背景颜色", self._bubble_bg_color)
        self._bubble_bg_transparency = QSpinBox()
        self._bubble_bg_transparency.setRange(0, 100)
        self._bubble_bg_transparency.setValue(ui.bubble_bg_transparency_percent)
        self._bubble_bg_transparency.setSuffix(" %")
        self._bubble_bg_transparency.setToolTip("0 = 不透明，100 = 完全透明")
        form_bubble.addRow("背景透明度", self._bubble_bg_transparency)
        self._stream_bubble = QCheckBox("流式输出（AI 生成时实时刷新气泡文字）")
        self._stream_bubble.setChecked(ui.stream_bubble_output)
        form_bubble.addRow("", self._stream_bubble)
        outer.addWidget(g_bubble)

        # —— 人物显示 ——
        g_char, form_c = self._form_group(
            "人物显示",
            "人物大小仅缩放模型；拖动人物窗边缘可调整模型框宽高。"
            "贴边与裁剪可减少四周留白。",
        )
        self._char_scale = QSpinBox()
        self._char_scale.setRange(
            int(CHARACTER_SCALE_MIN * 100),
            int(CHARACTER_SCALE_MAX * 100),
        )
        self._char_scale.setSingleStep(CHARACTER_SCALE_SPIN_STEP_PERCENT)
        self._char_scale.setValue(int(ui.character_scale * 100))
        self._char_scale.setSuffix(" %")
        form_c.addRow("人物大小", self._char_scale)
        self._fill_percent = QSpinBox()
        self._fill_percent.setRange(100, 165)
        self._fill_percent.setValue(int(ui.fill_percent))
        self._fill_percent.setSuffix(" %")
        form_c.addRow("贴边缩放", self._fill_percent)
        self._crop_shrink = QSpinBox()
        self._crop_shrink.setRange(0, 90)
        self._crop_shrink.setValue(int(ui.crop_shrink_percent))
        self._crop_shrink.setSuffix(" %")
        form_c.addRow("裁剪收紧", self._crop_shrink)
        self._idle_amplitude = QDoubleSpinBox()
        self._idle_amplitude.setRange(0.0, 3.0)
        self._idle_amplitude.setSingleStep(0.1)
        self._idle_amplitude.setValue(ui.idle_motion_amplitude)
        self._idle_amplitude.setSuffix(" 倍")
        self._idle_amplitude.setToolTip("0 = 静止不动，1.0 = 默认摇摆，3.0 = 最大幅度")
        form_c.addRow("动作幅度", self._idle_amplitude)
        outer.addWidget(g_char)

        outer.addStretch(1)
        return self._scroll_tab(container)

    def _build_llm_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_base, form_base = self._form_group(
            "LLM 基础",
            "连接本地 API（8765）。API Key 可在此填写并写入项目根 .env；留空表示不修改已保存的密钥。",
        )
        self._llm_provider = QComboBox()
        for name, _, _ in LLM_PROVIDER_PRESETS:
            self._llm_provider.addItem(name)
        self._llm_provider.currentIndexChanged.connect(self._on_llm_provider_changed)
        form_base.addRow("大语言模型供应商", self._llm_provider)

        self._llm_base_url = QLineEdit()
        self._llm_base_url.setPlaceholderText("https://api.deepseek.com")
        form_base.addRow("LLM 基础地址", self._llm_base_url)

        self._llm_api_key = QLineEdit()
        self._llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key.setPlaceholderText("未配置时填写 DeepSeek API Key")
        form_base.addRow("LLM API Key", self._llm_api_key)

        self._llm_model = QComboBox()
        self._llm_model.setEditable(True)
        self._llm_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for model_id, hint in DEEPSEEK_MODEL_PRESETS:
            self._llm_model.addItem(model_id)
            idx = self._llm_model.count() - 1
            self._llm_model.setItemData(idx, hint, Qt.ItemDataRole.ToolTipRole)
        if self._llm_model.lineEdit() is not None:
            self._llm_model.lineEdit().setPlaceholderText("deepseek-chat")
        form_base.addRow("模型 ID", self._llm_model)

        self._llm_vision_model = QComboBox()
        for model_id, hint in DASHSCOPE_VL_MODELS:
            self._llm_vision_model.addItem(model_id, model_id)
            idx = self._llm_vision_model.count() - 1
            self._llm_vision_model.setItemData(idx, hint, Qt.ItemDataRole.ToolTipRole)
        self._llm_vision_model.setToolTip(
            "DashScope 识图模型（附截图时分析图片）。"
            "需在 .env 配置 DASHSCOPE_API_KEY；DASHSCOPE_IMAGE_MODEL（wan）是生图，不能用于识图。"
        )
        form_base.addRow("视觉模型（识图）", self._llm_vision_model)

        self._llm_thinking = QCheckBox("启用思考模式（Thinking）")
        self._llm_thinking.setToolTip(
            "仅 DeepSeek V4 Pro 支持：模型先内部推理再回答，"
            "回复更稳但更慢、耗 token 更多。V4 Flash 无思考模式。"
            "桌宠只展示最终回答，不显示思考过程。"
        )
        form_base.addRow("", self._llm_thinking)

        self._llm_reasoning_effort = QComboBox()
        self._llm_reasoning_effort.addItem("标准（high）", "high")
        self._llm_reasoning_effort.addItem("深度（max）", "max")
        self._llm_reasoning_effort.setToolTip("思考强度：max 更慢、推理更深，适合复杂问题")
        form_base.addRow("思考强度", self._llm_reasoning_effort)

        self._llm_model.currentTextChanged.connect(self._sync_thinking_controls)
        self._llm_thinking.toggled.connect(self._sync_thinking_controls)
        self._sync_thinking_controls()
        layout.addWidget(g_base)

        g_role, form_role = self._form_group(
            "对话规则",
            "人物设定在「角色」页编辑；此处为输出/对话规则（system_prompt）。",
        )
        self._system_prompt = QLineEdit()
        self._system_prompt.setPlaceholderText("输出与对话规则（system_prompt）")
        form_role.addRow("系统提示", self._system_prompt)
        layout.addWidget(g_role)

        layout.addStretch(1)
        return self._scroll_tab(w)

    def _build_character_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_sel, form_sel = self._form_group(
            "角色包",
            "每个角色：人设、Live2D、回复语言、记忆核心。"
            "TTS 参考音/文本只在「TTS」页配置，保存时会写入当前角色包。"
            "切换后点「应用角色」或保存全部。",
        )
        self._pack_combo = QComboBox()
        self._pack_combo.currentIndexChanged.connect(self._on_pack_combo_changed)
        form_sel.addRow("当前角色", self._pack_combo)
        apply_btn = QPushButton("应用角色（切换 Live2D / TTS / 记忆）")
        apply_btn.setObjectName("ghostBtn")
        apply_btn.clicked.connect(self._apply_character_now)
        form_sel.addRow("", apply_btn)
        layout.addWidget(g_sel)

        g_edit, form_edit = self._form_group("角色包内容", "")
        self._pack_name = QLineEdit()
        form_edit.addRow("显示名", self._pack_name)
        self._pack_prompt = QTextEdit()
        self._pack_prompt.setMaximumHeight(100)
        self._pack_prompt.setPlaceholderText("人物设定 character_prompt")
        form_edit.addRow("人物设定", self._pack_prompt)
        self._pack_live2d = QLineEdit()
        self._pack_live2d.setPlaceholderText("相对项目根，如 live2d/14酱")
        form_edit.addRow("Live2D 目录", self._pack_live2d)
        self._pack_variant_combo = QComboBox()
        self._pack_variant_combo.setToolTip("同一角色的不同 Live2D 模型变体（如不同服装/场景）")
        form_edit.addRow("Live2D 变体", self._pack_variant_combo)
        self._pack_reply_lang = QComboBox()
        self._pack_reply_lang.addItem("日语（推荐，配合 TTS ja）", "ja")
        self._pack_reply_lang.addItem("简体中文", "zh")
        form_edit.addRow("AI 回复语言", self._pack_reply_lang)
        self._pack_core_card = QTextEdit()
        self._pack_core_card.setMaximumHeight(80)
        self._pack_core_card.setPlaceholderText("记忆核心设定（永不覆盖）")
        form_edit.addRow("记忆核心", self._pack_core_card)
        layout.addWidget(g_edit)

        g_tr, form_tr = self._form_group(
            "气泡中文显示（翻译）",
            "开启后：AI 仍按上方语言生成原文，TTS 朗读原文；"
            "气泡里显示翻译成中文后的文字。"
            "「必应网页」自动检测语言→中文，无需密钥；「百度 API」需 AppID/密钥。",
        )
        self._tr_enabled = QCheckBox("启用：气泡显示中文，TTS 用原文")
        form_tr.addRow("", self._tr_enabled)
        self._tr_provider = QComboBox()
        self._tr_provider.addItem("必应网页（自动检测→中文，免费）", "bing")
        self._tr_provider.addItem("百度翻译 API", "baidu")
        self._tr_provider.currentIndexChanged.connect(self._sync_translate_provider_ui)
        form_tr.addRow("翻译来源", self._tr_provider)
        self._tr_app_id = QLineEdit()
        self._tr_app_id.setPlaceholderText("百度翻译 AppID")
        form_tr.addRow("AppID", self._tr_app_id)
        self._tr_secret = QLineEdit()
        self._tr_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._tr_secret.setPlaceholderText("密钥（留空则不修改已保存）")
        form_tr.addRow("密钥", self._tr_secret)
        layout.addWidget(g_tr)
        layout.addStretch(1)
        return self._scroll_tab(w)

    def _build_memory_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_cfg, form_cfg = self._form_group(
            "记忆引擎",
            "每轮对话写入完整记录 [dialogue]；另可自动提取 fact/event。相似条目可 LLM 合并。",
        )
        self._mem_enabled = QCheckBox("启用长期记忆")
        self._mem_enabled.setChecked(True)
        form_cfg.addRow("", self._mem_enabled)
        self._mem_extract = QCheckBox("对话后自动提取记忆")
        self._mem_extract.setChecked(True)
        form_cfg.addRow("", self._mem_extract)
        self._mem_merge_llm = QCheckBox("相似记忆用大模型合并（处理矛盾/更新）")
        self._mem_merge_llm.setChecked(True)
        form_cfg.addRow("", self._mem_merge_llm)
        self._mem_top_k = QSpinBox()
        self._mem_top_k.setRange(1, 20)
        self._mem_top_k.setValue(5)
        form_cfg.addRow("每轮检索条数", self._mem_top_k)
        layout.addWidget(g_cfg)

        g_list = QGroupBox("当前角色记忆库")
        lay_list = QVBoxLayout(g_list)
        lay_list.setSpacing(8)
        mem_hint = QLabel(
            "每条左侧 × 可单独删除（不可恢复）；切换角色请在「角色」页操作。"
        )
        mem_hint.setObjectName("sectionHint")
        mem_hint.setWordWrap(True)
        lay_list.addWidget(mem_hint)
        self._mem_scroll = QScrollArea()
        self._mem_scroll.setWidgetResizable(True)
        self._mem_scroll.setMinimumHeight(180)
        self._mem_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._mem_list_container = QWidget()
        self._mem_list_layout = QVBoxLayout(self._mem_list_container)
        self._mem_list_layout.setContentsMargins(2, 2, 2, 2)
        self._mem_list_layout.setSpacing(6)
        self._mem_scroll.setWidget(self._mem_list_container)
        lay_list.addWidget(self._mem_scroll)
        row = QHBoxLayout()
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.setObjectName("ghostBtn")
        refresh_btn.clicked.connect(self._refresh_memory_list)
        row.addWidget(refresh_btn)
        row.addStretch(1)
        lay_list.addLayout(row)
        layout.addWidget(g_list)
        layout.addStretch(1)
        return self._scroll_tab(w)

    def _build_presence_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_pres, form_pres = self._form_group(
            "在场感",
            "空闲主动搭话、窗口焦点、情绪持久化、生活上下文（含天气）。",
        )
        self._presence_enabled = QCheckBox("启用在场感")
        self._presence_enabled.setChecked(True)
        form_pres.addRow("", self._presence_enabled)
        self._presence_idle_min = QSpinBox()
        self._presence_idle_min.setRange(1, 180)
        self._presence_idle_min.setValue(5)
        self._presence_idle_min.setSuffix(" 分钟")
        self._presence_idle_min.setToolTip(
            "用户多久未发消息后，角色可能主动开口。"
            "保存后立即生效；实际触发还受下方「空闲检测轮询」影响（约为间隔的一半）。"
        )
        form_pres.addRow("空闲搭话间隔", self._presence_idle_min)
        self._presence_idle_prob = QDoubleSpinBox()
        self._presence_idle_prob.setRange(0.0, 1.0)
        self._presence_idle_prob.setSingleStep(0.05)
        self._presence_idle_prob.setDecimals(2)
        self._presence_idle_prob.setValue(1.0)
        self._presence_idle_prob.setToolTip("每次轮询时的触发概率；1.0 表示到点后必开口")
        form_pres.addRow("空闲搭话概率", self._presence_idle_prob)
        self._presence_poll_sec = QSpinBox()
        self._presence_poll_sec.setRange(15, 600)
        self._presence_poll_sec.setValue(60)
        self._presence_poll_sec.setSuffix(" 秒")
        self._presence_poll_sec.setToolTip("后台检测空闲状态的轮询间隔")
        form_pres.addRow("空闲检测轮询", self._presence_poll_sec)
        self._presence_afk_hours = QSpinBox()
        self._presence_afk_hours.setRange(1, 48)
        self._presence_afk_hours.setValue(2)
        self._presence_afk_hours.setSuffix(" 小时")
        form_pres.addRow("长时间挂机阈值", self._presence_afk_hours)
        self._presence_weather = QCheckBox("注入天气上下文")
        self._presence_weather.setChecked(True)
        form_pres.addRow("", self._presence_weather)
        self._presence_city = QLineEdit()
        self._presence_city.setPlaceholderText("如：温州（通过 MSN 天气页面查询）")
        form_pres.addRow("所在城市", self._presence_city)
        layout.addWidget(g_pres)

        g_sched, form_sched = self._form_group(
            "日程与提醒",
            "独立于 LLM 临场发挥的约定提醒；打开窗口或到点可自动发起对话。",
        )
        self._sched_auto_open = QCheckBox("打开对话窗时检测日程")
        self._sched_auto_open.setChecked(True)
        form_sched.addRow("", self._sched_auto_open)
        self._sched_auto_greet = QCheckBox("打开对话窗时自动打招呼")
        self._sched_auto_greet.setChecked(True)
        form_sched.addRow("", self._sched_auto_greet)
        self._sched_bg = QCheckBox("后台轮询到点/爽约提醒")
        self._sched_bg.setChecked(True)
        form_sched.addRow("", self._sched_bg)
        layout.addWidget(g_sched)

        g_list = QGroupBox("当前角色待办约定")
        lay_list = QVBoxLayout(g_list)
        hint = QLabel("约定数据保存在 data/reminders/；删除后不可恢复。")
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        lay_list.addWidget(hint)
        self._reminder_list = QListWidget()
        self._reminder_list.setMinimumHeight(120)
        lay_list.addWidget(self._reminder_list)
        row = QHBoxLayout()
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.setObjectName("ghostBtn")
        refresh_btn.clicked.connect(self._refresh_reminder_list)
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("ghostBtn")
        del_btn.clicked.connect(self._delete_selected_reminder)
        row.addWidget(refresh_btn)
        row.addWidget(del_btn)
        row.addStretch(1)
        lay_list.addLayout(row)
        add_row = QHBoxLayout()
        self._reminder_title = QLineEdit()
        self._reminder_title.setPlaceholderText("事项，如：煮饭")
        self._reminder_when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self._reminder_when.setCalendarPopup(True)
        self._reminder_when.setDisplayFormat("yyyy-MM-dd HH:mm")
        add_btn = QPushButton("添加提醒")
        add_btn.setObjectName("ghostBtn")
        add_btn.clicked.connect(self._add_manual_reminder)
        add_row.addWidget(self._reminder_title, 2)
        add_row.addWidget(self._reminder_when, 2)
        add_row.addWidget(add_btn, 1)
        lay_list.addLayout(add_row)
        layout.addWidget(g_list)
        layout.addStretch(1)
        return self._scroll_tab(w)

    def _load_presence_fields(self) -> None:
        if not hasattr(self, "_presence_enabled"):
            return
        cfg = load_presence_config()
        self._presence_enabled.setChecked(cfg.presence_enabled)
        self._presence_idle_min.setValue(max(1, int(cfg.presence_idle_seconds) // 60))
        self._presence_idle_prob.setValue(float(cfg.presence_idle_probability))
        self._presence_poll_sec.setValue(max(15, int(cfg.presence_poll_seconds)))
        self._presence_afk_hours.setValue(max(1, int(cfg.presence_afk_seconds) // 3600))
        self._presence_weather.setChecked(cfg.presence_weather_enabled)
        self._presence_city.setText(cfg.presence_weather_city or "")
        self._sched_auto_open.setChecked(cfg.schedule_auto_trigger_on_open)
        self._sched_auto_greet.setChecked(cfg.schedule_auto_greet_on_open)
        self._sched_bg.setChecked(cfg.schedule_background_monitor)
        self._refresh_reminder_list()

    def _collect_presence_config(self) -> PresenceConfig:
        from dataclasses import replace

        base = load_presence_config()
        return replace(
            base,
            presence_enabled=self._presence_enabled.isChecked(),
            presence_idle_seconds=max(60, self._presence_idle_min.value() * 60),
            presence_idle_probability=float(self._presence_idle_prob.value()),
            presence_poll_seconds=max(15, self._presence_poll_sec.value()),
            presence_afk_seconds=max(3600, self._presence_afk_hours.value() * 3600),
            presence_weather_enabled=self._presence_weather.isChecked(),
            presence_weather_city=self._presence_city.text().strip(),
            schedule_auto_trigger_on_open=self._sched_auto_open.isChecked(),
            schedule_auto_greet_on_open=self._sched_auto_greet.isChecked(),
            schedule_background_monitor=self._sched_bg.isChecked(),
        )

    def _reminder_session_key(self) -> str:
        from pnn.pet.reminders.manager import session_key_from_character

        char_id = ""
        if hasattr(self, "_pack_combo"):
            char_id = str(self._pack_combo.currentData() or "").strip()
        if not char_id:
            try:
                from pnn.llm.config_store import load_llm_config

                char_id = (load_llm_config().active_character or "").strip()
            except Exception:
                pass
        if not char_id:
            try:
                from pnn.characters.service import character_pack_service

                character_pack_service.ensure_migrated()
                char_id = (character_pack_service.get_active_id() or "").strip()
            except Exception:
                pass
        return session_key_from_character(char_id)

    def _refresh_reminder_list(self) -> None:
        if not hasattr(self, "_reminder_list"):
            return
        self._reminder_list.clear()
        try:
            from pnn.pet.reminders.manager import get_reminder_manager

            sk = self._reminder_session_key()
            from pnn.pet.reminders.from_chat import cleanup_session_reminders

            mgr = get_reminder_manager()
            mgr.reload()
            cleanup_session_reminders(sk)
            mgr.reload()
            for r in mgr.list_for_session(sk):
                end = r.effective_end()
                line = (
                    f"{r.scheduled_start:%m-%d %H:%M}–{end:%H:%M}  "
                    f"[{r.status.value}] {r.title}"
                )
                self._reminder_list.addItem(line)
        except Exception as exc:
            self._reminder_list.addItem(f"（加载失败: {exc}）")

    def _add_manual_reminder(self) -> None:
        title = self._reminder_title.text().strip() if hasattr(self, "_reminder_title") else ""
        if not title:
            QMessageBox.warning(self, "提醒", "请填写事项名称")
            return
        try:
            from datetime import timedelta

            from pnn.pet.reminders.manager import get_reminder_manager

            sk = self._reminder_session_key()
            start = self._reminder_when.dateTime().toPython()
            mgr = get_reminder_manager()
            mgr.create(
                session_key=sk,
                title=title,
                scheduled_start=start,
                scheduled_end=start + timedelta(minutes=15),
                source="manual",
            )
            self._reminder_title.clear()
            self._refresh_reminder_list()
            QMessageBox.information(self, "提醒", f"已添加：{start:%m-%d %H:%M} {title}")
        except Exception as exc:
            QMessageBox.warning(self, "提醒", f"添加失败：{exc}")

    def _delete_selected_reminder(self) -> None:
        row = self._reminder_list.currentRow()
        if row < 0:
            return
        try:
            from pnn.pet.reminders.manager import get_reminder_manager

            sk = self._reminder_session_key()
            mgr = get_reminder_manager()
            items = mgr.list_for_session(sk)
            if row >= len(items):
                return
            rid = items[row].id
            if mgr.delete(rid):
                self._refresh_reminder_list()
        except Exception as exc:
            QMessageBox.warning(self, "删除失败", str(exc))

    def _load_pack_dict(self, char_id: str) -> dict:
        from pnn.characters.pack import load_pack

        pack = load_pack(str(char_id))
        if pack is None:
            raise ValueError(f"角色包不存在: {char_id}")
        return pack.to_dict()

    def _on_pack_combo_changed(self, _index: int) -> None:
        cid = self._pack_combo.currentData()
        if not cid or cid == self._active_pack_id:
            return
        pack: dict | None = None
        try:
            pack = self._api.get_character_pack(str(cid))
        except Exception as exc:
            logger.warning("角色包 API 加载失败，改用本地: %s", exc)
            try:
                pack = self._load_pack_dict(str(cid))
            except Exception as local_exc:
                QMessageBox.warning(
                    self,
                    "角色",
                    f"加载角色包失败：{local_exc}",
                )
                return
        try:
            self._fill_pack_fields(pack)
            self._apply_tts_fields_from_pack(pack)
            self._active_pack_id = str(cid)
            char_prefs = load_preferences().get_for_character(str(cid))
            self._char_scale.setValue(int(char_prefs.character_scale * 100))
            self._fill_percent.setValue(int(char_prefs.fill_percent))
            self._crop_shrink.setValue(int(char_prefs.crop_shrink_percent))
        except Exception as exc:
            QMessageBox.warning(self, "角色", f"填充角色字段失败：{exc}")

    def _fill_pack_fields(self, pack: dict) -> None:
        self._pack_name.setText(pack.get("name", "") or "")
        self._pack_prompt.setPlainText(pack.get("character_prompt", "") or "")
        live2d = pack.get("live2d") or {}
        self._pack_live2d.setText(live2d.get("model_dir", "") or "")
        lang = str(pack.get("reply_language", "ja"))
        idx = self._pack_reply_lang.findData(lang)
        if idx >= 0:
            self._pack_reply_lang.setCurrentIndex(idx)
        mem = pack.get("memory") or {}
        self._pack_core_card.setPlainText(mem.get("core_card", "") or "")
        # 变体下拉
        variants: list[dict] = live2d.get("variants") or []
        self._pack_variant_combo.blockSignals(True)
        self._pack_variant_combo.clear()
        if variants:
            self._pack_variant_combo.addItem("（默认）", "")
            for v in variants:
                name = v.get("name", v.get("dir", ""))
                self._pack_variant_combo.addItem(name, v.get("dir", ""))
            self._pack_variant_combo.setEnabled(True)
            saved_variant = load_preferences().get_for_character(self._active_pack_id).live2d_variant_dir
            match_idx = self._pack_variant_combo.findData(saved_variant)
            if match_idx >= 0:
                self._pack_variant_combo.setCurrentIndex(match_idx)
        else:
            self._pack_variant_combo.addItem("（无变体）", "")
            self._pack_variant_combo.setEnabled(False)
        self._pack_variant_combo.blockSignals(False)

    def _apply_tts_fields_from_pack(self, pack: dict) -> None:
        """TTS 页填入指定角色包配置（优先 pack.json + prompt.txt）。"""
        if not hasattr(self, "_tts_ref"):
            return
        tts = pack.get("tts") or {}
        cid = str(pack.get("id") or self._pack_combo.currentData() or "")
        prompt = (tts.get("prompt_text") or "").strip()
        if cid:
            try:
                from pnn.tts.character_layout import read_prompt_text

                prompt = read_prompt_text(cid) or prompt
            except Exception:
                pass
        pidx = self._tts_provider.findText("gpt-sovits")
        if pidx >= 0:
            self._tts_provider.setCurrentIndex(pidx)
        self._tts_gpt.setText(str(tts.get("gpt_model_path") or ""))
        self._tts_sovits.setText(str(tts.get("sovits_model_path") or ""))
        self._tts_ref.setText(str(tts.get("ref_audio_path") or ""))
        self._tts_prompt.setText(prompt)
        lang = str(tts.get("text_lang") or "ja")
        lidx = self._tts_lang.findText(lang)
        if lidx >= 0:
            self._tts_lang.setCurrentIndex(lidx)
        try:
            self._tts_speed.setValue(float(tts.get("speed_factor", 1.0)))
        except (TypeError, ValueError):
            self._tts_speed.setValue(1.0)

    def _tts_payload_from_ui(self) -> dict:
        lang = self._tts_lang.currentText()
        return {
            "provider": self._tts_provider.currentText(),
            "ref_audio_path": self._tts_ref.text().strip(),
            "prompt_text": self._tts_prompt.text().strip(),
            "prompt_lang": lang,
            "text_lang": lang,
            "gpt_model_path": self._tts_gpt.text().strip(),
            "sovits_model_path": self._tts_sovits.text().strip(),
            "speed_factor": float(self._tts_speed.value()),
        }

    def _apply_character_now(self) -> None:
        try:
            self._save_current_pack()
            cid = self._pack_combo.currentData()
            if not cid:
                QMessageBox.warning(self, "角色", "请先选择角色")
                return
            # 保存角色特定偏好（缩放/裁剪/贴边/变体）
            prefs = load_preferences()
            char_prev = prefs.get_for_character(str(cid))
            prefs.set_for_character(
                str(cid),
                scale=self._char_scale.value() / 100.0,
                fill=float(self._fill_percent.value()),
                crop=float(self._crop_shrink.value()),
                variant_dir=self._pack_variant_combo.currentData() or "",
                width_px=char_prev.character_width_px,
                height_px=char_prev.character_height_px,
            )
            save_preferences(prefs)
            if self._on_ui_saved:
                self._on_ui_saved(prefs.get_for_character(str(cid)))
            try:
                self._api.update_tts_config(**self._tts_payload_from_ui())
                self._api.apply_character_pack(str(cid))
                self._api.reload_chat_config()
            except Exception as exc:
                logger.warning("角色应用 API 失败，改用本地: %s", exc)
                from pnn.characters.service import character_pack_service

                character_pack_service.apply_pack(str(cid), persist_llm=True)
            if self._on_character_applied:
                self._on_character_applied()
            QMessageBox.information(
                self,
                "角色",
                f"已切换到「{self._pack_name.text() or cid}」。"
                "Live2D 已尝试重载；GPT 权重在后台切换，约 1～3 分钟。",
            )
        except Exception as exc:
            QMessageBox.critical(self, "角色", str(exc))

    def _save_current_pack(self) -> None:
        cid = self._pack_combo.currentData()
        if not cid:
            return
        body = {
            "name": self._pack_name.text().strip(),
            "character_prompt": self._pack_prompt.toPlainText().strip(),
            "live2d_model_dir": self._pack_live2d.text().strip(),
            "tts": self._tts_payload_from_ui(),
            "memory_core_card": self._pack_core_card.toPlainText().strip(),
            "reply_language": str(self._pack_reply_lang.currentData() or "ja"),
        }
        try:
            self._api.save_character_pack(str(cid), **body)
        except Exception as exc:
            logger.warning("角色包 API 保存失败，改用本地: %s", exc)
            from pnn.settings.batch_save import _build_pack_from_body

            pack = _build_pack_from_body(str(cid), body)
            from pnn.characters.service import character_pack_service

            character_pack_service.save_pack_data(pack)

    def _toggle_settings_fullscreen(self) -> None:
        if self.isMaximized():
            self.showNormal()
            self._fullscreen_btn.setText("全屏")
        else:
            self.showMaximized()
            self._fullscreen_btn.setText("还原")

    def _make_memory_row_widget(self, memory_id: str, line: str) -> QWidget:
        row = QWidget()
        row.setObjectName("memoryRow")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(6, 6, 8, 6)
        lay.setSpacing(8)
        del_btn = QPushButton("×")
        del_btn.setObjectName("memoryDelBtn")
        del_btn.setFixedSize(28, 28)
        del_btn.setToolTip("删除此条记忆（不可恢复）")
        del_btn.clicked.connect(
            lambda _checked=False, mid=memory_id: self._delete_memory_by_id(mid)
        )
        label = QLabel(line)
        label.setWordWrap(True)
        label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(label, 1)
        return row

    def _clear_memory_list_ui(self) -> None:
        layout = self._mem_list_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_memory_list(self, items: list) -> None:
        self._clear_memory_list_ui()
        for it in items or []:
            if not isinstance(it, dict):
                continue
            mid = str(it.get("id") or "")
            if not mid:
                continue
            kind = it.get("kind", "fact")
            body = (it.get("content") or "").strip()
            preview = body.replace("\n", " ↵ ")
            cap = 280 if kind == "dialogue" else 160
            line = f"[{kind}] {preview[:cap]}"
            self._mem_list_layout.addWidget(self._make_memory_row_widget(mid, line))

    def _refresh_memory_list(self) -> None:
        try:
            items = self._api.list_memories(100)
            self._populate_memory_list(items)
        except Exception as exc:
            QMessageBox.warning(self, "记忆", f"加载失败：{exc}")

    def _delete_memory_by_id(self, memory_id: str) -> None:
        mid = (memory_id or "").strip()
        if not mid:
            return
        try:
            self._api.delete_memory(mid)
            self._refresh_memory_list()
        except Exception as exc:
            QMessageBox.warning(self, "记忆", str(exc))

    def _sync_translate_provider_ui(self) -> None:
        use_baidu = str(self._tr_provider.currentData() or "bing") == "baidu"
        self._tr_app_id.setEnabled(use_baidu)
        self._tr_secret.setEnabled(use_baidu)

    def _on_llm_provider_changed(self, index: int) -> None:
        if index < 0 or index >= len(LLM_PROVIDER_PRESETS):
            return
        name, base, model = LLM_PROVIDER_PRESETS[index]
        if name == "自定义":
            return
        if base:
            self._llm_base_url.setText(base)
        if model:
            self._set_llm_model_id(model)

    def _sync_thinking_controls(self, *_args) -> None:
        model = self._llm_model.currentText().strip().lower()
        from pnn.llm.client import model_supports_thinking

        supported = model_supports_thinking(model)
        if not supported and self._llm_thinking.isChecked():
            self._llm_thinking.setChecked(False)
        self._llm_thinking.setEnabled(supported)
        self._llm_reasoning_effort.setEnabled(supported and self._llm_thinking.isChecked())
        if not supported:
            self._llm_thinking.setToolTip(
                "当前模型不支持思考模式（请选 deepseek-v4-pro；V4 Flash 无此功能）"
            )
        else:
            self._llm_thinking.setToolTip(
                "DeepSeek V4 Pro 思考模式：先推理再回答，更稳但更慢。"
                "桌宠只展示最终回复，不显示思考链。"
            )

    def _set_llm_model_id(self, model_id: str) -> None:
        self._llm_model.setCurrentText((model_id or "").strip())

    def _set_vision_model_id(self, model_id: str) -> None:
        mid = (model_id or "").strip() or DASHSCOPE_VL_MODELS[0][0]
        idx = self._llm_vision_model.findData(mid)
        if idx >= 0:
            self._llm_vision_model.setCurrentIndex(idx)
        else:
            self._llm_vision_model.setCurrentIndex(0)

    def _build_mcp_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_cfg, form_cfg = self._form_group(
            "MCP 总开关",
            "Model Context Protocol：连接外部工具（Playwright 浏览器、项目代码读写）。"
            "配置文件 data/config/mcp.json，新增 Server 可编辑该 JSON。\n"
            "filesystem 服务用于在桌宠对话里 read/write 本项目代码；浏览器下载保存到 data/mcp/…",
        )
        self._mcp_enabled = QCheckBox("启用 MCP")
        self._mcp_enabled.setChecked(True)
        form_cfg.addRow("", self._mcp_enabled)
        self._mcp_use_in_chat = QCheckBox("桌宠对话中自动调用 MCP 工具（Agent 模式）")
        self._mcp_use_in_chat.setChecked(True)
        self._mcp_use_in_chat.setToolTip(
            "开启后，AI 可在回复前调用 MCP 工具（浏览器、读写项目代码等）；"
            "关闭则仅普通聊天。"
        )
        form_cfg.addRow("", self._mcp_use_in_chat)
        self._mcp_preload = QCheckBox("API 启动时预连接 MCP（可选，略占资源）")
        form_cfg.addRow("", self._mcp_preload)
        self._mcp_playwright_headless = QCheckBox("Playwright 无头模式（后台运行，不弹出浏览器）")
        self._mcp_playwright_headless.setChecked(False)
        self._mcp_playwright_headless.setToolTip(
            "关闭时 Agent 调用 browser_navigate 会弹出 Edge 窗口；"
            "开启时仅在后台读取页面快照（browser_snapshot），适合服务器环境。"
        )
        form_cfg.addRow("", self._mcp_playwright_headless)
        from pnn.mcp.config_store import DEFAULT_MAX_AGENT_STEPS, MAX_AGENT_STEPS_LIMIT

        self._mcp_max_steps = QSpinBox()
        self._mcp_max_steps.setRange(1, MAX_AGENT_STEPS_LIMIT)
        self._mcp_max_steps.setValue(DEFAULT_MAX_AGENT_STEPS)
        self._mcp_max_steps.setToolTip(
            f"每轮 = LLM 思考 + 工具调用。浏览器寻图/截图下载建议 15–{MAX_AGENT_STEPS_LIMIT}。"
        )
        form_cfg.addRow("Agent 最大轮数", self._mcp_max_steps)
        self._mcp_timeout = QSpinBox()
        self._mcp_timeout.setRange(5, 600)
        self._mcp_timeout.setValue(120)
        self._mcp_timeout.setSuffix(" 秒")
        form_cfg.addRow("工具调用超时", self._mcp_timeout)
        layout.addWidget(g_cfg)

        g_srv = QGroupBox("MCP 服务器")
        lay_srv = QVBoxLayout(g_srv)
        lay_srv.setSpacing(8)
        srv_hint = QLabel(
            "勾选启用；点「连接并刷新工具」拉取工具列表（Playwright 首次约 1–3 分钟）。"
            "关闭「无头模式」后，Agent 打开网页时会弹出 Edge 窗口。"
        )
        srv_hint.setObjectName("sectionHint")
        srv_hint.setWordWrap(True)
        lay_srv.addWidget(srv_hint)
        self._mcp_status_label = QLabel("状态：尚未加载")
        self._mcp_status_label.setObjectName("sectionHint")
        self._mcp_status_label.setWordWrap(True)
        lay_srv.addWidget(self._mcp_status_label)

        self._mcp_servers_host = QWidget()
        self._mcp_servers_layout = QVBoxLayout(self._mcp_servers_host)
        self._mcp_servers_layout.setContentsMargins(0, 0, 0, 0)
        self._mcp_servers_layout.setSpacing(6)
        lay_srv.addWidget(self._mcp_servers_host)

        row_srv = QHBoxLayout()
        btn_connect = QPushButton("连接并刷新工具")
        btn_connect.setObjectName("ghostBtn")
        btn_connect.clicked.connect(lambda: self._refresh_mcp_tools(connect=True))
        btn_status = QPushButton("刷新状态")
        btn_status.setObjectName("ghostBtn")
        btn_status.clicked.connect(self._refresh_mcp_status_only)
        row_srv.addWidget(btn_connect)
        row_srv.addWidget(btn_status)
        btn_restart_api = QPushButton("重启 API")
        btn_restart_api.setObjectName("ghostBtn")
        btn_restart_api.setToolTip("MCP 返回 404 时：重启 8765 上的 API 以加载新模块")
        btn_restart_api.clicked.connect(self._restart_api_for_mcp)
        row_srv.addWidget(btn_restart_api)
        row_srv.addStretch(1)
        lay_srv.addLayout(row_srv)
        layout.addWidget(g_srv)

        g_tools = QGroupBox("可用工具")
        lay_tools = QVBoxLayout(g_tools)
        lay_tools.setSpacing(8)
        tools_hint = QLabel(
            "Agent 模式下 LLM 可调用下列工具（名称格式 server_id__tool_name）。"
        )
        tools_hint.setObjectName("sectionHint")
        tools_hint.setWordWrap(True)
        lay_tools.addWidget(tools_hint)
        self._mcp_tools_list = QListWidget()
        self._mcp_tools_list.setMinimumHeight(160)
        lay_tools.addWidget(self._mcp_tools_list)
        self._mcp_tools_hint = QLabel("切换到本页或点「连接并刷新工具」加载列表。")
        self._mcp_tools_hint.setObjectName("sectionHint")
        self._mcp_tools_hint.setWordWrap(True)
        lay_tools.addWidget(self._mcp_tools_hint)
        layout.addWidget(g_tools)

        layout.addStretch(1)
        return self._scroll_tab(w)

    def _on_tab_changed(self, index: int) -> None:
        if not hasattr(self, "_tabs"):
            return
        if self._tabs.tabText(index) == "MCP":
            self._refresh_mcp_status_only()

    def _rebuild_mcp_server_checks(self, servers: list[dict]) -> None:
        self._mcp_server_checks.clear()
        while self._mcp_servers_layout.count():
            item = self._mcp_servers_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not servers:
            tip = QLabel("（无 MCP 服务器，请编辑 data/config/mcp.json）")
            tip.setObjectName("sectionHint")
            self._mcp_servers_layout.addWidget(tip)
            return
        for s in servers:
            sid = str(s.get("id") or "")
            name = str(s.get("name") or sid)
            transport = str(s.get("transport") or "stdio")
            connected = bool(s.get("connected"))
            err = str(s.get("error") or "").strip()
            tool_count = int(s.get("tool_count") or 0)
            state = "已连接" if connected else ("失败: " + err[:60] if err else "未连接")
            cb = QCheckBox(f"{name} ({sid}) · {transport} · {state} · {tool_count} 工具")
            cb.setChecked(bool(s.get("enabled", True)))
            cb.setToolTip(
                f"command: {s.get('command', '')} {' '.join(s.get('args') or [])}".strip()
                or str(s.get("url") or "")
            )
            self._mcp_server_checks[sid] = cb
            self._mcp_servers_layout.addWidget(cb)

    def _apply_mcp_status(self, status: dict) -> None:
        from pnn.core.api_health import is_mcp_config_api_ready

        cfg_path = status.get("config_path") or "data/config/mcp.json"
        sdk = "已安装" if status.get("sdk_available") else "未安装（pip install mcp）"
        ready = "就绪" if status.get("ready") else "未就绪"
        agent = "可接入对话" if status.get("enabled") and status.get("sdk_available") else "未启用"
        stale = not is_mcp_config_api_ready()
        extra = ""
        if stale:
            extra = "\n⚠ API 进程版本过旧，MCP 设置无法保存 — 请点「重启 API」。"
        self._mcp_status_label.setText(
            f"Python SDK: {sdk} · 连接: {ready} · 配置: {cfg_path}{extra}"
        )
        servers = status.get("servers") or []
        self._rebuild_mcp_server_checks(servers)

        if not hasattr(self, "_mcp_enabled"):
            return
        if "enabled" in status:
            self._mcp_enabled.setChecked(bool(status.get("enabled")))
        if "use_in_chat" in status:
            self._mcp_use_in_chat.setChecked(bool(status.get("use_in_chat")))
        if "preload_on_startup" in status:
            self._mcp_preload.setChecked(bool(status.get("preload_on_startup")))
        if "playwright_headless" in status:
            self._mcp_playwright_headless.setChecked(bool(status.get("playwright_headless")))
        elif servers:
            for s in servers:
                if str(s.get("id") or "") == "playwright":
                    args = s.get("args") or []
                    self._mcp_playwright_headless.setChecked("--headless" in args)
                    break
        if status.get("max_agent_steps") is not None:
            from pnn.mcp.config_store import DEFAULT_MAX_AGENT_STEPS

            self._mcp_max_steps.setValue(int(status.get("max_agent_steps") or DEFAULT_MAX_AGENT_STEPS))
        if status.get("default_call_timeout") is not None:
            timeout = int(float(status.get("default_call_timeout") or 120))
            self._mcp_timeout.setValue(max(5, min(600, timeout)))
        self._refresh_mcp_save_baseline()

    def _fill_mcp_tools_list(self, tools_data: dict) -> None:
        self._mcp_tools_list.clear()
        tools = tools_data.get("tools") or []
        count = int(tools_data.get("count") or len(tools))
        for t in tools:
            llm_name = t.get("llm_name") or t.get("registered_name") or t.get("name") or "?"
            desc = str(t.get("description") or "").strip()
            if len(desc) > 100:
                desc = desc[:100] + "…"
            server = t.get("server_name") or t.get("server_id") or ""
            item_text = f"{llm_name}\n  [{server}] {desc}"
            self._mcp_tools_list.addItem(item_text)
        self._mcp_tools_hint.setText(
            f"共 {count} 个工具。"
            + (" Agent 对话中 LLM 可按需调用。" if count else " 请先连接 MCP 服务器。")
        )

    @staticmethod
    def _is_mcp_not_found(err: str) -> bool:
        low = (err or "").lower()
        return "not found" in low or "404" in low

    def _mcp_not_found_hint(self) -> str:
        return (
            "当前 API(8765) 是旧进程，未加载 MCP 模块（404 Not Found）。\n"
            "请点「重启 API」，或完全退出桌宠后重新运行「启动桌宠.bat」。"
        )

    def _restart_api_for_mcp(self) -> None:
        from pnn.core.api_health import restart_api

        self._mcp_status_label.setText("正在重启 API…")
        ok = restart_api(timeout=45.0)
        if ok:
            self._mcp_status_label.setText("API 已重启，MCP 模块已加载。")
            self._refresh_mcp_status_only()
        else:
            self._mcp_status_label.setText("API 重启失败，请手动关闭旧 python 进程后重开桌宠。")
            QMessageBox.warning(self, "MCP", "API 重启失败。请关闭任务管理器中的旧 python.exe，再运行启动桌宠.bat。")

    def _refresh_mcp_status_only(self) -> None:
        try:
            status = self._api.get_mcp_status()
            full = self._api.get_mcp_config()
            status = {**full, **status}
            self._apply_mcp_status(status)
        except Exception as exc:
            msg = str(exc)
            if self._is_mcp_not_found(msg):
                self._mcp_status_label.setText(self._mcp_not_found_hint())
            else:
                self._mcp_status_label.setText(f"加载 MCP 状态失败：{msg}")

    def _refresh_mcp_tools(self, *, connect: bool = True) -> None:
        if self._mcp_tools_loader is not None and self._mcp_tools_loader.isRunning():
            return
        self._mcp_tools_hint.setText("正在连接 MCP 并拉取工具列表…")
        self._mcp_tools_list.clear()
        worker = _McpToolsLoader(self._api, connect=connect, parent=self)
        worker.finished_ok.connect(self._on_mcp_tools_loaded)
        worker.failed.connect(self._on_mcp_tools_failed)
        worker.finished.connect(worker.deleteLater)
        self._mcp_tools_loader = worker
        worker.start()

    def _on_mcp_tools_loaded(self, data: dict) -> None:
        self._mcp_tools_loader = None
        status = data.get("status") or {}
        try:
            cfg = self._api.get_mcp_config()
            merged = {**cfg, **status}
        except Exception:
            merged = status
        self._apply_mcp_status(merged)
        self._fill_mcp_tools_list(data.get("tools") or {})

    def _on_mcp_tools_failed(self, err: str) -> None:
        self._mcp_tools_loader = None
        if self._is_mcp_not_found(err):
            self._mcp_tools_hint.setText(self._mcp_not_found_hint())
            QMessageBox.warning(self, "MCP", self._mcp_not_found_hint())
        else:
            self._mcp_tools_hint.setText(f"拉取工具失败：{err}")
            QMessageBox.warning(self, "MCP", f"连接或拉取工具失败：\n{err}")

    def _collect_mcp_save_fields(self) -> dict | None:
        """从界面收集 MCP 字段（不发起网络请求）。"""
        if not hasattr(self, "_mcp_enabled"):
            return None
        server_enabled = {
            sid: cb.isChecked() for sid, cb in self._mcp_server_checks.items() if sid
        }
        return dict(
            enabled=self._mcp_enabled.isChecked(),
            use_in_chat=self._mcp_use_in_chat.isChecked(),
            preload_on_startup=self._mcp_preload.isChecked(),
            playwright_headless=self._mcp_playwright_headless.isChecked(),
            max_agent_steps=self._mcp_max_steps.value(),
            default_call_timeout=float(self._mcp_timeout.value()),
            server_enabled=server_enabled or None,
        )

    def _persist_mcp_config_local(self, fields: dict | None) -> str | None:
        """仅写入本地 mcp.json（主线程，毫秒级）；API 同步在后台 worker。"""
        if not fields:
            return None
        from pnn.mcp.config_store import patch_mcp_config

        patch_mcp_config(**fields)
        return None

    @staticmethod
    @staticmethod
    def _save_settings_legacy(
        api: PetApiClient,
        snap: dict,
        mcp_fields: dict | None,
        mcp_note: str | None,
        *,
        timeout: float,
    ) -> dict:
        """旧版 API 无批量端点时的串行回退。"""
        if mcp_fields and not snap.get("mcp_skip"):
            mcp_note = SettingsDialog._sync_mcp_config_to_api(
                api, mcp_fields, mcp_note, timeout=timeout
            )
        pack = snap.get("pack")
        char_id = str(snap.get("char_id") or "")
        llm_cfg = api.update_chat_config(timeout=timeout, **snap["llm"])
        if pack and char_id:
            pack_fields = {k: v for k, v in pack.items() if k != "char_id"}
            api.save_character_pack(char_id, timeout=timeout, **pack_fields)
            api.apply_character_pack(char_id, timeout=timeout)
        else:
            api.update_tts_config(timeout=timeout, **snap["tts"])
        api.update_asr_config(timeout=timeout, **snap["asr"])
        api.update_memory_config(timeout=timeout, **snap["memory"])
        api.update_translate_config(timeout=timeout, **snap["translate"])
        return {"llm": llm_cfg, "mcp_synced": bool(mcp_fields and not snap.get("mcp_skip"))}

    @staticmethod
    def _normalize_mcp_save_fields(fields: dict | None) -> dict | None:
        if not fields:
            return None
        se = fields.get("server_enabled")
        if isinstance(se, dict):
            se = {k: bool(se[k]) for k in sorted(se)}
        return {
            "enabled": bool(fields.get("enabled")),
            "use_in_chat": bool(fields.get("use_in_chat")),
            "preload_on_startup": bool(fields.get("preload_on_startup")),
            "playwright_headless": bool(fields.get("playwright_headless")),
            "max_agent_steps": int(fields.get("max_agent_steps") or 0),
            "default_call_timeout": float(fields.get("default_call_timeout") or 0),
            "server_enabled": se,
        }

    def _refresh_mcp_save_baseline(self) -> None:
        self._mcp_save_baseline = self._normalize_mcp_save_fields(
            self._collect_mcp_save_fields()
        )

    def _mcp_save_fields_changed(self, fields: dict | None) -> bool:
        if not fields:
            return False
        cur = self._normalize_mcp_save_fields(fields)
        if self._mcp_save_baseline is None:
            return True
        return cur != self._mcp_save_baseline

    @staticmethod
    def _format_save_error(exc: BaseException) -> str:
        msg = str(exc).strip() or type(exc).__name__
        low = msg.lower()
        if "read timed out" in low or "timed out" in low:
            return (
                "保存超时：本地 API (127.0.0.1:8765) 响应过慢。\n"
                "常见原因：MCP/Playwright 正在断开、TTS 正在加载权重。\n"
                "请等待约 1 分钟后重试，或在 MCP 页点击「重启 API」后再保存。"
            )
        return msg

    def _sync_mcp_config_to_api(
        api: PetApiClient,
        mcp_fields: dict,
        mcp_note: str | None,
        *,
        timeout: float = 30,
    ) -> str | None:
        """后台将 MCP 推送到 API；失败时保留本地文件并返回提示。"""
        import time

        from pnn.core.api_health import is_mcp_config_api_ready

        if not is_mcp_config_api_ready():
            return mcp_note or "MCP 已写入本地；API 未就绪时请点「重启 API」后再保存一次。"

        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                api.update_mcp_config(timeout=timeout, **mcp_fields)
                return mcp_note
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(0.4)
        extra = f"MCP API 同步失败（已保留本地 mcp.json）：{last_exc}"
        extra += "\n可在 MCP 页点击「重启 API」后再次保存。"
        return f"{mcp_note}\n\n{extra}" if mcp_note else extra

    def _save_mcp_config(self) -> str | None:
        """兼容旧调用：本地写入 + 返回提示（不在主线程重启 API）。"""
        fields = self._collect_mcp_save_fields()
        return self._persist_mcp_config_local(fields)

    def _build_tts_tab(self) -> QWidget:
        ui = load_preferences()
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_voice, form_voice = self._form_group(
            "语音输出",
            "关闭后仍显示文字气泡与翻译，但不合成、不播放语音。",
        )
        self._tts_voice_on = QCheckBox("启用语音输出（TTS 朗读）")
        self._tts_voice_on.setChecked(ui.voice_output_enabled)
        form_voice.addRow("", self._tts_voice_on)
        layout.addWidget(g_voice)

        g, form = self._form_group(
            "语音合成",
            "路径相对项目根，如 data/tts/里想奈/reference.wav。"
            "切换「角色」页角色时会自动载入该角色包配置。",
        )
        self._tts_provider = QComboBox()
        self._tts_provider.addItems(["gpt-sovits", "genie-tts", "index-tts", "cosyvoice"])
        form.addRow("引擎", self._tts_provider)
        self._tts_gpt = QLineEdit()
        self._tts_gpt.setPlaceholderText("models/character/{角色}/{角色}.ckpt")
        form.addRow("GPT 权重", self._tts_gpt)
        self._tts_sovits = QLineEdit()
        self._tts_sovits.setPlaceholderText("models/character/{角色}/{角色}.pth")
        form.addRow("SoVITS 权重", self._tts_sovits)
        self._tts_ref = QLineEdit()
        form.addRow("参考音频", self._tts_ref)
        self._tts_prompt = QLineEdit()
        form.addRow("参考文本", self._tts_prompt)
        self._tts_lang = QComboBox()
        self._tts_lang.addItems(["zh", "ja", "en", "ko"])
        form.addRow("合成语言", self._tts_lang)
        self._tts_speed = QDoubleSpinBox()
        self._tts_speed.setRange(0.5, 2.0)
        self._tts_speed.setSingleStep(0.1)
        self._tts_speed.setValue(1.0)
        form.addRow("语速", self._tts_speed)
        boot = QPushButton("启动 TTS 服务")
        boot.setObjectName("ghostBtn")
        boot.clicked.connect(self._boot_tts)
        form.addRow("", boot)
        layout.addWidget(g)
        layout.addStretch(1)
        return self._scroll_tab(w)

    def _build_asr_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_w, form_w = self._form_group("语音识别", "Whisper 流式 ASR 参数。")
        self._asr_model = QComboBox()
        self._asr_model.addItems(["tiny", "base", "small", "medium", "large-v2", "large-v3"])
        form_w.addRow("Whisper 模型", self._asr_model)
        self._asr_lang = QComboBox()
        self._asr_lang.addItem("自动", "")
        self._asr_lang.addItem("中文", "zh")
        self._asr_lang.addItem("English", "en")
        self._asr_lang.addItem("日本語", "ja")
        form_w.addRow("语言", self._asr_lang)
        layout.addWidget(g_w)

        mic_hint = QLabel("常开麦克风（说完自动发送）请点对话窗上的麦克风按钮开关。")
        mic_hint.setObjectName("sectionHint")
        mic_hint.setWordWrap(True)
        layout.addWidget(mic_hint)

        g_meter, form_m = self._form_group(
            "音量测试",
            "与网页端相同：绿条为当前音量，白线为触发阈值；超过阈值会显示「已触发」。",
        )
        self._asr_meter = VolumeMeterWidget()
        form_m.addRow("", self._asr_meter)
        self._btn_asr_test = QPushButton("开始测试麦克风")
        self._btn_asr_test.setObjectName("ghostBtn")
        self._btn_asr_test.clicked.connect(self._toggle_asr_test)
        form_m.addRow("", self._btn_asr_test)
        layout.addWidget(g_meter)

        g_th, form_th = self._form_group("触发阈值", "")
        self._asr_auto_threshold = QCheckBox("自动校准声音阈值（环境噪声自适应）")
        self._asr_auto_threshold.setChecked(True)
        self._asr_auto_threshold.toggled.connect(self._on_asr_auto_threshold_toggled)
        form_th.addRow("", self._asr_auto_threshold)

        self._asr_energy = QDoubleSpinBox()
        self._asr_energy.setRange(0.005, 0.4)
        self._asr_energy.setSingleStep(0.005)
        self._asr_energy.setDecimals(3)
        self._asr_energy.setValue(0.03)
        self._asr_energy.setToolTip(
            "能量高于此值视为说话；越小越灵敏，越大越不易误触发（0.005~0.4）"
        )
        form_th.addRow("声音阈值", self._asr_energy)
        self._asr_energy.valueChanged.connect(self._apply_threshold_live)
        layout.addWidget(g_th)
        layout.addStretch(1)
        return self._scroll_tab(w)

    def _on_asr_auto_threshold_toggled(self, checked: bool) -> None:
        self._asr_energy.setEnabled(not checked)
        self._apply_threshold_live()

    def _apply_threshold_live(self) -> None:
        try:
            th = (
                None
                if self._asr_auto_threshold.isChecked()
                else float(self._asr_energy.value())
            )
            self._api.update_asr_config(energy_threshold=th)
        except Exception:
            pass

    def _on_probe_level(self, energy: float, threshold: float, is_speech: bool) -> None:
        self._asr_meter.set_level(energy, threshold, is_speech=is_speech)

    def _on_probe_error(self, err: str) -> None:
        self._stop_asr_test()
        QMessageBox.warning(self, "ASR 测试", err)

    def _toggle_asr_test(self) -> None:
        if self._asr_probe.is_active():
            self._stop_asr_test()
        else:
            self._start_asr_test()

    def _start_asr_test(self) -> None:
        self._apply_threshold_live()
        self._btn_asr_test.setText("停止测试")
        self._asr_probe.set_level_meter_enabled(True)
        self._asr_probe.start()

    def _stop_asr_test(self) -> None:
        if self._asr_probe.is_active():
            self._asr_probe.stop()
        self._asr_probe.set_level_meter_enabled(False)
        self._btn_asr_test.setText("开始测试麦克风")
        self._asr_meter.set_level(0, self._asr_energy.value(), is_speech=False)

    def _sync_llm_provider_combo(self, base_url: str) -> None:
        base = (base_url or "").strip().rstrip("/")
        idx = len(LLM_PROVIDER_PRESETS) - 1
        for i, (_, url, _) in enumerate(LLM_PROVIDER_PRESETS):
            if url and base == url.rstrip("/"):
                idx = i
                break
        self._llm_provider.blockSignals(True)
        self._llm_provider.setCurrentIndex(idx)
        self._llm_provider.blockSignals(False)

    def _apply_remote_config(self, data: dict) -> None:
        self._remote_loader = None
        errors: list[str] = []

        try:
            chat = data.get("chat") or {}
            base = chat.get("base_url", "") or ""
            self._llm_base_url.setText(base)
            self._sync_llm_provider_combo(base)
            self._set_llm_model_id(chat.get("model", "") or "")
            if hasattr(self, "_llm_vision_model"):
                self._set_vision_model_id(chat.get("vision_model", "") or "")
            self._llm_thinking.setChecked(bool(chat.get("thinking_enabled")))
            effort = str(chat.get("reasoning_effort") or "high").strip().lower()
            idx = self._llm_reasoning_effort.findData("max" if effort == "max" else "high")
            if idx >= 0:
                self._llm_reasoning_effort.setCurrentIndex(idx)
            self._sync_thinking_controls()
            self._system_prompt.setText(chat.get("system_prompt", "") or "")
            masked = chat.get("api_key_masked", "") or ""
            if chat.get("configured"):
                self._llm_api_key.setPlaceholderText(
                    f"已配置 {masked}，留空则不修改"
                    if masked
                    else "已配置，留空则不修改"
                )
            else:
                self._llm_api_key.setPlaceholderText(
                    "未配置：填写 Key 或设置环境变量 DEEPSEEK_API_KEY / .env"
                )
            self._llm_api_key.clear()
            packs = data.get("packs") or data.get("characters") or []
            self._pack_combo.blockSignals(True)
            self._pack_combo.clear()
            active = chat.get("active_character", "")
            for c in packs:
                self._pack_combo.addItem(c.get("name") or c.get("id", ""), c.get("id"))
            idx = self._pack_combo.findData(active)
            if idx >= 0:
                self._pack_combo.setCurrentIndex(idx)
            self._pack_combo.blockSignals(False)
            if active:
                try:
                    try:
                        pack = self._api.get_character_pack(active)
                    except Exception:
                        pack = self._load_pack_dict(active)
                    self._fill_pack_fields(pack)
                    self._active_pack_id = active
                except Exception as pack_exc:
                    errors.append(f"角色包详情: {pack_exc}")
        except Exception as exc:
            errors.append(f"LLM/角色: {exc}")

        try:
            mem_cfg = data.get("memory") or {}
            self._mem_enabled.setChecked(bool(mem_cfg.get("enabled", True)))
            self._mem_extract.setChecked(bool(mem_cfg.get("extraction_enabled", True)))
            self._mem_merge_llm.setChecked(bool(mem_cfg.get("merge_similar_with_llm", True)))
            self._mem_top_k.setValue(int(mem_cfg.get("top_k", 5)))
            self._populate_memory_list(data.get("memories") or [])
        except Exception as exc:
            errors.append(f"记忆: {exc}")

        try:
            tr = data.get("translate") or {}
            self._tr_enabled.setChecked(bool(tr.get("enabled")))
            provider = str(tr.get("provider") or "bing").strip().lower()
            idx = self._tr_provider.findData(provider)
            if idx < 0:
                idx = self._tr_provider.findData("bing")
            self._tr_provider.setCurrentIndex(max(0, idx))
            self._tr_app_id.setText(tr.get("app_id", "") or "")
            if tr.get("configured") and provider == "baidu":
                self._tr_secret.setPlaceholderText("已配置，留空则不修改")
            elif provider == "baidu":
                self._tr_secret.setPlaceholderText("百度翻译密钥")
            else:
                self._tr_secret.setPlaceholderText("必应模式无需密钥")
            self._tr_secret.clear()
            self._sync_translate_provider_ui()
        except Exception as exc:
            errors.append(f"翻译: {exc}")

        try:
            mcp = data.get("mcp") or {}
            if mcp:
                self._apply_mcp_status(mcp)
        except Exception as exc:
            errors.append(f"MCP: {exc}")

        try:
            tts = data.get("tts") or {}
            pidx = self._tts_provider.findText(tts.get("provider", "gpt-sovits"))
            if pidx >= 0:
                self._tts_provider.setCurrentIndex(pidx)
            self._tts_speed.setValue(float(tts.get("speed_factor", 1.0)))
            active = str((data.get("chat") or {}).get("active_character") or "")
            pack_data = None
            for item in data.get("packs") or []:
                if str(item.get("id")) == active:
                    pack_data = self._api.get_character_pack(active)
                    break
            if pack_data:
                self._apply_tts_fields_from_pack(pack_data)
            else:
                self._tts_gpt.setText(tts.get("gpt_model_path", "") or "")
                self._tts_sovits.setText(tts.get("sovits_model_path", "") or "")
                self._tts_ref.setText(tts.get("ref_audio_path", "") or "")
                self._tts_prompt.setText(tts.get("prompt_text", "") or "")
                lidx = self._tts_lang.findText(tts.get("text_lang", "zh"))
                if lidx >= 0:
                    self._tts_lang.setCurrentIndex(lidx)
        except Exception as exc:
            errors.append(f"TTS: {exc}")

        try:
            asr = data.get("asr") or {}
            midx = self._asr_model.findText(asr.get("model", "small"))
            if midx >= 0:
                self._asr_model.setCurrentIndex(midx)
            lang = asr.get("language") or ""
            for i in range(self._asr_lang.count()):
                if self._asr_lang.itemData(i) == lang:
                    self._asr_lang.setCurrentIndex(i)
                    break
            th = asr.get("energy_threshold")
            if th is None:
                self._asr_auto_threshold.setChecked(True)
                active_th = asr.get("active_threshold")
                if active_th is not None:
                    self._asr_energy.setValue(float(active_th))
            else:
                self._asr_auto_threshold.setChecked(False)
                self._asr_energy.setValue(float(th))
            self._on_asr_auto_threshold_toggled(self._asr_auto_threshold.isChecked())
        except Exception as exc:
            errors.append(f"ASR: {exc}")

        remote_warnings = list(data.get("_load_warnings") or [])
        all_issues = remote_warnings + errors
        if all_issues:
            self._load_status.setText(
                "部分配置未加载（API 可能正忙 TTS 预热，可关闭后重试）："
                + "；".join(all_issues[:4])
                + ("…" if len(all_issues) > 4 else "")
            )
        else:
            self._load_status.setText("")

    def _boot_tts(self) -> None:
        health = self._api.tts_health()
        if health.get("ok"):
            QMessageBox.information(self, "TTS", "TTS 已就绪（含推理预热）")
            return
        if health.get("server_alive") and not health.get("inference_ready"):
            QMessageBox.information(
                self,
                "TTS",
                "9880 已启动，推理仍在预热中（约 1～8 分钟）。\n请稍候…",
            )
        else:
            self._api.start_tts_server()
            QMessageBox.information(
                self,
                "TTS",
                "正在后台启动 GPT-SoVITS 并完成推理预热（首次约 1～8 分钟）。\n"
                "请稍候或先发文字，首句语音会自动等待预热完成。",
            )
        if self._api.wait_tts_ready(timeout=300):
            QMessageBox.information(self, "TTS", "TTS 已就绪（含推理预热）")
        else:
            detail = self._api.tts_health().get("error") or ""
            QMessageBox.warning(
                self,
                "TTS",
                "仍未完成推理预热。请确认 work_path、参考音频与 9880 端口。\n"
                + (detail if detail else ""),
            )

    def _collect_ui_preferences(self) -> PetUiPreferences:
        prev = load_preferences()
        ui_prefs = replace(
            prev,
            chat_text_color=self._chat_color.hex_color(),
            chat_bg_color=self._chat_bg_color.hex_color(),
            chat_bg_transparency_percent=self._chat_bg_transparency.value(),
            bubble_font_size=self._bubble_font_size.value(),
            bubble_text_color=self._bubble_color.hex_color(),
            bubble_bg_color=self._bubble_bg_color.hex_color(),
            bubble_bg_transparency_percent=self._bubble_bg_transparency.value(),
            page_interval_ms=self._page_interval.value() * 1000,
            voice_output_enabled=self._tts_voice_on.isChecked(),
            stream_bubble_output=self._stream_bubble.isChecked(),
            idle_motion_amplitude=self._idle_amplitude.value(),
        )
        char_id = self._pack_combo.currentData()
        if char_id:
            char_prev = prev.get_for_character(str(char_id))
            ui_prefs.set_for_character(
                str(char_id),
                scale=self._char_scale.value() / 100.0,
                fill=float(self._fill_percent.value()),
                crop=float(self._crop_shrink.value()),
                variant_dir=self._pack_variant_combo.currentData() or "",
                width_px=char_prev.character_width_px,
                height_px=char_prev.character_height_px,
            )
        return ui_prefs

    def _save_ui_preferences(self, *, apply_callback: bool = True) -> PetUiPreferences:
        ui_prefs = self._collect_ui_preferences()
        save_preferences(ui_prefs)
        if apply_callback and self._on_ui_saved:
            char_id = self._pack_combo.currentData()
            self._on_ui_saved(ui_prefs.get_for_character(str(char_id) if char_id else ""))
        return ui_prefs

    def _collect_save_snapshot(self) -> dict:
        char_id = self._pack_combo.currentData()
        payload: dict = {
            "base_url": self._llm_base_url.text().strip().rstrip("/"),
            "model": self._llm_model.currentText().strip(),
            "vision_model": self._llm_vision_model.currentData() or self._llm_vision_model.currentText(),
            "system_prompt": self._system_prompt.text().strip(),
            "thinking_enabled": self._llm_thinking.isChecked(),
            "reasoning_effort": self._llm_reasoning_effort.currentData() or "high",
        }
        api_key = self._llm_api_key.text().strip()
        if api_key:
            payload["api_key"] = api_key
        vision_model = str(
            self._llm_vision_model.currentData() or self._llm_vision_model.currentText() or ""
        ).strip()
        if vision_model:
            upsert_env("DASHSCOPE_VL_MODEL", vision_model)
        if char_id:
            payload["active_character"] = char_id
        energy_th = (
            None
            if self._asr_auto_threshold.isChecked()
            else float(self._asr_energy.value())
        )
        pack_payload: dict | None = None
        if char_id:
            pack_payload = {
                "char_id": str(char_id),
                "name": self._pack_name.text().strip(),
                "character_prompt": self._pack_prompt.toPlainText().strip(),
                "live2d_model_dir": self._pack_live2d.text().strip(),
                "tts": self._tts_payload_from_ui(),
                "memory_core_card": self._pack_core_card.toPlainText().strip(),
                "reply_language": str(self._pack_reply_lang.currentData() or "ja"),
            }
        tr_payload: dict = {
            "enabled": self._tr_enabled.isChecked(),
            "provider": str(self._tr_provider.currentData() or "bing"),
            "app_id": self._tr_app_id.text().strip(),
            "from_lang": "auto-detect",
            "to_lang": "zh-Hans",
        }
        secret = self._tr_secret.text().strip()
        if secret:
            tr_payload["secret"] = secret
        return {
            "char_id": str(char_id) if char_id else "",
            "tts": self._tts_payload_from_ui(),
            "pack": pack_payload,
            "llm": payload,
            "asr": {
                "model": self._asr_model.currentText(),
                "language": self._asr_lang.currentData(),
                "energy_threshold": energy_th,
            },
            "memory": {
                "enabled": self._mem_enabled.isChecked(),
                "extraction_enabled": self._mem_extract.isChecked(),
                "merge_similar_with_llm": self._mem_merge_llm.isChecked(),
                "top_k": self._mem_top_k.value(),
                "core_card": self._pack_core_card.toPlainText().strip(),
            },
            "translate": tr_payload,
        }

    def _save_worker_is_running(self) -> bool:
        worker = self._save_worker
        if worker is None:
            return False
        try:
            return worker.isRunning()
        except RuntimeError:
            # deleteLater 后 C++ 对象已销毁，清空悬空引用
            self._save_worker = None
            return False

    def _detach_save_worker(self, worker: _SaveSettingsWorker) -> None:
        if self._save_worker is worker:
            self._save_worker = None

    def _save_all(self) -> None:
        if self._save_worker_is_running():
            return
        if self._save_btn is not None:
            self._save_btn.setEnabled(False)
            self._save_btn.setText("保存中…")
        try:
            api_key = self._llm_api_key.text().strip()
            if api_key:
                upsert_env("DEEPSEEK_API_KEY", api_key)
            mcp_fields = self._collect_mcp_save_fields()
            mcp_note = self._persist_mcp_config_local(mcp_fields)
            ui_prefs = self._collect_ui_preferences()
            save_preferences(ui_prefs)
            if hasattr(self, "_presence_enabled"):
                save_presence_config(self._collect_presence_config())
                if self._on_presence_saved:
                    self._on_presence_saved()
            snapshot = self._collect_save_snapshot()
            snapshot["mcp_fields"] = mcp_fields
            snapshot["mcp_skip"] = not self._mcp_save_fields_changed(mcp_fields)
            snapshot["mcp_note"] = mcp_note
            char_id = snapshot.get("char_id") or ""
            worker = _SaveSettingsWorker(self._api, snapshot, parent=self)
            self._save_worker = worker

            def _on_ok(done: str) -> None:
                if self._save_btn is not None:
                    self._save_btn.setEnabled(True)
                    self._save_btn.setText("保存设置")
                self._refresh_mcp_save_baseline()

                def _after_save() -> None:
                    QMessageBox.information(self, "已保存", done)
                    if self._on_ui_saved:
                        self._on_ui_saved(ui_prefs.get_for_character(char_id))
                    if char_id and self._on_character_applied:
                        QTimer.singleShot(0, self._on_character_applied)

                QTimer.singleShot(0, _after_save)

            def _on_fail(err: str) -> None:
                if self._save_btn is not None:
                    self._save_btn.setEnabled(True)
                    self._save_btn.setText("保存设置")
                QMessageBox.critical(self, "保存失败", err)

            worker.finished_ok.connect(_on_ok)
            worker.failed.connect(_on_fail)
            worker.finished.connect(lambda w=worker: self._detach_save_worker(w))
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception as exc:
            if self._save_btn is not None:
                self._save_btn.setEnabled(True)
                self._save_btn.setText("保存设置")
            QMessageBox.critical(self, "保存失败", self._format_save_error(exc))
