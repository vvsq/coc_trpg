"""房间 → 模组骨架（阶段 5，替换 4.1 的临时单文件方案）。

优先取房间挂载模组的结构化结果（parse_status=ready）渲染成骨架文本；
未挂载 / 未就绪 / 渲染为空时回退 backend/data/scenario_brief.txt
——保证没挂模组的房间行为与阶段 4 完全一致。

注入点（两处共用本模块，语义一致）：
  - 协同建议：assembler.build_suggestion_messages 的 L3 段（拼进 system）
  - 全自动主持：assembler.build_auto_messages 的 BP2（剧情记忆前置段）

防剧透分层（D8）：
  渲染成【模组骨架·公开层】与【模组骨架·仅KP】两段，让模型明确边界；
  公开叙事里出现守秘内容由 AUTO_PROTOCOL 铁律 + keeper.filter_final_visibility
  兜底（后者用 module_keeper_markers 把模组的守秘字段也纳入过滤标记）。
"""
from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from app.models import ModuleScenario, Room

# 回退骨架（4.1 临时方案）的路径与上限
_SCENARIO_PATH = Path(__file__).resolve().parents[2] / 'data' / 'scenario_brief.txt'
_SCENARIO_MAX_CHARS = 4000

# 结构化模组骨架的字符上限：比单文件方案放宽（结构化内容密度更高），
# 但仍要压住 token——超出部分按优先级截断并留提示
MODULE_BRIEF_MAX_CHARS = 8000

# 逐字段裁剪上限（实测：真实模组的单字段常写 300+ 字，不裁剪会在 6 个 NPC
# 处就把预算吃光，导致时钟/结局/检定段整段丢失）
_FIELD_LIMITS = {
    'background': 700,
    'act_summary': 220,
    'npc_field': 150,
    'clue': 150,
    'ending': 150,
    'clock_note': 120,
    'check_stake': 120,
    'warning': 120,
}

_TRUNCATED_NOTE = '（模组骨架过长，已按优先级截断；完整内容见模组库）'


def _clip(text: str, limit: int) -> str:
    """把单字段裁到 limit 字并补省略号（保信息密度，防个别长字段吃掉整段预算）。"""
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def _load_scenario_brief() -> str | None:
    """回退骨架：backend/data/scenario_brief.txt 存在即整体注入（≤4000 字）。"""
    try:
        text = _SCENARIO_PATH.read_text(encoding='utf-8').strip()
    except OSError:
        return None
    return text[:_SCENARIO_MAX_CHARS] or None


def module_review_digest(session: Session, room_id: str) -> str:
    """审卡用的**公开层**模组摘要（2026-09-10 用户反馈 #5）。

    与 load_module_brief 的区别：这里只取"判断玩家物品/技能是否契合"所需的公开设定
    （标题/基调/背景/时代线索/分幕标题/NPC 公开身份），**不注入守秘字段**——
    检卡结论只给 KP 看，没必要把隐藏动机带进来，也避免污染建议文本。
    """
    room = session.get(Room, room_id)
    if not room or not room.module_id:
        return ''
    module = session.get(ModuleScenario, room.module_id)
    if not module or module.parse_status != 'ready' or not module.parsed:
        return ''
    parsed = module.parsed

    parts: list[str] = [f"模组：{parsed.get('title') or module.name}"]
    if parsed.get('tone'):
        parts.append(f"基调：{parsed['tone']}")
    if parsed.get('background'):
        parts.append(f"背景：{_clip(parsed['background'], _FIELD_LIMITS['background'])}")
    if parsed.get('hook'):
        parts.append(f"开场钩子：{_clip(parsed['hook'], _FIELD_LIMITS['clue'])}")

    acts = [a for a in (parsed.get('acts') or []) if isinstance(a, dict)]
    if acts:
        titles = '；'.join(
            f"{a.get('order', i + 1)}. {a.get('title', '')}" for i, a in enumerate(acts)
        )
        parts.append(f'分幕：{titles}')

    npcs = [n for n in (parsed.get('npcs') or []) if isinstance(n, dict)]
    if npcs:
        # 只给公开身份（隐藏动机属守秘字段，不进审卡上下文）
        who = '；'.join(
            f"{n.get('name', '?')}（{_clip(n.get('public_identity', ''), 40) or '身份未明'}）"
            for n in npcs[:8]
        )
        parts.append(f'NPC（公开身份）：{who}')

    clocks = [c for c in (parsed.get('clocks') or []) if isinstance(c, dict)]
    if clocks:
        names = '；'.join(str(c.get('name', '')) for c in clocks[:4] if c.get('name'))
        if names:
            parts.append(f'威胁时钟：{names}')

    return '\n'.join(parts)


def load_module_brief(session: Session, room_id: str) -> str | None:
    """房间的模组骨架：挂载且已解析 → 结构化渲染；否则回退单文件骨架。"""
    room = session.get(Room, room_id)
    module = session.get(ModuleScenario, room.module_id) if room and room.module_id else None
    if module and module.parse_status == 'ready' and module.parsed:
        rendered = render_module_brief(module.parsed)
        if rendered:
            return rendered
    return _load_scenario_brief()


def _section(lines: list[str], title: str, body: list[str]) -> None:
    """按「标题 + 若干行」追加一段（空段落直接跳过，不留空标题）。"""
    body = [line for line in body if line and line.strip()]
    if not body:
        return
    lines.append(f'【{title}】')
    lines.extend(body)
    lines.append('')


def _npc_lines(npcs: list[dict]) -> list[str]:
    out: list[str] = []
    limit = _FIELD_LIMITS['npc_field']
    for npc in npcs:
        name = (npc.get('name') or '?').strip()
        identity = _clip(npc.get('public_identity') or '', limit)
        out.append(f'- {name}（公开身份：{identity or "未明"}）')
        for label, key in (('隐藏动机', 'hidden_motive'), ('误导', 'misdirection'),
                           ('被逼问', 'pressed_reaction'), ('离场方案', 'exit_plan'),
                           ('玩家可得线索', 'player_clues')):
            value = _clip(npc.get(key) or '', limit)
            if value:
                out.append(f'  {label}：{value}')
        stats = npc.get('stats') or {}
        if stats:
            out.append(f'  原文数值：{stats}')
    return out


def render_module_brief(parsed: dict, *, max_chars: int = MODULE_BRIEF_MAX_CHARS) -> str:
    """把结构化模组渲染成注入用骨架文本（公开层在前，守秘层在后）。

    按优先级顺序拼接：公开层 → 真相 → NPC → 分幕守秘目标 → 线索 → 时钟 →
    结局 → 关键检定 → 存疑提示。超预算时后面的段落被丢弃（并在末尾留提示），
    因此最重要的信息一定进得去。
    """
    if not isinstance(parsed, dict):
        return ''
    # 空壳（只有 warnings 之类）视为没有骨架：返回空串让调用方回退单文件方案，
    # 而不是往提示词里塞两个空段落
    has_content = any(
        parsed.get(key) for key in
        ('title', 'tone', 'hook', 'background',
         'acts', 'npcs', 'clues', 'clocks', 'endings', 'key_checks')
    )
    if not has_content:
        return ''

    lines: list[str] = ['【模组骨架·公开层】（可写进玩家可见叙事，但仍需按剧情节奏逐步展开）']
    if parsed.get('title'):
        lines.append(f"模组：{parsed['title']}")
    if parsed.get('tone'):
        lines.append(f"基调：{parsed['tone']}")
    if parsed.get('hook'):
        lines.append(f"开场钩子：{_clip(parsed['hook'], _FIELD_LIMITS['clue'] * 2)}")
    for act in parsed.get('acts') or []:
        head = f"第{act.get('order', '?')}幕「{act.get('title', '')}」"
        summary = _clip(act.get('summary') or '', _FIELD_LIMITS['act_summary'])
        if summary:
            head += f"：{summary}"
        lines.append(f'- {head}')
        if act.get('public_goal'):
            lines.append(f"  玩家可见目标：{_clip(act['public_goal'], _FIELD_LIMITS['act_summary'])}")
        if act.get('key_clues'):
            lines.append(f"  关键线索：{_clip(act['key_clues'], _FIELD_LIMITS['act_summary'])}")
    lines.append('')

    lines.append('【模组骨架·仅KP】（绝对不得出现在公开叙事或行动选项中）')
    if parsed.get('background'):
        lines.append(f"真相与背景：{_clip(parsed['background'], _FIELD_LIMITS['background'])}")
    lines.append('')

    public_clues = [c for c in (parsed.get('clues') or []) if c.get('visibility') == 'public']
    keeper_clues = [c for c in (parsed.get('clues') or []) if c.get('visibility') != 'public']

    def _clue_lines(items: list[dict]) -> list[str]:
        return [
            f"- {_clip(c.get('content') or '', _FIELD_LIMITS['clue'])}"
            + (f"（指向：{_clip(c['points_to'], 60)}）" if c.get('points_to') else '')
            for c in items
        ]

    # 段落顺序 = 截断优先级：主持时最需要的东西排在前面。
    # 实测教训：把 NPC 档案（字段最多最长）放在时钟/结局/检定之前，
    # 真实模组会在 NPC 段就吃光预算，导致时钟与检定整段丢失。
    sections: list[tuple[str, list[str]]] = [
        ('威胁时钟（推进到满格必须兑现后果）',
         [f"- {ck.get('name', '')} {ck.get('target', '?')} 格"
          + (f"（走满后果：{_clip(ck['note'], _FIELD_LIMITS['clock_note'])}）" if ck.get('note') else '')
          for ck in parsed.get('clocks') or []]),
        ('结局与收束条件',
         [f"- {e.get('name', '')}：{_clip(e.get('condition') or '', _FIELD_LIMITS['ending'])}"
          for e in parsed.get('endings') or []]),
        ('关键检定（AI 应优先用 request_check 下放这些检定）',
         [f"- {c.get('skill', '')}·{c.get('difficulty', 'standard')}"
          + (f"（{_clip(c['scene'], 30)}）" if c.get('scene') else '')
          + (f" 失败后果：{_clip(c['stake'], _FIELD_LIMITS['check_stake'])}" if c.get('stake') else '')
          for c in parsed.get('key_checks') or []]),
        ('NPC 档案（守秘字段仅 KP 可见）', _npc_lines(parsed.get('npcs') or [])),
        ('线索（玩家可获得）', _clue_lines(public_clues)),
        ('线索（仅 KP 知晓）', _clue_lines(keeper_clues)),
        ('各幕守秘目标',
         [f"第{act.get('order', '?')}幕「{act.get('title', '')}」："
          f"{_clip(act['keeper_goal'], _FIELD_LIMITS['act_summary'])}"
          for act in parsed.get('acts') or [] if act.get('keeper_goal')]),
        ('解析存疑项（模组抽取不确定处，KP 可自行裁定）',
         [f"- {_clip(w, _FIELD_LIMITS['warning'])}" for w in parsed.get('warnings') or []]),
    ]

    budget = max(500, max_chars)
    truncated = False
    for title, body in sections:
        chunk = f'【{title}】\n' + '\n'.join(body) + '\n\n'
        if sum(len(line) + 1 for line in lines) + len(chunk) > budget:
            truncated = True
            continue
        _section(lines, title, body)

    text = '\n'.join(lines).strip()
    if truncated:
        text += f'\n\n{_TRUNCATED_NOTE}'
    return text[: max(budget, 1) + len(_TRUNCATED_NOTE) + 4]


def module_echo(session: Session, room: Room) -> dict | None:
    """房间当前模组的轻量回显（KP 台面板回显用）：id + 名称 + 解析状态。

    与 kp_styles.style_echo 同款：REST 详情与广播 payload 共用同一份结构，
    避免两处手拼字段漂移。
    """
    if not room or not room.module_id:
        return None
    module = session.get(ModuleScenario, room.module_id)
    if not module:
        return None
    return {
        'module_id': module.id,
        'module_name': module.name,
        'parse_status': module.parse_status,
    }


def module_keeper_markers(session: Session, room_id: str) -> list[str]:
    """房间挂载模组里的守秘片段（供 filter_final_visibility 做系统级过滤）。

    只取"成句"的守秘描述（≥8 字）作为标记：短词（如 NPC 名、模组名）
    在公开叙事里出现是正常的，误伤会把叙事打得到处是占位符。
    """
    room = session.get(Room, room_id)
    module = session.get(ModuleScenario, room.module_id) if room and room.module_id else None
    if not (module and module.parse_status == 'ready' and module.parsed):
        return []
    parsed = module.parsed

    markers: list[str] = []
    for npc in parsed.get('npcs') or []:
        for key in ('hidden_motive', 'misdirection', 'pressed_reaction', 'exit_plan'):
            value = (npc.get(key) or '').strip()
            if len(value) >= 8:
                markers.append(value)
    for ending in parsed.get('endings') or []:
        value = (ending.get('condition') or '').strip()
        if len(value) >= 8:
            markers.append(value)
    for clock in parsed.get('clocks') or []:
        value = (clock.get('note') or '').strip()
        if len(value) >= 8:
            markers.append(value)
    for clue in parsed.get('clues') or []:
        if clue.get('visibility') == 'keeper':
            value = (clue.get('content') or '').strip()
            if len(value) >= 8:
                markers.append(value)
    return markers
