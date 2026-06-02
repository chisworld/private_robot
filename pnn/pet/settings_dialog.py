"""桌宠设置：ASR / TTS / LLM / 界面。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
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
from pnn.pet.ui_constants import (
    CHARACTER_SCALE_MAX,
    CHARACTER_SCALE_MIN,
    CHARACTER_SCALE_SPIN_STEP_PERCENT,
)
from pnn.pet.volume_meter_widget import VolumeMeterWidget
from pnn.pet.settings_styles import SETTINGS_DIALOG_QSS

LLM_PROVIDER_PRESETS: list[tuple[str, str, str]] = [
    ("DeepSeek", "https://api.deepseek.com", "deepseek-chat"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("自定义", "", ""),
]


class _RemoteConfigLoader(QThread):
    """在后台拉取 LLM/TTS/ASR 配置，避免阻塞设置窗主线程。"""

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, api: PetApiClient, parent=None) -> None:
        super().__init__(parent)
        self._api = api

    def run(self) -> None:
        try:
            self.finished_ok.emit(
                {
                    "chat": self._api.get_chat_config(),
                    "characters": self._api.list_characters(),
                    "packs": self._api.list_character_packs(),
                    "memory": self._api.get_memory_config(),
                    "memories": self._api.list_memories(80),
                    "translate": self._api.get_translate_config(),
                    "tts": self._api.get_tts_config(),
                    "asr": self._api.get_asr_config(),
                }
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class SettingsDialog(QDialog):
    def __init__(
        self,
        api: PetApiClient,
        *,
        on_ui_saved: Callable[[PetUiPreferences], None] | None = None,
        on_character_applied: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._on_ui_saved = on_ui_saved
        self._on_character_applied = on_character_applied
        self._active_pack_id = ""
        self.setWindowTitle("桌宠设置")
        self.setMinimumSize(440, 520)
        self.resize(480, 580)
        self.setStyleSheet(SETTINGS_DIALOG_QSS)

        title = QLabel("桌宠设置")
        title.setObjectName("dialogTitle")

        tabs = QTabWidget()
        tabs.addTab(self._build_ui_tab(), "界面")
        tabs.addTab(self._build_character_tab(), "角色")
        tabs.addTab(self._build_memory_tab(), "记忆")
        tabs.addTab(self._build_llm_tab(), "LLM")
        tabs.addTab(self._build_tts_tab(), "TTS")
        tabs.addTab(self._build_asr_tab(), "ASR")

        save_btn = QPushButton("保存设置")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save_all)
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryBtn")
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

        layout.addWidget(title)
        layout.addWidget(self._load_status)
        layout.addWidget(tabs, stretch=1)
        layout.addLayout(footer)

        self._remote_loader: _RemoteConfigLoader | None = None
        self._asr_probe = AsrSession(self._api, parent=self)
        self._asr_probe.level_changed.connect(self._on_probe_level)
        self._asr_probe.error_occurred.connect(self._on_probe_error)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_remote_load()

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
        self._load_status.setText(
            f"远程配置加载失败：{err}\n界面项仍可使用，LLM/TTS/ASR 请确认 API(8765) 已启动。"
        )

    def closeEvent(self, event) -> None:
        self._stop_asr_test()
        if self._remote_loader is not None and self._remote_loader.isRunning():
            self._remote_loader.wait(3000)
        self._remote_loader = None
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_asr_test()
        super().reject()

    def accept(self) -> None:
        self._stop_asr_test()
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
        outer.addWidget(g_bubble)

        # —— 人物显示 ——
        g_char, form_c = self._form_group("人物显示", "贴边与裁剪可减少人物四周留白。")
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

        self._llm_model = QLineEdit()
        self._llm_model.setPlaceholderText("deepseek-chat")
        form_base.addRow("模型 ID", self._llm_model)
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
            "气泡中文显示（百度翻译）",
            "开启后：AI 仍按上方语言生成原文，TTS 朗读原文；"
            "气泡里显示翻译成中文后的文字。需百度翻译开放平台 AppID/密钥。",
        )
        self._tr_enabled = QCheckBox("启用：气泡显示中文，TTS 用原文")
        form_tr.addRow("", self._tr_enabled)
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
            "对话后自动提取记忆；相似记忆用 LLM 合并（可关闭则仅文本相似覆盖）。",
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
        mem_hint = QLabel("删除后不可恢复；切换角色请在「角色」页操作。")
        mem_hint.setObjectName("sectionHint")
        mem_hint.setWordWrap(True)
        lay_list.addWidget(mem_hint)
        self._mem_list = QListWidget()
        self._mem_list.setMinimumHeight(160)
        lay_list.addWidget(self._mem_list)
        row = QHBoxLayout()
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.setObjectName("ghostBtn")
        refresh_btn.clicked.connect(self._refresh_memory_list)
        del_btn = QPushButton("删除选中")
        del_btn.setObjectName("ghostBtn")
        del_btn.clicked.connect(self._delete_selected_memory)
        row.addWidget(refresh_btn)
        row.addWidget(del_btn)
        row.addStretch(1)
        lay_list.addLayout(row)
        layout.addWidget(g_list)
        layout.addStretch(1)
        return self._scroll_tab(w)

    def _on_pack_combo_changed(self, _index: int) -> None:
        cid = self._pack_combo.currentData()
        if not cid or cid == self._active_pack_id:
            return
        try:
            pack = self._api.get_character_pack(str(cid))
            self._fill_pack_fields(pack)
            self._active_pack_id = str(cid)
        except Exception:
            pass

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

    def _tts_payload_for_pack(self) -> dict:
        try:
            tts = self._api.get_tts_config()
        except Exception:
            return {}
        return {
            "ref_audio_path": tts.get("ref_audio_path", "") or "",
            "prompt_text": tts.get("prompt_text", "") or "",
            "prompt_lang": tts.get("prompt_lang", "ja"),
            "text_lang": tts.get("text_lang", "ja"),
            "gpt_model_path": tts.get("gpt_model_path", "") or "",
            "sovits_model_path": tts.get("sovits_model_path", "") or "",
            "speed_factor": float(tts.get("speed_factor", 1.0)),
        }

    def _apply_character_now(self) -> None:
        try:
            self._save_current_pack()
            cid = self._pack_combo.currentData()
            if not cid:
                QMessageBox.warning(self, "角色", "请先选择角色")
                return
            self._api.apply_character_pack(str(cid))
            self._api.reload_chat_config()
            if self._on_character_applied:
                self._on_character_applied()
            QMessageBox.information(
                self,
                "角色",
                f"已切换到「{self._pack_name.text() or cid}」。"
                "Live2D 已尝试重载；若未变化请重启桌宠。",
            )
        except Exception as exc:
            QMessageBox.critical(self, "角色", str(exc))

    def _save_current_pack(self) -> None:
        cid = self._pack_combo.currentData()
        if not cid:
            return
        self._api.save_character_pack(
            str(cid),
            name=self._pack_name.text().strip(),
            character_prompt=self._pack_prompt.toPlainText().strip(),
            live2d_model_dir=self._pack_live2d.text().strip(),
            tts=self._tts_payload_for_pack(),
            memory_core_card=self._pack_core_card.toPlainText().strip(),
            reply_language=str(self._pack_reply_lang.currentData() or "ja"),
        )

    def _refresh_memory_list(self) -> None:
        try:
            items = self._api.list_memories(100)
            self._mem_list.clear()
            for it in items:
                line = f"[{it.get('kind', 'fact')}] {it.get('content', '')}"
                self._mem_list.addItem(f"{it.get('id', '')} | {line[:120]}")
                row = self._mem_list.item(self._mem_list.count() - 1)
                if row is not None:
                    row.setData(Qt.ItemDataRole.UserRole, it.get("id"))
        except Exception as exc:
            QMessageBox.warning(self, "记忆", f"加载失败：{exc}")

    def _delete_selected_memory(self) -> None:
        item = self._mem_list.currentItem()
        if item is None:
            return
        mid = item.data(Qt.ItemDataRole.UserRole)
        if not mid:
            return
        try:
            self._api.delete_memory(str(mid))
            self._refresh_memory_list()
        except Exception as exc:
            QMessageBox.warning(self, "记忆", str(exc))

    def _on_llm_provider_changed(self, index: int) -> None:
        if index < 0 or index >= len(LLM_PROVIDER_PRESETS):
            return
        name, base, model = LLM_PROVIDER_PRESETS[index]
        if name == "自定义":
            return
        if base:
            self._llm_base_url.setText(base)
        if model:
            self._llm_model.setText(model)

    def _build_tts_tab(self) -> QWidget:
        ui = load_preferences()
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        g_mode, form_mode = self._form_group(
            "朗读方式",
            "与网页对话一致：分句朗读首句更快，整段朗读更连贯。",
        )
        self._tts_sentence = QRadioButton("分句朗读")
        self._tts_full = QRadioButton("整段朗读")
        if ui.tts_speak_mode == "sentence":
            self._tts_sentence.setChecked(True)
        else:
            self._tts_full.setChecked(True)
        tts_row = QHBoxLayout()
        tts_row.addWidget(self._tts_sentence)
        tts_row.addWidget(self._tts_full)
        tts_row.addStretch(1)
        tts_wrap = QWidget()
        tts_wrap.setLayout(tts_row)
        form_mode.addRow("", tts_wrap)
        layout.addWidget(g_mode)

        g, form = self._form_group("语音合成", "GPT-SoVITS 等引擎参数。")
        self._tts_provider = QComboBox()
        self._tts_provider.addItems(["gpt-sovits", "genie-tts", "index-tts", "cosyvoice"])
        form.addRow("引擎", self._tts_provider)
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
            self._llm_model.setText(chat.get("model", "") or "")
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
                    pack = self._api.get_character_pack(active)
                    self._fill_pack_fields(pack)
                    self._active_pack_id = active
                except Exception:
                    pass
        except Exception as exc:
            errors.append(f"LLM/角色: {exc}")

        try:
            mem_cfg = data.get("memory") or {}
            self._mem_enabled.setChecked(bool(mem_cfg.get("enabled", True)))
            self._mem_extract.setChecked(bool(mem_cfg.get("extraction_enabled", True)))
            self._mem_merge_llm.setChecked(bool(mem_cfg.get("merge_similar_with_llm", True)))
            self._mem_top_k.setValue(int(mem_cfg.get("top_k", 5)))
            self._mem_list.clear()
            for it in data.get("memories") or []:
                line = f"[{it.get('kind', 'fact')}] {it.get('content', '')}"
                self._mem_list.addItem(f"{it.get('id', '')} | {line[:120]}")
                row = self._mem_list.item(self._mem_list.count() - 1)
                if row is not None:
                    row.setData(Qt.ItemDataRole.UserRole, it.get("id"))
        except Exception as exc:
            errors.append(f"记忆: {exc}")

        try:
            tr = data.get("translate") or {}
            self._tr_enabled.setChecked(bool(tr.get("enabled")))
            self._tr_app_id.setText(tr.get("app_id", "") or "")
            if tr.get("configured"):
                self._tr_secret.setPlaceholderText("已配置，留空则不修改")
            else:
                self._tr_secret.setPlaceholderText("百度翻译密钥")
            self._tr_secret.clear()
        except Exception as exc:
            errors.append(f"翻译: {exc}")

        try:
            tts = data.get("tts") or {}
            pidx = self._tts_provider.findText(tts.get("provider", "gpt-sovits"))
            if pidx >= 0:
                self._tts_provider.setCurrentIndex(pidx)
            self._tts_ref.setText(tts.get("ref_audio_path", "") or "")
            self._tts_prompt.setText(tts.get("prompt_text", "") or "")
            lidx = self._tts_lang.findText(tts.get("text_lang", "zh"))
            if lidx >= 0:
                self._tts_lang.setCurrentIndex(lidx)
            self._tts_speed.setValue(float(tts.get("speed_factor", 1.0)))
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

        if errors:
            self._load_status.setText("部分配置未加载：" + "；".join(errors))
        else:
            self._load_status.setText("")

    def _boot_tts(self) -> None:
        health = self._api.tts_health()
        if health.get("ok"):
            QMessageBox.information(self, "TTS", "TTS 服务已就绪")
            return
        self._api.start_tts_server()
        QMessageBox.information(
            self,
            "TTS",
            "正在后台启动 GPT-SoVITS（首次约 1–3 分钟）。\n"
            "请稍后再点「启动 TTS 服务」确认，或直接发一条消息测试语音。",
        )
        if self._api.wait_tts_ready(timeout=30):
            QMessageBox.information(self, "TTS", "TTS 服务已就绪")
        else:
            QMessageBox.warning(
                self,
                "TTS",
                "仍未就绪。请确认 data/config/tts.json 的 work_path 正确，"
                "且 9880 端口未被占用。",
            )

    def _save_all(self) -> None:
        try:
            prev = load_preferences()
            ui_prefs = PetUiPreferences(
                chat_font_size=prev.chat_font_size,
                chat_text_color=self._chat_color.hex_color(),
                chat_bg_color=self._chat_bg_color.hex_color(),
                chat_bg_transparency_percent=self._chat_bg_transparency.value(),
                chat_font_family=prev.chat_font_family,
                bubble_font_size=self._bubble_font_size.value(),
                bubble_font_family=prev.bubble_font_family,
                use_imported_font=prev.use_imported_font,
                bubble_width_px=prev.bubble_width_px,
                bubble_height_px=prev.bubble_height_px,
                bubble_text_color=self._bubble_color.hex_color(),
                bubble_bg_color=self._bubble_bg_color.hex_color(),
                bubble_bg_transparency_percent=self._bubble_bg_transparency.value(),
                page_interval_ms=self._page_interval.value() * 1000,
                character_scale=self._char_scale.value() / 100.0,
                fill_percent=float(self._fill_percent.value()),
                crop_shrink_percent=float(self._crop_shrink.value()),
                bubble_v_center_percent=prev.bubble_v_center_percent,
                bubble_gap_px=prev.bubble_gap_px,
                asr_always_on=prev.asr_always_on,
                tts_speak_mode=(
                    "sentence" if self._tts_sentence.isChecked() else "full"
                ),
            )
            save_preferences(ui_prefs)
            if self._on_ui_saved:
                self._on_ui_saved(ui_prefs)

            self._save_current_pack()
            char_id = self._pack_combo.currentData()
            payload: dict = {
                "base_url": self._llm_base_url.text().strip().rstrip("/"),
                "model": self._llm_model.text().strip(),
                "system_prompt": self._system_prompt.text().strip(),
            }
            api_key = self._llm_api_key.text().strip()
            if api_key:
                payload["api_key"] = api_key
                upsert_env("DEEPSEEK_API_KEY", api_key)
            if char_id:
                payload["active_character"] = char_id
                self._api.apply_character_pack(str(char_id))
                if self._on_character_applied:
                    self._on_character_applied()
            llm_cfg = self._api.update_chat_config(**payload)
            try:
                self._api.reload_chat_config()
            except Exception:
                pass
            self._api.update_tts_config(
                provider=self._tts_provider.currentText(),
                ref_audio_path=self._tts_ref.text().strip(),
                prompt_text=self._tts_prompt.text().strip(),
                text_lang=self._tts_lang.currentText(),
                speed_factor=self._tts_speed.value(),
            )
            energy_th = (
                None
                if self._asr_auto_threshold.isChecked()
                else float(self._asr_energy.value())
            )
            self._api.update_asr_config(
                model=self._asr_model.currentText(),
                language=self._asr_lang.currentData(),
                energy_threshold=energy_th,
            )
            self._api.update_memory_config(
                enabled=self._mem_enabled.isChecked(),
                extraction_enabled=self._mem_extract.isChecked(),
                merge_similar_with_llm=self._mem_merge_llm.isChecked(),
                top_k=self._mem_top_k.value(),
                core_card=self._pack_core_card.toPlainText().strip(),
            )
            tr_payload: dict = {
                "enabled": self._tr_enabled.isChecked(),
                "app_id": self._tr_app_id.text().strip(),
                "from_lang": "jp",
                "to_lang": "zh",
            }
            secret = self._tr_secret.text().strip()
            if secret:
                tr_payload["secret"] = secret
            self._api.update_translate_config(**tr_payload)
            done = "设置已保存并生效"
            if not llm_cfg.get("configured"):
                done += (
                    "\n\n提示：尚未配置 LLM API Key，对话会失败。"
                    "请在「LLM」页填写 Key，或在项目根 .env 设置 DEEPSEEK_API_KEY。"
                )
            QMessageBox.information(self, "已保存", done)
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
