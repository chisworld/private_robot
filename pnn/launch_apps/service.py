"""白名单程序/文件夹/网址启动与 local 工具。"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pnn.launch_apps.config_store import (
    LAUNCH_APPS_CONFIG_PATH,
    LAUNCH_TOOL_NAME,
    LOCAL_SERVER_ID,
    OPEN_FOLDER_TOOL_NAME,
    OPEN_URL_TOOL_NAME,
    FolderEntry,
    LaunchAppEntry,
    LaunchAppsConfig,
    UrlEntry,
    load_launch_apps_config,
    save_launch_apps_config,
)
from pnn.launch_apps.ingest import (
    aliases_for_label,
    ensure_unique_app_ids,
    is_launchable_path,
    label_from_path,
    normalize_match_text,
    slug_from_label,
)
from pnn.mcp.service import llm_tool_name

logger = logging.getLogger(__name__)

FailNotifier = Callable[[str, str], None]
_LAUNCHABLE_SUFFIXES = {".exe", ".bat", ".cmd", ".com", ".lnk"}


class LaunchAppsService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = load_launch_apps_config()
        self._fail_notifiers: list[FailNotifier] = []

    def register_fail_notifier(self, cb: FailNotifier) -> None:
        if cb not in self._fail_notifiers:
            self._fail_notifiers.append(cb)

    def _notify_fail(self, kind: str, detail: str) -> None:
        title = (kind or "打开失败").strip()
        msg = (detail or "未知错误").strip()
        logger.warning("%s: %s", title, msg)
        for cb in list(self._fail_notifiers):
            try:
                cb(title, msg)
            except Exception:
                logger.debug("fail notifier 回调异常", exc_info=True)

    def reload_config(self) -> LaunchAppsConfig:
        with self._lock:
            cfg = load_launch_apps_config()
            apps, changed = ensure_unique_app_ids(cfg.apps)
            if changed:
                cfg.apps = apps
                save_launch_apps_config(cfg)
            self._config = cfg
            return self._config

    def _sync_from_disk(self) -> LaunchAppsConfig:
        """对话/工具调用前从磁盘重载，避免桌宠拖入快捷方式后 8765 进程仍用旧白名单。"""
        return self.reload_config()

    def _entry_exists(self, path: Path, *, expect_dir: bool) -> bool:
        try:
            if expect_dir:
                return path.is_dir()
            if path.is_file():
                return True
            if os.name == "nt" and path.suffix.lower() == ".lnk":
                return path.is_file()
            return False
        except OSError:
            return False

    def _serialize_entries(
        self,
        entries: list[LaunchAppEntry | FolderEntry | UrlEntry],
        *,
        path_key: str = "path",
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in entries:
            payload = {**asdict(entry)}
            if path_key in payload and payload[path_key]:
                p = Path(str(payload[path_key]))
                if path_key == "path":
                    payload["path_exists"] = self._entry_exists(
                        p,
                        expect_dir=isinstance(entry, FolderEntry),
                    )
                elif path_key == "url":
                    payload["url_valid"] = bool(str(payload["url"]).strip())
            out.append(payload)
        return out

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            cfg = self._config
            return {
                "enabled": cfg.enabled,
                "use_in_chat": cfg.use_in_chat,
                "apps": self._serialize_entries(cfg.apps),
                "folders": self._serialize_entries(cfg.folders),
                "urls": self._serialize_entries(cfg.urls, path_key="url"),
                "config_path": str(LAUNCH_APPS_CONFIG_PATH),
            }

    def update_config(
        self,
        *,
        enabled: bool | None = None,
        use_in_chat: bool | None = None,
        apps: list[dict[str, Any]] | None = None,
        folders: list[dict[str, Any]] | None = None,
        urls: list[dict[str, Any]] | None = None,
    ) -> LaunchAppsConfig:
        with self._lock:
            cfg = load_launch_apps_config()
            if enabled is not None:
                cfg.enabled = bool(enabled)
            if use_in_chat is not None:
                cfg.use_in_chat = bool(use_in_chat)
            if apps is not None:
                cfg.apps = self._parse_apps(apps)
            if folders is not None:
                cfg.folders = self._parse_folders(folders)
            if urls is not None:
                cfg.urls = self._parse_urls(urls)
            save_launch_apps_config(cfg)
            self._config = cfg
            return cfg

    def _parse_apps(self, raw_apps: list[dict[str, Any]]) -> list[LaunchAppEntry]:
        parsed: list[LaunchAppEntry] = []
        for raw in raw_apps:
            if not isinstance(raw, dict):
                continue
            app_id = str(raw.get("id") or "").strip()
            label = str(raw.get("label") or app_id).strip() or app_id
            if not app_id and not label:
                continue
            path = str(raw.get("path") or "").strip()
            if path:
                path = str(Path(path))
            parsed.append(
                LaunchAppEntry(
                    id=app_id or slug_from_label(label, existing={a.id for a in parsed}),
                    label=label,
                    aliases=[str(x).strip() for x in (raw.get("aliases") or []) if str(x).strip()],
                    path=path,
                    args=[str(x).strip() for x in (raw.get("args") or []) if str(x).strip()],
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        parsed, _ = ensure_unique_app_ids(parsed)
        return parsed

    def _parse_folders(self, raw_folders: list[dict[str, Any]]) -> list[FolderEntry]:
        parsed: list[FolderEntry] = []
        for raw in raw_folders:
            if not isinstance(raw, dict):
                continue
            entry_id = str(raw.get("id") or "").strip()
            if not entry_id:
                continue
            path = str(raw.get("path") or "").strip()
            if path:
                path = str(Path(path))
            parsed.append(
                FolderEntry(
                    id=entry_id,
                    label=str(raw.get("label") or entry_id).strip() or entry_id,
                    aliases=[str(x).strip() for x in (raw.get("aliases") or []) if str(x).strip()],
                    path=path,
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        return parsed

    def _parse_urls(self, raw_urls: list[dict[str, Any]]) -> list[UrlEntry]:
        parsed: list[UrlEntry] = []
        for raw in raw_urls:
            if not isinstance(raw, dict):
                continue
            entry_id = str(raw.get("id") or "").strip()
            if not entry_id:
                continue
            parsed.append(
                UrlEntry(
                    id=entry_id,
                    label=str(raw.get("label") or entry_id).strip() or entry_id,
                    aliases=[str(x).strip() for x in (raw.get("aliases") or []) if str(x).strip()],
                    url=str(raw.get("url") or "").strip(),
                    enabled=bool(raw.get("enabled", True)),
                )
            )
        return parsed

    def enabled_apps(self) -> list[LaunchAppEntry]:
        with self._lock:
            cfg = self._sync_from_disk()
            if not cfg.enabled:
                return []
            return [a for a in cfg.apps if a.enabled and a.path.strip()]

    def enabled_folders(self) -> list[FolderEntry]:
        with self._lock:
            cfg = self._config
            if not cfg.enabled:
                return []
            return [f for f in cfg.folders if f.enabled and f.path.strip()]

    def enabled_urls(self) -> list[UrlEntry]:
        with self._lock:
            cfg = self._config
            if not cfg.enabled:
                return []
            return [u for u in cfg.urls if u.enabled and u.url.strip()]

    def chat_enabled(self) -> bool:
        with self._lock:
            cfg = self._config
            has_any = bool(self.enabled_apps() or self.enabled_folders() or self.enabled_urls())
            return bool(cfg.enabled and cfg.use_in_chat and has_any)

    def get_app_by_id(self, app_id: str) -> LaunchAppEntry | None:
        key = (app_id or "").strip().lower()
        if not key:
            return None
        for app in self.enabled_apps():
            if app.id.strip().lower() == key:
                return app
        return None

    def registered_app_hints(self) -> list[str]:
        hints: list[str] = []
        for app in self.enabled_apps():
            names = [app.id, app.label, *app.aliases]
            hints.append("/".join(self._uniq_names(names)[:4]))
        return hints

    def registered_folder_hints(self) -> list[str]:
        hints: list[str] = []
        for folder in self.enabled_folders():
            names = [folder.id, folder.label, *folder.aliases]
            hints.append("/".join(self._uniq_names(names)[:4]))
        return hints

    def registered_url_hints(self) -> list[str]:
        hints: list[str] = []
        for url in self.enabled_urls():
            names = [url.id, url.label, *url.aliases]
            hints.append("/".join(self._uniq_names(names)[:4]))
        return hints

    @staticmethod
    def _uniq_names(names: list[str]) -> list[str]:
        uniq: list[str] = []
        seen: set[str] = set()
        for name in names:
            key = name.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(name.strip())
        return uniq

    def resolve_app(self, query: str) -> LaunchAppEntry | None:
        return self._resolve_entry(query, self.enabled_apps())

    def find_app_in_text(self, text: str) -> LaunchAppEntry | None:
        """在对话/待办标题中匹配快捷启动白名单（优先最长显示名）。"""
        body = (text or "").strip()
        if not body:
            return None
        body_norm = normalize_match_text(body)
        body_lower = body.lower()
        best: LaunchAppEntry | None = None
        best_len = 0
        for app in self.enabled_apps():
            for name in self._uniq_names([app.label, app.id, *app.aliases]):
                n = name.strip()
                if len(n) < 2 and n.lower() not in body_norm:
                    continue
                nl = n.lower()
                nn = normalize_match_text(n)
                matched = (
                    (nl and nl in body_lower)
                    or (n and n in body)
                    or (nn and len(nn) >= 2 and nn in body_norm)
                    or (len(n) == 1 and n.lower() in body_norm)
                )
                if matched:
                    score_len = max(len(n), len(nn))
                    if score_len > best_len:
                        best_len = score_len
                        best = app
        return best

    def resolve_folder(self, query: str) -> FolderEntry | None:
        return self._resolve_entry(query, self.enabled_folders())

    def resolve_url(self, query: str) -> UrlEntry | None:
        return self._resolve_entry(query, self.enabled_urls())

    def _resolve_entry(self, query: str, entries: list[Any]) -> Any | None:
        q = normalize_match_text(query)
        if not q:
            return None
        best = None
        best_score = -1
        for entry in entries:
            candidates = [entry.id, entry.label, *getattr(entry, "aliases", [])]
            for cand in candidates:
                c = normalize_match_text(cand)
                if not c:
                    continue
                score = -1
                if q == c:
                    score = 100
                elif c in q or q in c:
                    score = 80 + min(len(c), len(q))
                if score > best_score:
                    best_score = score
                    best = entry
        return best

    @staticmethod
    def _is_launchable_file(path: Path) -> bool:
        if not path.is_file():
            return False
        suffix = path.suffix.lower()
        if suffix in _LAUNCHABLE_SUFFIXES:
            return True
        return os.name != "nt" and os.access(path, os.X_OK)

    def _open_path(self, path: Path, *, args: list[str] | None = None) -> None:
        resolved = path.resolve()
        if os.name == "nt":
            if args:
                subprocess.Popen(
                    [str(resolved), *args],
                    cwd=str(resolved.parent),
                    shell=False,
                )
            else:
                os.startfile(str(resolved))  # noqa: S606
            return
        subprocess.Popen(
            [str(resolved), *(args or [])],
            cwd=str(resolved.parent),
            shell=False,
        )

    def launch_entry(self, entry: LaunchAppEntry) -> str:
        path = Path(entry.path.strip())
        if not self._is_launchable_file(path):
            raise FileNotFoundError(f"程序不存在或不可启动: {path}")
        label = entry.label or entry.id
        self._open_path(path, args=entry.args or None)
        logger.info("已启动白名单程序: %s (%s)", label, path)
        return f"已启动 {label}"

    def open_folder_entry(self, entry: FolderEntry) -> str:
        path = Path(entry.path.strip())
        if not path.is_dir():
            raise FileNotFoundError(f"文件夹不存在: {path}")
        label = entry.label or entry.id
        if os.name == "nt":
            os.startfile(str(path.resolve()))  # noqa: S606
        elif sys_platform_open_folder(path):
            pass
        else:
            subprocess.Popen(["xdg-open", str(path.resolve())], shell=False)
        logger.info("已打开白名单文件夹: %s (%s)", label, path)
        return f"已打开文件夹 {label}"

    def open_url_entry(self, entry: UrlEntry) -> str:
        url = self._normalize_whitelist_url(entry.url)
        if not url:
            raise ValueError(f"网址无效: {entry.url}")
        if not webbrowser.open(url, new=2):
            raise RuntimeError(f"系统无法打开浏览器: {url}")
        label = entry.label or entry.id
        logger.info("已打开白名单网址: %s (%s)", label, url)
        return f"已打开 {label}"

    def _normalize_whitelist_url(self, raw: str) -> str:
        url = (raw or "").strip()
        if not url:
            return ""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ""
        if not parsed.netloc:
            return ""
        return url

    def _fail_result(self, kind: str, detail: str) -> str:
        self._notify_fail(kind, detail)
        return detail

    def call_launch_app(self, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        query = str(args.get("app") or args.get("name") or args.get("id") or "").strip()
        if not query:
            hints = "、".join(self.registered_app_hints()) or "（白名单为空）"
            return f"缺少参数 app。可用程序：{hints}"
        entry = self.resolve_app(query)
        if entry is None:
            hints = "、".join(self.registered_app_hints()) or "（白名单为空）"
            return self._fail_result("打开程序失败", f"未找到「{query}」。当前白名单：{hints}")
        try:
            return self.launch_entry(entry)
        except FileNotFoundError as exc:
            return self._fail_result("打开程序失败", str(exc))
        except Exception as exc:
            return self._fail_result("打开程序失败", f"启动失败: {exc}")

    def call_open_folder(self, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        query = str(args.get("folder") or args.get("name") or args.get("id") or "").strip()
        if not query:
            hints = "、".join(self.registered_folder_hints()) or "（白名单为空）"
            return f"缺少参数 folder。可用文件夹：{hints}"
        entry = self.resolve_folder(query)
        if entry is None:
            hints = "、".join(self.registered_folder_hints()) or "（白名单为空）"
            return self._fail_result("打开文件夹失败", f"未找到「{query}」。当前白名单：{hints}")
        try:
            return self.open_folder_entry(entry)
        except FileNotFoundError as exc:
            return self._fail_result("打开文件夹失败", str(exc))
        except Exception as exc:
            return self._fail_result("打开文件夹失败", f"打开失败: {exc}")

    def call_open_url(self, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        query = str(args.get("url") or args.get("name") or args.get("id") or "").strip()
        if not query:
            hints = "、".join(self.registered_url_hints()) or "（白名单为空）"
            return f"缺少参数 url。可用网址：{hints}"
        entry = self.resolve_url(query)
        if entry is None:
            hints = "、".join(self.registered_url_hints()) or "（白名单为空）"
            return self._fail_result("打开网址失败", f"未找到「{query}」。当前白名单：{hints}")
        try:
            return self.open_url_entry(entry)
        except ValueError as exc:
            return self._fail_result("打开网址失败", str(exc))
        except Exception as exc:
            return self._fail_result("打开网址失败", f"打开失败: {exc}")

    def ingest_shortcut_path(self, raw_path: str) -> tuple[LaunchAppEntry, bool]:
        """拖入快捷方式：写入白名单。返回 (条目, 是否新建)。"""
        path = Path(str(raw_path or "").strip())
        if not is_launchable_path(path):
            raise FileNotFoundError(f"不是可启动的快捷方式/程序: {path}")
        resolved = str(path.resolve())
        label = label_from_path(path)
        with self._lock:
            cfg = load_launch_apps_config()
            for app in cfg.apps:
                if app.path.strip().lower() == resolved.lower():
                    if not cfg.enabled:
                        cfg.enabled = True
                    if not cfg.use_in_chat:
                        cfg.use_in_chat = True
                    save_launch_apps_config(cfg)
                    self._config = cfg
                    return app, False
            existing_ids = {a.id for a in cfg.apps}
            app_id = slug_from_label(label, existing=existing_ids)
            entry = LaunchAppEntry(
                id=app_id,
                label=label,
                aliases=aliases_for_label(label),
                path=resolved,
                args=[],
                enabled=True,
            )
            cfg.apps.append(entry)
            cfg.enabled = True
            cfg.use_in_chat = True
            save_launch_apps_config(cfg)
            self._config = cfg
            logger.info("已登记快捷启动: %s (%s)", label, resolved)
            return entry, True

    def list_tool_specs(self) -> list[dict[str, Any]]:
        if not self.chat_enabled():
            return []
        specs: list[dict[str, Any]] = []
        app_hints = self.registered_app_hints()
        if app_hints:
            specs.append(
                self._tool_spec(
                    LAUNCH_TOOL_NAME,
                    "启动用户预先登记的白名单程序（支持 exe/bat/cmd/lnk）。"
                    f"参数 app 填 id 或别名，例如：{', '.join(app_hints[:8])}",
                    {
                        "app": {
                            "type": "string",
                            "description": "程序 id 或别名，如 qq、vscode",
                        }
                    },
                    required=["app"],
                )
            )
        folder_hints = self.registered_folder_hints()
        if folder_hints:
            specs.append(
                self._tool_spec(
                    OPEN_FOLDER_TOOL_NAME,
                    "打开用户预先登记的白名单文件夹。"
                    f"参数 folder 填 id 或别名，例如：{', '.join(folder_hints[:8])}",
                    {
                        "folder": {
                            "type": "string",
                            "description": "文件夹 id 或别名，如 downloads、project",
                        }
                    },
                    required=["folder"],
                )
            )
        url_hints = self.registered_url_hints()
        if url_hints:
            specs.append(
                self._tool_spec(
                    OPEN_URL_TOOL_NAME,
                    "在浏览器打开用户预先登记的白名单网址。"
                    f"参数 url 填 id 或别名，例如：{', '.join(url_hints[:8])}",
                    {
                        "url": {
                            "type": "string",
                            "description": "网址 id 或别名，如 bilibili、docs",
                        }
                    },
                    required=["url"],
                )
            )
        return specs

    def _tool_spec(
        self,
        tool_name: str,
        description: str,
        properties: dict[str, Any],
        *,
        required: list[str],
    ) -> dict[str, Any]:
        llm_name = llm_tool_name(LOCAL_SERVER_ID, tool_name)
        return {
            "server_id": LOCAL_SERVER_ID,
            "server_name": "本机快捷启动",
            "name": tool_name,
            "llm_name": llm_name,
            "registered_name": llm_name,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


def sys_platform_open_folder(path: Path) -> bool:
    """macOS open；其它平台由调用方 fallback。"""
    if os.name != "posix" or os.uname().sysname != "Darwin":
        return False
    subprocess.Popen(["open", str(path.resolve())], shell=False)
    return True


launch_apps_service = LaunchAppsService()
