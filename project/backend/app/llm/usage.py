"""Token 消耗全局总账（4.4，goal §7：token 消耗统计）。

记录点在 provider._complete 拿到真实响应之后（mock 调用无 usage，不计入）。
粒度为全局累计（用户决策 2026-09-08）：单行 LlmUsage 表 + 内存缓存，
写库 best-effort——统计失败绝不影响调用主流程。
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlmodel import Session

from app.db import engine
from app.models import LlmUsage

logger = logging.getLogger('app.llm.usage')


def record_usage(model: str, prompt_tokens: int, completion_tokens: int) -> None:
    """累加一次真实调用的 token 用量。任何异常只记日志，不向上抛。"""
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return
    try:
        with Session(engine) as session:
            row = session.get(LlmUsage, 1)
            if row is None:
                row = LlmUsage(id=1)
                session.add(row)
            row.calls += 1
            row.prompt_tokens += int(prompt_tokens)
            row.completion_tokens += int(completion_tokens)
            row.updated_at = datetime.now()
            session.add(row)
            session.commit()
        logger.debug(
            'token 用量 +1 model=%s prompt=%s completion=%s',
            model, prompt_tokens, completion_tokens,
        )
    except Exception:  # 统计是锦上添花，失败不影响主流程
        logger.warning('token 用量记录失败', exc_info=True)


def get_usage() -> dict:
    """读取全局总账；表不存在/读取失败时返回零值（GET /llm/status 用）。"""
    try:
        with Session(engine) as session:
            row = session.get(LlmUsage, 1)
            if row is None:
                return {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
            return {
                'calls': row.calls,
                'prompt_tokens': row.prompt_tokens,
                'completion_tokens': row.completion_tokens,
            }
    except Exception:
        logger.warning('token 用量读取失败', exc_info=True)
        return {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
