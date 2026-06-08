"""角色包 ZIP 导入/导出（换机、分享人设）。"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from pnn.characters.pack import (
    PACK_FILENAME,
    CharacterPack,
    list_pack_ids,
    load_pack,
    pack_dir,
    save_pack,
)
from pnn.tts.character_layout import character_tts_dir

MANIFEST_NAME = "manifest.json"
PACK_EXPORT_VERSION = 1
_SAFE_ID_RE = re.compile(r"^[\w\u4e00-\u9fff\-]+$", re.UNICODE)


def _safe_id(char_id: str) -> str:
    cid = (char_id or "").strip()
    if not cid or not _SAFE_ID_RE.match(cid):
        raise ValueError(f"角色 ID 无效: {char_id!r}")
    return cid


def export_character_pack_zip(char_id: str) -> bytes:
    cid = _safe_id(char_id)
    pack = load_pack(cid)
    if pack is None:
        raise ValueError(f"角色包不存在: {cid}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            MANIFEST_NAME,
            json.dumps(
                {"id": pack.id, "name": pack.name, "version": PACK_EXPORT_VERSION},
                ensure_ascii=False,
                indent=2,
            ),
        )
        zf.writestr(
            PACK_FILENAME,
            json.dumps(pack.to_dict(), ensure_ascii=False, indent=2) + "\n",
        )
        tts_dir = character_tts_dir(pack.id)
        if tts_dir.is_dir():
            for file_path in sorted(tts_dir.rglob("*")):
                if not file_path.is_file():
                    continue
                arc = f"tts/{file_path.relative_to(tts_dir).as_posix()}"
                zf.write(file_path, arcname=arc)
    return buf.getvalue()


def import_character_pack_zip(
    data: bytes,
    *,
    new_id: str | None = None,
    overwrite: bool = False,
) -> CharacterPack:
    if not data:
        raise ValueError("ZIP 文件为空")
    with tempfile.TemporaryDirectory(prefix="pnn-pack-import-") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/")
                if ".." in name.split("/"):
                    raise ValueError(f"ZIP 路径非法: {name}")
                target = tmp_path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        manifest_path = tmp_path / MANIFEST_NAME
        pack_json_path = tmp_path / PACK_FILENAME
        if not pack_json_path.is_file():
            raise ValueError("ZIP 缺少 pack.json")
        raw_pack = json.loads(pack_json_path.read_text(encoding="utf-8"))
        if not isinstance(raw_pack, dict):
            raise ValueError("pack.json 格式错误")
        pack = CharacterPack.from_dict(raw_pack)
        target_id = _safe_id(new_id or pack.id)
        if target_id in list_pack_ids() and not overwrite:
            raise ValueError(f"角色包已存在: {target_id}（可指定 new_id 或 overwrite）")
        pack.id = target_id
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(manifest, dict) and manifest.get("name"):
                    pack.name = str(manifest["name"])
            except json.JSONDecodeError:
                pass
        dest = pack_dir(target_id)
        if dest.exists() and overwrite:
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
        save_pack(pack)
        tts_src = tmp_path / "tts"
        if tts_src.is_dir():
            tts_dest = character_tts_dir(target_id)
            if tts_dest.exists() and overwrite:
                shutil.rmtree(tts_dest)
            tts_dest.mkdir(parents=True, exist_ok=True)
            for file_path in tts_src.rglob("*"):
                if not file_path.is_file():
                    continue
                rel = file_path.relative_to(tts_src)
                out = tts_dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, out)
        return load_pack(target_id) or pack
