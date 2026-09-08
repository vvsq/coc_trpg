"""掷骰接口 — 属性生成 + 技能检定（阶段 3.2）。

规则与随机全部在后端（rules/coc7），前端只上报意图、只消费结果：
  - POST /dice/attributes  建卡用：投点法属性生成
  - POST /dice/check       房间内技能检定：coc7.check() 判定 → 落 message 表
                           （type=dice）→ roll_result 广播进剧情流 → 返回结果对象

MVP 约定（goal.md §7 3.2）：技能值 value 由请求体携带（前端从自己的角色卡算出），
不从 card 表反查——服务端权威体现在"骰子与判定必须经过本接口"，绑卡取值收紧留待 3.3。

暗骰（secret=true）：D8 收紧（3.3 落地）——结果只定向发给 KP 连接
（manager.broadcast_to_roles 按 room_member 花名册对出 role），玩家连接在协议层
收不到信封；前端 store 的 secret && 非 KP 过滤保留作兜底。注意 type=dice 的
暗骰行仍落 message 表，3.4 历史补齐时必须对 secret 行做可见性过滤。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models import Message, Room
from app.rules.coc7 import check, roll_attributes, target_for
from app.ws.manager import build_envelope, manager

router = APIRouter()

Difficulty = Literal['standard', 'hard', 'extreme']

# 广播与返回共用的 payload 组装抽成函数，避免 REST 响应与 WS 两处手拼字段漂移
LEVEL_LABELS = {
    'critical': '大成功',
    'extreme': '极难成功',
    'hard': '困难成功',
    'regular': '常规成功',
    'fail': '失败',
    'fumble': '大失败',
}

DIFFICULTY_LABELS = {'standard': '常规', 'hard': '困难', 'extreme': '极难'}


class CheckRequest(BaseModel):
    """技能检定请求体。value = 技能当前值（基础值+成长值），由前端计算携带。"""

    room_id: str
    sender: str = Field(min_length=1, max_length=50)
    skill_name: str = Field(min_length=1, max_length=50)
    detail: str = Field(default='', max_length=50)  # 分类技能细分，如"斗殴"
    difficulty: Difficulty = 'standard'
    bonus: int = Field(default=0, ge=0, le=2)  # 奖励骰数量
    penalty: int = Field(default=0, ge=0, le=2)  # 惩罚骰数量
    value: int = Field(ge=1, le=99)  # 技能当前值，后端 clamp 到合法区间
    secret: bool = False  # 暗骰：只进 KP 视图


def _result_payload(
    sender: str,
    req: CheckRequest,
    level: str,
    target: int,
    roll: dict,
) -> dict:
    """REST 返回值与 roll_result 广播 payload 共用同一结构。"""
    return {
        'sender': sender,
        'skill_name': req.skill_name,
        'detail': req.detail,
        'value': req.value,
        'difficulty': req.difficulty,
        'level': level,
        'level_label': LEVEL_LABELS[level],
        'target': target,
        'roll': roll,
        'secret': req.secret,
    }


@router.post('/dice/attributes')
def roll_all_attributes():
    """投点法属性生成：STR/CON/DEX/APP/POW/LUK=3D6×5，SIZ/INT/EDU=(2D6+6)×5。"""
    return roll_attributes()


@router.post('/dice/check')
async def dice_check(req: CheckRequest, session: Session = Depends(get_session)):
    """技能检定：规则引擎判定 → 落库（type=dice）→ roll_result 广播 → 返回结果。

    房间校验失败返回 404；广播是 fire-and-forget 语义（连接异常由 manager 摘除）。
    """
    room = session.get(Room, req.room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')

    level, d100 = check(req.value, req.difficulty, req.bonus, req.penalty)
    target = target_for(req.value, req.difficulty)
    roll = {
        'units': d100.units,
        'tens': d100.tens,
        'value': d100.value,
        'bonus': d100.bonus,
        'penalty': d100.penalty,
    }
    payload = _result_payload(req.sender, req, level, target, roll)

    # 可读文本随骰子消息落库（3.4 历史补齐直接可用；骰值细节由前端按 payload 渲染）
    skill_label = f'{req.skill_name}（{req.detail}）' if req.detail else req.skill_name
    content = (
        f'{req.sender} 进行 {skill_label} {req.value} '
        f'{DIFFICULTY_LABELS[req.difficulty]}检定：掷出 {d100.value}'
        f'（目标 {target}）→ {LEVEL_LABELS[level]}'
    )
    session.add(Message(
        room_id=req.room_id, channel='narrative', type='dice',
        sender=req.sender, content=content,
        secret=req.secret, payload=payload,  # 3.4：暗骰过滤标记 + 结构化骰值（历史回放重建徽章）
    ))
    session.commit()

    envelope = build_envelope('roll_result', req.room_id, req.sender, 'narrative', payload)
    if req.secret:
        # D8 收紧（3.3）：暗骰只发 KP 连接，玩家协议层收不到（前端过滤仅兜底）
        await manager.broadcast_to_roles(req.room_id, envelope, {'kp'})
    else:
        await manager.broadcast(req.room_id, envelope)
    return payload


class CheckRollBody(BaseModel):
    """检定下放的投掷请求体：只有被点名的调查员本人能投。"""

    player_name: str = Field(min_length=1, max_length=50)


@router.post('/rooms/{room_id}/check-requests/{request_id}/roll')
async def roll_check_request(
    room_id: str, request_id: str, body: CheckRollBody,
    session: Session = Depends(get_session),
):
    """检定下放结算（4.3 实测反馈，正统玩法）：AI 定技能/难度/后果，玩家本人投掷。

    公平性（D5）：技能值在 AI 发起请求时已由服务端按角色卡查好存进请求 payload，
    玩家只点「投掷」——没有自掷刷优势的空间。每条请求只能结算一次。
    结算后落 type=dice 行 + roll_result 广播（payload 带 request_id 供前端销按钮）；
    auto 模式下唤醒 AI 主持读结果继续叙事。
    """
    # 内联导入防环：keeper → tools → api.dice（标签常量）
    from app.agent.keeper import auto_keeper
    from app.tasks import spawn_background

    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    rows = session.exec(
        select(Message)
        .where(Message.room_id == room_id, Message.type == 'check_request')
        .order_by(Message.id.desc())
    ).all()
    msg = next((m for m in rows if (m.payload or {}).get('request_id') == request_id), None)
    if msg is None:
        raise HTTPException(status_code=404, detail='检定请求不存在')
    payload = msg.payload or {}
    if payload.get('fulfilled'):
        raise HTTPException(status_code=409, detail='该检定请求已完成投掷')
    if payload.get('target') != body.player_name:
        raise HTTPException(status_code=403, detail='只有被点名的调查员能投这颗骰子')

    value = int(payload.get('value') or 0)
    difficulty = payload.get('difficulty') or 'standard'
    level, d100 = check(value, difficulty)
    target_num = target_for(value, difficulty)
    roll = {
        'units': d100.units, 'tens': d100.tens, 'value': d100.value,
        'bonus': d100.bonus, 'penalty': d100.penalty,
    }
    roll_payload = {
        'sender': body.player_name,
        'skill_name': payload.get('skill_name', ''),
        'detail': '',
        'value': value,
        'difficulty': difficulty,
        'level': level,
        'level_label': LEVEL_LABELS[level],
        'target': target_num,
        'roll': roll,
        'secret': False,
        'request_id': request_id,
    }
    content = (
        f'{body.player_name} 进行 {payload.get("skill_name", "")} {value} '
        f'{DIFFICULTY_LABELS[difficulty]}检定：掷出 {d100.value}'
        f'（目标 {target_num}）→ {LEVEL_LABELS[level]}'
    )
    session.add(Message(
        room_id=room_id, channel='narrative', type='dice',
        sender=body.player_name, content=content, secret=False, payload=roll_payload,
    ))
    msg.payload = {**payload, 'fulfilled': True}  # JSON 列整体重赋触发变更检测
    session.add(msg)
    session.commit()

    await manager.broadcast(room_id, build_envelope(
        'roll_result', room_id, body.player_name, 'narrative', roll_payload,
    ))
    if room.agent_mode == 'auto':
        spawn_background(
            auto_keeper.run_turn(room_id, trigger='auto'),
            name=f'check-roll-keeper-{room_id}',
        )
    return roll_payload
