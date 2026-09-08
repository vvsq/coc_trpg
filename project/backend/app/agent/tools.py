"""LLM 工具集（4.2，goal §6.7 的 4.2 子集）— LLM 一切状态变更的唯一入口。

铁律（D3/D9，goal §9）：
  - LLM 禁止直接生成数值变更文本：HP/SAN/骰子全部由本模块调用规则引擎产生，
    结果经落库 + 广播生效后，才以 JSON 摘要回喂 LLM
  - 工具失败返回 {"error": ...} 让 LLM 澄清重试，绝不静默编造、也不抛异常中断回合
  - 一切数值变更必带 reason（D9 溯源），operator 固定为 AI 主持者身份

可见性（D8）：每个工具产出的消息走双通道——玩家可知的（检定徽章 / 状态行 /
公开叙事）走全员广播；keeper 独有的（暗骰、疯狂细节）走 Message.secret=True
落库 + broadcast_to_roles({'kp'})，与 3.3 暗骰同一机制，玩家协议层收不到。
"""
import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.api.dice import DIFFICULTY_LABELS, LEVEL_LABELS
from app.db import engine
from app.models import Card, Clue, GameClock, Message, Npc, RoomMember, ScenarioState, Thread
from app.rules import sanity
from app.rules.coc7 import check as coc7_check
from app.rules.coc7 import target_for
from app.rules.dice import roll as roll_expr
from app.agent.state_ops import apply_scene_change, apply_status_change
from app.tasks import spawn_background
from app.ws.manager import build_envelope, manager

# AI 主持者在消息流里的统一署名（前端据此渲染「AI 主持」标识）
AI_KEEPER_NAME = 'AI主持'

# 当日 SAN 损失登记上限防溢出（不可能触发，防御性）
_SAN_TODAY_MAX = 99

# LLM 可能幻觉出离谱骰子表达式（如 999999d6）拖死执行，限制规模
_MAX_DICE_NUM = 100
_MAX_DICE_FACES = 1000


def _validate_dice_expr(expr: str) -> str:
    """校验骰子表达式格式与规模，返回规范化文本；不合法抛 ValueError（error 回喂）。"""
    text = (expr or '').strip()
    m = re.fullmatch(r'(\d*)[dD](\d+)([+-]\d+)?', text)
    if not m:
        raise ValueError(f'骰子表达式 {expr!r} 不合法（格式如 1D6、2d3+1）')
    num = int(m.group(1) or 1)
    faces = int(m.group(2))
    if not 1 <= num <= _MAX_DICE_NUM or not 1 <= faces <= _MAX_DICE_FACES:
        raise ValueError(
            f'骰子规模过大：数量 ≤{_MAX_DICE_NUM}、面数 ≤{_MAX_DICE_FACES}，收到 {expr!r}'
        )
    return text


def _today() -> str:
    """当前日期（本地时区）。独立函数便于测试 monkeypatch 跨天场景。"""
    return datetime.now().strftime('%Y-%m-%d')


def _san_today_bucket(data: dict, today: str) -> dict[str, int]:
    """读取"当日" SAN 损失桶：日期不符（跨天）或旧格式（无 date 键）一律清零。

    不定性疯狂的阈值是「一天内累计损失 ≥ 1/5 当前 SAN」，桶必须按天隔离。
    存储格式：{'date': 'YYYY-MM-DD', 'loss': {玩家名: 当日累计}}。
    """
    bucket = data.get('san_today', {}) or {}
    if isinstance(bucket, dict) and bucket.get('date') == today:
        loss = bucket.get('loss', {})
        if isinstance(loss, dict):
            return {k: int(v) for k, v in loss.items()}
    return {}


# ==================== 工具 schema（OpenAI function calling 格式） ====================

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        'type': 'function',
        'function': {
            'name': 'roll_check',
            'description': '进行一次技能检定（D100，明骰全员可见）——仅用于 NPC/剧情骰（无 target）。'
                           '调查员的检定一律用 request_check 下放给玩家本人投掷，禁止代掷。'
                           '所有检定必须先在正文说明技能/难度/后果再调用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'skill_name': {'type': 'string', 'description': '技能名，如 侦查 / 图书馆使用'},
                    'difficulty': {'type': 'string', 'enum': ['standard', 'hard', 'extreme'],
                                   'description': '难度：常规/困难/极难'},
                    'reason': {'type': 'string', 'description': '这次检定在剧情里的缘由（必填）'},
                    'value': {'type': 'integer', 'minimum': 1, 'maximum': 99,
                              'description': 'NPC/剧情骰的技能值（必填）'},
                    'bonus': {'type': 'integer', 'minimum': 0, 'maximum': 2, 'description': '奖励骰数'},
                    'penalty': {'type': 'integer', 'minimum': 0, 'maximum': 2, 'description': '惩罚骰数'},
                },
                'required': ['skill_name', 'difficulty', 'reason', 'value'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'request_check',
            'description': '把一次技能检定下放给调查员本人投掷（正统跑团：KP 定技能/难度/后果，玩家掷骰）。'
                           '先在正文铺垫「技能/难度/失败后果」，再调用本工具；本轮叙事在检定点收束，'
                           '玩家投掷后系统会用骰子结果唤醒你继续主持。调查员检定一律用它，不要代掷。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'target': {'type': 'string', 'description': '调查员名字（须在场且绑卡）'},
                    'skill_name': {'type': 'string', 'description': '技能名（服务端按其角色卡查值）'},
                    'difficulty': {'type': 'string', 'enum': ['standard', 'hard', 'extreme'],
                                   'description': '难度：常规/困难/极难'},
                    'reason': {'type': 'string', 'description': '检定缘由与失败后果（必填，会展示给玩家）'},
                },
                'required': ['target', 'skill_name', 'difficulty', 'reason'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'roll_dice',
            'description': '掷任意骰子表达式并全员公开（如 1D6 决定先攻、1D3 随机数量），不用于技能/理智检定。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'expr': {'type': 'string', 'description': '骰子表达式，如 1D6、2D3+1'},
                    'reason': {'type': 'string', 'description': '掷骰缘由（必填）'},
                },
                'required': ['expr', 'reason'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'san_check',
            'description': '对一名调查员进行理智检定并自动结算损失与疯狂（触发恐惧场景时必须调用本工具，禁止在正文直接写 SAN 数值变化）。损失写法「成功/失败」如 0/1D6。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'target': {'type': 'string', 'description': '调查员名字（须在场且绑卡）'},
                    'loss_formula': {'type': 'string', 'description': '损失公式，成功损失/失败损失，如 0/1D6、1/1D4+1'},
                    'reason': {'type': 'string', 'description': '触发理智检定的恐怖场景（必填）'},
                    'alone_or_all': {'type': 'boolean', 'description': '独处或全场同时发疯时 true（用总结症状），默认 false（即时症状）'},
                },
                'required': ['target', 'loss_formula', 'reason'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'secret_roll',
            'description': '暗骰：掷任意骰子表达式，结果只有 KP 可见（NPC 隐藏检定、敌人行动、是否惊动守夜人等）。叙事里不得向玩家泄露结果。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'expr': {'type': 'string', 'description': '骰子表达式，如 1D100、1D6'},
                    'reason': {'type': 'string', 'description': '暗骰缘由（必填，会展示给 KP）'},
                },
                'required': ['expr', 'reason'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_status',
            'description': '修改一名调查员的 HP/SAN 绝对值（服务端会 clamp 到上限）。禁止用正文宣布数值变化，一切扣血扣 SAN 必须走本工具。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'target': {'type': 'string', 'description': '调查员名字（须在场且绑卡）'},
                    'hp': {'type': 'integer', 'minimum': 0, 'description': '变更后的 HP 绝对值'},
                    'sanity': {'type': 'integer', 'minimum': 0, 'description': '变更后的 SAN 绝对值'},
                    'reason': {'type': 'string', 'description': '变更原因（必填，如：受到步枪射击）'},
                },
                'required': ['target', 'reason'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'set_scene',
            'description': '切换场景标题栏（地点/时间 + 全员可见的场景描述）。场景推进时调用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'scene_title': {'type': 'string', 'description': '地点/时间，如：仓库二层 · 深夜'},
                    'scene_desc': {'type': 'string', 'description': '一句话场景描述（全员可见）'},
                },
                'required': ['scene_title'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'get_card',
            'description': '读取一名在场调查员的整卡摘要（属性/技能当前值/状态/背景钩子），不确定技能值时先查再检定。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'target': {'type': 'string', 'description': '调查员名字（须在场且绑卡）'},
                },
                'required': ['target'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'record_events',
            'description': '登记本轮发生的关键事件（1~3 条短句），供后续剧情记忆引用。每次推进后应登记。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'events': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 3,
                               'description': '关键事件短句列表'},
                },
                'required': ['events'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'add_clue',
            'description': '登记一条线索（编号自动分配）。玩家当面获得的信息设 visibility=public，'
                           '仅 KP 知晓的（暗中获得、NPC 真相）用默认 keeper。登记动作本身只进 KP 屏。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'content': {'type': 'string', 'description': '线索内容（一句话）'},
                    'source': {'type': 'string', 'description': '来源（谁/哪里获得）'},
                    'points_to': {'type': 'string', 'description': '指向（暗示什么）'},
                    'visibility': {'type': 'string', 'enum': ['keeper', 'public'],
                                   'description': '默认 keeper'},
                },
                'required': ['content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'update_clue',
            'description': '更新线索验证状态：pending（待验证）→ confirmed（已证实）/ excluded（已排除）。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'clue_id': {'type': 'integer', 'description': '线索 id（add_clue 返回）'},
                    'status': {'type': 'string', 'enum': ['pending', 'confirmed', 'excluded']},
                },
                'required': ['clue_id', 'status'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'add_thread',
            'description': '登记伏笔/未结算事项（延迟 SAN 惩罚、暗骰后果、待回收伏笔）。仅 KP 可见。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'content': {'type': 'string', 'description': '伏笔内容（一句话）'},
                },
                'required': ['content'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'resolve_thread',
            'description': '标记某条伏笔已结算/已回收。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'thread_id': {'type': 'integer', 'description': '伏笔 id（add_thread 返回）'},
                },
                'required': ['thread_id'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'advance_clock',
            'description': '推进威胁时钟（如 教团仪式、追兵逼近）。进度走满会提示 KP 触发后果。'
                           '首次推进按 target 建钟，其后沿用。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': '时钟名，如 教团仪式'},
                    'by': {'type': 'integer', 'minimum': 1, 'maximum': 3, 'description': '本次推进格数，默认 1'},
                    'target': {'type': 'integer', 'minimum': 2, 'maximum': 20, 'description': '总格数（仅首次建钟时生效，默认 4）'},
                    'note': {'type': 'string', 'description': '走满后果备注（仅首次生效）'},
                },
                'required': ['name'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'upsert_npc',
            'description': '登记/更新 NPC 档案（核心 NPC 六要素）。新登场的具名 NPC 应建档；'
                           'hidden_motive 仅 KP 可见，公开叙事禁止提及。',
            'parameters': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'description': 'NPC 名字'},
                    'public_identity': {'type': 'string', 'description': '公开身份'},
                    'hidden_motive': {'type': 'string', 'description': '隐藏动机（仅 KP 可见）'},
                    'player_clues': {'type': 'string', 'description': '玩家可从其身上获得的线索'},
                    'misdirection': {'type': 'string', 'description': '误导点'},
                    'pressed_reaction': {'type': 'string', 'description': '被逼问时的反应'},
                    'exit_plan': {'type': 'string', 'description': '死亡或离场替代方案（防剧情脆断）'},
                    'status': {'type': 'string', 'enum': ['active', 'gone'], 'description': '默认 active'},
                },
                'required': ['name'],
            },
        },
    },
]


# ==================== 场景状态读写 ====================

def get_scenario(session: Session, room_id: str) -> ScenarioState:
    """取（或初始化）房间剧情状态行。data 变更需整体重赋值触发 SQLAlchemy 变更检测。"""
    row = session.get(ScenarioState, room_id)
    if row is None:
        row = ScenarioState(room_id=room_id, data={'scene': {}, 'events': [], 'san_today': {}})
        session.add(row)
    return row


def _mutate_scenario(session: Session, row: ScenarioState, **kwargs) -> None:
    """整体重赋 data 并落库（调用方自行 commit 或由后续 commit 一并提交）。"""
    data = {**row.data, **kwargs}
    row.data = data
    row.updated_at = datetime.now()
    session.add(row)


# ==================== 消息双通道（D8） ====================

def persist_keeper_note(session: Session, room_id: str, text: str) -> None:
    """keeper 独有信息落库（secret=True）+ 只定向 KP 广播：玩家协议层收不到。

    广播为 fire-and-forget（spawn_background 挂异常回调，与项目后台任务
    约定一致）；无事件循环（纯同步测试）时广播跳过，落库仍有效。
    """
    session.add(Message(
        room_id=room_id, channel='narrative', type='text',
        sender=AI_KEEPER_NAME, content=text, secret=True,
        payload={'role': 'kp', 'keeper': True},
    ))
    session.commit()

    envelope = build_envelope('chat_new', room_id, AI_KEEPER_NAME, 'narrative',
                              {'text': text, 'role': 'kp', 'keeper': True})
    try:
        spawn_background(
            manager.broadcast_to_roles(room_id, envelope, {'kp'}),
            name=f'keeper-note-{room_id}',
        )
    except RuntimeError:
        pass  # 无事件循环（纯同步测试）：广播跳过，落库仍有效


# ==================== 卡与成员读取 ====================

def _load_member_card(session: Session, room_id: str, target: str) -> tuple[RoomMember, Card, dict]:
    member = session.exec(
        select(RoomMember).where(
            RoomMember.room_id == room_id, RoomMember.player_name == target,
        )
    ).first()
    if not member:
        raise ValueError(f'「{target}」不在房间内')
    if not member.card_id:
        raise ValueError(f'「{target}」未绑定角色卡')
    card = session.get(Card, member.card_id)
    if not card:
        raise ValueError(f'「{target}」的角色卡不存在')
    return member, card, card.card_data or {}


def _card_summary(data: dict) -> dict:
    """get_card 工具返回的整卡摘要（属性/技能当前值/状态/背景）。"""
    skills = []
    for s in data.get('skills', []):
        label = s.get('name', '')
        if s.get('detail'):
            label = f"{label}（{s['detail']}）"
        skills.append({'name': label, 'value': _skill_row_value(s)})
    return {
        'name': data.get('name', ''),
        'occupation': data.get('occupation', ''),
        'age': data.get('age'),
        'attributes': data.get('attributes', {}),
        'derived': data.get('derived', {}),
        'state': data.get('state', {}),
        'skills': skills,
        'background': data.get('background', {}),
    }


def _skill_row_value(s: dict) -> int:
    """技能行当前值：存档格式是 base + increment（合并后的成长值）；
    兼容旧式 occupation_points + interest_points 分离字段。"""
    base = int(s.get('base', 0) or 0)
    inc = s.get('increment')
    if inc is not None:
        return base + int(inc or 0)
    return base + int(s.get('occupation_points', 0) or 0) + int(s.get('interest_points', 0) or 0)


def _skill_value(data: dict, skill_name: str) -> int | None:
    """按名查技能当前值（名字含分类技能细分，前后缀匹配）。"""
    want = skill_name.strip()
    for s in data.get('skills', []):
        label = s.get('name', '')
        if s.get('detail'):
            label = f"{label}（{s['detail']}）"
        if label == want or label.startswith(want):
            return _skill_row_value(s)
    return None


# ==================== 工具执行器 ====================

async def execute_tool(name: str, arguments: dict, room_id: str) -> str:
    """执行一个工具调用并把结果摘要作为 JSON 字符串返回（回喂 tool 消息）。

    业务错误（成员不在/公式非法/参数越界…）一律转 {"error": ...} 返回，
    由 LLM 澄清重试（D3）；意外异常同样捕获，不让单次工具失败中断整回合。
    """
    try:
        with Session(engine) as session:
            handler = _HANDLERS.get(name)
            if handler is None:
                return json.dumps({'error': f'未知工具：{name}'}, ensure_ascii=False)
            result = await handler(session, room_id, arguments or {})
            return json.dumps(result, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({'error': str(exc)}, ensure_ascii=False)
    except HTTPException as exc:
        return json.dumps({'error': exc.detail}, ensure_ascii=False)
    except Exception as exc:  # 防御：非预期异常也不中断回合
        return json.dumps({'error': f'工具执行异常：{exc}'}, ensure_ascii=False)


async def _tool_roll_check(session: Session, room_id: str, args: dict) -> dict:
    skill_name = str(args.get('skill_name') or '').strip()
    difficulty = str(args.get('difficulty') or 'standard')
    reason = str(args.get('reason') or '').strip()
    target = str(args.get('target') or '').strip()
    bonus = max(0, min(2, int(args.get('bonus') or 0)))
    penalty = max(0, min(2, int(args.get('penalty') or 0)))
    if not skill_name or not reason:
        raise ValueError('roll_check 需要 skill_name 与 reason')
    if difficulty not in ('standard', 'hard', 'extreme'):
        raise ValueError(f'难度必须是 standard/hard/extreme，收到 {difficulty!r}')

    # 4.3 实测遗留修复（工具层硬拦截）：调查员检定禁止 AI 代掷——LLM 偶发绕过
    # request_check 用 roll_check 带 target 代玩家掷骰。系统级拦截，不依赖提示词自觉。
    if target:
        raise ValueError(
            f'「{target}」是在场调查员，其检定必须用 request_check 下放给本人投掷，'
            '禁止用 roll_check 代掷（防代掷铁律）。'
        )

    # 走到这里必然无 target：剧情/NPC 检定，值由 LLM 提供（仅 NPC 骰，风险可控）
    value = int(args.get('value') or 0)
    if not 1 <= value <= 99:
        raise ValueError(f'剧情/NPC 检定（无 target）需要提供合法 value（1~99），收到 {value!r}')
    sender = AI_KEEPER_NAME

    level, d100 = coc7_check(value, difficulty, bonus, penalty)
    tgt = target_for(value, difficulty)
    payload = {
        'sender': sender,
        'skill_name': skill_name,
        'detail': '',
        'value': value,
        'difficulty': difficulty,
        'level': level,
        'level_label': LEVEL_LABELS[level],
        'target': tgt,
        'roll': {'units': d100.units, 'tens': d100.tens, 'value': d100.value,
                 'bonus': d100.bonus, 'penalty': d100.penalty},
        'secret': False,
    }
    content = (
        f'{sender} 进行 {skill_name} {value} {DIFFICULTY_LABELS[difficulty]}检定：'
        f'掷出 {d100.value}（目标 {tgt}）→ {LEVEL_LABELS[level]}'
    )
    session.add(Message(
        room_id=room_id, channel='narrative', type='dice',
        sender=sender, content=content, secret=False, payload=payload,
    ))
    session.commit()
    await manager.broadcast(room_id, build_envelope('roll_result', room_id, sender, 'narrative', payload))
    return {'skill': skill_name, 'difficulty': difficulty, 'roll': d100.value, 'target': tgt,
            'level': level, 'level_label': LEVEL_LABELS[level], 'success': level not in ('fail', 'fumble')}


async def _tool_request_check(session: Session, room_id: str, args: dict) -> dict:
    """检定下放（正统玩法）：AI 定技能/难度/后果，玩家本人投掷（实测反馈方案落地）。

    服务端按目标角色卡查技能值（D5），玩家只点「投掷」按钮，无自掷刷优势空间。
    投掷端点 POST /rooms/{id}/check-requests/{request_id}/roll 完成结算并唤醒 AI。
    """
    target = str(args.get('target') or '').strip()
    skill_name = str(args.get('skill_name') or '').strip()
    difficulty = str(args.get('difficulty') or 'standard')
    reason = str(args.get('reason') or '').strip()
    if not target or not skill_name or not reason:
        raise ValueError('request_check 需要 target / skill_name / reason')
    if difficulty not in ('standard', 'hard', 'extreme'):
        raise ValueError(f'难度必须是 standard/hard/extreme，收到 {difficulty!r}')
    _, _, data = _load_member_card(session, room_id, target)
    value = _skill_value(data, skill_name)
    if value is None:
        raise ValueError(
            f'「{target}」的技能表里没有「{skill_name}」。请先调用 get_card 查询其技能表'
        )

    request_id = uuid.uuid4().hex[:12]
    payload = {
        'role': 'kp', 'ai': True, 'check_request': True,
        'request_id': request_id, 'target': target,
        'skill_name': skill_name, 'difficulty': difficulty,
        'value': value, 'reason': reason[:200], 'fulfilled': False,
    }
    content = f'请 {target} 进行 {skill_name}（{DIFFICULTY_LABELS[difficulty]}）检定：{reason[:150]}'
    session.add(Message(
        room_id=room_id, channel='narrative', type='check_request',
        sender=AI_KEEPER_NAME, content=content, secret=False, payload=payload,
    ))
    session.commit()
    await manager.broadcast(room_id, build_envelope(
        'chat_new', room_id, AI_KEEPER_NAME, 'narrative', payload,
    ))
    return {
        'status': 'requested', 'request_id': request_id, 'target': target,
        'skill': skill_name, 'value': value, 'difficulty': difficulty,
        'note': '已向玩家发起投掷请求。本轮叙事在检定点收束即可（铺垫正文已写），'
                '玩家投掷后系统会用骰子结果唤醒你继续主持。',
    }


async def _tool_roll_dice(session: Session, room_id: str, args: dict) -> dict:
    expr = _validate_dice_expr(str(args.get('expr') or ''))
    reason = str(args.get('reason') or '').strip()
    if not reason:
        raise ValueError('roll_dice 需要 reason')
    result = roll_expr(expr)
    text = f'{AI_KEEPER_NAME} 掷骰 {expr} → {result}（{reason}）'
    session.add(Message(
        room_id=room_id, channel='narrative', type='text',
        sender=AI_KEEPER_NAME, content=text, secret=False,
        payload={'role': 'kp', 'ai': True, 'dice_expr': expr, 'dice_result': result},
    ))
    session.commit()
    await manager.broadcast(room_id, build_envelope(
        'chat_new', room_id, AI_KEEPER_NAME, 'narrative',
        {'text': text, 'role': 'kp', 'ai': True}))
    return {'expr': expr, 'result': result}


async def _tool_secret_roll(session: Session, room_id: str, args: dict) -> dict:
    expr = _validate_dice_expr(str(args.get('expr') or ''))
    reason = str(args.get('reason') or '').strip()
    if not reason:
        raise ValueError('secret_roll 需要 reason')
    result = roll_expr(expr)
    persist_keeper_note(session, room_id, f'暗骰 {expr} → {result}（{reason}）')
    return {'expr': expr, 'result': result, 'secret': True}


async def _tool_san_check(session: Session, room_id: str, args: dict) -> dict:
    target = str(args.get('target') or '').strip()
    formula = str(args.get('loss_formula') or '').strip()
    reason = str(args.get('reason') or '').strip()
    alone_or_all = bool(args.get('alone_or_all') or False)
    if not target or not reason:
        raise ValueError('san_check 需要 target 与 reason')

    _, card, data = _load_member_card(session, room_id, target)
    state = data.get('state', {})
    san_before = int(state.get('current_sanity', 0))
    int_value = int((data.get('attributes') or {}).get('INT', 50))
    success_expr, fail_expr = sanity.parse_loss_formula(formula)

    # 理智检定：D100 ≤ 当前 SAN，无奖惩骰（docs §6.2）；大失败取失败式最大值
    level, d100 = coc7_check(san_before)
    success = level not in ('fail', 'fumble')
    loss = sanity.roll_loss_max(fail_expr) if level == 'fumble' else \
        sanity.roll_loss(success_expr, fail_expr, success=success)
    san_after = max(0, san_before - loss)

    # 疯狂判定（当日累计损失从 scenario_state 取；跨天自动清零，见 _san_today_bucket）
    scenario = get_scenario(session, room_id)
    today = _today()
    loss_map = _san_today_bucket(scenario.data, today)
    day_before = int(loss_map.get(target, 0))
    madness = sanity.determine_madness(
        loss, san_before, san_after, int_value,
        day_loss_before=day_before, alone_or_all=alone_or_all,
    )
    _mutate_scenario(session, scenario,
                     san_today={'date': today,
                                'loss': {**loss_map,
                                         target: min(_SAN_TODAY_MAX, day_before + loss)}})

    # 1) 理智检定徽章（明骰，全员可见）
    payload = {
        'sender': target,
        'skill_name': '理智',
        'detail': '',
        'value': san_before,
        'difficulty': 'standard',
        'level': level,
        'level_label': LEVEL_LABELS[level],
        'target': san_before,
        'roll': {'units': d100.units, 'tens': d100.tens, 'value': d100.value,
                 'bonus': 0, 'penalty': 0},
        'secret': False,
    }
    content = (
        f'{target} 进行理智检定（当前 SAN {san_before}）：掷出 {d100.value}'
        f' → {LEVEL_LABELS[level]}，损失 {loss} 点（{reason}）'
    )
    session.add(Message(
        room_id=room_id, channel='narrative', type='dice',
        sender=target, content=content, secret=False, payload=payload,
    ))
    session.commit()
    # 先广播检定徽章，再做扣减（前端时间线：骰子行 → 状态行）
    await manager.broadcast(room_id, build_envelope('roll_result', room_id, target, 'narrative', payload))
    # 2) 扣 SAN（绝对值走共享状态操作：clamp + save_card + status 行 + 广播）
    await apply_status_change(
        session, room_id, target, sanity=san_after,
        reason=f'理智损失 {loss}（{reason}）', operator=AI_KEEPER_NAME,
    )
    # 3) 疯狂细节 → keeper 通道（玩家只知道「状态变差了」，症状细节只有 KP 知道）
    keeper_text = ''
    if madness.has_breakdown:
        keeper_text = f'【理智检定后】{target} ' + madness.summary()
        persist_keeper_note(session, room_id, keeper_text)

    return {
        'target': target,
        'san_before': san_before,
        'roll': d100.value,
        'level': level,
        'success': success,
        'loss': loss,
        'san_after': san_after,
        'madness': madness.summary() or '无疯狂发作',
    }


async def _tool_update_status(session: Session, room_id: str, args: dict) -> dict:
    target = str(args.get('target') or '').strip()
    reason = str(args.get('reason') or '').strip()
    if not target or not reason:
        raise ValueError('update_status 需要 target 与 reason')
    hp = args.get('hp')
    sanity_v = args.get('sanity')
    if hp is None and sanity_v is None:
        raise ValueError('hp 与 sanity 至少提供一个')
    payload = await apply_status_change(
        session, room_id, target,
        hp=int(hp) if hp is not None else None,
        sanity=int(sanity_v) if sanity_v is not None else None,
        reason=reason, operator=AI_KEEPER_NAME,
    )
    return {'target': target, 'hp': payload['hp'], 'sanity': payload['sanity'],
            'hp_max': payload['hp_max'], 'sanity_max': payload['sanity_max']}


async def _tool_set_scene(session: Session, room_id: str, args: dict) -> dict:
    title = str(args.get('scene_title') or '').strip()
    desc = str(args.get('scene_desc') or '').strip()
    if not title:
        raise ValueError('set_scene 需要 scene_title')
    # 同轮重复调用防刷屏：场景标题未变（AI 偶发同轮二次 set_scene、或仅微调描述）
    # 时只静默更新记忆层，不再落「更新了场景」系统行、不再广播
    scenario = get_scenario(session, room_id)
    prev = scenario.data.get('scene', {}) or {}
    if prev.get('scene_title') == title:
        if prev.get('scene_desc', '') != desc:
            _mutate_scenario(session, scenario,
                             scene={'scene_title': title, 'scene_desc': desc})
            session.commit()
        return {'scene_title': title, 'scene_desc': desc, 'unchanged': True}
    payload = await apply_scene_change(
        session, room_id, scene_title=title, scene_desc=desc, operator=AI_KEEPER_NAME,
    )
    # 场景双写进剧情状态（BP2 记忆层引用）
    _mutate_scenario(session, scenario,
                     scene={'scene_title': payload['scene_title'], 'scene_desc': payload['scene_desc']})
    session.commit()
    return {'scene_title': payload['scene_title'], 'scene_desc': payload['scene_desc']}


async def _tool_get_card(session: Session, room_id: str, args: dict) -> dict:
    target = str(args.get('target') or '').strip()
    if not target:
        raise ValueError('get_card 需要 target')
    _, _, data = _load_member_card(session, room_id, target)
    return _card_summary(data)


async def _tool_record_events(session: Session, room_id: str, args: dict) -> dict:
    events = args.get('events')
    if not isinstance(events, list) or not events:
        raise ValueError('record_events 需要非空 events 数组')
    clean = [str(e).strip()[:120] for e in events if str(e).strip()][:3]
    if not clean:
        raise ValueError('events 全为空')
    scenario = get_scenario(session, room_id)
    merged = (scenario.data.get('events', []) or []) + clean
    _mutate_scenario(session, scenario, events=merged[-20:])  # 滚动保留最近 20 条
    session.commit()
    return {'recorded': clean, 'total': len(merged)}


# ---------- 记忆五要素工具（4.3，goal §6.5/§6.6） ----------

async def _tool_add_clue(session: Session, room_id: str, args: dict) -> dict:
    content = str(args.get('content') or '').strip()
    if not content:
        raise ValueError('add_clue 需要 content')
    visibility = str(args.get('visibility') or 'keeper')
    if visibility not in ('keeper', 'public'):
        raise ValueError("visibility 只能是 keeper/public")
    count = len(session.exec(select(Clue).where(Clue.room_id == room_id)).all())
    clue = Clue(
        room_id=room_id, code=f'线索-{count + 1:02d}', content=content[:200],
        source=str(args.get('source') or '').strip()[:100],
        points_to=str(args.get('points_to') or '').strip()[:100],
        visibility=visibility,
    )
    session.add(clue)
    session.commit()
    session.refresh(clue)
    persist_keeper_note(session, room_id,
                        f'登记{clue.code}（{"公开" if visibility == "public" else "仅KP"}）：'
                        f'{clue.content[:80]}' + (f'，来源：{clue.source}' if clue.source else ''))
    return {'clue_id': clue.id, 'code': clue.code, 'visibility': visibility}


async def _tool_update_clue(session: Session, room_id: str, args: dict) -> dict:
    clue_id = int(args.get('clue_id') or 0)
    status = str(args.get('status') or '')
    if status not in ('pending', 'confirmed', 'excluded'):
        raise ValueError('status 必须是 pending/confirmed/excluded')
    clue = session.get(Clue, clue_id)
    if clue is None or clue.room_id != room_id:
        raise ValueError(f'线索 {clue_id} 不存在（或不在本房间）')
    old = clue.status
    clue.status = status
    clue.updated_at = datetime.now()
    session.add(clue)
    session.commit()
    persist_keeper_note(session, room_id, f'{clue.code} 状态：{old} → {status}（{clue.content[:60]}）')
    return {'clue_id': clue.id, 'code': clue.code, 'status': status}


async def _tool_add_thread(session: Session, room_id: str, args: dict) -> dict:
    content = str(args.get('content') or '').strip()
    if not content:
        raise ValueError('add_thread 需要 content')
    thread = Thread(room_id=room_id, content=content[:200])
    session.add(thread)
    session.commit()
    session.refresh(thread)
    persist_keeper_note(session, room_id, f'登记伏笔 #{thread.id}：{thread.content[:80]}')
    return {'thread_id': thread.id}


async def _tool_resolve_thread(session: Session, room_id: str, args: dict) -> dict:
    thread_id = int(args.get('thread_id') or 0)
    thread = session.get(Thread, thread_id)
    if thread is None or thread.room_id != room_id:
        raise ValueError(f'伏笔 {thread_id} 不存在（或不在本房间）')
    thread.resolved = True
    session.add(thread)
    session.commit()
    persist_keeper_note(session, room_id, f'伏笔 #{thread.id} 已结算：{thread.content[:60]}')
    return {'thread_id': thread.id, 'resolved': True}


async def _tool_advance_clock(session: Session, room_id: str, args: dict) -> dict:
    name = str(args.get('name') or '').strip()
    if not name:
        raise ValueError('advance_clock 需要 name')
    by = max(1, min(3, int(args.get('by') or 1)))
    row = session.exec(
        select(GameClock).where(GameClock.room_id == room_id, GameClock.name == name)
    ).first()
    if row is None:
        row = GameClock(
            room_id=room_id, name=name[:50],
            target=max(2, min(20, int(args.get('target') or 4))),
            note=str(args.get('note') or '').strip()[:100],
        )
        progress = 0
    else:
        progress = row.progress
    new_progress = min(row.target, progress + by)
    full = new_progress >= row.target
    row.progress = new_progress
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    persist_keeper_note(
        session, room_id,
        f'威胁时钟「{name}」推进到 {new_progress}/{row.target}' + ('——已走满，后果触发！' if full else ''),
    )
    return {'name': name, 'progress': new_progress, 'target': row.target, 'full': full}


async def _tool_upsert_npc(session: Session, room_id: str, args: dict) -> dict:
    name = str(args.get('name') or '').strip()
    if not name:
        raise ValueError('upsert_npc 需要 name')
    status = str(args.get('status') or 'active')
    if status not in ('active', 'gone'):
        raise ValueError('status 只能是 active/gone')
    fields = {
        k: str(args.get(k) or '').strip()[:200]
        for k in ('public_identity', 'hidden_motive', 'player_clues',
                  'misdirection', 'pressed_reaction', 'exit_plan')
        if str(args.get(k) or '').strip()
    }
    row = session.exec(
        select(Npc).where(Npc.room_id == room_id, Npc.name == name)
    ).first()
    if row is None:
        row = Npc(room_id=room_id, name=name[:50], status=status, **fields)
        action = '新建'
    else:
        for k, v in fields.items():
            setattr(row, k, v)
        row.status = status
        action = '更新'
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    persist_keeper_note(session, room_id,
                        f'{action} NPC 档案：{name}（{row.public_identity or "身份未明"}）')
    return {'npc_id': row.id, 'name': name, 'action': action, 'status': row.status}


_HANDLERS = {
    'roll_check': _tool_roll_check,
    'request_check': _tool_request_check,
    'roll_dice': _tool_roll_dice,
    'secret_roll': _tool_secret_roll,
    'san_check': _tool_san_check,
    'update_status': _tool_update_status,
    'set_scene': _tool_set_scene,
    'get_card': _tool_get_card,
    'record_events': _tool_record_events,
    'add_clue': _tool_add_clue,
    'update_clue': _tool_update_clue,
    'add_thread': _tool_add_thread,
    'resolve_thread': _tool_resolve_thread,
    'advance_clock': _tool_advance_clock,
    'upsert_npc': _tool_upsert_npc,
}
