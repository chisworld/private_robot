"""对话历史校验：空 content 会导致 chat API 422。"""

from __future__ import annotations

from server.routes.chat import ChatCompletionRequest


def test_empty_history_content_is_pruned():
    req = ChatCompletionRequest.model_validate(
        {
            "message": "你好",
            "history": [
                {"role": "user", "content": "上一轮"},
                {"role": "assistant", "content": ""},
                {"role": "assistant", "content": "   "},
            ],
        }
    )
    assert len(req.history) == 1
    assert req.history[0].content == "上一轮"


def test_sanitize_client_history():
    from pnn.pet.api_client import ChatMessage, _sanitize_chat_history

    out = _sanitize_chat_history(
        [
            ChatMessage(role="user", content="a"),
            ChatMessage(role="assistant", content=""),
            ChatMessage(role="assistant", content="b"),
        ]
    )
    assert len(out) == 2
    assert out[1].content == "b"
