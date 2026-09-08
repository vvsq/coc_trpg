"""供应商预设注册表 + API key / base_url 自动识别。

借鉴 ccswitch 的「预设模板 + 填 key 即用」思路：常用 OpenAI 兼容供应商的
base_url 与推荐模型预先登记，凭 base_url 的 host 或 key 的形态即可识别
供应商，避免 KP 手抄出错。阶段 4.4 的 KP 设置页直接复用本表做下拉预设。

D11（4.1+ 修订）：模型名迭代太快，静态表只作「推荐」参考——真实可用模型
以 `GET /llm/models` 实时探测（client.models.list()）为准，前端保留手填兜底。
现役模型名 2026-09-06 已按各家官方文档核实：
  智谱 glm-5.3-flash / glm-5.3（docs.bigmodel.cn）
  DeepSeek deepseek-v4-pro / deepseek-v4-flash（旧别名 2026-07-24 停用）
  OpenAI gpt-5-mini / gpt-5.2（developers.openai.com/api/docs/models）

识别优先级：base_url host 匹配 > key 形态启发式 > custom。
key 形态只能区分智谱（id.secret）与 dashscope 新式工作区 key（sk-ws-前缀），
deepseek/openai 同为 sk- 前缀，仅凭 key 无法区分 → 返回 None 交由 base_url 定。
key 形态启发式仅供参考展示（/llm/status、/llm/test），不参与任何关键路径；
智谱新 key 格式（id.secret 变长）旧正则可能已不匹配，识别不出按 custom 展示即可。
"""
import re
from urllib.parse import urlparse

# 预设注册表：preset_key → 展示信息。models 仅为静态推荐（首位是日常档），真实列表以探测为准。
PROVIDER_PRESETS: dict[str, dict] = {
    'zhipu': {
        'label': '智谱 GLM',
        'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'models': ['glm-5.3-flash', 'glm-5.3'],
        'key_hint': '格式为 id.secret',
    },
    'deepseek': {
        'label': 'DeepSeek',
        'base_url': 'https://api.deepseek.com/v1',
        'models': ['deepseek-v4-pro', 'deepseek-v4-flash'],
        'key_hint': '以 sk- 开头',
    },
    'dashscope': {
        'label': '阿里云百炼（千问）',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'models': ['qwen3.8-max', 'qwen3.8-flash', 'qwen3.7-plus'],
        'key_hint': '以 sk- 或 sk-ws- 开头',
    },
    'openai': {
        'label': 'OpenAI',
        'base_url': 'https://api.openai.com/v1',
        'models': ['gpt-5-mini', 'gpt-5.2'],
        'key_hint': '以 sk- 开头',
    },
}

# host 关键词 → preset_key（base_url 识别依据，子串匹配）
_HOST_HINTS: dict[str, str] = {
    'bigmodel.cn': 'zhipu',
    'deepseek.com': 'deepseek',
    'dashscope.aliyuncs.com': 'dashscope',
    'aliyuncs.com': 'dashscope',
    'api.openai.com': 'openai',
    'openai.com': 'openai',
}

# 智谱 key 形态：32 位 hex + '.' + 16 位字母数字（旧格式；新 key 可能不匹配，仅展示参考）
_ZHIPU_KEY_RE = re.compile(r'^[0-9a-f]{32}\.[0-9a-zA-Z]{16}$')


def detect_provider(api_key: str = '', base_url: str = '') -> str:
    """识别供应商，返回 preset_key；识别不出但已配置时返回 'custom'，完全未配置返回 ''。"""
    if not api_key and not base_url:
        return ''
    url = (base_url or '').strip()
    if url:
        host = urlparse(url if '://' in url else f'https://{url}').hostname or ''
        for hint, preset in _HOST_HINTS.items():
            if host and (host == hint or host.endswith('.' + hint) or hint in host):
                return preset
    key = (api_key or '').strip()
    if key.startswith('sk-ws-'):
        return 'dashscope'  # 百炼工作区 key（实测格式 sk-ws-…）
    if _ZHIPU_KEY_RE.match(key):
        return 'zhipu'
    return 'custom'
