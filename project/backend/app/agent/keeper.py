"""全自动主持引擎（4.2，goal §7 4.2 / §6.3 / §6.4 / §6.7）。

流程：玩家剧情行动或 KP 插话（WS chat_send，agent_mode='auto'）→
收集上下文（模组骨架 + scenario_state + 会话窗口，to_thread）→ 缓存感知
组装（BP1/BP2/BP3）→ 工具循环（LLM 调用工具 → 引擎执行 → 结果回喂，
最多 MAX_TOOL_ROUNDS 轮）→ 四段 JSON 终稿 → **双通道分发**（D8）：

  narration_public → Message(secret=False) 落库 + chat_new 全员广播
  keeper_notes     → Message(secret=True) 落库 + 只定向 KP（复用暗骰机制）

韧性设计（与协同建议引擎同款）：单飞 + 合并 + pending 补跑；连续
FAILURE_FALLBACK_THRESHOLD 次失败自动回退 manual + 系统消息；后台协程
spawn_background 挂异常回调；上下文收集经 asyncio.to_thread 移出事件循环。

终稿解析失败自动带原输出重问一次修复（temperature=0.2 + json_mode），
仍失败按 bad_response 计入失败计数。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.agent.assembler import (
    SESSION_WINDOW_SIZE,
    AutoContext,
    build_auto_messages,
    parse_auto_turn,
)
from app.agent.kp_styles import get_style, render_style_directive
from app.agent.suggest import _load_scenario_brief
from app.agent.tools import (
    AI_KEEPER_NAME,
    TOOL_SCHEMAS,
    _skill_row_value,
    execute_tool,
    get_scenario,
)
from app.db import engine
from app.llm.config import get_settings
from app.llm.provider import LLMUnavailableError, get_client, get_light_client
from app.models import Card, Clue, GameClock, Message, Npc, Room, RoomMember, Thread
from app.tasks import spawn_background
from app.ws.manager import build_envelope, manager

logger = logging.getLogger('app.agent.keeper')

# 工具循环轮数上限：防 LLM 无限工具调用（一轮内 5 次工具调用足够铺开一段剧情）
MAX_TOOL_ROUNDS = 5

# 自动触发静默期（秒）：静默期内来新玩家行动就重排计时，停止发言才开轮
AUTO_DEBOUNCE_SECONDS = 2.5

# 连续失败 N 次自动回退纯人工主持（与协同建议同策略）
FAILURE_FALLBACK_THRESHOLD = 3

_REPAIR_INSTRUCTION = (
    '上面的输出不是合法终稿（必须是一个 JSON 对象：narration_public 非空、'
    'keeper_notes 字符串、options 为 2~4 条的字符串数组）。'
    '请修复并只输出符合协议的 JSON 对象，禁止任何解释或代码围栏。'
)


def filter_final_visibility(final: dict, keeper_markers: list[str]) -> dict:
    """D8 系统级兜底（goal §6.4）：公开叙事与行动选项中出现的 keeper 专属片段
    强制替换为占位符，并转入 keeper_notes 供 KP 对照。纯函数，便于单测。

    标记来源见 _keeper_markers：keeper 线索编号 / keeper 时钟名 / 未结算伏笔 /
    NPC 隐藏动机。提示词自觉之外的第二道闸——不依赖 LLM 不越权。
    """

    def _clean(text: str) -> tuple[str, list[str]]:
        hits: list[str] = []
        for marker in keeper_markers:
            if marker and marker in text:
                text = text.replace(marker, '（……）')
                hits.append(marker)
        return text, hits

    narration, hits = _clean(final['narration_public'])
    options: list[str] = []
    for opt in final['options']:
        cleaned, opt_hits = _clean(opt)
        hits.extend(h for h in opt_hits if h not in hits)
        options.append(cleaned)
    if hits:
        final['narration_public'] = narration
        final['options'] = options
        note = '【可见性过滤】已从公开叙事摘除 keeper 片段：' + '；'.join(hits)
        final['keeper_notes'] = f"{final['keeper_notes']}\n{note}" if final['keeper_notes'] else note
    return final


def _keeper_markers(session: Session, room_id: str) -> list[str]:
    """当前房间不得出现在公开叙事里的字符串清单（D8 过滤依据）。"""
    markers: list[str] = []
    for c in session.exec(select(Clue).where(Clue.room_id == room_id)).all():
        if c.visibility == 'keeper':
            markers.append(c.code)
    for ck in session.exec(select(GameClock).where(GameClock.room_id == room_id)).all():
        if ck.visibility == 'keeper':
            markers.append(ck.name)
    for t in session.exec(select(Thread).where(Thread.room_id == room_id)).all():
        if not t.resolved and len(t.content) >= 8:
            markers.append(t.content)
    for n in session.exec(select(Npc).where(Npc.room_id == room_id)).all():
        if n.hidden_motive and len(n.hidden_motive) >= 8:
            markers.append(n.hidden_motive)
    return markers


class AutoKeeper:
    """全自动主持引擎。单例 auto_keeper；每房间同一时刻最多一轮在跑。"""

    def __init__(self) -> None:
        self._inflight: set[str] = set()
        self._pending: set[str] = set()       # 生成中又来新行动 → 完成后补跑一轮
        self._failures: dict[str, int] = {}   # room_id → 连续失败计数
        self._debounce_tasks: dict[str, asyncio.Task] = {}  # room_id → 静默期计时任务

    def schedule_turn(self, room_id: str) -> None:
        """自动触发入口（玩家行动）：静默期 debounce，停止发言才真正开轮。

        auto 模式一轮最多 5 次 LLM 调用，是 token 消耗大头——单飞合并防并发、
        debounce 防频率（与协同建议引擎同款策略）。
        """
        self.cancel_scheduled(room_id)
        self._debounce_tasks[room_id] = spawn_background(
            self._debounced_turn(room_id), name=f'auto-keeper-debounce-{room_id}',
        )

    def run_immediately(self, room_id: str) -> None:
        """KP 插话/手动触发：取消未到期的静默期计时，立即开轮。

        KP 的推进是有意识的主持动作，不该被静默期吞掉；玩家的最新行动已在
        消息表里，立即开轮拿到的上下文自然包含它。
        """
        self.cancel_scheduled(room_id)
        spawn_background(self.run_turn(room_id), name=f'auto-keeper-immediate-{room_id}')

    def cancel_scheduled(self, room_id: str) -> None:
        """取消该房间的静默期计时（KP 插话 / 切回 manual / 降级时调用）。"""
        task = self._debounce_tasks.pop(room_id, None)
        if task and not task.done():
            task.cancel()

    async def _debounced_turn(self, room_id: str) -> None:
        await asyncio.sleep(AUTO_DEBOUNCE_SECONDS)
        self._debounce_tasks.pop(room_id, None)
        await self.run_turn(room_id)

    async def run_turn(self, room_id: str, *, trigger: str = 'auto') -> dict | None:
        """跑一整轮主持（工具循环 + 终稿双通道分发）。并入在途轮次时返回 None。"""
        self.cancel_scheduled(room_id)  # 真正开轮时取消尚未到期的静默期计时
        if room_id in self._inflight:
            self._pending.add(room_id)
            return None
        self._inflight.add(room_id)
        try:
            payload = await self._turn(room_id, request_id=uuid.uuid4().hex[:12], trigger=trigger)
        except LLMUnavailableError as exc:
            payload = await self._handle_failure(room_id, exc)
        except ValueError as exc:  # 终稿修复后仍解析失败
            payload = await self._handle_failure(
                room_id, LLMUnavailableError('bad_response', f'AI 终稿无法解析：{exc}'),
            )
        except Exception as exc:  # 非预期异常（DB 等）：计失败并让 KP 看见，防「主持中」永久挂起
            logger.exception('AI 主持轮次内部异常 room=%s', room_id)
            payload = await self._handle_failure(
                room_id, LLMUnavailableError('server', f'AI 主持内部错误：{exc}'),
            )
        finally:
            self._inflight.discard(room_id)
        # 在途期间有新行动：补跑一轮拿到最新上下文（含本轮 AI 叙事）
        if room_id in self._pending:
            self._pending.discard(room_id)
            spawn_background(self.run_turn(room_id), name=f'auto-keeper-replay-{room_id}')
        return payload

    # ---------- 内部 ----------

    async def _turn(self, room_id: str, *, request_id: str, trigger: str) -> dict:
        ctx, ok = await asyncio.to_thread(self._collect_context, room_id)
        if not ok:
            return self._payload(request_id, 'degraded', None, trigger,
                                 error='房间不存在或已解散', category='no_room')
        messages = build_auto_messages(ctx)

        # ---- 工具循环：LLM 调用 → 引擎执行 → 结果回喂 ----
        used_tools: set[str] = set()
        for _ in range(MAX_TOOL_ROUNDS):
            # 4.4：不传 max_tokens（实测 DeepSeek-v4-pro 设预算反而触发异常长思考，
            # 见 provider._complete 注释）；输出规模由协议与供应商上限兜底
            turn = await get_client().chat_with_tools(
                messages, tools=TOOL_SCHEMAS, temperature=0.7,
            )
            if not turn.has_tool_calls:
                return await self._finalize(room_id, request_id, trigger, messages, turn.content)

            # assistant 工具调用消息回喂（arguments 重新序列化为 JSON 字符串）
            messages.append({
                'role': 'assistant',
                'content': turn.content or None,
                'tool_calls': [
                    {
                        'id': tc['id'],
                        'type': 'function',
                        'function': {'name': tc['name'], 'arguments': json.dumps(tc['arguments'], ensure_ascii=False)},
                    }
                    for tc in turn.tool_calls
                ],
            })
            for tc in turn.tool_calls:
                used_tools.add(tc['name'])
                result = await execute_tool(tc['name'], tc['arguments'], room_id)
                messages.append({'role': 'tool', 'tool_call_id': tc['id'], 'content': result})

        # 工具轮数耗尽：强制无工具输出终稿（叙事必须收口，不允许轮次悄悄蒸发）
        content = await get_client().chat(
            messages, temperature=0.5, json_mode=True,
        )
        return await self._finalize(room_id, request_id, trigger, messages, content,
                                    scene_changed='set_scene' in used_tools)

    async def _finalize(self, room_id, request_id, trigger, messages, content: str,
                        *, scene_changed: bool = False) -> dict:
        """解析终稿（失败重问一次），双通道分发后返回 payload。

        scene_changed：本轮推进了场景 → 触发场景收束摘要（后台 best-effort）。
        """
        try:
            final = parse_auto_turn(content)
        except ValueError:
            fixed = await get_client().chat(
                messages + [
                    {'role': 'assistant', 'content': content},
                    {'role': 'user', 'content': _REPAIR_INSTRUCTION},
                ],
                temperature=0.2, json_mode=True,
            )
            final = parse_auto_turn(fixed)
        self._failures.pop(room_id, None)  # 成功清零
        await self._dispatch_final(room_id, final)
        if scene_changed:
            spawn_background(self._summarize_scene(room_id), name=f'scene-summary-{room_id}')
        return self._payload(request_id, 'ok', final, trigger, model=get_settings().model)

    @staticmethod
    async def _dispatch_final(room_id: str, final: dict) -> None:
        """双通道分发（D8）：公开叙事全员可见，keeper 笔记只进 KP 屏。

        分发前过 filter_final_visibility——提示词自觉之外的系统级兜底。
        """
        with Session(engine) as session:
            final = filter_final_visibility(final, _keeper_markers(session, room_id))
        with Session(engine) as session:
            session.add(Message(
                room_id=room_id, channel='narrative', type='text',
                sender=AI_KEEPER_NAME, content=final['narration_public'], secret=False,
                payload={'role': 'kp', 'ai': True, 'options': final['options']},
            ))
            session.commit()
        await manager.broadcast(room_id, build_envelope(
            'chat_new', room_id, AI_KEEPER_NAME, 'narrative',
            {'text': final['narration_public'], 'role': 'kp', 'ai': True,
             'options': final['options']},
        ))
        if final['keeper_notes']:
            with Session(engine) as session:
                from app.agent.tools import persist_keeper_note

                persist_keeper_note(session, room_id, final['keeper_notes'])

    def _collect_context(self, room_id: str) -> tuple[AutoContext, bool]:
        """一次 DB 会话收集全部上下文（同步函数，调用方 to_thread）。"""
        with Session(engine) as session:
            room = session.get(Room, room_id)
            if not room:
                return AutoContext(), False

            investigators = []
            rows = session.exec(
                select(RoomMember, Card)
                .join(Card, RoomMember.card_id == Card.id)
                .where(RoomMember.room_id == room_id, RoomMember.role == 'player')
            ).all()
            for member, card in rows:
                data = card.card_data or {}
                derived = data.get('derived', {})
                # 技能表：label → 当前值，按值降序取前 40 条（压 token，覆盖主用技能）
                skills: dict[str, int] = {}
                for s in data.get('skills', []):
                    label = s.get('name', '')
                    if s.get('detail'):
                        label = f"{label}（{s['detail']}）"
                    value = _skill_row_value(s)
                    if value > 0:
                        skills[label] = value
                investigators.append({
                    'name': data.get('name', card.name),
                    'occupation': card.occupation,
                    'hp': card.current_hp,
                    'hp_max': int(derived.get('HP', 0)),
                    'san': card.current_sanity,
                    'san_max': int(derived.get('SAN', 0)),
                    'skills': dict(sorted(skills.items(), key=lambda kv: -kv[1])[:40]),
                })

            recent = session.exec(
                select(Message)
                .where(Message.room_id == room_id, Message.channel == 'narrative')
                .order_by(Message.id.desc())
                .limit(SESSION_WINDOW_SIZE)
            ).all()
            window = [
                {'sender': m.sender, 'role': (m.payload or {}).get('role', ''), 'text': m.content}
                for m in reversed(recent)
            ]
            scenario_row = get_scenario(session, room_id)
            events = list(scenario_row.data.get('events', []) or [])

            # ── 剧情记忆五要素（4.3，KP 全知视角；公开层兜底见 filter_final_visibility）──
            clue_lines = [
                f'[{c.code}·{"公开" if c.visibility == "public" else "仅KP"}·{c.status}] {c.content}'
                + (f'（来源：{c.source}）' if c.source else '')
                + (f'（指向：{c.points_to}）' if c.points_to else '')
                for c in session.exec(
                    select(Clue).where(Clue.room_id == room_id).order_by(Clue.id)
                ).all()
            ]
            clock_lines = [
                f'{ck.name} {ck.progress}/{ck.target}' + (f'（{ck.note}）' if ck.note else '')
                for ck in session.exec(
                    select(GameClock).where(GameClock.room_id == room_id).order_by(GameClock.id)
                ).all()
            ]
            thread_lines = [
                f'#{t.id} {t.content}'
                for t in session.exec(
                    select(Thread).where(Thread.room_id == room_id).order_by(Thread.id)
                ).all()
                if not t.resolved
            ]
            npc_lines = [
                f'{n.name}（{"在场" if n.status == "active" else "已离场"}；'
                f'身份：{n.public_identity or "未明"}）'
                + (f'｜动机(仅KP)：{n.hidden_motive}' if n.hidden_motive else '')
                + (f'｜误导(仅KP)：{n.misdirection}' if n.misdirection else '')
                + (f'｜被逼问(仅KP)：{n.pressed_reaction}' if n.pressed_reaction else '')
                + (f'｜离场预案(仅KP)：{n.exit_plan}' if n.exit_plan else '')
                for n in session.exec(
                    select(Npc).where(Npc.room_id == room_id).order_by(Npc.id)
                ).all()
            ]
            summary_lines = [
                f'「{s.get("scene_title", "")}」{s.get("public", "")}'
                for s in (scenario_row.data.get('scene_summaries', []) or [])
                if isinstance(s, dict)
            ]

            ctx = AutoContext(
                room_name=room.name,
                scene_title=room.scene_title,
                scene_desc=room.scene_desc,
                style=render_style_directive(get_style(session, room.style_id)),  # L2（4.4）
                scenario=_load_scenario_brief(),
                clues=clue_lines,
                clocks=clock_lines,
                threads=thread_lines,
                npcs=npc_lines,
                scene_summaries=summary_lines,
                events=events,
                investigators=investigators,
                session_window=window,
                latest_action=recent[0].content if recent else '',
            )
            return ctx, True

    async def _summarize_scene(self, room_id: str) -> None:
        """场景收束摘要（4.3，goal §6.5：场景结束触发双份摘要）。

        set_scene 工具触发，后台 best-effort（失败只记日志，不阻塞下一轮）：
        玩家版摘要入 BP2 剧情记忆（公开信息，跨场景引用）；KP 版仅存档备查。
        存 scenario_state.data['scene_summaries']，滚动保留最近 5 条。
        """
        try:
            ctx, ok = await asyncio.to_thread(self._collect_context, room_id)
            if not ok:
                return
            recent_text = '\n'.join(
                f"[{m['sender']}] {m['text'][:120]}" for m in ctx.session_window[-12:]
            )
            raw = await get_light_client().chat(
                [
                    {'role': 'system', 'content': (
                        '你是跑团剧情摘要器。根据剧情记录只输出一个 JSON 对象：'
                        '{"public": "...", "keeper": "..."}。'
                        'public 是玩家视角的场景摘要（≤120 字，只含玩家可知信息，'
                        '禁止出现仅 KP 可知的线索/动机/暗骰结果）；'
                        'keeper 是 KP 视角补充（≤150 字，含未回收伏笔与暗线现状）。'
                        '禁止任何解释或代码围栏。')},
                    {'role': 'user', 'content':
                        f'【场景】{ctx.scene_title or "（未设置）"}\n'
                        + '\n'.join(f'- {e}' for e in ctx.events[-10:])
                        + '\n【剧情记录】（旧 → 新）\n' + recent_text},
                ],
                temperature=0.3, max_tokens=500, json_mode=True,
            )
            data = json.loads(raw)
            public = str(data.get('public') or '').strip()[:300]
            keeper = str(data.get('keeper') or '').strip()[:300]
            if not public:
                return

            def _save() -> None:
                with Session(engine) as session:
                    row = get_scenario(session, room_id)
                    summaries = list(row.data.get('scene_summaries', []) or [])
                    summaries.append({
                        'scene_title': ctx.scene_title, 'public': public, 'keeper': keeper,
                        'created_at': datetime.now().isoformat(timespec='seconds'),
                    })
                    row.data = {**row.data, 'scene_summaries': summaries[-5:]}  # 整体重赋触发变更检测
                    session.add(row)
                    session.commit()

            await asyncio.to_thread(_save)
            logger.info('场景摘要完成 room=%s scene=%s', room_id, ctx.scene_title)
        except Exception:
            logger.warning('场景摘要生成失败 room=%s', room_id, exc_info=True)

    async def _handle_failure(self, room_id: str, exc: LLMUnavailableError) -> dict:
        """连续失败计数 + 达阈值自动降级：置回 manual、广播全员、落系统消息。

        每次失败都给 KP 发一条 keeper 提示——AI 没说话时 KP 必须知道为什么
        （keeper 行只进 KP 屏幕，玩家无感）。
        """
        count = self._failures.get(room_id, 0) + 1
        self._failures[room_id] = count
        try:
            with Session(engine) as session:
                from app.agent.tools import persist_keeper_note

                persist_keeper_note(
                    session, room_id,
                    f'⚠️ AI 主持本轮失败（第 {count} 次）：{exc.message}',
                )
        except Exception:  # 提示落库失败不影响失败计数主流程
            logger.warning('失败提示落库失败 room=%s', room_id, exc_info=True)
        # 4.4 遗留修复：降级时同步给 KP 发 suggestions 降级信封——前端据此清掉
        # 「AI 主持中」骨架（此前失败只发 keeper 文本，keeperPending 永不清除而残留）
        try:
            await manager.broadcast_to_roles(
                room_id,
                build_envelope('suggestions', room_id, 'assistant', 'system', {
                    'request_id': uuid.uuid4().hex[:12],
                    'status': 'degraded', 'suggestions': [], 'trigger': 'auto',
                    'created_at': datetime.now().isoformat(timespec='seconds'),
                    'error': exc.message, 'category': exc.category,
                }),
                {'kp'},
            )
        except Exception:
            logger.warning('降级信封广播失败 room=%s', room_id, exc_info=True)
        if count >= FAILURE_FALLBACK_THRESHOLD:
            self.cancel_scheduled(room_id)  # 已回退纯人工，取消尚未到期的静默期计时
            self._failures.pop(room_id, None)
            with Session(engine) as session:
                room = session.get(Room, room_id)
                if room and room.agent_mode != 'manual':
                    room.agent_mode = 'manual'
                    session.add(room)
                    session.add(Message(
                        room_id=room_id, channel='system', type='sys', sender='system',
                        content=f'AI 主持连续 {FAILURE_FALLBACK_THRESHOLD} 轮失败'
                                f'（{exc.message}），已自动回退纯人工主持',
                    ))
                    session.commit()
            await manager.broadcast(room_id, build_envelope(
                'agent_mode_changed', room_id, 'system', 'system',
                {'agent_mode': 'manual'},
            ))
        return self._payload(
            uuid.uuid4().hex[:12], 'degraded', None, 'auto',
            error=exc.message, category=exc.category,
        )

    @staticmethod
    def _payload(request_id: str, status: str, final: dict | None, trigger: str, **extra) -> dict:
        payload = {
            'request_id': request_id,
            'status': status,
            'turn': final,
            'trigger': trigger,
            'created_at': datetime.now().isoformat(timespec='seconds'),
        }
        payload.update(extra)
        return payload


auto_keeper = AutoKeeper()
