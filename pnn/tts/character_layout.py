"""按角色 ID 组织 TTS 参考音、prompt 文本、合成输出与权重路径。"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from pnn.characters.pack import TtsPackSettings, list_pack_ids, load_pack, pack_path, save_pack
from pnn.core.paths import PROJECT_ROOT, character_tts_weight_paths

logger = logging.getLogger(__name__)

CHARACTER_TTS_ROOT = PROJECT_ROOT / "data" / "tts"
LEGACY_REFERENCE_DIR = CHARACTER_TTS_ROOT / "reference"
LEGACY_OUTPUT_DIR = CHARACTER_TTS_ROOT / "output"
LEGACY_FLAT_REF = LEGACY_REFERENCE_DIR / "character_ref.wav"
LEGACY_REF_OWNER = "塞拉"

_SCREENSHOT_HINTS_ROOT = PROJECT_ROOT / "data" / "assets" / "screenshot_hints"
_LEGACY_SCREENSHOT_HINTS = PROJECT_ROOT / "data" / "cache" / "screenshot_hints"

_SAFE_CHAR_RE = re.compile(r"^[\w\u4e00-\u9fff\-]+$", re.UNICODE)

DEFAULT_PROMPT_JA = (
    "思ったより広いんですね。これならゲーム以外のものも開発できますよ。電子ドラッグとか?"
)


def _safe_character_id(char_id: str) -> str:
    cid = (char_id or "").strip()
    if not cid or not _SAFE_CHAR_RE.match(cid):
        raise ValueError(f"角色 ID 无效: {char_id!r}")
    return cid


def list_character_ids() -> list[str]:
    """已配置角色包 ID 列表。"""
    ids = list_pack_ids()
    return ids if ids else [LEGACY_REF_OWNER]


def active_character_id() -> str:
    try:
        from pnn.characters.service import character_pack_service

        character_pack_service.ensure_migrated()
        return _safe_character_id(character_pack_service.get_active_id())
    except Exception:
        return LEGACY_REF_OWNER


def character_tts_dir(char_id: str | None = None) -> Path:
    d = CHARACTER_TTS_ROOT / _safe_character_id(char_id or active_character_id())
    d.mkdir(parents=True, exist_ok=True)
    return d


def character_reference_wav(char_id: str | None = None) -> Path:
    return character_tts_dir(char_id) / "reference.wav"


def character_prompt_file(char_id: str | None = None) -> Path:
    return character_tts_dir(char_id) / "prompt.txt"


def character_emotions_dir(char_id: str | None = None) -> Path:
    d = character_tts_dir(char_id) / "emotions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def character_output_dir(char_id: str | None = None) -> Path:
    d = character_tts_dir(char_id) / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


def relative_ref_audio_path(char_id: str) -> str:
    return f"data/tts/{_safe_character_id(char_id)}/reference.wav"


def relative_prompt_file_path(char_id: str) -> str:
    return f"data/tts/{_safe_character_id(char_id)}/prompt.txt"


def relative_model_paths(char_id: str) -> tuple[str, str]:
    cid = _safe_character_id(char_id)
    return character_tts_weight_paths(cid)


def read_prompt_text(char_id: str) -> str:
    path = character_prompt_file(char_id)
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return ""


def write_prompt_text(char_id: str, text: str) -> None:
    path = character_prompt_file(char_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((text or "").strip() + "\n", encoding="utf-8")


def to_project_relative(path: str | Path) -> str:
    """将项目内绝对路径转为相对路径字符串（便于 pack.json 迁移）。"""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        return str(path).replace("\\", "/")
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT.resolve())
        return rel.as_posix()
    except ValueError:
        return str(p.resolve())


def resolve_project_path(path: str) -> str:
    """解析 pack / 配置中的路径为绝对路径（存在则 resolve）。"""
    raw = (path or "").strip()
    if not raw:
        return raw
    candidate = Path(raw)
    if candidate.is_file():
        return str(candidate.resolve())
    rooted = PROJECT_ROOT / raw
    if rooted.is_file():
        return str(rooted.resolve())
    return raw


def default_tts_pack_settings(char_id: str) -> TtsPackSettings:
    cid = _safe_character_id(char_id)
    gpt_rel, sovits_rel = relative_model_paths(cid)
    prompt = read_prompt_text(cid) or DEFAULT_PROMPT_JA
    return TtsPackSettings(
        ref_audio_path=relative_ref_audio_path(cid),
        prompt_text=prompt,
        prompt_lang="ja",
        text_lang="ja",
        gpt_model_path=gpt_rel,
        sovits_model_path=sovits_rel,
        speed_factor=1.0,
    )


def normalize_tts_pack_settings(
    tts: TtsPackSettings,
    char_id: str,
    *,
    fill_missing: bool = True,
) -> TtsPackSettings:
    """规范为按角色目录的相对路径；必要时从 prompt.txt / 默认布局补全。"""
    cid = _safe_character_id(char_id)
    defaults = default_tts_pack_settings(cid)

    ref = (tts.ref_audio_path or "").strip()
    if ref:
        resolved = resolve_project_path(ref)
        if Path(resolved).is_file():
            tts.ref_audio_path = to_project_relative(resolved)
        elif fill_missing:
            tts.ref_audio_path = defaults.ref_audio_path
    elif fill_missing:
        tts.ref_audio_path = defaults.ref_audio_path

    gpt_rel, sovits_rel = relative_model_paths(cid)
    gpt_resolved = resolve_project_path(tts.gpt_model_path) if (tts.gpt_model_path or "").strip() else ""
    if gpt_resolved and Path(gpt_resolved).is_file():
        owner = Path(gpt_resolved).parent.name
        if owner == cid:
            tts.gpt_model_path = to_project_relative(gpt_resolved)
        else:
            tts.gpt_model_path = gpt_rel
    else:
        tts.gpt_model_path = gpt_rel

    sovits_resolved = (
        resolve_project_path(tts.sovits_model_path) if (tts.sovits_model_path or "").strip() else ""
    )
    if sovits_resolved and Path(sovits_resolved).is_file():
        owner = Path(sovits_resolved).parent.name
        if owner == cid:
            tts.sovits_model_path = to_project_relative(sovits_resolved)
        else:
            tts.sovits_model_path = sovits_rel
    else:
        tts.sovits_model_path = sovits_rel

    prompt = (tts.prompt_text or "").strip()
    if not prompt:
        prompt = read_prompt_text(cid) or defaults.prompt_text
    tts.prompt_text = prompt
    if fill_missing and prompt:
        write_prompt_text(cid, prompt)

    if not (tts.prompt_lang or "").strip():
        tts.prompt_lang = defaults.prompt_lang
    if not (tts.text_lang or "").strip():
        tts.text_lang = defaults.text_lang
    return tts


def pack_tts_from_runtime_config(
    char_id: str,
    *,
    ref_audio_path: str = "",
    prompt_text: str = "",
    prompt_lang: str = "",
    text_lang: str = "",
    gpt_model_path: str = "",
    sovits_model_path: str = "",
    speed_factor: float = 1.0,
) -> TtsPackSettings:
    tts = TtsPackSettings(
        ref_audio_path=ref_audio_path,
        prompt_text=prompt_text,
        prompt_lang=prompt_lang,
        text_lang=text_lang,
        gpt_model_path=gpt_model_path,
        sovits_model_path=sovits_model_path,
        speed_factor=speed_factor,
    )
    return normalize_tts_pack_settings(tts, char_id)


def screenshot_hints_dir(char_id: str | None = None) -> Path:
    d = _SCREENSHOT_HINTS_ROOT / _safe_character_id(char_id or active_character_id())
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_ref_if_missing(src: Path, dest: Path) -> bool:
    if dest.is_file() or not src.is_file():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def migrate_legacy_tts_assets(*, copy_shared_ref: bool = True) -> dict[str, int]:
    """迁移旧平铺 TTS 资源到 data/tts/{角色ID}/，并回写 pack.json。"""
    stats = {"refs": 0, "prompts": 0, "packs": 0, "screenshot_hints": 0}
    ids = list_pack_ids()
    if not ids:
        return stats

    shared_ref_src = LEGACY_FLAT_REF if LEGACY_FLAT_REF.is_file() else None
    if shared_ref_src is None:
        owner_ref = character_reference_wav(LEGACY_REF_OWNER)
        if owner_ref.is_file():
            shared_ref_src = owner_ref

    for cid in ids:
        character_tts_dir(cid)
        character_output_dir(cid)
        character_emotions_dir(cid)
        dest_ref = character_reference_wav(cid)

        if cid == LEGACY_REF_OWNER and LEGACY_FLAT_REF.is_file() and not dest_ref.is_file():
            try:
                shutil.move(str(LEGACY_FLAT_REF), str(dest_ref))
                stats["refs"] += 1
            except OSError as exc:
                logger.warning("迁移参考音到 %s 失败: %s", cid, exc)
        elif copy_shared_ref and shared_ref_src and _copy_ref_if_missing(shared_ref_src, dest_ref):
            stats["refs"] += 1

        pack = load_pack(cid)
        if pack is None:
            continue
        if not (pack.tts.prompt_text or "").strip():
            pack.tts.prompt_text = DEFAULT_PROMPT_JA
        pack.tts = normalize_tts_pack_settings(pack.tts, cid)
        save_pack(pack)
        stats["packs"] += 1
        if character_prompt_file(cid).is_file():
            stats["prompts"] += 1

    if _LEGACY_SCREENSHOT_HINTS.is_dir():
        for wav in _LEGACY_SCREENSHOT_HINTS.glob("screenshot_recognized_*.wav*"):
            if not wav.is_file():
                continue
            target = screenshot_hints_dir(LEGACY_REF_OWNER) / wav.name
            if target.is_file():
                try:
                    wav.unlink()
                except OSError:
                    pass
                continue
            try:
                shutil.move(str(wav), str(target))
                stats["screenshot_hints"] += 1
            except OSError:
                pass

    flat_hints = _SCREENSHOT_HINTS_ROOT.glob("screenshot_recognized_*.wav*")
    for wav in flat_hints:
        if not wav.is_file():
            continue
        target = screenshot_hints_dir(LEGACY_REF_OWNER) / wav.name
        if target.is_file():
            continue
        try:
            shutil.move(str(wav), str(target))
            stats["screenshot_hints"] += 1
        except OSError:
            pass

    return stats


def refresh_all_pack_tts_paths() -> int:
    n = 0
    for cid in list_pack_ids():
        pack = load_pack(cid)
        if pack is None:
            continue
        pack.tts = normalize_tts_pack_settings(pack.tts, cid)
        save_pack(pack)
        n += 1
    return n
