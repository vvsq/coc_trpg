"""LLM 客户端修订项单元测试（4.1+）— temperature 黑名单 / deadline 自洽 /
attempts 覆盖 / json_mode 去参回退 / list_models / Mock 客户端。

纯函数与参数传递层测试，全部用假 SDK 客户端，不发真实网络请求。
"""
import asyncio
import json

import httpx
import pytest
from openai import APIConnectionError, BadRequestError

import app.llm.provider as provider_mod
from app.llm.config import LLMSettings
from app.llm.mock import MockLLMClient
from app.llm.provider import (
    LLMClient,
    LLMUnavailableError,
    _compute_deadline,
    _model_rejects_temperature,
)


# ---------- temperature 黑名单守卫 ----------

@pytest.mark.parametrize(
    ('model', 'rejected'),
    [
        ('gpt-5.2', True),
        ('gpt-5-mini', True),
        ('o1', True),
        ('o3-mini', True),
        ('o4-mini', True),
        ('codex-max', True),
        ('qwen-flash', False),
        ('glm-5.3', False),
        ('deepseek-v4-pro', False),
        ('GPT-5-MINI', True),  # 大小写不敏感
    ],
)
def test_model_rejects_temperature(model: str, rejected: bool):
    assert _model_rejects_temperature(model) is rejected


# ---------- deadline 预算自洽 ----------

def test_compute_deadline():
    # 默认：3 次尝试 × 30s + 退避 (0.8 + 1.6) + 1s 余量 = 93.4（末次重试不再被恒裁）
    assert _compute_deadline(3, 30.0) == pytest.approx(93.4)
    assert _compute_deadline(1, 30.0) == pytest.approx(31.0)   # ping：单次
    assert _compute_deadline(2, 10.0) == pytest.approx(21.8)   # 2×10 + 0.8 + 1
    assert _compute_deadline(0, 30.0) == pytest.approx(31.0)   # 防御：0 次按 1 次算


# ---------- chat()：假 SDK 客户端 ----------

class _FakeCompletions:
    def __init__(self, recorder, fail_first=None, always_fail=False):
        self._recorder = recorder
        self._fail_first = fail_first  # 抛出的异常
        self._always_fail = always_fail  # True=每次调用都抛（测重试链），False=只抛首笔

    async def create(self, **kwargs):
        self._recorder.append(kwargs)
        if self._fail_first is not None and (self._always_fail or len(self._recorder) == 1):
            raise self._fail_first

        class _Msg:
            content = 'OK'

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeSDK:
    def __init__(self, recorder, fail_first=None, always_fail=False, models=None):
        self.chat = type(
            'C', (), {'completions': _FakeCompletions(recorder, fail_first, always_fail)})()
        self._models = models

    def with_options(self, **kwargs):
        return self

    @property
    def models(self):
        return self._models


_REQUEST = httpx.Request('POST', 'https://example.com/v1/chat/completions')


def _llm_client(model: str = 'qwen-flash', retries: int = 2) -> LLMClient:
    settings = LLMSettings(
        base_url='https://example.com/v1', api_key='sk-test-1234567890',
        model=model, timeout=30.0, retries=retries, provider='custom',
    )
    client = LLMClient(settings)
    return client


def test_chat_drops_temperature_for_reasoning_models(monkeypatch):
    """gpt-5/o1/o3/o4/codex 系不传 temperature；普通模型照传。"""
    recorder: list[dict] = []
    monkeypatch.setattr(LLMClient, '_ensure_client', lambda self: _FakeSDK(recorder))
    asyncio.run(_llm_client(model='gpt-5.2').chat([{'role': 'user', 'content': 'hi'}]))
    assert 'temperature' not in recorder[-1]

    recorder.clear()
    asyncio.run(_llm_client(model='qwen-flash').chat([{'role': 'user', 'content': 'hi'}]))
    assert recorder[-1]['temperature'] == 0.8


def test_chat_json_mode_and_fallback(monkeypatch):
    """json_mode 传 response_format；供应商 400 拒绝时同轮次去参重试一次。"""
    recorder: list[dict] = []
    monkeypatch.setattr(LLMClient, '_ensure_client', lambda self: _FakeSDK(recorder))
    asyncio.run(_llm_client().chat([{'role': 'user', 'content': 'hi'}], json_mode=True))
    assert recorder[-1]['response_format'] == {'type': 'json_object'}

    # 400 报文提及 response_format → 去参重试，且不消耗重试次数（attempts=1 共 2 笔调用）
    bad = BadRequestError(
        'response_format is not supported',
        response=httpx.Response(400, request=_REQUEST), body=None,
    )
    recorder.clear()
    monkeypatch.setattr(LLMClient, '_ensure_client', lambda self: _FakeSDK(recorder, fail_first=bad))
    out = asyncio.run(_llm_client().chat([{'role': 'user', 'content': 'hi'}], json_mode=True, attempts=1))
    assert out == 'OK'
    assert len(recorder) == 2
    assert 'response_format' in recorder[0] and 'response_format' not in recorder[1]


def test_chat_attempts_override_skips_retry_chain(monkeypatch):
    """ping 场景：attempts=1 连接失败只打 1 笔（默认 3 笔），不退避重试。"""
    recorder: list[dict] = []
    fail = APIConnectionError(request=_REQUEST)
    monkeypatch.setattr(
        LLMClient, '_ensure_client',
        lambda self: _FakeSDK(recorder, fail_first=fail, always_fail=True),
    )

    # 默认 retries=2 → 3 次尝试
    with pytest.raises(LLMUnavailableError):
        asyncio.run(_llm_client().chat([{'role': 'user', 'content': 'hi'}]))
    assert len(recorder) == 3

    recorder.clear()
    with pytest.raises(LLMUnavailableError):
        asyncio.run(_llm_client().chat([{'role': 'user', 'content': 'hi'}], attempts=1))
    assert len(recorder) == 1


def test_ping_uses_single_attempt(monkeypatch):
    """ping() 自带 attempts=1（清单：连通性测试不等满重试链）。"""
    recorder: list[dict] = []
    monkeypatch.setattr(LLMClient, '_ensure_client', lambda self: _FakeSDK(recorder))
    latency = asyncio.run(_llm_client().ping())
    assert latency >= 0 and len(recorder) == 1


# ---------- list_models 实时探测 ----------

class _FakeModels:
    def __init__(self, ids):
        self._ids = ids

    async def list(self):
        class _M:
            def __init__(self, id):
                self.id = id

        class _Resp:
            data = [_M(i) for i in self._ids]

        return _Resp()


def test_list_models_sorted_unique(monkeypatch):
    sdk = _FakeSDK([], models=_FakeModels(['b-model', 'a-model', 'a-model', '']))
    monkeypatch.setattr(LLMClient, '_ensure_client', lambda self: sdk)
    assert asyncio.run(_llm_client().list_models()) == ['a-model', 'b-model']


def test_list_models_not_configured():
    settings = LLMSettings(base_url='https://x/v1', api_key='', model='',
                           timeout=30.0, retries=2, provider='')
    client = LLMClient(settings)
    with pytest.raises(LLMUnavailableError) as exc:
        asyncio.run(client.list_models())
    assert exc.value.category == 'not_configured'


# ---------- Mock 客户端（LLM_MODEL=mock） ----------

def test_mock_client_produces_parseable_suggestions():
    from app.agent.assembler import parse_suggestions

    mock = MockLLMClient()
    messages = [{'role': 'system', 'content': '协议'},
                {'role': 'user', 'content': '【近期剧情】…\n【最新剧情推进】我推开了地下室的铁门。'}]
    raw = asyncio.run(mock.chat(messages, json_mode=True))
    suggestions = parse_suggestions(raw)
    assert 1 <= len(suggestions) <= 3
    assert all(s['text'] for s in suggestions)
    assert asyncio.run(mock.ping()) >= 0
    assert 'mock' in ','.join(asyncio.run(mock.list_models()))


def test_get_client_returns_mock_when_model_mock(monkeypatch):
    monkeypatch.setattr(provider_mod, 'get_settings', lambda: LLMSettings(
        base_url='', api_key='', model='mock', timeout=30.0, retries=2, provider='',
    ))
    assert isinstance(provider_mod.get_client(), MockLLMClient)


def test_get_client_returns_llm_client_when_real(monkeypatch):
    monkeypatch.setattr(provider_mod, 'get_settings', lambda: LLMSettings(
        base_url='https://x/v1', api_key='sk-x', model='qwen-flash',
        timeout=30.0, retries=2, provider='dashscope',
    ))
    client = provider_mod.get_client()
    assert isinstance(client, LLMClient)
    assert not isinstance(client, MockLLMClient)


# ---------- 供应商拒绝 tools：显式报错（4.3 前置小修） ----------

def test_chat_with_tools_rejected_raises_explicitly(monkeypatch):
    """供应商 400 拒绝 tools：不再静默去参跑偏，显式抛 bad_request 走降级。"""
    bad = BadRequestError(
        'tools is not supported by this model',
        response=httpx.Response(400, request=_REQUEST), body=None,
    )
    recorder: list[dict] = []
    monkeypatch.setattr(
        LLMClient, '_ensure_client',
        lambda self: _FakeSDK(recorder, fail_first=bad, always_fail=True),
    )
    with pytest.raises(LLMUnavailableError) as exc:
        asyncio.run(_llm_client().chat_with_tools(
            [{'role': 'user', 'content': 'hi'}], tools=[{'type': 'function', 'function': {'name': 'x'}}],
        ))
    assert exc.value.category == 'bad_request'
    assert 'function calling' in exc.value.message
    assert len(recorder) == 1  # 未去参重试


def test_json_mode_rejection_still_stripped(monkeypatch):
    """json_mode 被拒仍走静默去参（锦上添花，行为不变）。"""
    bad = BadRequestError(
        'response_format is not supported',
        response=httpx.Response(400, request=_REQUEST), body=None,
    )
    recorder: list[dict] = []
    monkeypatch.setattr(
        LLMClient, '_ensure_client',
        lambda self: _FakeSDK(recorder, fail_first=bad),
    )
    out = asyncio.run(_llm_client().chat(
        [{'role': 'user', 'content': 'hi'}], json_mode=True, attempts=1,
    ))
    assert out == 'OK'
