"""首次安装：创建 venv、安装依赖、初始化 .env 与 config（给最终用户）。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / ".install_done"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
REQ = ROOT / "requirements.txt"
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"
CONFIG_DIR = ROOT / "data" / "config"
TEMPLATE_DIR = ROOT / "config" / "templates"

CONFIG_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("llm.json.example", "llm.json"),
    ("tts.json.example", "tts.json"),
    ("memory.json.example", "memory.json"),
    ("mcp.json.example", "mcp.json"),
    ("translate.json.example", "translate.json"),
    ("launch_apps.json.example", "launch_apps.json"),
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _python_ok() -> bool:
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 11):
        _log(f"[错误] 需要 Python 3.11+，当前 {v.major}.{v.minor}.{v.micro}")
        _log("       请从 https://www.python.org/downloads/ 安装，并勾选 Add to PATH")
        return False
    _log(f"[OK] Python {v.major}.{v.minor}.{v.micro}")
    return True


def _ensure_venv() -> Path:
    if VENV_PY.is_file():
        _log("[OK] 已存在 .venv")
        return VENV_PY
    _log("[步骤] 创建虚拟环境 .venv …")
    subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True, cwd=ROOT)
    if not VENV_PY.is_file():
        raise RuntimeError("创建 .venv 失败")
    _log("[OK] .venv 已创建")
    return VENV_PY


def _pip_install(py: Path) -> None:
    _log("[步骤] 安装 Python 依赖（含 chromadb，可能需要几分钟）…")
    subprocess.run(
        [str(py), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [str(py), "-m", "pip", "install", "-r", str(REQ)],
        check=True,
        cwd=ROOT,
    )
    _log("[OK] requirements.txt 安装完成")


def _ensure_config_files() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in CONFIG_TEMPLATES:
        dst = CONFIG_DIR / dst_name
        if dst.is_file():
            continue
        src = TEMPLATE_DIR / src_name
        if src.is_file():
            shutil.copy2(src, dst)
            _log(f"[OK] 已生成 data/config/{dst_name}")


def _ensure_env(interactive: bool = True) -> None:
    if ENV_FILE.is_file():
        text = ENV_FILE.read_text(encoding="utf-8")
        if re.search(r"DEEPSEEK_API_KEY=\s*sk-[a-zA-Z0-9]", text):
            _log("[OK] .env 已存在且含 DeepSeek Key")
            return
        _log("[提示] .env 存在但未配置有效的 DEEPSEEK_API_KEY")
    elif ENV_EXAMPLE.is_file():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        _log("[OK] 已从 .env.example 创建 .env")
    else:
        ENV_FILE.write_text("DEEPSEEK_API_KEY=\n", encoding="utf-8")

    if not interactive or not sys.stdin.isatty():
        _log("[提示] 请编辑 .env，填入 DEEPSEEK_API_KEY=sk-...")
        return

    _log("")
    _log("请输入 DeepSeek API Key（对话必需，输入 sk- 开头；直接回车则稍后手动编辑 .env）：")
    try:
        key = input("DEEPSEEK_API_KEY> ").strip()
    except EOFError:
        key = ""
    if not key:
        return
    text = ENV_FILE.read_text(encoding="utf-8")
    if "DEEPSEEK_API_KEY=" in text:
        text = re.sub(
            r"DEEPSEEK_API_KEY=.*",
            f"DEEPSEEK_API_KEY={key}",
            text,
            count=1,
        )
    else:
        text = f"DEEPSEEK_API_KEY={key}\n" + text
    ENV_FILE.write_text(text, encoding="utf-8")
    _log("[OK] 已写入 DEEPSEEK_API_KEY")


def _ensure_data_dirs() -> None:
    for sub in ("memory", "logs", "tts/output", "tts/reference"):
        (ROOT / "data" / sub).mkdir(parents=True, exist_ok=True)
    models = ROOT / "models"
    models.mkdir(exist_ok=True)
    for sub in ("ASR/whisper", "TTS", "character"):
        (models / sub).mkdir(parents=True, exist_ok=True)


def _verify_chroma(py: Path) -> None:
    code = (
        "from pnn.memory.store import _chroma_available; "
        "print('ChromaDB:', _chroma_available())"
    )
    try:
        out = subprocess.check_output(
            [str(py), "-c", code],
            cwd=ROOT,
            text=True,
            timeout=60,
        )
        _log(f"[OK] {out.strip()}")
    except Exception as exc:
        _log(f"[警告] ChromaDB 自检失败: {exc}")


def run(*, interactive: bool = True, skip_pip: bool = False) -> int:
    _log("")
    _log("========================================")
    _log("  private_robot 首次安装")
    _log("========================================")
    _log("")

    if not _python_ok():
        return 1

    try:
        py = _ensure_venv()
        if not skip_pip or not MARKER.is_file():
            _pip_install(py)
        _ensure_data_dirs()
        _ensure_config_files()
        _ensure_env(interactive=interactive)
        _verify_chroma(py)
        MARKER.write_text("ok\n", encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        _log(f"[错误] 命令失败: {exc}")
        return exc.returncode or 1
    except Exception as exc:
        _log(f"[错误] {exc}")
        return 1

    _log("")
    _log("========================================")
    _log("  安装完成")
    _log("========================================")
    _log("  下一步：")
    _log("    1. 双击「启动桌宠.bat」")
    _log("    2. TTS 语音：在桌宠设置里点模型下载链接，安装 GPT-SoVITS 整合包")
    _log("    3. 可选 NSFW 本地模型：见 docs/MODEL_DOWNLOADS.md")
    _log("")
    return 0


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="private_robot 首次安装")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--skip-pip", action="store_true", help="仅补 .env/config，不重装 pip")
    args = p.parse_args()
    raise SystemExit(run(interactive=not args.non_interactive, skip_pip=args.skip_pip))


if __name__ == "__main__":
    main()
