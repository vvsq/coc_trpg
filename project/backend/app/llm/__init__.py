"""LLM 供应商适配层 — 阶段 4.1（goal §3/§7，决策 D2/D10）。

职责边界：
  - config.py     .env 配置加载（llm_config 表与 KP 设置页后置 4.4，决策 D10）
  - providers.py  供应商预设注册表 + API key/base_url 自动识别（借鉴 ccswitch）
  - provider.py   OpenAI 兼容异步客户端：超时 / 重试 / 失败降级异常

上层（app/agent/）只依赖 provider.chat() 一个入口，供应商差异全部在这里消化。
"""
