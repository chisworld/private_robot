"""本地模型下载地址登记（供设置页、API、文档复用）。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from pnn.core.env import load_env
from pnn.core.paths import (
    ASR_MODELS_ROOT,
    MODELS_ROOT,
    QWEN_LOCAL_BUNDLE_DIR,
    TTS_MODELS_ROOT,
    _GPT_SOVITS_DIRNAME,
)


@dataclass(frozen=True)
class ModelDownloadLink:
    label: str
    url: str


@dataclass(frozen=True)
class ModelDownloadEntry:
    id: str
    category: str
    name: str
    install_path: str
    description: str
    links: tuple[ModelDownloadLink, ...]


def hf_endpoint() -> str:
    load_env()
    base = (os.getenv("HF_ENDPOINT") or "https://hf-mirror.com").strip().rstrip("/")
    return base or "https://hf-mirror.com"


def hf_repo_url(repo_id: str) -> str:
    return f"{hf_endpoint()}/{repo_id.strip().strip('/')}"


def _entries() -> tuple[ModelDownloadEntry, ...]:
    whisper_root = ASR_MODELS_ROOT / "whisper"
    gpt_sovits_dir = TTS_MODELS_ROOT / _GPT_SOVITS_DIRNAME
    qwen_gguf_repo = "HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive"

    return (
        ModelDownloadEntry(
            id="whisper_tiny",
            category="asr",
            name="Whisper tiny（faster-whisper）",
            install_path=str(whisper_root / "faster_whisper_tiny"),
            description="体积最小，适合试跑；中文识别效果一般。",
            links=(
                ModelDownloadLink("HuggingFace 模型页", hf_repo_url("Systran/faster-whisper-tiny")),
            ),
        ),
        ModelDownloadEntry(
            id="whisper_small",
            category="asr",
            name="Whisper small（faster-whisper，推荐中文）",
            install_path=str(whisper_root / "faster_whisper_small"),
            description="识别中文请用多语言版（不要选带 .en 的英文专用版）。",
            links=(
                ModelDownloadLink("HuggingFace 模型页", hf_repo_url("Systran/faster-whisper-small")),
            ),
        ),
        ModelDownloadEntry(
            id="gpt_sovits_bundle",
            category="tts",
            name="GPT-SoVITS v2pro 整合包",
            install_path=str(gpt_sovits_dir),
            description="须含 api_v2.py 与 runtime/python.exe；解压到 models/TTS/ 下。",
            links=(
                ModelDownloadLink(
                    "GitHub Releases",
                    "https://github.com/RVC-Boss/GPT-SoVITS/releases",
                ),
                ModelDownloadLink(
                    "项目 TTS 资源说明",
                    "https://github.com/chisworld/Pnn_garden/blob/main/docs/TTS_LOCAL_ASSETS.md",
                ),
            ),
        ),
        ModelDownloadEntry(
            id="qwen_gguf",
            category="llm_local",
            name="Qwen3.6-35B-A3B GGUF 主模型",
            install_path=str(QWEN_LOCAL_BUNDLE_DIR / "Models"),
            description=(
                "下载 IQ2_M 等等主 .gguf 放入 Models/；"
                "与项目默认 NSFW 本地对话配套。"
            ),
            links=(
                ModelDownloadLink("HuggingFace 模型页", hf_repo_url(qwen_gguf_repo)),
            ),
        ),
        ModelDownloadEntry(
            id="llama_server",
            category="llm_local",
            name="llama-server（CUDA 版）",
            install_path=str(QWEN_LOCAL_BUNDLE_DIR),
            description=(
                "将 llama-server.exe 与 ggml-cuda.dll 等放入 "
                f"{QWEN_LOCAL_BUNDLE_DIR.name}/；"
                "或使用已打包好的同名目录。"
            ),
            links=(
                ModelDownloadLink(
                    "llama.cpp Releases（选 CUDA 构建）",
                    "https://github.com/ggerganov/llama.cpp/releases",
                ),
            ),
        ),
        ModelDownloadEntry(
            id="qwen_mmproj",
            category="llm_local",
            name="Qwen 视觉 mmproj（可选）",
            install_path=str(QWEN_LOCAL_BUNDLE_DIR / "Models"),
            description="仅在使用 --vision-local 本地识图时需要；默认推荐 DashScope 云端识图。",
            links=(
                ModelDownloadLink("同仓库 Files（mmproj*.gguf）", hf_repo_url(qwen_gguf_repo)),
            ),
        ),
        ModelDownloadEntry(
            id="character_tts_weights",
            category="tts",
            name="角色 GPT / SoVITS 权重",
            install_path=str(MODELS_ROOT / "character/{角色id}"),
            description="各角色 .ckpt / .pth；可用 GPT-SoVITS 训练或从角色包 ZIP 导入。",
            links=(
                ModelDownloadLink(
                    "GPT-SoVITS 训练文档",
                    "https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md",
                ),
            ),
        ),
    )


_MODEL_ENTRIES: tuple[ModelDownloadEntry, ...] = _entries()


def list_model_downloads(*, category: str | None = None) -> list[ModelDownloadEntry]:
    items = list(_MODEL_ENTRIES)
    cat = (category or "").strip().lower()
    if cat:
        items = [e for e in items if e.category == cat]
    return items


def model_downloads_payload(*, category: str | None = None) -> dict[str, Any]:
    items = list_model_downloads(category=category)
    return {
        "hf_endpoint": hf_endpoint(),
        "models_root": str(MODELS_ROOT),
        "entries": [
            {
                **{k: v for k, v in asdict(entry).items() if k != "links"},
                "links": [asdict(link) for link in entry.links],
            }
            for entry in items
        ],
    }
