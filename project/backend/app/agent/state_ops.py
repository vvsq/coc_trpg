"""状态变更共享操作（4.2 抽取）— KP REST 端点与 LLM 工具层共用的单一实现。

抽自 app/api/kp.py 的 update_status / update_scene 主体：clamp → save_card
单一写入口 → type=status / sys 消息落库（D9 溯源）→ 广播。REST 与工具走
同一函数，保证「AI 改状态」与「KP 手动改状态」的落库/广播行为完全同构，
前端零改动即可复用血条驱动与历史回放。

权限语义差异：kp_name 明文比对（403）留在 REST 端点；工具层以系统身份
（operator='AI主持'）调用本模块——AI 的写权全部来自工具（D3），每个调用
必带 reason（D9），由 AutoKeeper 在进入 auto 模式后才可能触发。
"""
import copy

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Card, Message, RoomMember, save_card
from app.ws.manager import build_envelope, manager


async def apply_status_change(
    session: Session,
    room_id: str,
    target: str,
    *,
    hp: int | None = None,
    sanity: int | None = None,
    reason: str,
    operator: str,
) -> dict:
    """改成员 HP/SAN（绝对值 + clamp）：写卡、落 type=status 消息、广播 status_changed。

    返回与 3.3 端点一致的 payload；成员/卡不存在等业务错误抛 HTTPException
    （REST 直接映射响应，工具层捕获后转成让 LLM 澄清的错误文本）。
    """
    if hp is None and sanity is None:
        raise HTTPException(status_code=400, detail='hp 与 sanity 至少提供一个')

    member = session.exec(
        select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.player_name == target,
        )
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail='目标成员不在房间内')
    if not member.card_id:
        raise HTTPException(status_code=400, detail='该成员未绑定角色卡，无法修改状态')
    card = session.get(Card, member.card_id)
    if not card:
        raise HTTPException(status_code=404, detail='角色卡不存在')

    card_data = copy.deepcopy(card.card_data)
    state = card_data.setdefault('state', {})
    derived = card_data.get('derived', {})
    hp_max = int(derived.get('HP', 0))
    sanity_max = int(derived.get('SAN', 0))

    old_hp = int(state.get('current_hp', 0))
    old_sanity = int(state.get('current_sanity', 0))
    new_hp = max(0, min(hp, hp_max)) if hp is not None else old_hp
    new_sanity = max(0, min(sanity, sanity_max)) if sanity is not None else old_sanity

    state['current_hp'] = new_hp
    state['current_sanity'] = new_sanity
    save_card(card, card_data)

    payload = {
        'target': target,
        'hp': new_hp,
        'sanity': new_sanity,
        'hp_max': hp_max,
        'sanity_max': sanity_max,
        'reason': reason,
        'operator': operator,
    }

    # 可读文本随消息落库（D9 溯源：谁改的、改了多少、为什么）。delta 按 clamp
    # 后的实际变化计算，与信封里的绝对值同源。
    parts = []
    if hp is not None:
        parts.append(f'HP {new_hp - old_hp:+d}（残余 {new_hp}/{hp_max}）')
    if sanity is not None:
        parts.append(f'SAN {new_sanity - old_sanity:+d}（残余 {new_sanity}/{sanity_max}）')
    content = f'{operator} 将 {target} {"、".join(parts)}：{reason}'

    session.add(Message(
        room_id=room_id, channel='narrative', type='status',
        sender=operator, content=content,
        payload=payload,  # 3.4：结构化状态数据，历史回放重建状态行用
    ))
    session.commit()

    await manager.broadcast(
        room_id,
        build_envelope('status_changed', room_id, operator, 'narrative', payload),
    )
    return payload


async def apply_scene_change(
    session: Session,
    room_id: str,
    *,
    scene_title: str,
    scene_desc: str,
    operator: str,
) -> dict:
    """更新场景标题栏：写 room 列 + sys 消息落库（历史可回放）→ 广播 scene_changed。"""
    from app.models import Room

    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')

    room.scene_title = scene_title
    room.scene_desc = scene_desc
    content = f'更新了场景：「{scene_title}」'
    if scene_desc:
        content += f'（{scene_desc}）'
    session.add(Message(
        room_id=room_id, channel='system', type='sys',
        sender=operator, content=content,
        payload={'scene_title': scene_title, 'scene_desc': scene_desc},
    ))
    session.commit()

    payload = {
        'scene_title': scene_title,
        'scene_desc': scene_desc,
        'operator': operator,
    }
    await manager.broadcast(
        room_id,
        build_envelope('scene_changed', room_id, operator, 'system', payload),
    )
    return payload
