"""将 launch 与根目录 .bat 转为 Windows CRLF（LF 会导致 cmd 闪退）。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROOT_STUBS = {
    "启动桌宠.bat": (
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        'if not exist "%~dp0launch\\start_pet.bat" (\r\n'
        "  echo [ERROR] missing launch\\start_pet.bat\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        'call "%~dp0launch\\start_pet.bat"\r\n'
        "if errorlevel 1 pause\r\n"
        "exit /b %ERRORLEVEL%\r\n"
    ),
    "一键启动.bat": (
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        'if not exist "%~dp0launch\\start_garden.bat" (\r\n'
        "  echo [ERROR] missing launch\\start_garden.bat\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        'call "%~dp0launch\\start_garden.bat"\r\n'
        "if errorlevel 1 pause\r\n"
        "exit /b %ERRORLEVEL%\r\n"
    ),
}

LAUNCH_BATS = [
    "launch/start_pet.bat",
    "launch/start_garden.bat",
]


def to_crlf(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def main() -> None:
    for name, content in ROOT_STUBS.items():
        (ROOT / name).write_bytes(content.encode("utf-8"))
        print(f"stub {name}")
    for rel in LAUNCH_BATS:
        p = ROOT / rel.replace("/", "\\")
        to_crlf(p)
        print(f"crlf {rel}")


if __name__ == "__main__":
    main()
