from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from pnn.core.paths import DATA_DIR
from pnn.pet.presence.models import SessionPresenceBundle, SessionPresenceState

logger = logging.getLogger(__name__)

_PRESENCE_DIR = DATA_DIR / "presence"


def _safe_filename(session_key: str) -> str:
    key = (session_key or "__default__").strip()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return f"{digest}.json"


def bundle_path(session_key: str) -> Path:
    return _PRESENCE_DIR / _safe_filename(session_key)


def load_bundle(session_key: str) -> SessionPresenceBundle:
    path = bundle_path(session_key)
    if not path.is_file():
        return SessionPresenceBundle(state=_default_state(session_key))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        bundle = SessionPresenceBundle.model_validate(raw)
        if not bundle.state.session_key:
            bundle.state.session_key = session_key
        return bundle
    except Exception:
        logger.exception("读取 presence 失败: %s", path)
        return SessionPresenceBundle(state=_default_state(session_key))


def save_bundle(session_key: str, bundle: SessionPresenceBundle) -> None:
    path = bundle_path(session_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not bundle.state.session_key:
        bundle.state.session_key = session_key
    path.write_text(
        json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_state(session_key: str) -> SessionPresenceState:
    return SessionPresenceState(session_key=session_key)
