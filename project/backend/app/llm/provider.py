"""OpenAI 兼容异步客户端 — 超时 / 重试 / 失败降级异常（goal 阶段 4.1）。

失败语义（goal §10 风险对策）：单次请求超时 LLM_TIMEOUT（默认 30s）；
可重试错误（超时 / 连接失败 / 429 / 5xx）最多重试 LLM_RETRIES（默认 2）次；
不可重试错误（401/400/404 等）立即失败。所有失败统一抛
LLMUnavailableError，由上层捕获后回退纯人工主持并提示 KP。

为什么不直接用 SDK 内置重试：SDK 的 max_retries 不区分「可降级重试」与
「配置错误」，且我们要求每次尝试独立超时 + 总 deadline 兜底，自己控制更直白。

4.1+ 修订：deadline 按 attempts×timeout+退避动态计算（不再恒裁末次重试）；
ping 走 attempts=1 不吃重试链；推理系模型自动去 temperature；可选 json_mode
（response_format=json_object，供应商拒绝时同轮次自动去参重试）。
4.2 修订：新增 chat_with_tools（function calling），与 chat 共用同一套
重试/deadline/temperature/json_mode 基础设施。
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)

from app.llm.config import LLMSettings, get_settings

if TYPE_CHECKING:
    from app.llm.mock import MockLLMClient

logger = logging.getLogger('app.llm')

# 重试退避基数（秒）：第 1 次重试等 0.8s，第 2 次等 1.6s
_BACKOFF_BASE = 0.8

# 单次请求输出 token 上限（4.4：仅在调用方显式传 max_tokens 时作为翻倍重试的天花板）
_MAX_OUTPUT_TOKENS_CAP = 8000


def _model_rejects_temperature(model: str) -> bool:
    """推理系模型拒绝 temperature 参数，请求前按模型名过滤（借鉴 AiChatTrpg）。"""
    m = (model or '').lower()
    return m.startswith(('gpt-5', 'o1', 'o3', 'o4')) or 'codex' in m


def _compute_deadline(attempts: int, timeout: float) -> float:
    """整体预算 = attempts×单次超时 + 累计退避 + 1s 余量。

    自洽性：默认 3 次尝试 × 30s + (0.8+1.6)s + 1 ≈ 93.4s，末次重试不再被预算恒裁。
    """
    n = max(1, attempts)
    backoff = sum(_BACKOFF_BASE * i for i in range(1, n))
    return n * timeout + backoff + 1.0


class LLMUnavailableError(Exception):
    """LLM 不可用（配置缺失 / 网络 / 鉴权 / 限流 / 服务端错误 / 空响应）。

    category 用于前端区分提示文案；message 是面向 KP 的中文原因。
    """

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass
class AssistantTurn:
    """一次补全的解析结果：文本内容 + 工具调用（function calling，4.2）。

    tool_calls 元素：{'id': str, 'name': str, 'arguments': dict}。
    """

    content: str = ''
    tool_calls: list[dict] = field(default_factory=list)
    raw_message: object | None = None  # 原始 assistant 消息（工具循环回喂用）

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


def _friendly(status_error: APIStatusError) -> tuple[str, str]:
    """把 SDK 的状态错误翻译成（category, 面向 KP 的中文原因）。"""
    detail = (getattr(status_error, 'message', '') or '').strip()
    detail = detail[:120]
    status = getattr(status_error, 'status_code', 0) or 0
    if isinstance(status_error, AuthenticationError):
        return 'auth', f'API Key 无效或未授权（401）{("：" + detail) if detail else ""}'
    if isinstance(status_error, RateLimitError):
        return 'rate_limit', f'LLM 触发限流（429）{("：" + detail) if detail else ""}'
    if isinstance(status_error, NotFoundError):
        return 'not_found', f'模型或接口地址不存在（404）{("：" + detail) if detail else ""}'
    if isinstance(status_error, BadRequestError):
        return 'bad_request', f'请求被拒绝（400）{("：" + detail) if detail else ""}'
    if status >= 500:
        return 'server', f'LLM 服务端错误（{status}）'
    return 'server', f'LLM 返回异常（{status or "未知状态"}）{("：" + detail) if detail else ""}'


def _cached_tokens(usage_obj) -> int:
    """从 usage 里取「命中前缀缓存的输入 token」（OpenAI 兼容 / DashScope 文本模型同名字段）。

    2026-09-10 实测：DashScope 隐式缓存自动生效，同前缀第二次调用
    `prompt_tokens_details.cached_tokens` ≈ prompt_tokens 的 99%。
    该值只用于成本观测，取不到（供应商不给 / 结构不同）一律按 0 处理。
    """
    details = getattr(usage_obj, 'prompt_tokens_details', None)
    if details is None and isinstance(usage_obj, dict):
        details = usage_obj.get('prompt_tokens_details')
    if details is None:
        return 0
    value = getattr(details, 'cached_tokens', None)
    if value is None and isinstance(details, dict):
        value = details.get('cached_tokens')
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _parse_tool_calls(message) -> list[dict]:
    """解析 SDK 的 tool_calls → [{id, name, arguments(dict)}]。参数 JSON 非法按坏响应处理。"""
    parsed: list[dict] = []
    for tc in (getattr(message, 'tool_calls', None) or []):
        fn = getattr(tc, 'function', None)
        raw_args = getattr(fn, 'arguments', '') or ''
        try:
            args = json.loads(raw_args) if raw_args else {}
        except ValueError as exc:
            raise LLMUnavailableError(
                'bad_response', f'工具 {getattr(fn, "name", "?")} 的参数不是合法 JSON：{exc}'
            ) from exc
        if not isinstance(args, dict):
            raise LLMUnavailableError('bad_response', f'工具 {getattr(fn, "name", "?")} 的参数必须是 JSON 对象')
        parsed.append({'id': getattr(tc, 'id', ''), 'name': getattr(fn, 'name', ''), 'arguments': args})
    return parsed


class LLMClient:
    """按 LLMSettings 惰性构建的 AsyncOpenAI 薄包装。settings 变化时自动重建。"""

    def __init__(self, settings: LLMSettings):
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    @property
    def settings(self) -> LLMSettings:
        return self._settings

    def _ensure_client(self) -> AsyncOpenAI:
        if self._client is None:
            # max_retries=0：重试策略由本类掌控，避免与 SDK 内置重试叠乘
            self._client = AsyncOpenAI(
                base_url=self._settings.base_url or None,
                api_key=self._settings.api_key,
                timeout=self._settings.timeout,
                max_retries=0,
            )
        return self._client

    async def _complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        deadline: float | None = None,
        attempts: int | None = None,
        json_mode: bool = False,
        tools: list[dict] | None = None,
        tool_choice: str = 'auto',
    ) -> AssistantTurn:
        """chat / chat_with_tools 共用的重试核心。任何失败抛 LLMUnavailableError。

        deadline=None 时按 attempts×timeout+退避自动计算；attempts=None 时
        取 LLM_RETRIES+1（ping 等连通性探测传 attempts=1 免重试链）。
        """
        if not self._settings.enabled:
            raise LLMUnavailableError(
                'not_configured', '未配置 LLM_API_KEY / LLM_MODEL（backend/.env），已回退纯人工主持'
            )
        started = time.monotonic()
        n_attempts = max(1, attempts if attempts is not None else self._settings.retries + 1)
        if deadline is None:
            deadline = _compute_deadline(n_attempts, self._settings.timeout)
        chosen_model = model or self._settings.model
        last_error: LLMUnavailableError | None = None

        attempt = 0
        budget_boosts = 0  # 推理预算翻倍重试次数（独立于重试链，只受 deadline 约束）
        while True:
            remaining = deadline - (time.monotonic() - started)
            if remaining <= 0:
                raise LLMUnavailableError(
                    'timeout', f'LLM 整体耗时超过 {deadline:.0f}s 预算，已放弃本次请求'
                )
            try:
                call_kwargs: dict = {
                    'model': chosen_model,
                    'messages': messages,
                    'timeout': min(self._settings.timeout, remaining),
                }
                if max_tokens:
                    # 4.4 实测（DeepSeek-v4-pro）：设了 max_tokens 反而会触发异常长思考
                    # （思考吃满预算 → content 空）；不设时思考短促收敛（41 tokens 级）。
                    # 默认不传，由供应商自身上限兜底；翻倍重试仅在显式传值时生效。
                    call_kwargs['max_tokens'] = max_tokens
                if not _model_rejects_temperature(chosen_model):
                    call_kwargs['temperature'] = temperature
                if json_mode:
                    call_kwargs['response_format'] = {'type': 'json_object'}
                if tools:
                    call_kwargs['tools'] = tools
                    call_kwargs['tool_choice'] = tool_choice
                if self._settings.disable_thinking:
                    # 混合推理模型（qwen3 系）默认思考模式：非流式下思考+生成常超时，
                    # 跑团场景要的是即时叙事，关掉（DashScope compatible-mode extra_body）
                    call_kwargs['extra_body'] = {'enable_thinking': False}
                client = self._ensure_client()
                try:
                    resp = await client.chat.completions.create(**call_kwargs)
                except BadRequestError as exc:
                    text = str(exc)
                    if 'enable_thinking' in text and 'extra_body' in call_kwargs:
                        # 关思考不被支持（非混合模型）：去掉后重试一次
                        logger.warning('供应商拒绝 enable_thinking，已自动去参重试：%s', exc)
                        call_kwargs.pop('extra_body', None)
                        resp = await client.chat.completions.create(**call_kwargs)
                    elif json_mode and 'response_format' in text:
                        # json_mode 是锦上添花：个别供应商不支持时同轮次去参重试一次
                        logger.warning('供应商拒绝 response_format，已自动去参重试：%s', exc)
                        call_kwargs.pop('response_format', None)
                        resp = await client.chat.completions.create(**call_kwargs)
                    elif tools and ('tool' in text or 'function' in text):
                        # tools 是功能支柱（D3）：去掉它 LLM 会直接输出文本跑偏——
                        # 显式报错走降级（计数回退），让 KP 换模型而不是悄悄出废稿
                        raise LLMUnavailableError(
                            'bad_request',
                            f'该模型/供应商不支持 function calling（tools），请更换模型：{text[:120]}',
                        ) from exc
                    else:
                        raise
                if not resp.choices:
                    raise LLMUnavailableError('empty_response', 'LLM 返回了空内容')
                message = resp.choices[0].message
                content = (message.content or '').strip()
                tool_calls = _parse_tool_calls(message)
                if not content and not tool_calls:
                    # 4.4（DeepSeek-v4 实测）：推理模型的思考 token 也计入 max_tokens，
                    # 预算被思考耗尽时 finish_reason=length 且 content 为空——不是
                    # 真空响应，翻倍输出预算重试（独立于重试链，只受 deadline 约束）。
                    finish = getattr(resp.choices[0], 'finish_reason', '') or ''
                    new_cap = min((max_tokens or 0) * (2 ** (budget_boosts + 1)),
                                  _MAX_OUTPUT_TOKENS_CAP)
                    if finish == 'length' and max_tokens and new_cap > (max_tokens or 0):
                        budget_boosts += 1
                        call_kwargs['max_tokens'] = new_cap
                        logger.warning(
                            '推理输出预算耗尽（思考吃满 max_tokens），已提高到 %s 重试',
                            new_cap,
                        )
                        continue
                    raise LLMUnavailableError(
                        'empty_response',
                        'LLM 返回了空内容（输出预算被思考耗尽，建议换非推理模型或调大预算）',
                    )
                # 4.4 token 统计：真实响应才记账（mock 无 usage；记账失败不影响主流程）
                usage_obj = getattr(resp, 'usage', None)
                if usage_obj is not None:
                    from app.llm.usage import record_usage

                    record_usage(
                        chosen_model,
                        int(getattr(usage_obj, 'prompt_tokens', 0) or 0),
                        int(getattr(usage_obj, 'completion_tokens', 0) or 0),
                        cached_tokens=_cached_tokens(usage_obj),
                    )
                return AssistantTurn(content=content, tool_calls=tool_calls, raw_message=message)
            except (APITimeoutError, APIConnectionError, RateLimitError, APIStatusError) as exc:
                if isinstance(exc, APIStatusError):
                    last_error = LLMUnavailableError(*_friendly(exc))
                    retryable = (
                        isinstance(exc, RateLimitError)
                        or (getattr(exc, 'status_code', 0) or 0) >= 500
                    )
                else:
                    # APITimeoutError 是 APIConnectionError 的子类，必须先判超时
                    if isinstance(exc, APITimeoutError):
                        last_error = LLMUnavailableError(
                            'timeout', f'LLM 请求超时（{self._settings.timeout:.0f}s）'
                        )
                    else:
                        last_error = LLMUnavailableError('network', '无法连接 LLM 服务（网络异常）')
                    retryable = True
                attempt += 1
                if not retryable or attempt >= n_attempts:
                    raise last_error
                await asyncio.sleep(_BACKOFF_BASE * attempt)
        raise last_error or LLMUnavailableError('server', 'LLM 请求失败')

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        deadline: float | None = None,
        attempts: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """对话补全，返回首条回复文本。任何失败抛 LLMUnavailableError。"""
        turn = await self._complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens,
            deadline=deadline, attempts=attempts, json_mode=json_mode,
        )
        return turn.content

    async def chat_with_tools(
        self,
        messages: list[dict],
        *,
        tools: list[dict],
        tool_choice: str = 'auto',
        model: str | None = None,
        temperature: float = 0.8,
        max_tokens: int | None = None,
        deadline: float | None = None,
        attempts: int | None = None,
        json_mode: bool = False,
    ) -> AssistantTurn:
        """带 function calling 的补全，返回 (文本, 工具调用列表)。任何失败抛 LLMUnavailableError。"""
        return await self._complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens,
            deadline=deadline, attempts=attempts, json_mode=json_mode,
            tools=tools, tool_choice=tool_choice,
        )

    async def ping(self) -> float:
        """最小连通性测试，返回耗时 ms；失败抛 LLMUnavailableError。

        max_tokens=64：推理系模型（deepseek-v4 / o 系）的思考 token 也计入
        completion 预算，8 tokens 会全部耗在 reasoning 上导致 content 为空
        （实测 2026-09-08），给足余量。
        """
        started = time.monotonic()
        await self.chat(
            [{'role': 'user', 'content': '回复 OK'}],
            temperature=0.0,
            max_tokens=64,
            attempts=1,  # 连通性探测不走重试链：服务宕机时尽快返回
        )
        return round((time.monotonic() - started) * 1000)

    async def list_models(self) -> list[str]:
        """实时探测供应商可用模型（GET /models），单次尝试不走重试链（D11）。

        静态预设只是推荐，模型目录以本探测为准；供应商不支持 /models 时
        抛 LLMUnavailableError，由前端回退手填。
        """
        if not self._settings.enabled:
            raise LLMUnavailableError(
                'not_configured', '未配置 LLM_API_KEY / LLM_MODEL（backend/.env）'
            )
        try:
            response = await self._ensure_client().with_options(timeout=10.0).models.list()
        except (APITimeoutError, APIConnectionError, APIStatusError) as exc:
            if isinstance(exc, APIStatusError):
                raise LLMUnavailableError(*_friendly(exc)) from exc
            if isinstance(exc, APITimeoutError):
                raise LLMUnavailableError('timeout', '模型探测超时（10s）') from exc
            raise LLMUnavailableError('network', '无法连接 LLM 服务（网络异常）') from exc
        ids = sorted({getattr(m, 'id', '') for m in (response.data or []) if getattr(m, 'id', '')})
        return ids


_client: LLMClient | None = None
_light_client: LLMClient | None = None


def get_client() -> 'LLMClient | MockLLMClient':
    """进程级单例；配置重载（reset_settings_cache 后）会自动换绑新配置。

    LLM_MODEL=mock 时返回 MockLLMClient（无 key 跑通全流程 / 断网演示兜底）。
    """
    global _client
    settings = get_settings()
    if settings.mock_mode:
        from app.llm.mock import get_mock_client

        return get_mock_client()
    if _client is None or _client.settings is not settings:
        _client = LLMClient(settings)
    return _client


def get_light_client() -> 'LLMClient | MockLLMClient':
    """轻任务客户端（4.4 分级路由）：建议生成 / 场景摘要等低风险调用用快模型。

    未配置 light_model 或主模型为 mock 时与 get_client() 同一实例（零开销回退）。
    """
    global _light_client
    settings = get_settings()
    if settings.mock_mode or not settings.light_ready:
        return get_client()
    light_settings = settings.with_light_as_main()
    if _light_client is None or _light_client.settings is not light_settings:
        _light_client = LLMClient(light_settings)
    return _light_client
