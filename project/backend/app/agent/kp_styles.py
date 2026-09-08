"""KP 风格系统（4.4，goal §6.2）——风格只影响表达，不影响公平。

内置三种风格（剧情沉浸 / 规则教学 / 平衡 Keeper）以代码常量登记，实现为
JSON 四旋钮配置而非写死在提示词里；自定义风格存 kp_style 表（支持保存/
删除/导出导入 JSON）。渲染成 L2 叙事指令注入提示词（goal §6.1）：

  - 协同建议：拼进 system（L1 之后）
  - 全自动主持：放进 BP2 剧情记忆段（风格切换只作废 BP2 缓存，不动 BP1）

四旋钮（§6.2 表格的列）：
  narrative_density          叙事密度：high 多感官描写 / low 精炼直给
  rule_explanation           规则解释：high 每次检定附规则说明 / low 只报结果
  hidden_roll_transparency   暗骰透明度：high 承认存在隐藏判定 / low 完全保密
  option_granularity         选项颗粒度：fine 手把手细项 / coarse 开放式方向

铁律不变：骰子永远由规则引擎产生，风格参数无权重改骰。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlmodel import Session, select

from app.models import KpStyle, Room

# 四旋钮的合法取值与缺省（平衡 Keeper = 全中档，§6.2 默认行）
VALID_KNOBS: dict[str, set[str]] = {
    'narrative_density': {'high', 'medium', 'low'},
    'rule_explanation': {'high', 'medium', 'low'},
    'hidden_roll_transparency': {'high', 'medium', 'low'},
    'option_granularity': {'high', 'fine', 'coarse', 'medium', 'low'},
}

_BUILTIN_BALANCED = {
    'narrative_density': 'medium',
    'rule_explanation': 'medium',
    'hidden_roll_transparency': 'medium',
    'option_granularity': 'medium',
}

BUILTIN_STYLES: list[dict] = [
    {
        'id': 'balanced',
        'name': '平衡 Keeper',
        'description': '默认风格：叙事与规则讲解并重，藏与露有度（§6.2 推荐档）。',
        'params': dict(_BUILTIN_BALANCED),
    },
    {
        'id': 'immersive',
        'name': '剧情沉浸',
        'description': '高叙事密度、多感官描写；少讲规则只报结果；暗骰完全保密；行动切口开放式。',
        'params': {
            'narrative_density': 'high',
            'rule_explanation': 'low',
            'hidden_roll_transparency': 'low',
            'option_granularity': 'coarse',
        },
    },
    {
        'id': 'teaching',
        'name': '规则教学',
        'description': '面向新手：每次检定附规则说明与难度依据，坦承存在隐藏判定，选项手把手。',
        'params': {
            'narrative_density': 'medium',
            'rule_explanation': 'high',
            'hidden_roll_transparency': 'high',
            'option_granularity': 'fine',
        },
    },
]

BUILTIN_IDS = {s['id'] for s in BUILTIN_STYLES}

_KNOB_LABELS = {
    'narrative_density': '叙事密度',
    'rule_explanation': '规则解释',
    'hidden_roll_transparency': '暗骰透明度',
    'option_granularity': '选项颗粒度',
}


def validate_params(params: dict) -> dict:
    """规整四旋钮参数：非法值回退 medium、缺失补缺省；返回新 dict。"""
    params = params if isinstance(params, dict) else {}
    out: dict[str, str] = {}
    for knob, allowed in VALID_KNOBS.items():
        value = str(params.get(knob) or '').strip().lower()
        out[knob] = value if value in allowed else 'medium'
    note = str(params.get('note') or '').strip()[:200]
    if note:
        out['note'] = note
    return out


def get_style(session: Session, style_id: str) -> dict | None:
    """解析 style_id → 风格对象 {id, name, params}；内置优先，其次查自定义表。"""
    style_id = (style_id or '').strip()
    if not style_id:
        return None
    if style_id in BUILTIN_IDS:
        for s in BUILTIN_STYLES:
            if s['id'] == style_id:
                return {'id': s['id'], 'name': s['name'], 'params': dict(s['params'])}
        return None
    row = session.get(KpStyle, style_id)
    if row is None:
        return None
    return {'id': row.id, 'name': row.name, 'params': validate_params(row.params)}


def list_styles(session: Session) -> dict:
    """GET /kp-styles 响应：内置 + 自定义两列。"""
    customs = [
        {
            'id': row.id,
            'name': row.name,
            'params': validate_params(row.params),
            'created_at': row.created_at.isoformat(timespec='seconds'),
        }
        for row in session.exec(
            select(KpStyle).order_by(KpStyle.created_at)
        ).all()
    ]
    builtins = [
        {'id': s['id'], 'name': s['name'], 'description': s['description'],
         'params': dict(s['params'])}
        for s in BUILTIN_STYLES
    ]
    return {'builtins': builtins, 'customs': customs}


def create_custom_style(session: Session, name: str, params: dict) -> KpStyle:
    """保存自定义风格（导出 JSON 再导入即走这里）。名字唯一性不强制——id 才是键。"""
    row = KpStyle(
        id=f"custom-{uuid.uuid4().hex[:8]}",
        name=name.strip()[:30] or '自定义风格',
        params=validate_params(params),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_custom_style(session: Session, style_id: str) -> bool:
    """删除自定义风格；引用它的房间回退 balanced。内置 id 返回 False。"""
    if style_id in BUILTIN_IDS:
        return False
    row = session.get(KpStyle, style_id)
    if row is None:
        return False
    session.delete(row)
    for room in session.exec(select(Room).where(Room.style_id == style_id)).all():
        room.style_id = 'balanced'
        session.add(room)
    session.commit()
    return True


def render_style_directive(style: dict | None) -> str | None:
    """风格 JSON → L2 叙事指令文本（≈0.5k，goal §6.1 L2 层）。

    None / 未知风格返回 None（组装器跳过该层）。只写表达指令，不碰公平性——
    骰子与数值仍全部由工具/规则引擎产生。
    """
    if not style:
        return None
    p = validate_params(style.get('params') or {})
    lines = [f"当前 KP 风格：「{style.get('name', '自定义')}」（只影响表达方式，公平性规则不变）"]

    density = p['narrative_density']
    if density == 'high':
        lines.append('- 叙事密度：高。多用感官细节（声音/气味/光线/触感）与环境描写渲染氛围，'
                     '但单轮公开叙事仍遵守输出协议的长度上限，不为了细节拖慢节奏。')
    elif density == 'low':
        lines.append('- 叙事密度：低。精炼直给，短句推进，把时间留给玩家的行动与选择。')
    else:
        lines.append('- 叙事密度：中。关键场景细写，过渡场景一笔带过。')

    rule = p['rule_explanation']
    if rule == 'high':
        lines.append('- 规则解释：高。每次检定后在叙事中用一句话说明规则依据（难度等级/目标值'
                     '含义/为何这样判定），面向新手玩家教学；规则讲解只放叙事或 keeper 笔记，'
                     '禁止出现在行动切口里。')
    elif rule == 'low':
        lines.append('- 规则解释：低。只报检定结果与后果，不作规则说明，保持叙事沉浸。')
    else:
        lines.append('- 规则解释：中。玩家疑惑时才解释，否则只报结果。')

    hidden = p['hidden_roll_transparency']
    if hidden == 'high':
        lines.append('- 暗骰透明度：高。可以坦承「这里我进行了一次隐藏判定」以建立信任，'
                     '但结果与内容仍然保密。')
    elif hidden == 'low':
        lines.append('- 暗骰透明度：低。隐藏判定完全保密，绝不暗示其存在。')
    else:
        lines.append('- 暗骰透明度：中。一般不提隐藏判定，除非剧情需要暗示「有看不见的力量在起作用」。')

    gran = p['option_granularity']
    if gran == 'fine':
        lines.append('- 选项颗粒度：细。行动切口给手把手的具体步骤（先做什么、再做什么）。')
    elif gran == 'coarse':
        lines.append('- 选项颗粒度：粗。行动切口只给开放式方向或情绪意图，具体做法留给玩家。')
    else:
        lines.append('- 选项颗粒度：中。行动切口给明确目标但不说死步骤。')

    if p.get('note'):
        lines.append(f'- KP 补充要求：{p["note"]}')
    return '\n'.join(lines)


def style_echo(session: Session, room: Room) -> dict:
    """房间当前风格的对外展示摘要（房间详情 / 切换广播 payload 共用）。"""
    style = get_style(session, room.style_id)
    if style is None:  # 自定义被删等异常：按默认处理
        return {'style_id': 'balanced', 'style_name': '平衡 Keeper'}
    return {'style_id': style['id'], 'style_name': style['name']}


def now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')
