"""房间与成员接口 — 阶段 3.1，3.4 加历史/快照两个全员可读端点。

职责边界（照 cards.py 的模式）：
  - POST   /rooms            KP 建房：同一事务写 Room + KP 的 RoomMember
  - POST   /rooms/{id}/join  加入：校验房间/角色卡存在；同名重进幂等（不重复建行）
  - GET    /rooms            大厅列表（只列 waiting 状态的房间）
  - GET    /rooms/{id}       房间详情（退出时前端判断是否提示解散用）
  - DELETE /rooms/{id}       KP 解散房间（校验 kp_name，清成员与消息）
  - GET    /rooms/{id}/history  消息历史分页（3.4：暗骰行 D8 可见性过滤）
  - GET    /rooms/{id}/state    room_state 全量快照（3.4：重连补齐 / load 广播共用）

成员列表的组装逻辑抽成 _list_members()，join 的返回值与后续 WS 的
member_changed 广播共用同一份结构，避免两处手拼字段漂移。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.agent.kp_styles import style_echo
from app.db import get_session
from app.models import Card, Message, Room, RoomMember
from app.ws.manager import build_envelope, manager

router = APIRouter()


class RoomCreate(BaseModel):
    """建房请求体。KP 名即建房者昵称（无账号系统，名字就是身份）。"""

    name: str = Field(min_length=1, max_length=50)
    kp_name: str = Field(min_length=1, max_length=50)


class JoinRequest(BaseModel):
    """加入请求体。card_id 可空：允许先进房再看卡/建卡（3.3 侧栏再引导绑定）。"""

    player_name: str = Field(min_length=1, max_length=50)
    card_id: str | None = None


def _member_payload(m: RoomMember) -> dict:
    return {'player_name': m.player_name, 'role': m.role, 'card_id': m.card_id}


def _list_members(session: Session, room_id: str) -> list[dict]:
    """房间全量成员（REST 返回值与 WS member_changed 广播共用此结构）。"""
    rows = session.exec(
        select(RoomMember).where(RoomMember.room_id == room_id)
    ).all()
    return [_member_payload(m) for m in rows]


@router.post('/rooms', status_code=201)
def create_room(payload: RoomCreate, session: Session = Depends(get_session)):
    """KP 建房：Room 与 KP 成员记录同事务写入，保证有房必有 KP。"""
    room = Room(name=payload.name, kp_name=payload.kp_name)
    session.add(room)
    session.flush()  # 先拿生成的短码 id 再写成员
    session.add(RoomMember(room_id=room.id, player_name=payload.kp_name, role='kp'))
    session.commit()
    return {'room_id': room.id, 'name': room.name}


@router.post('/rooms/{room_id}/join')
def join_room(room_id: str, payload: JoinRequest, session: Session = Depends(get_session)):
    """加入房间：校验房间存在 / 角色卡存在；同名重进幂等，返回成员列表。

    重进语义（无账号系统，名字即身份）：
      - 报名 == kp_name：KP 重进，不新建成员行，身份保持 KP
      - 报名与现有玩家重名：视为同一人重连（刷新/误退重进），幂等返回花名册
    代价是"撞名顶号"（局域网熟人局可接受）；鉴权接入后此处收紧。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if payload.card_id and not session.get(Card, payload.card_id):
        raise HTTPException(status_code=404, detail='角色卡不存在')
    if payload.player_name == room.kp_name:
        # KP 重进幂等；但显式 leave（关网页 beacon）会删花名册行——行不在则补建，
        # 否则 KP 刷新后成员列表缺自己（4.4+ 修复）
        kp_row = session.exec(
            select(RoomMember).where(
                RoomMember.room_id == room_id,
                RoomMember.player_name == payload.player_name,
            )
        ).first()
        if not kp_row:
            session.add(RoomMember(
                room_id=room_id, player_name=payload.player_name, role='kp',
            ))
            session.commit()
        return _list_members(session, room_id)
    dup = session.exec(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.player_name == payload.player_name,
        )
    ).first()
    if dup:
        return _list_members(session, room_id)

    session.add(RoomMember(
        room_id=room_id,
        player_name=payload.player_name,
        role='player',
        card_id=payload.card_id,
    ))
    session.commit()
    return _list_members(session, room_id)


class LeaveRequest(BaseModel):
    """离开房间请求体（4.4+：关网页时 sendBeacon 发出）。"""

    player_name: str = Field(min_length=1, max_length=50)


@router.post('/rooms/{room_id}/leave')
async def leave_room(
    room_id: str, payload: LeaveRequest, session: Session = Depends(get_session),
):
    """显式离开房间（关网页 beacon / 退出按钮兜底）：删花名册行 + 系统消息 + 广播。

    4.4+ 语义：WS 断开一律按掉线处理，不再广播离开；只有显式 leave 才算退出。
    sendBeacon 在页面卸载时发不出 WS 帧，故走 REST。幂等：人不在花名册时静默返回。
    """
    room = session.get(Room, room_id)
    if not room:
        return {'ok': True}  # 房间已没了（解散后卸载），beacon 场景静默成功
    row = session.exec(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.player_name == payload.player_name,
        )
    ).first()
    if row is None:
        return {'ok': True}
    session.delete(row)
    session.add(Message(
        room_id=room_id, channel='system', type='sys',
        sender='system', content=f'{payload.player_name} 离开了房间',
    ))
    session.commit()
    members = _list_members(session, room_id)
    await manager.broadcast(room_id, build_envelope(
        'chat_new', room_id, 'system', 'system',
        {'text': f'{payload.player_name} 离开了房间'},
    ))
    await manager.broadcast(room_id, build_envelope(
        'member_changed', room_id, 'system', 'system', {'members': members},
    ))
    return {'ok': True}


@router.get('/rooms/{room_id}')
def get_room(room_id: str, session: Session = Depends(get_session)):
    """房间详情（轻量：不带成员，成员走 join/WS）。"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    return {
        'room_id': room.id,
        'name': room.name,
        'kp_name': room.kp_name,
        'status': room.status,
        # 场景标题栏（3.3）：玩家进房即拿到当前场景
        'scene': {'scene_title': room.scene_title, 'scene_desc': room.scene_desc},
        # Agent 模式（4.1）：manual 纯人工 / collab 协同建议（KP 控制台面板回显用）
        'agent_mode': room.agent_mode,
        # KP 风格（4.4）：id + 名称（面板回显用）
        'style': style_echo(session, room),
    }


@router.get('/rooms')
def list_waiting_rooms(session: Session = Depends(get_session)):
    """大厅：只列等待中的房间（playing 的房间不重开，入口在 3.3 KP 控制台）。"""
    rows = session.exec(select(Room).where(Room.status == 'waiting')).all()
    return [
        {
            'room_id': r.id,
            'name': r.name,
            'kp_name': r.kp_name,
            'created_at': r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.delete('/rooms/{room_id}', status_code=204)
async def dissolve_room(room_id: str, kp_name: str, session: Session = Depends(get_session)):
    """KP 解散房间：kp_name 对不上即 403（MVP 的轻量鉴权，名字即身份）。

    删除数据前先广播 room_dissolved 并关闭全房连接：在线成员收到信封即
    自行退出回大厅，遗留连接由 close_room 兜底关闭（4404=房间不存在），
    不再出现"人还在已解散的房间里发消息"的幽灵状态。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能解散房间')
    await manager.broadcast(
        room_id,
        build_envelope('room_dissolved', room_id, kp_name, 'system', {'operator': kp_name}),
    )
    await manager.close_room(room_id)
    for m in session.exec(select(RoomMember).where(RoomMember.room_id == room_id)).all():
        session.delete(m)
    for msg in session.exec(select(Message).where(Message.room_id == room_id)).all():
        session.delete(msg)
    session.delete(room)
    session.commit()


# ==================== 阶段 3.4：历史检索 + room_state 全量快照 ====================

def build_room_state(session: Session, room: Room) -> dict:
    """room_state 全量快照组装器：REST /state 与 load 的 WS 广播共用同一结构。

    members 用持久花名册全量语义（4.4+ 与 member_changed 广播一致：掉线成员
    仍在列表里，只有显式 leave 才删行；读档时花名册由快照重建，无幽灵行）；
    hp_sanity 按持久花名册全量组装——离线成员的 HP/SAN 也给全，重连补齐不缺行。
    HP/SAN 以上限 card_data 为准（投影列只作索引），上限取 derived 的 HP/SAN。
    """
    roster = session.exec(select(RoomMember).where(RoomMember.room_id == room.id)).all()

    members = [
        {'player_name': m.player_name, 'role': m.role, 'card_id': m.card_id}
        for m in roster
    ]

    hp_sanity: dict[str, dict] = {}
    for m in roster:
        if not m.card_id:
            continue
        card = session.get(Card, m.card_id)
        if not card:
            continue
        state = card.card_data.get('state', {})
        derived = card.card_data.get('derived', {})
        hp_sanity[m.player_name] = {
            'hp': int(state.get('current_hp', 0)),
            'sanity': int(state.get('current_sanity', 0)),
            'hp_max': int(derived.get('HP', 0)),
            'sanity_max': int(derived.get('SAN', 0)),
        }

    return {
        'members': members,
        'scene': {'scene_title': room.scene_title, 'scene_desc': room.scene_desc},
        'hp_sanity': hp_sanity,
        'style': style_echo(session, room),
    }


def _history_payload(rows: list[Message], roster_roles: dict[str, str]) -> list[dict]:
    """历史行序列化：payload/secret 原样透出（前端按 type 还原 ChatItem），
    role 由花名册现查（system 落库署名固定 'system'）。"""
    items = []
    for r in rows:
        items.append({
            'id': r.id,
            'channel': r.channel,
            'type': r.type,
            'sender': r.sender,
            'content': r.content,
            'secret': r.secret,
            'payload': r.payload,
            'role': 'system' if r.sender == 'system' else roster_roles.get(r.sender, 'player'),
            'created_at': r.created_at.isoformat(),
        })
    return items


@router.get('/rooms/{room_id}/history')
def get_room_history(
    room_id: str,
    viewer: str,
    before_id: int | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    """消息历史分页（3.4）：按 id 倒序翻页，前端一次性拉全量后正序回放。

    D8 延伸（4.2 收紧为全类型）：secret 行（暗骰、AI 主持的 keeper 笔记）
    只对 viewer==kp_name 返回；其余行全员可见。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')

    stmt = select(Message).where(Message.room_id == room_id)
    if before_id is not None:
        stmt = stmt.where(Message.id < before_id)
    if viewer != room.kp_name:
        stmt = stmt.where(Message.secret.is_(False))
    stmt = stmt.order_by(Message.id.desc()).limit(max(1, min(limit, 500)))

    rows = session.exec(stmt).all()
    roster_roles = {
        m.player_name: m.role
        for m in session.exec(select(RoomMember).where(RoomMember.room_id == room_id)).all()
    }
    return {'messages': _history_payload(list(rows), roster_roles)}


@router.get('/rooms/{room_id}/state')
def get_room_state(room_id: str, session: Session = Depends(get_session)):
    """room_state 全量快照（3.4）：重连成功后前端主动拉一次补齐状态。"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    return build_room_state(session, room)
