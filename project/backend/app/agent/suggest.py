"""协同建议引擎 — 阶段 4.1（goal §7，决策 D10：协同先行，LLM 无写权）。

流程：玩家剧情行动（WS chat_send 自动触发）或 KP 手动触发 →
收集上下文（场景 / 调查员摘要 / L5 会话窗口）→ 组装提示词 → LLM 生成
2~3 条候选建议 → **只定向广播给 KP**（D8 同款定向广播，D10：无需可见性过滤）。

韧性设计：
  - 单飞 + 合并：同房间生成中再来请求只记 pending，完成后用最新上下文补跑
    一次（玩家连发消息不堆积并发 LLM 调用，也不丢最后一次意图）
  - 自动触发 debounce：静默期 AUTO_DEBOUNCE_SECONDS 秒内来新消息就重排，
    玩家停止发言才生成（单飞防并发、debounce 防频率，长团 token 治理）
  - 自动降级：连续 FAILURE_FALLBACK_THRESHOLD 次失败 → room.agent_mode 置回
    manual + 全员广播 agent_mode_changed + 系统消息（「断网自动降级纯人工」验收）
  - 生成全程在后台协程，聊天与 WS 循环不被阻塞；上下文收集（同步 DB 查询 +
    模组骨架文件读）经 asyncio.to_thread 移出事件循环，防 SQLite 写锁期间
    卡住 WS 心跳 / 聊天广播
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.agent.assembler import (
    SESSION_WINDOW_SIZE,
    SuggestionContext,
    build_suggestion_messages,
    parse_suggestions,
)
from app.agent.kp_styles import get_style, render_style_directive
from app.agent.module_context import load_module_brief
from app.db import engine
from app.llm.config import get_settings
from app.llm.provider import LLMUnavailableError, get_client, get_light_client
from app.models import Card, Message, Room, RoomMember
from app.tasks import spawn_background
from app.ws.manager import build_envelope, manager

# 连续失败 N 次自动回退纯人工主持
FAILURE_FALLBACK_THRESHOLD = 3

# 自动触发静默期（秒）：静默期内来新消息就重排计时，停止发言才生成
AUTO_DEBOUNCE_SECONDS = 2.5

# 4.4：建议生成不传 max_tokens（DeepSeek-v4 系设预算会触发异常长思考，
# 见 provider._complete 注释）；轻任务模型（qwen3.8-flash）默认思考已关，规模可控


class SuggestionEngine:
    def __init__(self) -> None:
        self._inflight: set[str] = set()      # room_id：正在生成
        self._pending: set[str] = set()       # 生成中又来新请求 → 完成后补跑
        self._failures: dict[str, int] = {}   # room_id → 连续失败计数
        self._debounce_tasks: dict[str, asyncio.Task] = {}  # room_id → 静默期计时任务

    def schedule_auto_generate(self, room_id: str) -> None:
        """自动触发入口（WS chat_send）：静默期 debounce，停止发言才真正生成。"""
        self.cancel_auto(room_id)
        self._debounce_tasks[room_id] = spawn_background(
            self._debounced_generate(room_id), name=f'suggestions-debounce-{room_id}',
        )

    def cancel_auto(self, room_id: str) -> None:
        """取消该房间的静默期计时（手动触发 / 切回 manual / 降级时调用）。"""
        task = self._debounce_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

    async def _debounced_generate(self, room_id: str) -> None:
        await asyncio.sleep(AUTO_DEBOUNCE_SECONDS)
        self._debounce_tasks.pop(room_id, None)
        await self.generate_and_broadcast(room_id, trigger='auto')

    async def generate_and_broadcast(
        self,
        room_id: str,
        *,
        request_id: str | None = None,
        focus: str = '',
        trigger: str = 'auto',
    ) -> dict | None:
        """生成建议并 KP 定向广播。返回 payload 供测试断言；并入在途请求时返回 None。"""
        self.cancel_auto(room_id)  # 手动触发 / 补跑时取消尚未到期的静默期计时
        if room_id in self._inflight:
            self._pending.add(room_id)
            return None
        self._inflight.add(room_id)
        try:
            payload = await self._generate(
                room_id, request_id=request_id or uuid.uuid4().hex[:12],
                focus=focus, trigger=trigger,
            )
        finally:
            self._inflight.discard(room_id)
        await self._broadcast_payload(room_id, payload)
        # 在途期间有新请求：补跑一次拿到最新上下文（新任务，不递归占当前栈）
        if room_id in self._pending:
            self._pending.discard(room_id)
            spawn_background(
                self.generate_and_broadcast(room_id, trigger='auto'),
                name=f'suggestions-replay-{room_id}',
            )
        return payload

    # ---------- 内部 ----------

    async def _generate(
        self, room_id: str, *, request_id: str, focus: str, trigger: str,
    ) -> dict:
        # 同步 DB 查询 + 模组骨架文件读移出事件循环（防 SQLite 写锁期间阻塞 WS 心跳/广播）
        ctx, room_ok = await asyncio.to_thread(self._collect_context, room_id, focus=focus)
        if not room_ok:
            return self._payload(request_id, 'degraded', [], trigger,
                                 error='房间不存在或已解散', category='no_room')
        try:
            messages = build_suggestion_messages(ctx)
            # 4.4 分级路由：建议生成是低风险轻任务，走轻任务模型（未配置则同主模型）
            raw = await get_light_client().chat(
                messages, temperature=0.8, json_mode=True,
            )
            try:
                suggestions = parse_suggestions(raw)
            except ValueError:
                # 输出解析失败：带原输出向模型重问一次修复（比直接降级体验好得多）
                fixed = await get_light_client().chat(
                    messages + [
                        {'role': 'assistant', 'content': raw},
                        {'role': 'user', 'content':
                            '上面的输出不是合法 JSON（常见错误：缺逗号、字符串内换行）。'
                            '请修复并只输出符合协议的 JSON 对象，禁止任何解释或代码围栏。'},
                    ],
                    temperature=0.2, json_mode=True,
                )
                suggestions = parse_suggestions(fixed)
        except LLMUnavailableError as exc:
            return await self._handle_failure(room_id, request_id, trigger, exc)
        except ValueError as exc:  # LLM 输出解析失败，按降级处理
            return await self._handle_failure(
                room_id, request_id, trigger,
                LLMUnavailableError('bad_response', f'LLM 输出无法解析：{exc}'),
            )
        self._failures.pop(room_id, None)  # 成功即清零
        s = get_settings()
        return self._payload(
            request_id, 'ok', suggestions, trigger,
            model=s.light_model if s.light_ready else s.model,
        )

    def _collect_context(self, room_id: str, *, focus: str = '') -> tuple[SuggestionContext, bool]:
        """一次 DB 会话收集全部上下文；房间不存在返回 (空上下文, False)。"""
        with Session(engine) as session:
            room = session.get(Room, room_id)
            if not room:
                return SuggestionContext(), False

            investigators = []
            rows = session.exec(
                select(RoomMember, Card)
                .join(Card, RoomMember.card_id == Card.id)
                .where(RoomMember.room_id == room_id, RoomMember.role == 'player')
            ).all()
            for member, card in rows:
                card_data = card.card_data or {}
                derived = card_data.get('derived', {})
                investigators.append({
                    'name': card.name,
                    # 花名册昵称：工具 target 的唯一合法取值（4.4 实测修复，与 keeper 同源）
                    'player_name': member.player_name,
                    'occupation': card.occupation,
                    'hp': card.current_hp,
                    'hp_max': int(derived.get('HP', 0)),
                    'san': card.current_sanity,
                    'san_max': int(derived.get('SAN', 0)),
                })

            # L5 会话窗口：最近 N 条 narrative（含骰/状态/系统行，content 已是可读文本）
            recent = session.exec(
                select(Message)
                .where(Message.room_id == room_id, Message.channel == 'narrative')
                .order_by(Message.id.desc())
                .limit(SESSION_WINDOW_SIZE)
            ).all()
            window = [
                {
                    'sender': m.sender,
                    'role': (m.payload or {}).get('role', ''),
                    'text': m.content,
                }
                for m in reversed(recent)
            ]
            # "最新剧情推进"：窗口内最新一条消息（KP 叙事或玩家行动皆可——
            # 触发源已扩展到 KP 叙事后，上下文重心必须跟随最新推进，
            # 否则 KP 采纳建议继续叙事后，建议仍会回应上一条玩家行动）
            latest_action = recent[0].content if recent else ''

            return SuggestionContext(
                room_name=room.name,
                scene_title=room.scene_title,
                scene_desc=room.scene_desc,
                investigators=investigators,
                session_window=window,
                latest_action=latest_action,
                focus=focus,
                style=render_style_directive(get_style(session, room.style_id)),  # L2（4.4）
                # L3（5.4）：房间挂载的模组骨架；未挂载时回退 scenario_brief.txt
                scenario=load_module_brief(session, room_id),
            ), True

    async def _handle_failure(
        self, room_id: str, request_id: str, trigger: str, exc: LLMUnavailableError,
    ) -> dict:
        """连续失败计数 + 达阈值自动降级：置回 manual、广播全员、落系统消息。"""
        count = self._failures.get(room_id, 0) + 1
        self._failures[room_id] = count
        if count >= FAILURE_FALLBACK_THRESHOLD:
            self.cancel_auto(room_id)  # 已回退纯人工，取消尚未到期的静默期计时
            self._failures.pop(room_id, None)
            with Session(engine) as session:
                room = session.get(Room, room_id)
                if room and room.agent_mode != 'manual':
                    room.agent_mode = 'manual'
                    session.add(room)
                    session.add(Message(
                        room_id=room_id, channel='system', type='sys', sender='system',
                        content=f'LLM 连续 {FAILURE_FALLBACK_THRESHOLD} 次生成失败'
                                f'（{exc.message}），已自动回退纯人工主持',
                    ))
                    session.commit()
            # 全员广播模式变化（玩家也看得到"已回退纯人工"）；房间已不存在时是无连接空操作
            await manager.broadcast(room_id, build_envelope(
                'agent_mode_changed', room_id, 'system', 'system',
                {'agent_mode': 'manual'},
            ))
        return self._payload(
            request_id, 'degraded', [], trigger,
            error=exc.message, category=exc.category,
        )

    @staticmethod
    def _payload(
        request_id: str, status: str, suggestions: list, trigger: str,
        **extra,
    ) -> dict:
        payload = {
            'request_id': request_id,
            'status': status,
            'suggestions': suggestions,
            'trigger': trigger,
            'created_at': datetime.now().isoformat(timespec='seconds'),
        }
        payload.update(extra)
        return payload

    @staticmethod
    async def _broadcast_payload(room_id: str, payload: dict) -> None:
        """建议只进 KP 屏幕（D8 同款按角色定向；D10：协同模式无 keeper 内容外泄风险）。"""
        await manager.broadcast_to_roles(
            room_id,
            build_envelope('suggestions', room_id, 'assistant', 'system', payload),
            {'kp'},
        )


suggestion_engine = SuggestionEngine()
