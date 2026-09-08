"""WebSocket 房间端点 — 阶段 3.1，3.4 加服务端心跳踢除。

消息循环按 type 分派（客户端 → 服务端）：
  - join       首次注册身份（player_name），广播 member_changed + 进房系统消息
  - chat_send  聊天：落 message 表 + 广播 chat_new
  - ping       心跳，回 pong

服务端 → 客户端：chat_new / member_changed / pong / error（统一走 build_envelope 信封）。
断开时清理连接并广播离开消息与最新成员列表。

服务端心跳踢除（3.4）：prune_stale_loop 后台协程定期扫描 last_seen，把超时
未活跃的连接按正常离开语义摘除——根治 vite 代理抖动时 close 不转发遗留的
僵尸连接（重复收广播 / 成员列表虚胖）。

注意：
  - WS 事件循环里不走 FastAPI 的 Depends(get_session)（那是请求级依赖），
    每次落库/查询现场开 Session(engine)，用完即关
  - 房间不存在的处理与 HTTP 不同：不能 raise HTTPException，
    只能 accept 后发一条 error 信封再 close（自定义 code 4404）
  - sender 身份以 join 注册的 player_name 为准（服务端持有，防客户端伪造）
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session, select

from app.agent.keeper import auto_keeper
from app.agent.suggest import suggestion_engine
from app.db import engine
from app.models import Message, Room, RoomMember
from app.ws.manager import build_envelope, manager

router = APIRouter()

CLOSE_ROOM_NOT_FOUND = 4404  # 自定义关闭码：房间不存在

# ---------- 进出房消息去重（实测反馈：后台标签页被节流 → 心跳超时误杀 →
# 回前台自动重连，产生成对的「离开了/进入了房间」刷屏） ----------
# 策略：断开时 last_seen 落后超过 _STALE_DISCONNECT 视为「超时掉线」而非主动
# 退出 → 不落/不广播离开消息，只记录时间；同玩家在 _REJOIN_COOLDOWN 内重连
# → 静默恢复（不广播进入消息）。主动退出/首次进入的提示不受影响。
_STALE_DISCONNECT = 45.0    # 秒：断开时心跳落后超过该值 = 掉线
_REJOIN_COOLDOWN = 300.0    # 秒：静默重连窗口
_suppressed_leaves: dict[tuple[str, str], float] = {}  # (room_id, player_name) → 断开时刻


def _prune_suppressed(now: float) -> None:
    expired = [k for k, ts in _suppressed_leaves.items() if now - ts > _REJOIN_COOLDOWN]
    for k in expired:
        _suppressed_leaves.pop(k, None)


def _members_payload(session: Session, room_id: str) -> list[dict]:
    """持久花名册（字段与 REST join 返回值保持一致）。"""
    rows = session.exec(
        select(RoomMember).where(RoomMember.room_id == room_id)
    ).all()
    return [
        {'player_name': m.player_name, 'role': m.role, 'card_id': m.card_id}
        for m in rows
    ]


def _online_members(session: Session, room_id: str) -> list[dict]:
    """member_changed 用的"当前在线"成员列表。

    room_member 是持久花名册（离线不删），直接查库会让离开的人永远挂在
    列表里；因此以活跃连接为准，role/card_id 从花名册按名补齐。
    同名多连接（同开两个标签页）按名字去重。
    """
    roster = {m['player_name']: m for m in _members_payload(session, room_id)}
    online: dict[str, dict] = {}
    for ws in manager.active.get(room_id, []):
        name = manager.identities.get(id(ws))
        if name and name in roster:
            online[name] = roster[name]
    return list(online.values())


def _sys(text: str, room_id: str) -> dict:
    """系统提示消息信封（进房/离开等）。"""
    return build_envelope('chat_new', room_id, 'system', 'system', {'text': text})


def _persist_sys(session: Session, room_id: str, text: str) -> None:
    """进出房/踢除系统消息落库（3.4）：历史回放包含进出房，
    且前端「已同步 N 条」按 历史行数-现有消息数 计数的前提是
    消息流里每一行都有对应的库行（sys 行不再例外）。"""
    session.add(Message(
        room_id=room_id, channel='system', type='sys', sender='system', content=text,
    ))


async def prune_stale_loop(interval: float = 15.0, timeout: float = 75.0) -> None:
    """服务端心跳踢除（3.4）：每 interval 秒扫描，踢除 timeout 秒未活跃的连接。

    客户端 15s 一次 ping 会持续 touch；vite 代理抖动等导致 close 不转发时，
    僵尸连接再无消息进来，超时后按正常离开语义摘除并广播，防止重复收广播
    与成员列表虚胖。摘除前复查 last_seen：扫描期间刚复活（收到消息）的跳过。

    timeout 取 75s（5 个心跳周期）而非 45s：浏览器对后台标签页有定时器
    节流（-intensive throttling 下最低 1 次/分钟），60s 一次的 ping 必须
    放行，否则后台的活跃标签会被误杀反复重连。真正死链 75~90s 内必被清。
    """
    while True:
        await asyncio.sleep(interval)
        for room_id, ws in manager.stale_connections(timeout):
            now = time.monotonic()
            if now - manager.last_seen.get(id(ws), now) <= timeout:
                continue  # 扫描间隙收到消息，复活了
            name = manager.identities.get(id(ws))
            manager.disconnect(room_id, ws)
            if not name:
                continue  # 未 join 的裸连接静默摘除
            with Session(engine) as session:
                _persist_sys(session, room_id, f'{name} 心跳超时，已断开')
                session.commit()
                members = _online_members(session, room_id)
            await manager.broadcast(room_id, _sys(f'{name} 心跳超时，已断开', room_id))
            await manager.broadcast(room_id, build_envelope(
                'member_changed', room_id, 'system', 'system',
                {'members': members},
            ))


@router.websocket('/ws/{room_id}')
async def room_ws(websocket: WebSocket, room_id: str):
    # 1) 房间校验：不存在则礼貌报错后关闭
    with Session(engine) as session:
        if not session.get(Room, room_id):
            await websocket.accept()
            await websocket.send_json(build_envelope(
                'error', room_id, 'system', 'system', {'detail': '房间不存在'},
            ))
            await websocket.close(code=CLOSE_ROOM_NOT_FOUND)
            return

    player_name: str | None = None
    await websocket.accept()
    manager.connect(room_id, websocket)

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except ValueError:  # 非 JSON
                await websocket.send_json(build_envelope(
                    'error', room_id, 'system', 'system',
                    {'detail': '消息不是合法 JSON'},
                ))
                continue
            manager.touch(websocket)  # 3.4：任何消息（含 ping）都算活跃
            data = json.loads(raw)

            msg_type = data.get('type')
            payload = data.get('payload') or {}

            if msg_type == 'ping':
                await websocket.send_json(build_envelope(
                    'pong', room_id, 'system', 'system', {},
                ))
                continue

            if msg_type == 'join':
                name = str(payload.get('player_name') or '').strip()
                if not name:
                    await websocket.send_json(build_envelope(
                        'error', room_id, 'system', 'system',
                        {'detail': 'join 缺少 player_name'},
                    ))
                    continue
                if manager.identities.get(id(websocket)) == name:
                    continue  # 同连接重复 join（客户端竞态重放）：幂等忽略，不重复落库
                player_name = name
                manager.set_identity(websocket, name)
                now = time.monotonic()
                _prune_suppressed(now)
                rejoin_key = (room_id, name)
                silent_rejoin = now - _suppressed_leaves.get(rejoin_key, -1e18) < _REJOIN_COOLDOWN
                with Session(engine) as session:
                    members = _online_members(session, room_id)
                    if not silent_rejoin:
                        _persist_sys(session, room_id, f'{name} 进入了房间')
                    session.commit()
                await manager.broadcast(room_id, build_envelope(
                    'member_changed', room_id, 'system', 'system',
                    {'members': members},
                ))
                if silent_rejoin:
                    continue  # 掉线后的静默重连：不广播进入提示（成员列表已更新）
                # 进房提示排除本人：服务端先落库后广播，本人触发的历史回放与
                # 实时广播竞态会双份；本人从回放里看到这一行即可
                await manager.broadcast_except(room_id, _sys(f'{name} 进入了房间', room_id), websocket)
                continue

            if msg_type == 'chat_send':
                text = str(payload.get('text') or '').strip()
                channel = payload.get('channel') or 'ooc'
                if channel not in ('narrative', 'ooc'):
                    await websocket.send_json(build_envelope(
                        'error', room_id, 'system', 'system',
                        {'detail': f'非法频道: {channel}'},
                    ))
                    continue
                if not text:
                    continue  # 空消息直接忽略，不报错不打扰
                # TODO(3.2/3.3): narrative 频道现阶段全员可发（先跑通链路），
                # 掷骰进聊天流 / KP 控制台落地后按 role 收敛为 KP 主导 + 玩家行动描述
                sender = player_name or str(payload.get('sender') or '匿名')
                with Session(engine) as session:
                    # 发送者角色随消息下发（前端区分 KP 剧情 / 玩家行动 / 闲聊）；
                    # 先查 role 再落库，role 一并进 payload（3.4：历史行自包含）
                    row = session.exec(
                        select(RoomMember).where(
                            RoomMember.room_id == room_id,
                            RoomMember.player_name == sender,
                        )
                    ).first()
                    role = row.role if row else 'player'
                    room = session.get(Room, room_id)
                    agent_mode = room.agent_mode if room else 'manual'
                    session.add(Message(
                        room_id=room_id, channel=channel, sender=sender, content=text,
                        payload={'role': role},
                    ))
                    session.commit()
                await manager.broadcast(room_id, build_envelope(
                    'chat_new', room_id, sender, channel,
                    {'text': text, 'role': role},
                ))
                # 4.1 协同建议：任何剧情推进（KP 叙事或玩家行动）都触发后台生成，
                # 只发 KP。4.1+：自动触发走静默期 debounce（停止发言 2.5s 才生成）。
                # 4.2 全自动主持：玩家行动走静默期 debounce（一轮最多 5 次 LLM
                # 调用，连发不堆轮）；KP 插话是有意识的主持动作，取消未到期
                # 计时立即开轮。单飞合并防并发不变，聊天循环零阻塞。
                if channel == 'narrative' and agent_mode == 'collab':
                    suggestion_engine.schedule_auto_generate(room_id)
                elif channel == 'narrative' and agent_mode == 'auto':
                    if role == 'kp':
                        auto_keeper.run_immediately(room_id)
                    else:
                        auto_keeper.schedule_turn(room_id)
                continue

            # 未知类型：回 error 但不断连（客户端版本先行时前端可自愈）
            await websocket.send_json(build_envelope(
                'error', room_id, 'system', 'system',
                {'detail': f'未知消息类型: {msg_type}'},
            ))

    except WebSocketDisconnect:
        pass
    finally:
        # 掉线判定要在 disconnect 清理 last_seen 之前做
        stale_drop = (
            time.monotonic() - manager.last_seen.get(id(websocket), time.monotonic())
        ) > _STALE_DISCONNECT
        manager.disconnect(room_id, websocket)
        if player_name:
            now = time.monotonic()
            with Session(engine) as session:
                if stale_drop:
                    # 超时掉线（后台标签节流/网络抖动）：不落不广播离开消息，记录时间供静默重连判定
                    _suppressed_leaves[(room_id, player_name)] = now
                    _prune_suppressed(now)
                else:
                    # 主动退出：正常离开语义（离开广播放在 disconnect 之后，本人已不在接收列表）
                    _suppressed_leaves.pop((room_id, player_name), None)
                    _persist_sys(session, room_id, f'{player_name} 离开了房间')
                session.commit()
                members = _online_members(session, room_id)
            if not stale_drop:
                await manager.broadcast(room_id, _sys(f'{player_name} 离开了房间', room_id))
            await manager.broadcast(room_id, build_envelope(
                'member_changed', room_id, 'system', 'system',
                {'members': members},
            ))
