"""LLM 适配层单元测试 — 供应商识别（ccswitch 借鉴点）与配置加载。

不发起真实网络请求；4.4 起 llm_config 表为唯一权威（.env 仅首次 seed），
配置测试用 tmp 引擎 monkeypatch app.llm.config.engine + 缓存重置。
4.1+ 扩充：预设表锁现役模型名（官方文档核实，防再次过期不察觉）、mock_mode。
4.4 扩充：DB 权威配置 / .env seed / 轻任务分级路由（light_*）。
"""
import pytest

from app.llm.config import (
    LLMSettings,
    get_settings,
    get_light_settings,
    reset_settings_cache,
    save_settings,
)
from app.llm.providers import detect_provider


# ---------- detect_provider：base_url host 匹配优先 ----------

@pytest.mark.parametrize(
    ('api_key', 'base_url', 'expected'),
    [
        # base_url 识别（host 子串匹配）
        ('sk-anything', 'https://open.bigmodel.cn/api/paas/v4', 'zhipu'),
        ('sk-anything', 'https://api.deepseek.com/v1', 'deepseek'),
        ('', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'dashscope'),
        ('sk-x', 'https://api.openai.com/v1', 'openai'),
        # key 形态识别（base_url 缺省时）
        ('a' * 32 + '.' + 'b' * 16, '', 'zhipu'),          # 智谱 id.secret
        ('sk-ws-abc.def', '', 'dashscope'),                # 百炼工作区 key（实测格式）
        # base_url 优先于 key 形态：智谱地址 + sk- 开头 key 仍是 zhipu
        ('sk-plain', 'https://open.bigmodel.cn/api/paas/v4', 'zhipu'),
        # 识别不出但已配置 → custom；完全未配置 → ''
        ('sk-unknown-provider', 'https://relay.example.com/v1', 'custom'),
        ('', '', ''),
    ],
)
def test_detect_provider(api_key: str, base_url: str, expected: str):
    assert detect_provider(api_key, base_url) == expected


def test_preset_registry_shape():
    """预设表是 KP 设置页的数据源：必须含 label/base_url/models/key_hint。"""
    from app.llm.providers import PROVIDER_PRESETS

    for key in ('zhipu', 'deepseek', 'dashscope', 'openai'):
        preset = PROVIDER_PRESETS[key]
        assert preset['label'] and preset['base_url'].startswith('https://')
        assert preset['models'], f'{key} 预设缺常用模型'
        assert preset['key_hint']


def test_preset_models_are_current():
    """锁现役模型名（2026-09-06 官方文档核实）：glm-4 系/deepseek-chat 已失效，
    此处故意写死——预设再次过期时该测试会失败提醒刷新（D11：静态表只作推荐）。"""
    from app.llm.providers import PROVIDER_PRESETS

    assert PROVIDER_PRESETS['zhipu']['models'] == ['glm-5.3-flash', 'glm-5.3']
    assert PROVIDER_PRESETS['deepseek']['models'] == ['deepseek-v4-pro', 'deepseek-v4-flash']
    # 2026-09-07 实测刷新：qwen3 系混合推理成主力（LLM_DISABLE_THINKING 配套）
    assert PROVIDER_PRESETS['dashscope']['models'][:2] == ['qwen3.8-max', 'qwen3.8-flash']
    assert PROVIDER_PRESETS['openai']['models'] == ['gpt-5-mini', 'gpt-5.2']


# ---------- LLMSettings：enabled 开关与 key 掩码 ----------

def _settings(**kwargs) -> LLMSettings:
    defaults = dict(
        base_url='https://example.com/v1', api_key='sk-1234567890abcdef',
        model='test-model', timeout=30.0, retries=2, provider='custom',
    )
    defaults.update(kwargs)
    return LLMSettings(**defaults)


def test_settings_enabled_requires_key_and_model():
    assert _settings().enabled is True
    assert _settings(api_key='').enabled is False
    assert _settings(model='').enabled is False


def test_settings_mock_mode():
    """LLM_MODEL=mock 即演示模式：enabled 放宽为 True（无 key 也可跑通全流程）。"""
    assert _settings(model='mock').mock_mode is True
    assert _settings(model='mock').enabled is True
    assert _settings(model='MOCK', api_key='').enabled is True  # 大小写不敏感
    assert _settings(model='mock-x').mock_mode is False
    assert _settings(model='qwen-flash', api_key='').enabled is False


def test_settings_key_masked():
    assert _settings().api_key_masked == 'sk-12***cdef'
    # 过短 key 全掩码，不泄露任何位
    assert _settings(api_key='short').api_key_masked == '***'
    assert _settings(api_key='').api_key_masked == ''


# ---------- llm_config 表：DB 权威 + .env seed（4.4） ----------

@pytest.fixture()
def clean_settings_cache():
    """测试改动环境变量 / DB 后必须重置全局缓存，避免污染其他用例。"""
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture()
def config_engine(tmp_path, monkeypatch):
    """config 模块的 DB 引擎指到 tmp 库 + 清掉真实环境变量（隔离 seed 来源）。"""
    from sqlmodel import SQLModel, create_engine
    import app.llm.config as config_mod
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cfg.db'}", connect_args={'check_same_thread': False},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(config_mod, 'engine', engine)
    for key in config_mod._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    yield engine
    reset_settings_cache()


def test_env_seeds_db_on_first_read(config_engine, monkeypatch, clean_settings_cache):
    """llm_config 表为空时从 .env/环境变量 seed 一次，此后 DB 权威。"""
    monkeypatch.setenv('LLM_BASE_URL', 'https://api.deepseek.com/v1')
    monkeypatch.setenv('LLM_API_KEY', 'sk-' + 'a' * 32)
    monkeypatch.setenv('LLM_MODEL', 'deepseek-v4-flash')
    monkeypatch.setenv('LLM_TIMEOUT', '45')
    monkeypatch.setenv('LLM_RETRIES', '1')
    s = get_settings()
    assert s.provider == 'deepseek'
    assert s.enabled and s.timeout == 45.0 and s.retries == 1
    # 行已落库；再改环境变量不再影响运行时配置（.env 不再是运行时来源）
    monkeypatch.setenv('LLM_MODEL', 'mock')
    reset_settings_cache()
    assert get_settings().model == 'deepseek-v4-flash'


def test_get_settings_defaults_and_bad_values(config_engine, clean_settings_cache, monkeypatch):
    s = get_settings()
    assert s.enabled is False  # 缺 key/model → 未配置（回退纯人工）
    assert s.timeout == 30.0 and s.retries == 2


def test_save_settings_updates_and_resets_cache(config_engine, clean_settings_cache):
    """PUT /llm/config 链路：save_settings 写库 + 清缓存，下次读取即新值。"""
    from sqlmodel import Session
    from app.models import LlmConfig

    with Session(config_engine) as session:
        session.add(LlmConfig(id=1, base_url='https://old.example.com/v1',
                              api_key='sk-old-key-123456', model='old-model'))
        session.commit()

    s = save_settings({'base_url': 'https://new.example.com/v1', 'model': 'mock'})
    assert s.model == 'mock' and s.mock_mode and s.enabled
    # 缓存已被 save_settings 清掉：get_settings 读到新值
    assert get_settings().base_url == 'https://new.example.com/v1'
    with Session(config_engine) as session:
        row = session.get(LlmConfig, 1)
        assert row.api_key == 'sk-old-key-123456'  # 未触碰的字段原样保留


def test_light_routing_fallback_and_split(config_engine, clean_settings_cache):
    """轻任务分级路由：未配置 = 跟随主配置；配置后 = 独立 base_url/key/model。"""
    save_settings({
        'base_url': 'https://api.deepseek.com/v1', 'api_key': 'sk-main', 'model': 'deepseek-v4-pro',
        'light_base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'light_api_key': 'sk-ws-light', 'light_model': 'qwen-flash',
    })
    s = get_settings()
    assert s.light_ready is True
    light = get_light_settings()
    assert light is not s
    assert light.model == 'qwen-flash' and light.base_url.startswith('https://dashscope')
    assert light.enabled is True  # 轻任务配置自洽

    # 未配置 light：get_light_settings 直接返回主配置本身（零开销回退）
    save_settings({'light_model': '', 'light_api_key': '', 'light_base_url': ''})
    s2 = get_settings()
    assert s2.light_ready is False
    assert get_light_settings() is s2
