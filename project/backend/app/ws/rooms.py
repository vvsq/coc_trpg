"""WebSocket 房间端点 — 阶段 3.1，3.4 加服务端心跳踢除。

消息循环按 type 分派（客户端 → 服务端）：
  - join       首次注册身份（player_name），广播 member_changed + 进房系统消息
  - chat_send  聊天：落 message 表 + 广播 chat_new
  - ping       心跳，回 pong

服务端 → 客户端：chat_new / member_changed / pong / error（统一走 build_envelope 信封）。
4.4+：WS 断开一律按「掉线」处理（不广播离开、不改成员列表）；只有显式
leave 消息（退出按钮）/ REST leave（关网页 beacon）才广播离开并删花名册行。

服务端死链清理（3.4 引入，4.4+ 改静默）：prune_stale_loop 后台协程定期扫描
last_seen，静默摘除超时僵尸连接（vite 代理抖动时 close 不转发的遗留连接）。

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
# 策略（4.4+ 修订）：**WS 断开一律视为掉线，不再推导"主动退出"**——只有
# 显式 leave 消息（点退出按钮）/ REST leave（关网页 beacon）才广播离开。
# 切标签页、后台节流、网络抖动都不会再把人判为退出；成员列表改用持久
# 花名册全量展示（掉线的人仍在列表里，不视为离房）。
# 同玩家在 _REJOIN_COOLDOWN 内重连 → 静默恢复（不广播进入消息）。
_REJOIN_COOLDOWN = 300.0    # 秒：静默重连窗口
_suppressed_leaves: dict[tuple[str, str], float] = {}  # (room_id, player_name) → 断开时刻


def _prune_suppressed(now: float) -> None:
    expired = [k for k, ts in _suppressed_leaves.items() if now - ts > _REJOIN_COOLDOWN]
    for k in expired:
        _suppressed_leaves.pop(k, None)


def _members_payload(session: Session, room_id: str) -> list[dict]:
    """member_changed 用的成员列表 = 持久花名册（字段与 REST join 返回值一致）。

    4.4+ 起不再按"活跃连接"过滤：掉线/切标签页的成员仍在列表里显示
    （不视为退出），只有显式 leave（退出按钮 / 关网页）才删花名册行。
    """
    rows = session.exec(
        select(RoomMember).where(RoomMember.room_id == room_id)
    ).all()
    return [
        {'player_name': m.player_name, 'role': m.role, 'card_id': m.card_id}
        for m in rows
    ]


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


async def prune_stale_loop(interval: float = 15.0, timeout: float = 180.0) -> None:
    """服务端死链清理（3.4 引入，4.4+ 改为静默）：每 interval 秒扫描，摘除
    timeout 秒未活跃的连接。

    4.4+ 语义变更：超时连接一律按「掉线」静默摘除——不落库、不广播任何
    系统消息、不改成员列表（掉线成员保留在花名册里），同时补 ws.close()
    消灭"假在线"幽灵连接。此前按"心跳超时，已断开"广播离开语义，正是
    切标签页被判退出的根因之一；真正的离开只由显式 leave 消息表达。
    timeout 取 180s：后台标签 intensive throttling 下 ping 最低 1 次/分钟，
    必须宽放行；真死链（关进程/断网）3 分钟内清理，且已不再打扰任何人。
    """
    while True:
        await asyncio.sleep(interval)
        for room_id, ws in manager.stale_connections(timeout):
            now = time.monotonic()
            if now - manager.last_seen.get(id(ws), now) <= timeout:
                continue  # 扫描间隙收到消息，复活了
            manager.disconnect(room_id, ws)
            try:
                await ws.close()  # 补刀：断掉客户端侧的假在线连接（room_ws 的
                # receive 循环会收到断开，finally 的掉线分支与之幂等）
            except Exception:  # noqa: BLE001 已死连接，清理目的已达成
                pass


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
                    members = _members_payload(session, room_id)
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

            if msg_type == 'leave':
                # 显式退出（4.4+）：点「退出房间」按钮时客户端先发 leave 再断开。
                # 这是唯一在 WS 通道上广播"离开了房间"的路径；之后 finally 的
                # 掉线分支不再产生任何离开语义。
                if player_name:
                    with Session(engine) as session:
                        # 同名多标签页：还有别的连接挂着同名就不删花名册行
                        others = any(
                            manager.identities.get(id(w)) == player_name
                            for w in manager.active.get(room_id, [])
                            if w is not websocket
                        )
                        if not others:
                            row = session.exec(
                                select(RoomMember).where(
                                    RoomMember.room_id == room_id,
                                    RoomMember.player_name == player_name,
                                )
                            ).first()
                            if row:
                                session.delete(row)
                        _persist_sys(session, room_id, f'{player_name} 离开了房间')
                        session.commit()
                        members = _members_payload(session, room_id)
                    await manager.broadcast(room_id, _sys(f'{player_name} 离开了房间', room_id))
                    await manager.broadcast(room_id, build_envelope(
                        'member_changed', room_id, 'system', 'system',
                        {'members': members},
                    ))
                continue

            # 未知类型：回 error 但不断连（客户端版本先行时前端可自愈）
            await websocket.send_json(build_envelope(
                'error', room_id, 'system', 'system',
                {'detail': f'未知消息类型: {msg_type}'},
            ))

    except WebSocketDisconnect:
        pass
    finally:
        # 4.4+：WS 断开一律按「掉线」处理——不落库、不广播离开、不改成员列表
        # （切标签页/后台节流/网络抖动都不是退出）。只记录断开时刻供静默重连
        # 判定；真正的离开只由显式 leave 消息 / REST leave（关网页 beacon）表达。
        manager.disconnect(room_id, websocket)
        if player_name:
            now = time.monotonic()
            _suppressed_leaves[(room_id, player_name)] = now
            _prune_suppressed(now)
