"""Token 消耗全局总账（4.4，goal §7：token 消耗统计）。

记录点在 provider._complete 拿到真实响应之后（mock 调用无 usage，不计入）。
粒度为全局累计（用户决策 2026-09-08）：单行 LlmUsage 表 + 内存缓存，
写库 best-effort——统计失败绝不影响调用主流程。
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from sqlmodel import Session

from app.db import engine
from app.models import LlmUsage, RoomUsage

logger = logging.getLogger('app.llm.usage')

# 当前调用链所属房间（2026-09-10）：引擎层用 usage_room() 绑定，provider 记账时
# 无需感知 room_id。asyncio 下每个任务自带 context 副本，spawn_background 出的
# 后台任务会继承创建时刻的上下文，故「轮次/建议生成」内部所有 LLM 调用都能归集。
_current_room: ContextVar[str] = ContextVar('llm_usage_room', default='')


@contextmanager
def usage_room(room_id: str):
    """把当前协程分支内所有 LLM 调用归集到 room_id（用于按房间统计 token）。"""
    token = _current_room.set(room_id or '')
    try:
        yield
    finally:
        _current_room.reset(token)


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached_tokens: int = 0,
    room_id: str | None = None,
) -> None:
    """累加一次真实调用的 token 用量。任何异常只记日志，不向上抛。

    cached_tokens 是 prompt_tokens 中命中前缀缓存的部分（供应商按折扣计价）；
    SDK 没给该字段（无缓存的供应商/模型）时保持 0，口径与历史数据兼容。

    room_id 缺省时取调用链上绑定的房间（`usage_room` 上下文）——这样引擎层
    不用把 room_id 一路透传到 provider；与房间无关的调用（模组解析、连通性
    测试）只记全局总账。
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return
    cached = max(0, min(int(cached_tokens or 0), int(prompt_tokens or 0)))
    room = room_id if room_id is not None else _current_room.get()
    try:
        with Session(engine) as session:
            row = session.get(LlmUsage, 1)
            if row is None:
                row = LlmUsage(id=1)
                session.add(row)
            row.calls += 1
            row.prompt_tokens += int(prompt_tokens)
            row.completion_tokens += int(completion_tokens)
            row.cached_tokens += cached
            row.updated_at = datetime.now()
            session.add(row)
            if room:
                room_row = session.get(RoomUsage, room)
                if room_row is None:
                    room_row = RoomUsage(room_id=room)
                room_row.calls += 1
                room_row.prompt_tokens += int(prompt_tokens)
                room_row.completion_tokens += int(completion_tokens)
                room_row.cached_tokens += cached
                room_row.updated_at = datetime.now()
                session.add(room_row)
            session.commit()
        logger.debug(
            'token 用量 +1 model=%s room=%s prompt=%s（缓存命中 %s）completion=%s',
            model, room or '-', prompt_tokens, cached, completion_tokens,
        )
    except Exception:  # 统计是锦上添花，失败不影响主流程
        logger.warning('token 用量记录失败', exc_info=True)


_EMPTY = {
    'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0,
    'cached_tokens': 0, 'cache_hit_rate': 0.0,
}


def _pack(row) -> dict:
    """统一出参形态（全局/单房间同构），附 cache_hit_rate（0~1，保留 3 位）。"""
    prompt = int(row.prompt_tokens or 0)
    cached = int(getattr(row, 'cached_tokens', 0) or 0)
    return {
        'calls': row.calls,
        'prompt_tokens': prompt,
        'completion_tokens': row.completion_tokens,
        'cached_tokens': cached,
        'cache_hit_rate': round(cached / prompt, 3) if prompt else 0.0,
    }


def get_usage() -> dict:
    """读取全局总账；表不存在/读取失败时返回零值（GET /llm/status 用）。

    老库（无 cached_tokens 列）读取失败时回退零值，不阻塞设置面板。
    """
    try:
        with Session(engine) as session:
            row = session.get(LlmUsage, 1)
            return dict(_EMPTY) if row is None else _pack(row)
    except Exception:
        logger.warning('token 用量读取失败', exc_info=True)
        return dict(_EMPTY)


def get_room_usage(room_id: str) -> dict:
    """读取单房间（一场次）总账；无记录返回零值。

    2026-09-10 用户反馈 #3：全局总账看不出"一局团花了多少"，故按 room_id 累计。
    返回形态与 get_usage 完全一致，前端两行并排展示。
    """
    try:
        with Session(engine) as session:
            row = session.get(RoomUsage, room_id)
            return dict(_EMPTY) if row is None else _pack(row)
    except Exception:
        logger.warning('房间 token 用量读取失败 room=%s', room_id, exc_info=True)
        return dict(_EMPTY)


def clear_room_usage(room_id: str) -> None:
    """房间销毁时顺带清理该房间的用量行（best-effort，失败不影响解散）。"""
    try:
        with Session(engine) as session:
            row = session.get(RoomUsage, room_id)
            if row is not None:
                session.delete(row)
                session.commit()
    except Exception:
        logger.warning('房间 token 用量清理失败 room=%s', room_id, exc_info=True)
