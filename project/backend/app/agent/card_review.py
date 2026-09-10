"""角色卡合规检查（2026-09-10 用户反馈 #5）。

KP 挂好模组后点「检查调查员卡」，AI 逐张检查是否合理合规：
  - 技能是否配得上背景/职业描述（例：背景写"文弱学者"却把格斗点到 80）
  - 随身物品/武器是否与模组时代与场景冲突（例：1920s 模组带智能手机）
  - 数值是否越界（单技能超过创建上限、信用评级与职业区间不符）
  - 是否缺失可用要素（背景八要素大段空白、没有任何调查向技能）
  - 与模组的契合度（模组核心能力全员缺失 → 可能卡团）

用户决策（2026-09-10）：**只给建议，不拦截开团**——结果只是 KP 侧的参考清单。

走轻任务模型（与协同建议同档，低频手动触发、成本可控）；输出严格 JSON，
解析失败带原输出重问一次（与 suggest/keeper 同款容错）。
"""
from __future__ import annotations

import asyncio
import json
import re

from sqlmodel import Session, select

from app.agent.module_context import module_review_digest
from app.agent.tools import _skill_row_value
from app.db import engine
from app.llm.config import get_settings
from app.llm.provider import get_light_client
from app.llm.usage import usage_room
from app.models import Card, Room, RoomMember

# 输入侧上限：防一张卡把提示词撑爆（技能值降序取前 25 条）
MAX_SKILL_LINES = 25
MAX_DETAIL_CHARS = 260

_FENCE_RE = re.compile(r'^\s*```[a-zA-Z0-9]*\s*|\s*```\s*$')
_TRAILING_COMMA_RE = re.compile(r',\s*(?=[}\]])')

_SYSTEM = (
    '你是《克苏鲁的呼唤》第七版的开团前审卡助手。KP 已挂好模组，'
    '请逐张检查调查员卡是否合理合规。\n'
    '只输出一个 JSON 对象，禁止任何解释或代码围栏，格式：\n'
    '{"players":[{"player_name":"<必须原样照抄输入的玩家昵称>",'
    '"overall":"ok|suggestion|major","issues":['
    '{"severity":"suggestion|major","title":"≤20字","detail":"问题与理由",'
    '"advice":"具体怎么改"}]}]}\n\n'
    '检查维度（按重要性）：\n'
    '1. 技能与背景/职业是否自洽（背景与点数分配明显矛盾才算问题）\n'
    '2. 随身物品、武器是否与模组的时代与场景冲突\n'
    '3. 数值合规：单技能创建上限 90、信用评级是否与职业区间明显不符\n'
    '4. 是否缺关键要素：背景八要素大段空白、没有任何可用于调查的技能\n'
    '5. 与模组契合度：模组绕不开的核心能力（如侦查/图书馆使用）是否全员缺失\n\n'
    '判定口径：能用"扮演"自圆其说的轻微不协调 → suggestion；'
    '明显违反规则或与模组时代/设定直接冲突 → major。\n'
    '没有问题的卡给 overall="ok" 且 issues 为空数组。'
    '**不要为了凑数编问题**，拿不准的不写；每张卡最多 4 条。'
)

_REPAIR = (
    '上面的输出不是合法 JSON（必须是一个对象，含 players 数组，'
    '每项有 player_name / overall / issues）。请修复并只输出该 JSON 对象。'
)


def _card_digest(data: dict) -> str:
    """把整卡压成可读摘要（属性/技能/背景八要素/物品/武器）。"""
    attrs = data.get('attributes') or {}
    derived = data.get('derived') or {}
    bg = data.get('background') or {}

    skills: list[tuple[str, int]] = []
    for s in data.get('skills') or []:
        label = s.get('name', '')
        if s.get('detail'):
            label = f"{label}（{s['detail']}）"
        skills.append((label, _skill_row_value(s)))
    skills.sort(key=lambda kv: -kv[1])
    skill_text = '，'.join(f'{n} {v}' for n, v in skills[:MAX_SKILL_LINES]) or '（无）'

    bg_parts = [
        f'个人描述：{bg.get("personal_description") or "空"}',
        f'思想信念：{bg.get("ideology_beliefs") or "空"}',
        f'重要之人：{bg.get("significant_people") or "空"}',
        f'意义非凡之地：{bg.get("meaningful_location") or "空"}',
        f'宝贵之物：{bg.get("treasured_possession") or "空"}',
        f'特质：{bg.get("traits") or "空"}',
        f'资产：{bg.get("cash_assets") or "空"}',
    ]

    weapons = data.get('weapons') or []
    weapon_text = '，'.join(
        f"{w.get('name')}（{w.get('damage')}）" for w in weapons if w.get('name')
    ) or '（无）'

    return '\n'.join([
        f"角色名：{data.get('name', '?')}｜职业：{data.get('occupation') or '未填'}"
        f"｜年龄 {data.get('age', '?')}｜信用评级 {data.get('credit', '?')}"
        f"｜时代 {data.get('era', '?')}",
        '属性：' + ' '.join(
            f'{k} {attrs.get(k, "?")}' for k in ('STR', 'CON', 'SIZ', 'DEX', 'APP', 'INT', 'POW', 'EDU')
        ),
        f"衍生：HP {derived.get('HP', '?')}｜SAN {derived.get('SAN', '?')}｜MP {derived.get('MP', '?')}",
        f'技能（值降序，取前 {MAX_SKILL_LINES} 条）：{skill_text}',
        '背景八要素：' + '；'.join(bg_parts),
        f"随身物品：{(data.get('possessions') or '').strip() or '（未填）'}",
        f'武器：{weapon_text}',
    ])


def build_review_messages(payload: dict) -> list[dict]:
    """组装审卡请求（纯函数，便于离线回归）。"""
    players = payload.get('players') or []
    lines = [
        f"【房间】{payload.get('room_name') or '（未命名）'}",
        f"【当前场景】{payload.get('scene_title') or '（未设置）'}",
    ]
    module = payload.get('module') or ''
    lines.append('【模组设定】（判断物品/技能是否契合的依据）\n'
                 + (module or '未挂载模组，只做卡内自洽与数值合规检查。'))
    lines.append(f'【待检查的调查员卡】共 {len(players)} 张')
    for p in players:
        lines.append(f"--- 玩家昵称：{p['player_name']} ---\n{p['card']}")
    lines.append(
        '请逐张给出结论：player_name 必须原样照抄上面的玩家昵称；'
        '没有问题的卡写 overall="ok" 且 issues 留空数组。'
    )
    return [
        {'role': 'system', 'content': _SYSTEM},
        {'role': 'user', 'content': '\n\n'.join(lines)},
    ]


def parse_review(raw: str) -> dict:
    """解析审卡输出 → {players: [...]}；无有效条目抛 ValueError。"""
    text = _FENCE_RE.sub('', raw or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ValueError('LLM 输出中未找到 JSON 对象')
    try:
        data = json.loads(_TRAILING_COMMA_RE.sub('', text[start:end + 1]))
    except json.JSONDecodeError as exc:
        raise ValueError(f'LLM 输出不是合法 JSON：{exc}') from exc

    raw_players = data.get('players') if isinstance(data, dict) else None
    if not isinstance(raw_players, list):
        raise ValueError('LLM 输出缺少 players 数组')

    players: list[dict] = []
    for item in raw_players[:12]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('player_name') or '').strip()
        if not name:
            continue
        issues: list[dict] = []
        for issue in (item.get('issues') or [])[:4]:
            if not isinstance(issue, dict):
                continue
            title = str(issue.get('title') or '').strip()
            if not title:
                continue
            issues.append({
                'severity': 'major' if issue.get('severity') == 'major' else 'suggestion',
                'title': title[:60],
                'detail': str(issue.get('detail') or '').strip()[:400],
                'advice': str(issue.get('advice') or '').strip()[:300],
            })
        overall = item.get('overall')
        if overall not in ('ok', 'suggestion', 'major'):
            overall = 'suggestion'
        # 与 issues 对齐（LLM 常见自相矛盾：说 ok 却列出问题）
        if issues:
            overall = 'major' if any(i['severity'] == 'major' for i in issues) else 'suggestion'
        else:
            overall = 'ok'
        players.append({'player_name': name, 'overall': overall, 'issues': issues})

    if not players:
        raise ValueError('LLM 未返回任何调查员卡的检查结果')
    return {'players': players}


def _collect(room_id: str) -> tuple[dict, bool]:
    """收集审卡输入（同步；调用方 to_thread）。"""
    with Session(engine) as session:
        room = session.get(Room, room_id)
        if not room:
            return {}, False
        rows = session.exec(
            select(RoomMember, Card)
            .join(Card, RoomMember.card_id == Card.id)
            .where(RoomMember.room_id == room_id, RoomMember.role == 'player')
        ).all()
        players = [
            {'player_name': member.player_name, 'card': _card_digest(card.card_data or {})}
            for member, card in rows
        ]
        return {
            'room_name': room.name,
            'scene_title': room.scene_title,
            'module': module_review_digest(session, room_id),
            'players': players,
        }, True


async def review_room_cards(room_id: str) -> dict:
    """跑一次审卡：收集 → 轻任务模型 → 解析（失败带原输出重问一次）。

    无已绑卡玩家时直接返回空清单（不浪费一次 LLM 调用）。
    失败语义与其它引擎一致：LLM 不可用抛 LLMUnavailableError，解析不出抛 ValueError。
    """
    payload, ok = await asyncio.to_thread(_collect, room_id)
    if not ok:
        raise ValueError('房间不存在')
    settings = get_settings()
    model = settings.light_model if settings.light_ready else settings.model
    if not payload['players']:
        return {'players': [], 'model': model, 'note': '房间里还没有已绑角色卡的玩家'}

    client = get_light_client()
    messages = build_review_messages(payload)
    # 检卡是房间内的 KP 动作，计入本场消耗（与全自动轮次/建议生成同口径）
    with usage_room(room_id):
        raw = await client.chat(messages, temperature=0.3, json_mode=True)
        try:
            result = parse_review(raw)
        except ValueError:
            fixed = await client.chat(
                messages + [
                    {'role': 'assistant', 'content': raw},
                    {'role': 'user', 'content': _REPAIR},
                ],
                temperature=0.2, json_mode=True,
            )
            result = parse_review(fixed)

    # 只回传实际在房间里的玩家（LLM 偶尔杜撰名字），并保留输入顺序
    known = {p['player_name']: p for p in payload['players']}
    result['players'] = [p for p in result['players'] if p['player_name'] in known]
    if not result['players']:
        raise ValueError('LLM 返回的玩家名与本房间对不上')
    result['model'] = model
    result['module_mounted'] = bool(payload['module'])
    return result
