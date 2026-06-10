"""角色语音库：解析 models/{角色}/[情绪标签]参考文本.wav，导入为 TTS 多标签参考音预设。"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pnn.characters.pack import pack_dir
from pnn.core.paths import PROJECT_ROOT
from pnn.tts.character_layout import (
    character_emotions_dir,
    character_reference_wav,
    relative_ref_audio_path,
    write_prompt_text,
)

logger = logging.getLogger(__name__)

VOICE_EMOTIONS_FILENAME = "voice_emotions.json"
REF_WAV_PATTERN = re.compile(r"^\[([^\]]+)\](.+)\.wav$", re.IGNORECASE)

EMOTION_LABELS: dict[str, str] = {
    "angry": "生气",
    "asking": "疑问",
    "high": "兴奋",
    "ironic": "讽刺",
    "normal1": "平常",
    "normal2": "平常2",
    "soft": "轻柔",
}

# 情绪标签别名 → 参考音标签 id（如 LLM【表情:生气】、中文备注；可按 voice_emotions.json 覆盖）
DEFAULT_TAG_ALIASES: dict[str, str] = {
    "angry": "angry",
    "asking": "asking",
    "high": "high",
    "ironic": "ironic",
    "normal1": "normal1",
    "normal2": "normal2",
    "soft": "soft",
    "生气": "angry",
    "怒": "angry",
    "angry": "angry",
    "疑惑": "asking",
    "疑问": "asking",
    "asking": "asking",
    "开心": "high",
    "兴奋": "high",
    "笑": "high",
    "high": "high",
    "讽刺": "ironic",
    "ironic": "ironic",
    "轻柔": "soft",
    "温柔": "soft",
    "soft": "soft",
    "平常": "normal1",
    "默认": "normal1",
    "normal1": "normal1",
    "normal2": "normal2",
    "hi": "normal1",
    "wink": "normal2",
}


@dataclass
class VoiceClip:
    tag_id: str
    prompt_text: str
    source_wav: Path

    @property
    def label(self) -> str:
        return EMOTION_LABELS.get(self.tag_id, self.tag_id)


@dataclass
class VoiceLibraryManifest:
    character_id: str
    source_dir: str
    gpt_model_path: str = ""
    sovits_model_path: str = ""
    default_emotion_id: str = "normal1"
    active_emotion_id: str = "normal1"
    presets: list[dict] = field(default_factory=list)
    tag_aliases: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def voice_emotions_path(char_id: str) -> Path:
    return pack_dir(char_id) / VOICE_EMOTIONS_FILENAME


def models_voice_dir(char_id: str) -> Path:
    return PROJECT_ROOT / "models" / char_id


def parse_ref_wav_filename(name: str) -> VoiceClip | None:
    m = REF_WAV_PATTERN.match(name.strip())
    if not m:
        return None
    tag_id = m.group(1).strip().lower()
    prompt_text = m.group(2).strip()
    if not tag_id or not prompt_text:
        return None
    return VoiceClip(tag_id=tag_id, prompt_text=prompt_text, source_wav=Path(name))


def scan_voice_clips(source_dir: Path) -> list[VoiceClip]:
    if not source_dir.is_dir():
        return []
    clips: list[VoiceClip] = []
    for path in sorted(source_dir.glob("*.wav")):
        clip = parse_ref_wav_filename(path.name)
        if clip:
            clip.source_wav = path
            clips.append(clip)
    return clips


def discover_weight_paths(source_dir: Path) -> tuple[str, str]:
    ckpts = sorted(source_dir.glob("*.ckpt"))
    pths = sorted(source_dir.glob("*.pth"))
    gpt = ckpts[0] if ckpts else None
    sovits = pths[0] if pths else None
    gpt_rel = gpt.relative_to(PROJECT_ROOT).as_posix() if gpt else ""
    sovits_rel = sovits.relative_to(PROJECT_ROOT).as_posix() if sovits else ""
    return gpt_rel, sovits_rel


def import_voice_library(
    char_id: str,
    source_dir: Path | None = None,
    *,
    copy_wav: bool = True,
    tag_aliases: dict[str, str] | None = None,
) -> VoiceLibraryManifest:
    """扫描 models/{角色}/ 下 [标签]文本.wav，复制到 data/tts/{角色}/emotions/，写入 voice_emotions.json。"""
    cid = char_id.strip()
    src = source_dir or models_voice_dir(cid)
    if not src.is_dir():
        raise FileNotFoundError(f"语音库目录不存在: {src}")

    clips = scan_voice_clips(src)
    if not clips:
        raise ValueError(f"未找到 [情绪标签]文本.wav 格式的参考音: {src}")

    gpt_rel, sovits_rel = discover_weight_paths(src)
    dest_dir = character_emotions_dir(cid)
    presets: list[dict] = []

    for clip in clips:
        dest = dest_dir / f"{clip.tag_id}.wav"
        if copy_wav:
            shutil.copy2(clip.source_wav, dest)
            logger.info("参考音 [%s] → %s", clip.tag_id, dest)
        ref_rel = (
            dest.relative_to(PROJECT_ROOT).as_posix()
            if copy_wav
            else clip.source_wav.relative_to(PROJECT_ROOT).as_posix()
        )
        presets.append(
            {
                "id": clip.tag_id,
                "label": clip.label,
                "ref_audio_path": ref_rel,
                "prompt_text": clip.prompt_text,
                "prompt_lang": "ja",
            }
        )

    default_id = "normal1" if any(p["id"] == "normal1" for p in presets) else presets[0]["id"]
    default_preset = next(p for p in presets if p["id"] == default_id)

    manifest = VoiceLibraryManifest(
        character_id=cid,
        source_dir=src.relative_to(PROJECT_ROOT).as_posix(),
        gpt_model_path=gpt_rel,
        sovits_model_path=sovits_rel,
        default_emotion_id=default_id,
        active_emotion_id=default_id,
        presets=presets,
        tag_aliases={**DEFAULT_TAG_ALIASES, **(tag_aliases or {})},
    )

    out = voice_emotions_path(cid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if copy_wav and default_preset:
        main_ref = character_reference_wav(cid)
        shutil.copy2(dest_dir / f"{default_id}.wav", main_ref)
        write_prompt_text(cid, default_preset["prompt_text"])

    return manifest


def load_voice_emotions(char_id: str) -> VoiceLibraryManifest | None:
    path = voice_emotions_path(char_id)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 voice_emotions.json 失败: %s", exc)
        return None
    presets = raw.get("presets") or []
    return VoiceLibraryManifest(
        character_id=str(raw.get("character_id", char_id)),
        source_dir=str(raw.get("source_dir", "")),
        gpt_model_path=str(raw.get("gpt_model_path", "")),
        sovits_model_path=str(raw.get("sovits_model_path", "")),
        default_emotion_id=str(raw.get("default_emotion_id", "normal1")),
        active_emotion_id=str(raw.get("active_emotion_id", "normal1")),
        presets=presets if isinstance(presets, list) else [],
        tag_aliases=_load_tag_aliases(raw),
    )


def _load_tag_aliases(raw: dict) -> dict[str, str]:
    aliases = raw.get("tag_aliases")
    if isinstance(aliases, dict) and aliases:
        return dict(aliases)
    legacy = raw.get("expression_map")
    if isinstance(legacy, dict) and legacy:
        return dict(legacy)
    return {}


# 根据回复正文关键词推断 TTS 情绪标签（与 Live2D 表情无关）
TTS_TAG_TEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "angry": (
        "怒",
        "ふざけ",
        "ばか",
        "最低",
        "許さ",
        "むかつ",
        "生气",
        "讨厌",
        "烦死了",
        "混蛋",
        "闭嘴",
        "别闹",
    ),
    "asking": (
        "？",
        "?",
        "吗",
        "呢",
        "嘛",
        "なに",
        "なぜ",
        "どうして",
        "どう",
        "えっ",
        "え?",
        "疑问",
        "为什么",
        "怎么",
        "是不是",
    ),
    "high": (
        "笑",
        "嘻",
        "哈哈",
        "开心",
        "喜",
        "嬉しい",
        "楽しい",
        "かわいい",
        "最高",
        "太好了",
        "やった",
        "すごい",
        "兴奋",
        "！！",
        "!!",
    ),
    "ironic": (
        "呵呵",
        "哼",
        "讽刺",
        "就不",
        "才不",
        "まさか",
        "嘘でしょ",
        "骗",
        "可笑",
    ),
    "soft": (
        "恥",
        "照れ",
        "害羞",
        "温柔",
        "悄悄",
        "轻声",
        "ごめん",
        "对不起",
        "抱歉",
        "お願い",
        "拜托",
        "可以吗",
        "……",
        "悲",
        "寂",
        "つら",
    ),
}


def build_llm_emotion_tag_instruction(char_id: str) -> str:
    """注入 LLM：每句句首由 AI 选择 TTS 情绪标签（用户界面不显示）。"""
    lib = load_voice_emotions(char_id)
    if lib is None or not lib.presets:
        return ""
    lines = "\n".join(
        f"- {p.get('id', '')}（{p.get('label') or p.get('id', '')}）" for p in lib.presets
    )
    default = lib.default_emotion_id or "normal1"
    return (
        "【TTS 情绪标签 — 必须遵守，用户界面不会显示这些标签】\n"
        "在每一段完整句子（以 。！？!? 或换行 结束）的**最开头**，"
        "插入且仅插入一个标签，格式严格为：【情绪:标签id】\n"
        "「标签id」必须从下列列表中逐字复制（英文小写 id），由你根据该句语气自行选择：\n"
        f"{lines}\n"
        "可与【表情:…】【动作:…】同句出现；情绪标签应写在句首最前。\n"
        "推荐搭配：high→sway；soft→tilt_head；angry/ironic→shake_head；asking→tilt_head。\n"
        "标签只出现在句首，朗读正文中不得出现「情绪」「【】」等说明字样。\n"
        f"若难以判断，使用【情绪:{default}】。"
    )


def detect_tts_emotion_tag_from_text(text: str, char_id: str) -> str | None:
    """根据 LLM 回复正文推断情绪标签 id，用于选择参考音；无语音库时返回 None。"""
    lib = load_voice_emotions(char_id)
    if lib is None or not lib.presets:
        return None
    allowed = {str(p.get("id", "")).lower() for p in lib.presets}
    body = (text or "").strip()
    if not body:
        default = (lib.default_emotion_id or "").lower()
        return default if default in allowed else None

    best_tag: str | None = None
    best_score = 0
    for tag_id, keywords in TTS_TAG_TEXT_KEYWORDS.items():
        low_id = tag_id.lower()
        if low_id not in allowed:
            continue
        score = sum(1 for k in keywords if k in body)
        if low_id == "asking" and any(c in body for c in "?？"):
            score += 2
        if score > best_score:
            best_score = score
            best_tag = low_id

    if best_tag:
        return best_tag
    default = (lib.default_emotion_id or "").lower()
    return default if default in allowed else None


def resolve_tts_emotion_tag(alias_or_tag: str, char_id: str) -> str | None:
    """将情绪标签或其别名解析为 voice_emotions 中的标签 id；无法匹配时返回 None。"""
    name = (alias_or_tag or "").strip()
    if not name:
        return None
    lib = load_voice_emotions(char_id)
    if lib is None:
        return None
    preset_ids = {str(p.get("id", "")).lower() for p in lib.presets}
    low = name.lower()
    if low in preset_ids:
        return low
    emap = lib.tag_aliases or DEFAULT_TAG_ALIASES
    if name in emap:
        return emap[name]
    if low in emap:
        return emap[low]
    for key, val in emap.items():
        if key in name or name in key:
            return val
    return None


# 兼容旧名
resolve_tts_emotion_id = resolve_tts_emotion_tag


def apply_voice_emotions_to_tts_raw(
    raw: dict,
    manifest: VoiceLibraryManifest,
    *,
    pack_ref: str = "",
    pack_prompt: str = "",
) -> None:
    """将角色语音库写入 tts.json 结构（emotion_presets + 权重路径）。"""
    if manifest.gpt_model_path:
        raw["gpt_model_path"] = manifest.gpt_model_path
    if manifest.sovits_model_path:
        raw["sovits_model_path"] = manifest.sovits_model_path

    default = manifest.default_emotion_id
    active = manifest.active_emotion_id or default
    preset_by_id = {str(p.get("id")): p for p in manifest.presets}

    if active in preset_by_id:
        p = preset_by_id[active]
        raw["ref_audio_path"] = p.get("ref_audio_path") or pack_ref
        raw["prompt_text"] = p.get("prompt_text") or pack_prompt
        raw["prompt_lang"] = p.get("prompt_lang", "ja")
    elif pack_ref:
        raw["ref_audio_path"] = pack_ref
        raw["prompt_text"] = pack_prompt

    raw["emotion_presets"] = manifest.presets
    raw["active_emotion_id"] = active


def merge_voice_library_into_config(cfg: Any, manifest: VoiceLibraryManifest, *, char_id: str) -> None:
    """将 voice_emotions.json 合并进 TtsConfig 运行时对象。"""
    from pnn.tts.config_store import mirror_reference_audio, resolve_model_file_path

    if manifest.gpt_model_path:
        resolved = resolve_model_file_path(manifest.gpt_model_path)
        if Path(resolved).is_file():
            cfg.gpt_model_path = resolved
    if manifest.sovits_model_path:
        resolved = resolve_model_file_path(manifest.sovits_model_path)
        if Path(resolved).is_file():
            cfg.sovits_model_path = resolved

    cfg.emotion_presets = list(manifest.presets)
    cfg.active_emotion_id = manifest.active_emotion_id or manifest.default_emotion_id
    active_preset = next(
        (p for p in manifest.presets if p.get("id") == cfg.active_emotion_id),
        manifest.presets[0] if manifest.presets else None,
    )
    if active_preset:
        ref = str(active_preset.get("ref_audio_path", ""))
        resolved = resolve_model_file_path(ref)
        if Path(resolved).is_file():
            cfg.ref_audio_path = mirror_reference_audio(resolved, char_id=char_id)
        if active_preset.get("prompt_text"):
            cfg.prompt_text = str(active_preset["prompt_text"])
        if active_preset.get("prompt_lang"):
            cfg.prompt_lang = str(active_preset["prompt_lang"])
