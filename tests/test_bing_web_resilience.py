from __future__ import annotations

import pytest

from pnn.translate import bing_web


def test_is_transient_net_error_ssl_message():
    exc = RuntimeError(
        "HTTPSConnectionPool(host='cn.bing.com', port=443): "
        "SSLError(SSLEOFError(8, '[SSL: UNEXPECTED_EOF_WHILE_READING]'))"
    )
    assert bing_web._is_transient_net_error(exc) is True


def test_is_transient_net_error_plain_value_error():
    assert bing_web._is_transient_net_error(ValueError("bad json")) is False


def test_normalize_bing_lang_aliases():
    assert bing_web.normalize_bing_lang("jp") == "ja"
    assert bing_web.normalize_bing_lang("zh-cn") == "zh-Hans"


def test_bing_hosts_prefer_www():
    assert bing_web._BING_HOSTS[0] == "https://www.bing.com"


def test_bing_translate_falls_back_when_first_host_empty(monkeypatch):
    class FakeResp:
        def __init__(self, text: str, status_code: int = 200):
            self.text = text
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError("http error")

    html_www = (
        'IG:"IG_WWW", params_AbusePreventionHelper = [1,"tok",3600000]; '
        'data-iid="translator.5023"'
    )
    html_cn = (
        'IG:"IG_CN", params_AbusePreventionHelper = [2,"tok2",3600000]; '
        'data-iid="translator.5023"'
    )

    def fake_get(url, timeout=15.0):
        if "cn.bing.com" in url:
            return FakeResp(html_cn)
        return FakeResp(html_www)

    posts: list[str] = []

    def fake_post(url, data=None, headers=None, timeout=15.0):
        posts.append(url)
        if "www.bing.com" in url:
            return FakeResp("")
        return FakeResp(
            '[{"translations":[{"text":"你好","to":"zh-Hans"}]}]'
        )

    class FakeSession:
        def get(self, url, timeout=15.0):
            return fake_get(url, timeout=timeout)

        def post(self, url, data=None, headers=None, timeout=15.0):
            return fake_post(url, data=data, headers=headers, timeout=timeout)

        def close(self):
            pass

    fake = FakeSession()
    monkeypatch.setattr(bing_web, "_session", fake)
    monkeypatch.setattr(bing_web, "_session_get", lambda: fake)
    monkeypatch.setattr(bing_web, "_auth", None)
    out = bing_web.bing_web_translate("test", from_lang="ja", to_lang="zh-Hans")
    assert out == "你好"
    assert posts[0].startswith("https://www.bing.com/")
    assert any("cn.bing.com" in u for u in posts)
