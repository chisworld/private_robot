"""模型下载地址登记。"""

from __future__ import annotations

from pnn.core.model_downloads import (
    hf_endpoint,
    hf_repo_url,
    list_model_downloads,
    model_downloads_payload,
)


def test_hf_repo_url_uses_mirror():
    url = hf_repo_url("Systran/faster-whisper-small")
    assert url.endswith("Systran/faster-whisper-small")
    assert url.startswith("http")


def test_list_by_category():
    asr = list_model_downloads(category="asr")
    assert asr
    assert all(e.category == "asr" for e in asr)
    tts = list_model_downloads(category="tts")
    assert any(e.id == "gpt_sovits_bundle" for e in tts)


def test_payload_shape():
    data = model_downloads_payload(category="llm_local")
    assert data["hf_endpoint"]
    assert data["models_root"]
    assert any(e["id"] == "qwen_gguf" for e in data["entries"])
    entry = next(e for e in data["entries"] if e["id"] == "qwen_gguf")
    assert entry["links"][0]["url"].startswith("http")


def test_qwen_link_points_to_hauhaucs():
    entries = list_model_downloads(category="llm_local")
    qwen = next(e for e in entries if e.id == "qwen_gguf")
    assert "HauhauCS" in qwen.links[0].url


def test_hf_endpoint_default():
    ep = hf_endpoint()
    assert ep.startswith("https://")
