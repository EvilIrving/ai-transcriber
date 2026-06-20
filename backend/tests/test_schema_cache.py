"""_chat_optimize_with_schema json_schema 缓存行为测试。

模拟 API 响应验证：首次探测 → 缓存 → 后续跳过 try/catch → TTL 过期重探测。
不触网：通过 mock 控制 client.chat.completions.create 的返回值/异常。
"""
from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from summarizer import (
    _schema_cache,
    _schema_cache_lock,
    _get_schema_support,
    _set_schema_support,
    Summarizer,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """每个测试前清空模块级缓存，避免测试间干扰。"""
    with _schema_cache_lock:
        _schema_cache.clear()
    yield
    with _schema_cache_lock:
        _schema_cache.clear()


def make_summarizer(model="test-model", base_url=None, api_key="sk-test"):
    """构造一个带假 client 的 Summarizer，避免真实网络调用。"""
    s = Summarizer(api_key=api_key, base_url=base_url or "", model=model)
    s.client = mock.MagicMock()
    return s


class TestGetSetSchemaSupport:
    def test_get_none_when_empty(self):
        assert _get_schema_support("m", "u") is None

    def test_set_and_get(self):
        _set_schema_support("m", "u", True)
        assert _get_schema_support("m", "u") is True

    def test_set_and_get_false(self):
        _set_schema_support("m", "u", False)
        assert _get_schema_support("m", "u") is False

    def test_different_keys_independent(self):
        _set_schema_support("m1", "u1", True)
        _set_schema_support("m2", "u2", False)
        assert _get_schema_support("m1", "u1") is True
        assert _get_schema_support("m2", "u2") is False

    def test_ttl_expiry(self, monkeypatch):
        monkeypatch.setattr("summarizer._SCHEMA_CACHE_TTL", 0.01)
        _set_schema_support("m", "u", True)
        time.sleep(0.02)
        assert _get_schema_support("m", "u") is None


class TestChatOptimizeWithSchema:
    def test_unknown_probes_and_caches_success(self):
        s = make_summarizer()
        fake_response = mock.MagicMock()
        s.client.chat.completions.create.return_value = fake_response

        # 第一次：缓存未命中 → 探测
        r1 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert r1 is fake_response
        # 验证探了一次
        assert s.client.chat.completions.create.call_count == 1
        # 缓存应为 True
        assert _get_schema_support("test-model", "None") is True

        # 第二次：缓存命中 True → 直接走 schema，不再探
        r2 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert r2 is fake_response
        assert s.client.chat.completions.create.call_count == 2

    def test_unknown_probes_and_caches_unsupported(self):
        from openai import BadRequestError

        s = make_summarizer()
        # 第一次抛 400（不支持 json_schema）
        bad_req = BadRequestError(
            "response_format type unavailable",
            response=mock.MagicMock(),
            body={},
        )
        fallback_response = mock.MagicMock()
        s.client.chat.completions.create.side_effect = [
            bad_req,
            fallback_response,
        ]

        # probe → 400 → 缓存 False → 重试纯文本
        r1 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert r1 is fallback_response
        assert s.client.chat.completions.create.call_count == 2
        assert _get_schema_support("test-model", "None") is False

        # 第二次：缓存命中 False → 直接纯文本，不抛不探
        mock_create = s.client.chat.completions.create
        mock_create.reset_mock()
        mock_create.side_effect = None
        mock_create.return_value = fallback_response
        r2 = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert r2 is fallback_response
        assert mock_create.call_count == 1

    def test_unsupported_error_caching_only_once(self):
        """并发场景：已缓存 False 后不应再触发探测分支。"""
        from openai import BadRequestError

        s = make_summarizer()

        # 手动预设缓存为 False，模拟已有探测结果
        _set_schema_support("test-model", "None", False)

        fake = mock.MagicMock()
        s.client.chat.completions.create.return_value = fake

        r = s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert r is fake
        # 只调一次（纯文本路径），不应触发 schema 探测
        assert s.client.chat.completions.create.call_count == 1
        # 确认调用没带 response_format
        call_kwargs = s.client.chat.completions.create.call_args.kwargs
        assert "response_format" not in call_kwargs

    def test_non_schema_error_not_cached(self):
        """鉴权/连接等非 schema 错误应透传，不缓存。"""
        from openai import AuthenticationError

        s = make_summarizer()
        s.client.chat.completions.create.side_effect = AuthenticationError(
            "Invalid API key",
            response=mock.MagicMock(),
            body={},
        )
        with pytest.raises(AuthenticationError):
            s._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        # 不应缓存任何值
        assert _get_schema_support("test-model", "None") is None

    def test_different_models_independent_cache(self):
        from openai import BadRequestError

        s1 = make_summarizer(model="deepseek-chat")
        s2 = make_summarizer(model="gpt-4o")

        # model1 不支持
        s1.client.chat.completions.create.side_effect = [
            BadRequestError("response_format type unavailable",
                            response=mock.MagicMock(), body={}),
            mock.MagicMock(),
        ]
        s1._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert _get_schema_support("deepseek-chat", "None") is False

        # model2 支持
        s2.client.chat.completions.create.return_value = mock.MagicMock()
        s2._chat_optimize_with_schema([{"role": "user", "content": "hi"}])
        assert _get_schema_support("gpt-4o", "None") is True
        # model1 仍为 False
        assert _get_schema_support("deepseek-chat", "None") is False
