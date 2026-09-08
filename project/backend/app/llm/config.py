"""LLM 配置加载 — llm_config 表为唯一权威（4.4，goal §7；决策 D10 收尾）。

读取优先级：llm_config 表（单行 id=1）> backend/.env（仅首次无行时读入做种子）。
4.1~4.3 曾以 .env 为运行时来源；4.4 起设置面板写 DB，.env 保留兼容但不再是
运行时来源——已有部署首次启动时自动从 .env 迁移进表，之后改 .env 不再生效。

轻任务分级路由（用户决策 2026-09-08）：light_* 三字段配置「建议生成/场景摘要/
解析修复」等低风险调用的快模型（可跨供应商），light_model 为空 = 跟随主模型。

测试注意：settings 是进程级缓存；测试改环境变量或 DB 后必须 reset_settings_cache()。
"""
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import os

from sqlmodel import Session

from app.db import engine
from app.llm.providers import detect_provider
from app.models import LlmConfig

# backend/.env（app/llm/config.py → parents[2] = backend/）
_ENV_PATH = Path(__file__).resolve().parents[2] / '.env'
load_dotenv(_ENV_PATH)  # 仅作首次 seed 来源；已有环境变量优先

_ENV_KEYS = ('LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL', 'LLM_TIMEOUT', 'LLM_RETRIES',
             'LLM_DISABLE_THINKING')

_TRUTHY = ('1', 'true', 'yes')


def mask_key(key: str) -> str:
    """key 掩码展示（KP 设置页 / 状态接口用）：只露前 5 后 4 位。"""
    key = (key or '').strip()
    if not key:
        return ''
    if len(key) <= 9:
        return '***'
    return f'{key[:5]}***{key[-4:]}'


@dataclass(frozen=True)
class LLMSettings:
    """一次加载、全局只读的供应商配置。enabled 为接入总开关。"""

    base_url: str
    api_key: str
    model: str
    timeout: float
    retries: int
    provider: str  # providers.detect_provider 的结果（preset key / custom / ''）
    disable_thinking: bool = False  # 混合推理模型（qwen3 系）默认思考模式，非流式下极慢
    # 轻任务分级路由：建议生成 / 场景摘要 / 解析修复等低风险调用用快模型；
    # 三字段全空 = 跟随主模型（get_light_settings 返回主配置本身）
    light_base_url: str = ''
    light_api_key: str = ''
    light_model: str = ''

    @property
    def enabled(self) -> bool:
        """api_key 与 model 都非空才算配置完成；mock 模式除外。缺任一回退纯人工主持。"""
        if self.mock_mode:
            return True
        return bool(self.api_key.strip()) and bool(self.model.strip())

    @property
    def mock_mode(self) -> bool:
        """演示/断网兜底：model 填 mock 即用 MockLLMClient，不发起真实网络请求。"""
        return self.model.strip().lower() == 'mock'

    @property
    def light_ready(self) -> bool:
        """轻任务模型是否单独配置（否则轻任务跟主模型走同一客户端）。"""
        return bool(self.light_model.strip())

    @property
    def api_key_masked(self) -> str:
        return mask_key(self.api_key)

    @property
    def light_api_key_masked(self) -> str:
        return mask_key(self.light_api_key)

    def with_light_as_main(self) -> 'LLMSettings':
        """把轻任务配置换到主位（get_light_client 构建独立客户端用）。

        轻模型沿用主模型的 timeout/retries/disable_thinking——供应商不同时
        这些值也只是保守起点，不出错即可。
        """
        return replace(
            self,
            base_url=self.light_base_url or self.base_url,
            api_key=self.light_api_key or self.api_key,
            model=self.light_model,
            provider=detect_provider(self.light_api_key, self.light_base_url),
        )


def _env_seed() -> LlmConfig:
    """从环境变量 / .env 构造种子行（llm_config 表为空时用一次）。"""
    try:
        timeout = float(os.getenv('LLM_TIMEOUT', '') or 30)
    except ValueError:
        timeout = 30.0
    try:
        retries = int(os.getenv('LLM_RETRIES', '') or 2)
    except ValueError:
        retries = 2
    return LlmConfig(
        id=1,
        base_url=os.getenv('LLM_BASE_URL', '').strip(),
        api_key=os.getenv('LLM_API_KEY', '').strip(),
        model=os.getenv('LLM_MODEL', '').strip(),
        timeout=max(5.0, timeout),
        retries=max(0, retries),
        disable_thinking=os.getenv('LLM_DISABLE_THINKING', '').strip().lower() in _TRUTHY,
    )


def _row_to_settings(row: LlmConfig) -> LLMSettings:
    return LLMSettings(
        base_url=row.base_url or '',
        api_key=row.api_key or '',
        model=row.model or '',
        timeout=max(5.0, float(row.timeout or 30)),
        retries=max(0, int(row.retries or 0)),
        provider=detect_provider(row.api_key or '', row.base_url or ''),
        disable_thinking=bool(row.disable_thinking),
        light_base_url=row.light_base_url or '',
        light_api_key=row.light_api_key or '',
        light_model=row.light_model or '',
    )


def _read_settings() -> LLMSettings:
    """从 llm_config 表读配置；表空时从 .env/环境变量 seed 一次（迁移语义）。"""
    with Session(engine) as session:
        row = session.get(LlmConfig, 1)
        if row is None:
            row = _env_seed()
            session.add(row)
            session.commit()
            session.refresh(row)
        return _row_to_settings(row)


def save_settings(updates: dict) -> LLMSettings:
    """PUT /llm/config 的持久化入口：按字段更新 llm_config 行（不存在则先 seed）。

    updates 只接受 LlmConfig 的配置字段（base_url/api_key/model/light_*/timeout/
    retries/disable_thinking）；api_key 传 None/缺省 = 保持现有（掩码语义）。
    """
    allowed = {
        'base_url', 'api_key', 'model',
        'light_base_url', 'light_api_key', 'light_model',
        'timeout', 'retries', 'disable_thinking',
    }
    with Session(engine) as session:
        row = session.get(LlmConfig, 1)
        if row is None:
            row = _env_seed()
        for key, value in updates.items():
            if key in allowed and value is not None:
                setattr(row, key, value)
        row.updated_at = datetime.now()
        session.add(row)
        session.commit()
        session.refresh(row)
        settings = _row_to_settings(row)
    reset_settings_cache()
    return settings


_settings: LLMSettings | None = None


def get_settings() -> LLMSettings:
    """全局单例；测试改环境变量后调 reset_settings_cache() 再取。"""
    global _settings
    if _settings is None:
        _settings = _read_settings()
    return _settings


def reset_settings_cache() -> None:
    global _settings
    _settings = None


def get_light_settings() -> LLMSettings:
    """轻任务配置：未单独配置时直接用主配置（同一客户端，无额外开销）。"""
    s = get_settings()
    return s.with_light_as_main() if s.light_ready else s
