from __future__ import annotations

import os
from pathlib import Path

# pnn_garden 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------- 目录分类（见 docs/PROJECT_LAYOUT.md）----------
APPS_DIR = PROJECT_ROOT / "apps"
SERVER_DIR = PROJECT_ROOT / "server"
PNN_PKG_DIR = PROJECT_ROOT / "pnn"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
CLI_DIR = PROJECT_ROOT / "cli"
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"
# MCP 浏览器下载归类根目录：data/mcp/{网站}/{images|videos|...}/{文件名}
MCP_STORAGE_DIR = DATA_DIR / "mcp"
MCP_STORAGE_STAGING_DIR = MCP_STORAGE_DIR / "_staging"
# 兼容旧路径（MCP 已改用 data/mcp）
DOWNLOADS_DIR = DATA_DIR / "downloads"
CONFIG_TEMPLATES_DIR = PROJECT_ROOT / "config" / "templates"
ASSETS_DIR = PROJECT_ROOT / "assets"
DOCS_DIR = PROJECT_ROOT / "docs"
CUDA_DLL_DIR = PROJECT_ROOT / "CUDA_DLL"
CACHE_DIR = PROJECT_ROOT / "cache"  # audio/、tmp/ 等，见 pnn.core.runtime_files

# 模型资源（项目根 models/，与 data/config 配置分离）
MODELS_ROOT = PROJECT_ROOT / "models"
ASR_MODELS_ROOT = MODELS_ROOT / "ASR"
TTS_MODELS_ROOT = MODELS_ROOT / "TTS"
CHARACTER_MODELS_ROOT = MODELS_ROOT / "character"


def character_tts_weight_paths(char_id: str) -> tuple[str, str]:
    """角色权重相对路径：优先 models/{id}/*.ckpt|.pth，否则 models/character/{id}/{id}.ckpt|.pth。"""
    cid = (char_id or "").strip()
    if not cid:
        return "", ""
    model_dir = MODELS_ROOT / cid
    if model_dir.is_dir():
        ckpts = sorted(model_dir.glob("*.ckpt"))
        pths = sorted(model_dir.glob("*.pth"))
        if ckpts and pths:
            return (
                ckpts[0].relative_to(PROJECT_ROOT).as_posix(),
                pths[0].relative_to(PROJECT_ROOT).as_posix(),
            )
    base = f"models/character/{cid}"
    return f"{base}/{cid}.ckpt", f"{base}/{cid}.pth"
LIVE2D_ROOT = PROJECT_ROOT / "live2d"
# 兼容曾放在 assets/live2d 下的布局
_LEGACY_LIVE2D_ROOT = ASSETS_DIR / "live2d"

# 兼容旧路径（迁移前）
_LEGACY_MODELS_DIR = DATA_DIR / "models"
_LEGACY_WHISPER_ROOT = _LEGACY_MODELS_DIR / "whisper"

_GPT_SOVITS_DIRNAME = "GPT-SoVITS-v2pro-20250604"
_DEFAULT_API_HOST = "127.0.0.1"
_DEFAULT_API_PORT = "8765"


def api_base_url() -> str:
    """本地 FastAPI 网关根 URL（无尾部斜杠）。读取 PNN_API_HOST / PNN_API_PORT。"""
    from pnn.core.env import load_env

    load_env()
    host = os.getenv("PNN_API_HOST", _DEFAULT_API_HOST).strip() or _DEFAULT_API_HOST
    port = os.getenv("PNN_API_PORT", _DEFAULT_API_PORT).strip() or _DEFAULT_API_PORT
    return f"http://{host}:{port}"


def api_ws_asr_url() -> str:
    """ASR WebSocket 地址（/ws/asr）。"""
    base = api_base_url()
    if base.startswith("https://"):
        root = "wss://" + base[len("https://") :]
    else:
        root = "ws://" + base[len("http://") :]
    return f"{root}/ws/asr"


def _find_model3_json(directory: Path) -> Path | None:
    """Return the first model3.json found in the directory, or None."""
    if not directory.is_dir():
        return None
    candidates = sorted(directory.glob("*.model3.json"))
    return candidates[0] if candidates else None


def _live2d_model_candidates() -> list[Path]:
    return [
        LIVE2D_ROOT / "吸血姬模型本体",
        LIVE2D_ROOT / "14酱",
        LIVE2D_ROOT / "塞拉" / "pink_devil",
        LIVE2D_ROOT / "塞拉" / "xizaozhao",
        LIVE2D_ROOT / "里想奈",
        _LEGACY_LIVE2D_ROOT / "14酱",
        PROJECT_ROOT / "launch" / "assets" / "live2d" / "14酱",
        APPS_DIR / "web" / "public" / "live2d" / "models" / "14酱",
        PROJECT_ROOT / "14酱",
    ]


_live2d_cache_key: str | None = None
_live2d_cached_dir: Path | None = None
_live2d_cached_json: Path | None = None


def _live2d_resolve_cache_key() -> str:
    override = os.getenv("LIVE2D_MODEL_DIR", "").strip()
    if override:
        return f"env:{override}"
    try:
        from pnn.characters.service import character_pack_service

        pack = character_pack_service.get_active_pack()
        if pack is not None:
            return f"pack:{pack.id}:{pack.live2d_model_dir}"
    except Exception:
        pass
    return "default"


def invalidate_live2d_path_cache() -> None:
    """角色切换或模型路径变更后调用，避免沿用旧缓存。"""
    global _live2d_cache_key, _live2d_cached_dir, _live2d_cached_json
    _live2d_cache_key = None
    _live2d_cached_dir = None
    _live2d_cached_json = None
    try:
        from pnn.pet import paths as pet_paths

        pet_paths.invalidate_model_paths()
    except ImportError:
        pass


def _resolve_live2d_model_dir() -> Path:
    """Live2D 桌宠模型目录（环境变量 > 当前角色包 > live2d/14酱 > 旧路径）。"""
    override = os.getenv("LIVE2D_MODEL_DIR", "").strip()
    if override:
        p = Path(override)
        if _find_model3_json(p):
            return p
    try:
        from pnn.characters.service import character_pack_service

        character_pack_service.ensure_migrated()
        pack = character_pack_service.get_active_pack()
        if pack is not None:
            d = pack.resolve_live2d_dir()
            if _find_model3_json(d):
                return d
    except Exception:
        pass
    for candidate in _live2d_model_candidates():
        if _find_model3_json(candidate):
            return candidate
    return _live2d_model_candidates()[0]


def live2d_model_dir() -> Path:
    """Live2D 桌宠模型目录（环境变量 > 当前角色包 > live2d/14酱 > 旧路径）。"""
    global _live2d_cache_key, _live2d_cached_dir, _live2d_cached_json
    key = _live2d_resolve_cache_key()
    if _live2d_cached_dir is not None and _live2d_cache_key == key:
        return _live2d_cached_dir
    resolved = _resolve_live2d_model_dir()
    _live2d_cache_key = key
    _live2d_cached_dir = resolved
    _live2d_cached_json = None
    return resolved


def live2d_model_json() -> Path:
    """Return the full path to the discovered model3.json file."""
    global _live2d_cache_key, _live2d_cached_json
    key = _live2d_resolve_cache_key()
    if _live2d_cached_json is not None and _live2d_cache_key == key:
        return _live2d_cached_json
    model_dir = live2d_model_dir()
    found = _find_model3_json(model_dir)
    resolved = found if found else model_dir / "我也要死吗.model3.json"
    _live2d_cached_json = resolved
    return resolved


def _whisper_roots() -> list[Path]:
    roots = [ASR_MODELS_ROOT / "whisper", _LEGACY_WHISPER_ROOT]
    seen: set[Path] = set()
    ordered: list[Path] = []
    for r in roots:
        p = r.resolve()
        if p not in seen and p.is_dir():
            seen.add(p)
            ordered.append(p)
    return ordered


def _gpt_sovits_bundle_candidates() -> list[Path]:
    return [TTS_MODELS_ROOT / _GPT_SOVITS_DIRNAME]


def _resolve_existing_dir(path: Path) -> Path | None:
    """相对路径按项目根解析，便于 tts.json 写 models/TTS/...。"""
    for candidate in (path, PROJECT_ROOT / path if not path.is_absolute() else path):
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except OSError:
            continue
    return None


def resolve_gpt_sovits_bundle() -> Path | None:
    """返回含 api_v2.py 的 GPT-SoVITS 整合包目录（仅 models/TTS 布局）。"""
    seen_real: set[str] = set()

    def _remember(p: Path) -> bool:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p.absolute())
        if key in seen_real:
            return False
        seen_real.add(key)
        return True

    def _ok(p: Path) -> bool:
        return (p / "api_v2.py").is_file() and (p / "runtime" / "python.exe").is_file()

    for raw in _gpt_sovits_bundle_candidates():
        base = raw.expanduser()
        if not _remember(base):
            continue
        if _ok(base):
            return base.absolute()
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if not child.is_dir() or not _remember(child):
                    continue
                if _ok(child):
                    return child.absolute()
    return None


LOCAL_MODEL_DIRS: dict[str, str] = {
    "tiny": "faster_whisper_tiny",
    "small": "faster_whisper_small",
}

REMOTE_MODELS: list[str] = [
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
]


def resolve_local_model_path(model: str) -> str | None:
    """若本地已存在对应 Whisper 模型目录则返回绝对路径。"""
    folder = LOCAL_MODEL_DIRS.get(model)
    if not folder:
        return None
    for root in _whisper_roots():
        path = root / folder
        if (path / "model.bin").is_file():
            return str(path.resolve())
    return None


# 旧代码仍引用 MODELS_DIR 时指向 ASR/whisper
MODELS_DIR = ASR_MODELS_ROOT / "whisper"


def list_available_models() -> list[str]:
    """优先返回已下载到本地的模型；否则回退到完整列表。"""
    local = [name for name in LOCAL_MODEL_DIRS if resolve_local_model_path(name)]
    return local if local else REMOTE_MODELS


def is_english_only_model(path: str | Path) -> bool:
    """检测是否为 .en 英文专用模型（不支持中文）。"""
    model_dir = Path(path)
    readme = model_dir / "README.md"
    if not readme.is_file():
        return False
    text = readme.read_text(encoding="utf-8", errors="ignore").lower()
    markers = (
        "whisper-tiny.en",
        "whisper-small.en",
        "whisper-base.en",
        "whisper-medium.en",
        "whisper-large.en",
        "faster-whisper-tiny.en",
        "faster-whisper-small.en",
    )
    return any(marker in text for marker in markers)


def model_info(path: str | Path | None) -> dict[str, object]:
    if not path:
        return {"multilingual": True, "warning": None}
    if is_english_only_model(path):
        return {
            "multilingual": False,
            "warning": (
                "当前模型是英文专用版（.en），无法识别中文。"
                "请从 HuggingFace 下载多语言版本（不要选带 .en 的）："
                "Systran/faster-whisper-small，解压到 "
                "models/ASR/whisper/faster_whisper_small"
            ),
        }
    return {"multilingual": True, "warning": None}
