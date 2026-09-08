"""KP 控制台接口 — 阶段 3.3，3.4 加存档/读档。

职责边界（KP 专属操作，鉴权沿用 dissolve 的轻量模式：名字即身份，403 保护）：
  - POST /rooms/{id}/status       KP 改成员 HP/SAN：clamp → save_card 单一入口同步
                                  投影列 → message 落库（type=status，D9 溯源）→ 广播
  - PUT  /rooms/{id}/scene        KP 改场景标题栏：room 列 + sys 消息落库 → 广播
  - POST /rooms/{id}/save         KP 存档：花名册 + 各卡 card_data + 场景 → save_game 表
  - GET  /rooms/{id}/saves        存档列表
  - POST /rooms/{id}/load/{sid}   KP 读档：快照原子写回 → 广播 room_state + 系统消息

请求体一律携带 kp_name（与 room.kp_name 明文比对）；一切数值变更必带 reason。
"""
import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.agent.state_ops import apply_scene_change, apply_status_change
from app.api.rooms import build_room_state
from app.db import get_session
from app.models import (
    Card,
    Message,
    Room,
    RoomMember,
    SaveGame,
    save_card,
)
from app.ws.manager import build_envelope, manager

router = APIRouter()


class StatusRequest(BaseModel):
    """改状态请求体。hp/sanity 是"变更后的绝对值"，服务端 clamp 到 [0, derived]；
    至少给一个；reason 必填非空（D9：一切数值变更必须可溯源）。"""

    kp_name: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    hp: int | None = Field(default=None, ge=0)
    sanity: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=200)


class SceneRequest(BaseModel):
    """场景标题栏请求体。scene_desc 可空。"""

    kp_name: str = Field(min_length=1, max_length=50)
    scene_title: str = Field(min_length=1, max_length=100)
    scene_desc: str = Field(default='', max_length=500)


class SaveRequest(BaseModel):
    """存档请求体。name 是存档显示名（KP 起的，如"第一章·码头夜战"）。"""

    kp_name: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=50)


class StartGameRequest(BaseModel):
    """开团请求体（状态流转 waiting → playing 的唯一入口）。"""

    kp_name: str = Field(min_length=1, max_length=50)


class LoadRequest(BaseModel):
    """读档请求体。"""

    kp_name: str = Field(min_length=1, max_length=50)


@router.post('/rooms/{room_id}/status')
async def update_status(
    room_id: str,
    body: StatusRequest,
    session: Session = Depends(get_session),
):
    """KP 改成员 HP/SAN：clamp → save_card 单一入口 → 落 type=status 消息 → 广播。

    4.2 起主体逻辑抽到 app/agent/state_ops.py，与 LLM 工具层共用同一实现
    （AI 改状态与手动改状态行为完全同构）；此处只保留房间/KP 鉴权。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能修改成员状态')
    return await apply_status_change(
        session, room_id, body.target,
        hp=body.hp, sanity=body.sanity, reason=body.reason, operator=body.kp_name,
    )


@router.put('/rooms/{room_id}/scene')
async def update_scene(
    room_id: str,
    body: SceneRequest,
    session: Session = Depends(get_session),
):
    """KP 更新场景标题栏：写 room 列 + sys 消息落库（3.4 历史可回放）→ 广播 scene_changed。

    4.2 起主体逻辑抽到 app/agent/state_ops.py（与工具层共用），此处只保留鉴权。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能更新场景')
    return await apply_scene_change(
        session, room_id,
        scene_title=body.scene_title, scene_desc=body.scene_desc, operator=body.kp_name,
    )


# ==================== 开团：waiting → playing 状态流转 ====================

@router.put('/rooms/{room_id}/start')
async def start_game(
    room_id: str,
    body: StartGameRequest,
    session: Session = Depends(get_session),
):
    """KP 宣布开团：Room.status waiting → playing（此前全库无写入点，3.3 遗留）。

    开团后大厅不再展示本房间（list_waiting_rooms 只列 waiting），KP 退出时
    走"房间保留"分支而非解散。已开团时幂等返回，不重复落库广播。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能宣布开团')
    if room.status == 'playing':
        return {'status': 'playing', 'already_started': True}

    room.status = 'playing'
    content = f'{body.kp_name} 宣布开团，调查正式开始'
    session.add(Message(
        room_id=room_id, channel='system', type='sys',
        sender=body.kp_name, content=content,
        payload={'status': 'playing'},
    ))
    session.commit()

    await manager.broadcast(
        room_id,
        build_envelope('chat_new', room_id, body.kp_name, 'system', {'text': content}),
    )
    return {'status': 'playing', 'already_started': False}


# ==================== 阶段 3.4：存档 / 读档 ====================

@router.post('/rooms/{room_id}/save')
def save_game(room_id: str, body: SaveRequest, session: Session = Depends(get_session)):
    """KP 存档：snapshot = 成员花名册 + 各卡完整 card_data + 场景（§5.2）。

    聊天历史不在快照里——消息流是时间线，不随读档回滚。卡数据 deepcopy 后
    入快照，与后续在线改动隔离。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能存档')

    roster = session.exec(select(RoomMember).where(RoomMember.room_id == room_id)).all()
    members = [
        {'player_name': m.player_name, 'role': m.role, 'card_id': m.card_id}
        for m in roster
    ]
    cards: dict[str, dict] = {}
    for m in roster:
        if not m.card_id:
            continue
        card = session.get(Card, m.card_id)
        if card:
            cards[m.card_id] = copy.deepcopy(card.card_data)

    save = SaveGame(
        room_id=room_id,
        name=body.name,
        snapshot={
            'members': members,
            'cards': cards,
            'scene': {'scene_title': room.scene_title, 'scene_desc': room.scene_desc},
        },
    )
    session.add(save)
    session.commit()
    session.refresh(save)
    return {
        'save_id': save.id,
        'name': save.name,
        'created_at': save.created_at.isoformat(),
    }


@router.get('/rooms/{room_id}/saves')
def list_saves(room_id: str, session: Session = Depends(get_session)):
    """存档列表（仅名字与时间，不含快照体），读档弹窗数据源。"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    rows = session.exec(
        select(SaveGame).where(SaveGame.room_id == room_id).order_by(SaveGame.id.desc())
    ).all()
    return [
        {'id': s.id, 'name': s.name, 'created_at': s.created_at.isoformat()}
        for s in rows
    ]


@router.post('/rooms/{room_id}/load/{save_id}')
async def load_save(
    room_id: str,
    save_id: int,
    body: LoadRequest,
    session: Session = Depends(get_session),
):
    """KP 读档：快照原子写回（单事务）→ 广播 room_state + 系统消息。

    花名册按快照全删重插（真"回到存档时点"语义）；卡数据走 save_card 唯一
    写入口，卡被中途删过则按原 id 重建。当前在线但不在快照花名册里的成员
    会从列表消失（MVP 接受的快照语义）。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能读档')
    save = session.get(SaveGame, save_id)
    if not save or save.room_id != room_id:
        raise HTTPException(status_code=404, detail='存档不存在')

    snapshot = save.snapshot
    members = snapshot.get('members', [])
    cards = snapshot.get('cards', {})
    scene = snapshot.get('scene', {})

    # 1) 花名册全删重插（同事务内先删后插保证原子性）
    for m in session.exec(select(RoomMember).where(RoomMember.room_id == room_id)).all():
        session.delete(m)
    for m in members:
        session.add(RoomMember(
            room_id=room_id,
            player_name=str(m.get('player_name') or ''),
            role=str(m.get('role') or 'player'),
            card_id=m.get('card_id'),
        ))

    # 2) 卡数据写回：deepcopy 出新 dict 再传（save_card 以重赋引用识别变更）
    for card_id, card_data in cards.items():
        data = copy.deepcopy(card_data)
        card = session.get(Card, card_id)
        if not card:
            card = Card(id=card_id, owner='local', name=str(data.get('name', '调查员')))
            session.add(card)
        save_card(card, data)

    # 3) 场景写回
    room.scene_title = str(scene.get('scene_title', ''))
    room.scene_desc = str(scene.get('scene_desc', ''))

    # 4) 系统消息落库（D9 溯源：谁在何时读的档）
    content = f'读取了存档「{save.name}」，房间状态已回到存档时点'
    session.add(Message(
        room_id=room_id, channel='system', type='sys',
        sender=body.kp_name, content=content,
        payload={'save_name': save.name},
    ))
    session.commit()

    # 提交后广播：room_state 驱动全员界面整体刷新（D5：前端不自改，等广播）
    state_payload = build_room_state(session, room)
    await manager.broadcast(
        room_id,
        build_envelope('room_state', room_id, body.kp_name, 'system', state_payload),
    )
    await manager.broadcast(
        room_id,
        build_envelope('chat_new', room_id, body.kp_name, 'system', {'text': content}),
    )
    return state_payload
