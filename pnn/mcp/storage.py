"""MCP 下载存储：data/mcp/{网站}/{类型}/{文件名}。"""

from __future__ import annotations

import logging
import mimetypes
import re
import shutil
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

from pnn.core.paths import MCP_STORAGE_DIR, MCP_STORAGE_STAGING_DIR

logger = logging.getLogger(__name__)

MEDIA_CATEGORIES: dict[str, frozenset[str]] = {
    "images": frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif"}),
    "videos": frozenset({".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".m4v"}),
    "audio": frozenset({".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus"}),
    "documents": frozenset({".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md", ".html", ".htm", ".csv"}),
    "archives": frozenset({".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}),
}

_GENERIC_FILENAMES = frozenset(
    {
        "matched.png",
        "found.png",
        "download.png",
        "image.png",
        "screenshot.png",
        "download.jpg",
        "download.jpeg",
        "file.png",
        "temp.png",
    }
)


def ensure_mcp_storage_layout() -> None:
    """创建 data/mcp 根目录与各类型占位目录。"""
    MCP_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    MCP_STORAGE_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    for cat in (*MEDIA_CATEGORIES.keys(), "other"):
        (MCP_STORAGE_DIR / "_types" / cat).mkdir(parents=True, exist_ok=True)
    keep = MCP_STORAGE_DIR / ".gitkeep"
    if not keep.is_file():
        keep.write_text("", encoding="utf-8")


def mcp_storage_root() -> Path:
    ensure_mcp_storage_layout()
    return MCP_STORAGE_DIR.resolve()


def mcp_staging_dir() -> Path:
    ensure_mcp_storage_layout()
    return MCP_STORAGE_STAGING_DIR.resolve()


def website_slug(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return "unknown"
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.netloc or parsed.path.split("/")[0] or "unknown").lower()
    except Exception:
        return "unknown"
    if host.startswith("www."):
        host = host[4:]
    slug = re.sub(r"[^a-z0-9._-]+", "_", host.replace(".", "_"))
    slug = slug.strip("_")[:60]
    return slug or "unknown"


def safe_filename(name: str, *, max_len: int = 120) -> str:
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    base = unquote(base)
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base)
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"_+", "_", base).strip("._")
    if not base or base in (".", ".."):
        base = "download"
    if len(base) > max_len:
        stem = Path(base).stem[: max_len - 20]
        ext = Path(base).suffix[:12]
        base = f"{stem}{ext}"
    return base


def category_for_filename(filename: str, *, content_type: str = "") -> str:
    ext = Path(filename).suffix.lower()
    if not ext and content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ""
    for cat, exts in MEDIA_CATEGORIES.items():
        if ext in exts:
            return cat
    if content_type.startswith("image/"):
        return "images"
    if content_type.startswith("video/"):
        return "videos"
    if content_type.startswith("audio/"):
        return "audio"
    return "other"


def suggest_filename(
    original: str,
    *,
    page_url: str = "",
    download_url: str = "",
) -> str:
    name = safe_filename(original)
    if name.lower() not in _GENERIC_FILENAMES:
        return name

    for url in (download_url, page_url):
        if not url:
            continue
        try:
            path = unquote(urlparse(url).path.rstrip("/"))
            seg = path.split("/")[-1] if path else ""
            if seg and "." in seg:
                return safe_filename(seg)
            if seg:
                ext = Path(original).suffix or ".png"
                return safe_filename(f"{seg}{ext}")
        except Exception:
            continue

    ext = Path(original).suffix or ".png"
    ts = time.strftime("%Y%m%d_%H%M%S")
    site = website_slug(page_url)
    return safe_filename(f"{site}_{ts}{ext}")


def build_target_path(
    filename: str,
    *,
    site_url: str = "",
    content_type: str = "",
) -> Path:
    ensure_mcp_storage_layout()
    site = website_slug(site_url)
    name = suggest_filename(filename, page_url=site_url)
    cat = category_for_filename(name, content_type=content_type)
    dest_dir = MCP_STORAGE_DIR / site / cat
    dest_dir.mkdir(parents=True, exist_ok=True)
    return _unique_path(dest_dir, name)


def _unique_path(dest_dir: Path, filename: str) -> Path:
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem, ext = dest.stem, dest.suffix
    for i in range(2, 1000):
        candidate = dest_dir / f"{stem}_{i}{ext}"
        if not candidate.exists():
            return candidate
    return dest_dir / f"{stem}_{int(time.time())}{ext}"


def organize_file(
    source: Path,
    *,
    site_url: str = "",
    download_url: str = "",
    content_type: str = "",
) -> Path:
    if not source.is_file():
        return source
    target = build_target_path(
        suggest_filename(source.name, page_url=site_url, download_url=download_url),
        site_url=site_url,
        content_type=content_type,
    )
    if source.resolve() == target.resolve():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    logger.info("MCP 文件已归类: %s -> %s", source.name, target)
    return target


def _should_auto_organize(path: Path) -> bool:
    """跳过 Playwright 调试用的整页截图。"""
    name = path.name.lower()
    if name.startswith("page-") and name.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return False
    return True


def organize_staging(
    *,
    site_url: str = "",
    max_images: int | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """将 _staging 中的新文件移入 data/mcp/{网站}/{类型}/。

    max_images: 若为正整数，仅整理前 N 个图片文件，其余图片移入 _skipped。
    返回 (已整理列表, 被跳过的文件名列表)。
    """
    ensure_mcp_storage_layout()
    staging = MCP_STORAGE_STAGING_DIR
    if not staging.is_dir():
        return [], []

    moved: list[dict[str, str]] = []
    skipped: list[str] = []
    images_moved = 0
    for entry in sorted(staging.iterdir(), key=lambda p: p.stat().st_mtime):
        if not entry.is_file() or not _should_auto_organize(entry):
            continue
        cat = category_for_filename(entry.name)
        if max_images is not None and cat == "images" and images_moved >= max_images:
            quarantined = _quarantine_staging_file(entry)
            skipped.append(quarantined)
            continue
        try:
            dest = organize_file(entry, site_url=site_url)
            rel = dest.relative_to(MCP_STORAGE_DIR).as_posix()
            moved.append(
                {
                    "from": entry.name,
                    "to": str(dest),
                    "relative": rel,
                    "site": website_slug(site_url),
                    "category": dest.parent.name,
                }
            )
            if cat == "images":
                images_moved += 1
        except OSError as exc:
            logger.warning("整理 MCP 文件失败 %s: %s", entry, exc)
    return moved, skipped


def _quarantine_staging_file(entry: Path) -> str:
    """将多余暂存文件移入 _staging/_skipped，避免下次整理时再次入库。"""
    quarantine = MCP_STORAGE_STAGING_DIR / "_skipped"
    quarantine.mkdir(parents=True, exist_ok=True)
    dest = quarantine / safe_filename(entry.name)
    dest = _unique_path(quarantine, dest.name)
    try:
        shutil.move(str(entry), str(dest))
    except OSError as exc:
        logger.warning("隔离 MCP 暂存文件失败 %s: %s", entry, exc)
        return entry.name
    return dest.name


def purge_staging_images() -> int:
    """清理暂存目录中的图片文件（不含 _skipped 子目录）。返回删除/隔离数量。"""
    ensure_mcp_storage_layout()
    staging = MCP_STORAGE_STAGING_DIR
    if not staging.is_dir():
        return 0
    count = 0
    for entry in staging.iterdir():
        if not entry.is_file() or not _should_auto_organize(entry):
            continue
        if category_for_filename(entry.name) != "images":
            continue
        _quarantine_staging_file(entry)
        count += 1
    return count


def storage_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(MCP_STORAGE_DIR.resolve()).as_posix()
    except ValueError:
        return path.name


def build_agent_storage_instructions() -> str:
    root = mcp_storage_root()
    staging = mcp_staging_dir()
    cats = "、".join(MEDIA_CATEGORIES.keys()) + "、other"
    return (
        "【MCP 下载存储规则】\n"
        f"• 根目录：{root}\n"
        f"• 目录结构：{{网站域名}}/{{类型}}/{{文件名}}\n"
        f"  类型文件夹：{cats}\n"
        f"  网站文件夹示例：3dmgame_com、bilibili_com（由当前页面 URL 自动识别）\n"
        f"• Playwright 临时输出目录：{staging}\n"
        "  下载可先保存到此目录；系统会在工具调用后自动整理到上述分类路径。\n"
        "• 文件名：使用页面标题、图片 alt、作品名等语义化英文名或拼音，"
        "避免 matched.png 等泛名；仅下载 1 个目标文件。\n"
        "• 向用户报告时说明最终相对路径，如：3dmgame_com/images/角色名.png"
    )
