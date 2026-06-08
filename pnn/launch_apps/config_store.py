"""快捷启动配置（data/config/launch_apps.json）。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pnn.core.paths import PROJECT_ROOT

LAUNCH_APPS_CONFIG_PATH = PROJECT_ROOT / "data" / "config" / "launch_apps.json"
LOCAL_SERVER_ID = "local"
LAUNCH_TOOL_NAME = "launch_app"
OPEN_FOLDER_TOOL_NAME = "open_folder"
OPEN_URL_TOOL_NAME = "open_url"


@dataclass
class LaunchAppEntry:
    id: str
    label: str = ""
    aliases: list[str] = field(default_factory=list)
    path: str = ""
    args: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class FolderEntry:
    id: str
    label: str = ""
    aliases: list[str] = field(default_factory=list)
    path: str = ""
    enabled: bool = True


@dataclass
class UrlEntry:
    id: str
    label: str = ""
    aliases: list[str] = field(default_factory=list)
    url: str = ""
    enabled: bool = True


@dataclass
class LaunchAppsConfig:
    enabled: bool = True
    use_in_chat: bool = True
    apps: list[LaunchAppEntry] = field(default_factory=list)
    folders: list[FolderEntry] = field(default_factory=list)
    urls: list[UrlEntry] = field(default_factory=list)


def _safe_str_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _parse_app_entry(raw: object) -> LaunchAppEntry | None:
    if not isinstance(raw, dict):
        return None
    app_id = str(raw.get("id") or "").strip()
    if not app_id:
        return None
    label = str(raw.get("label") or app_id).strip() or app_id
    aliases = _safe_str_list(raw.get("aliases"))
    path = str(raw.get("path") or "").strip()
    args = _safe_str_list(raw.get("args"))
    enabled = bool(raw.get("enabled", True))
    return LaunchAppEntry(
        id=app_id,
        label=label,
        aliases=aliases,
        path=path,
        args=args,
        enabled=enabled,
    )


def _parse_folder_entry(raw: object) -> FolderEntry | None:
    if not isinstance(raw, dict):
        return None
    entry_id = str(raw.get("id") or "").strip()
    if not entry_id:
        return None
    label = str(raw.get("label") or entry_id).strip() or entry_id
    return FolderEntry(
        id=entry_id,
        label=label,
        aliases=_safe_str_list(raw.get("aliases")),
        path=str(raw.get("path") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
    )


def _parse_url_entry(raw: object) -> UrlEntry | None:
    if not isinstance(raw, dict):
        return None
    entry_id = str(raw.get("id") or "").strip()
    if not entry_id:
        return None
    label = str(raw.get("label") or entry_id).strip() or entry_id
    return UrlEntry(
        id=entry_id,
        label=label,
        aliases=_safe_str_list(raw.get("aliases")),
        url=str(raw.get("url") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
    )


def load_launch_apps_config() -> LaunchAppsConfig:
    if not LAUNCH_APPS_CONFIG_PATH.is_file():
        return LaunchAppsConfig()
    try:
        raw = json.loads(LAUNCH_APPS_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return LaunchAppsConfig()
    if not isinstance(raw, dict):
        return LaunchAppsConfig()
    apps: list[LaunchAppEntry] = []
    for item in raw.get("apps") or []:
        entry = _parse_app_entry(item)
        if entry is not None:
            apps.append(entry)
    folders: list[FolderEntry] = []
    for item in raw.get("folders") or []:
        entry = _parse_folder_entry(item)
        if entry is not None:
            folders.append(entry)
    urls: list[UrlEntry] = []
    for item in raw.get("urls") or []:
        entry = _parse_url_entry(item)
        if entry is not None:
            urls.append(entry)
    return LaunchAppsConfig(
        enabled=bool(raw.get("enabled", True)),
        use_in_chat=bool(raw.get("use_in_chat", True)),
        apps=apps,
        folders=folders,
        urls=urls,
    )


def save_launch_apps_config(cfg: LaunchAppsConfig) -> None:
    LAUNCH_APPS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "enabled": bool(cfg.enabled),
        "use_in_chat": bool(cfg.use_in_chat),
        "apps": [asdict(a) for a in cfg.apps],
        "folders": [asdict(f) for f in cfg.folders],
        "urls": [asdict(u) for u in cfg.urls],
    }
    LAUNCH_APPS_CONFIG_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
