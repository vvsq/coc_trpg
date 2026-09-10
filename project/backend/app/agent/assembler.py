"""最小提示词组装器 — 阶段 4.1：L1 基座 + L5 会话滚动窗口（goal §6.1）。

独立模块的用意（§6.1）：同一份记忆与状态可服务协同/全自动两种模式，
且便于离线回归测试提示词效果。L2 风格 / L3 剧情 / L4 状态层以可选字段
预留（4.3/4.4 落地），为 None 时组装直接跳过该层，不重复上层内容。
"""
from dataclasses import dataclass, field
import json
import re

from app.agent.prompts.l1_base import (
    AUTO_PROMPT_VERSION,
    AUTO_PROTOCOL,
    PROMPT_VERSION,
    SUGGESTION_PROTOCOL,
)

# L5 会话滚动窗口大小（条数）
SESSION_WINDOW_SIZE = 20

# 单条剧情文本截断长度，防个别超长消息挤爆窗口
_LINE_MAX = 200

_FENCE_RE = re.compile(r'^\s*```[a-zA-Z0-9]*\s*|\s*```\s*$')
# LLM 最常见的 JSON 小错：数组/对象末尾多逗号，解析前先剥掉
_TRAILING_COMMA_RE = re.compile(r',\s*(?=[}\]])')

_VALID_DIFFICULTIES = {'standard', 'hard', 'extreme'}


def _investigator_line(p: dict) -> str:
    """【在场调查员】的单行渲染（协同/全自动共用，防两处格式漂移）。

    4.4 实测修复：工具 target（request_check / san_check / update_status /
    get_card）查的是 `room_member.player_name`（花名册昵称），不是角色卡名。
    因此玩家昵称与角色名不同时两个都要喂给 LLM，且昵称必须放在括号外——
    否则 AI 只会照抄卡名当 target，工具端报「「test」不在房间内」。
    """
    card_name = str(p.get('name') or '?')
    player_name = str(p.get('player_name') or '').strip()
    occupation = p.get('occupation', '?')
    if player_name and player_name != card_name:
        who = f'{player_name}（{occupation}｜角色名 {card_name}）'
    else:
        who = f'{card_name}（{occupation}）'
    line = (f"- {who}"
            f"HP {p.get('hp', '?')}/{p.get('hp_max', '?')}，"
            f"SAN {p.get('san', '?')}/{p.get('san_max', '?')}")
    skills = p.get('skills') or {}
    if skills:
        skill_text = '，'.join(f'{k} {v}' for k, v in list(skills.items())[:30])
        line += f'\n  技能：{skill_text}'
    return line


@dataclass
class SuggestionContext:
    """协同建议的输入上下文。字段均可缺省，组装时空段落自动跳过。"""

    room_name: str = ''
    scene_title: str = ''
    scene_desc: str = ''
    # [{name(角色名), player_name(花名册昵称), occupation, hp, hp_max, san, san_max}]
    # L4 的轻量版（只取存活必需项）；player_name 缺失时渲染退化为只显示角色名
    investigators: list[dict] = field(default_factory=list)
    # L5 会话窗口：[{sender, role, text}]，时间升序（旧 → 新）
    session_window: list[dict] = field(default_factory=list)
    latest_action: str = ''  # 触发本次生成的玩家行动原文
    focus: str = ''  # KP 附加指令（如「偏向悬疑」「避免战斗」）
    # ── 为 4.3/4.4 五层全量预留 ──
    style: str | None = None        # L2：KP 风格参数 → 叙事指令
    scenario: str | None = None     # L3：模组结构化骨架 + 剧情记忆快照
    card_detail: str | None = None  # L4：调查员卡细节（背景钩子等）


def build_suggestion_messages(ctx: SuggestionContext) -> list[dict]:
    """组装 chat.completions 的 messages：system = L1（+L2 若有），user = 上下文。"""
    system = f'[提示词版本 {PROMPT_VERSION}]\n{SUGGESTION_PROTOCOL}'
    if ctx.style:
        system += f'\n\n# 当前 KP 风格\n{ctx.style}'

    sections: list[str] = []
    if ctx.room_name:
        sections.append(f'【房间】{ctx.room_name}')
    scene = ctx.scene_title or '（未设置）'
    if ctx.scene_desc:
        scene += f' — {ctx.scene_desc}'
    sections.append(f'【当前场景】{scene}')

    if ctx.investigators:
        lines = [_investigator_line(p) for p in ctx.investigators]
        sections.append('【在场调查员】\n' + '\n'.join(lines))
    if ctx.card_detail:
        sections.append(f'【调查员背景】\n{ctx.card_detail}')
    if ctx.scenario:
        sections.append(f'【模组骨架】\n{ctx.scenario}')

    if ctx.session_window:
        lines = []
        for m in ctx.session_window[-SESSION_WINDOW_SIZE:]:
            sender = m.get('sender') or '?'
            role = m.get('role')
            label = f'KP·{sender}' if role == 'kp' else sender
            text = (m.get('text') or '').strip()[:_LINE_MAX]
            lines.append(f'[{label}] {text}')
        sections.append('【近期剧情】（旧 → 新）\n' + '\n'.join(lines))

    if ctx.focus:
        sections.append(f'【KP 附加指令】{ctx.focus}')
    if ctx.latest_action:
        sections.append(f'【最新剧情推进】{ctx.latest_action[:_LINE_MAX]}')

    sections.append(
        '请基于以上信息生成 2~3 条剧情推进建议。建议必须描写【最新玩家行动】发生之后'
        '的当下场景与后果，禁止回溯或重复更早的情节（此前剧情只作为因果背景）。'
    )
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': '\n\n'.join(sections)},
    ]


def parse_suggestions(raw: str) -> list[dict]:
    """解析 LLM 输出为建议列表，返回 [{text, check_hint}]；解析不出或全无效抛 ValueError。

    容错策略：剥离 markdown 围栏 → 截取首个 { 到最后一个 } → json.loads；
    单条建议字段非法时降级（check_hint 置 null），不整批作废。
    """
    text = _FENCE_RE.sub('', raw or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ValueError('LLM 输出中未找到 JSON 对象')
    try:
        data = json.loads(_TRAILING_COMMA_RE.sub('', text[start:end + 1]))
    except json.JSONDecodeError as exc:
        raise ValueError(f'LLM 输出不是合法 JSON：{exc}') from exc

    items = data.get('suggestions') if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError('LLM 输出缺少 suggestions 数组')

    parsed: list[dict] = []
    for item in items[:5]:  # 上限 5，超出忽略；有效条目最终再截到 3
        if not isinstance(item, dict):
            continue
        body = (item.get('text') or '').strip()
        if not body:
            continue
        parsed.append({'text': body[:400], 'check_hint': _normalize_hint(item.get('check_hint'))})
    if not parsed:
        raise ValueError('LLM 未返回任何有效建议')
    return parsed[:3]


def _normalize_hint(hint) -> dict | None:
    """check_hint 字段规整：缺 skill 直接判 null，difficulty 非法回退 standard。"""
    if not isinstance(hint, dict):
        return None
    skill = (hint.get('skill') or '').strip()
    if not skill:
        return None
    difficulty = (hint.get('difficulty') or 'standard').strip()
    if difficulty not in _VALID_DIFFICULTIES:
        difficulty = 'standard'
    # LLM 有时把"失败则"写进 stake，前端展示会带同款前缀，此处剥掉防重复
    stake = (hint.get('stake') or '').strip()
    for prefix in ('失败则', '失败时', '失败：', '失败:'):
        if stake.startswith(prefix):
            stake = stake[len(prefix):].lstrip('，,、 ')
            break
    return {
        'skill': skill[:50],
        'difficulty': difficulty,
        'stake': stake[:100],
    }


# ==================== 全自动主持（4.2）：缓存感知组装 + 终稿解析 ====================

@dataclass
class AutoContext:
    """全自动主持的输入上下文（goal §6.1 BP1/BP2/BP3 映射）。

    BP1 = L1 基座（AUTO_PROTOCOL，字节稳定）
    BP2 = 模组骨架 + 场景信息（低频变化：只在 set_scene 时变 → 前置 user 稳定）
    BP3 = 事件登记 + 调查员状态 + 会话窗口 + 最新行动（每轮变化 → 尾部 user）
    """

    room_name: str = ''
    scene_title: str = ''
    scene_desc: str = ''
    style: str | None = None             # BP2：L2 KP 风格指令（4.4，切换时作废 BP2 缓存）
    scenario: str | None = None          # BP2：模组骨架（scenario_brief / 阶段 5 模组库）
    # ── BP2：剧情记忆五要素（4.3，goal §6.5/§6.6）——KP 全知视角注入，
    # 公开叙事中的 keeper 片段由 keeper.filter_final_visibility 兜底摘除 ──
    clues: list[str] = field(default_factory=list)     # 线索行（含编号/可见性/状态）
    clocks: list[str] = field(default_factory=list)    # 威胁时钟行
    threads: list[str] = field(default_factory=list)   # 未结算伏笔行
    npcs: list[str] = field(default_factory=list)      # NPC 档案行（六要素压缩）
    scene_summaries: list[str] = field(default_factory=list)  # 此前场景的公开摘要
    events: list[str] = field(default_factory=list)   # BP3：record_events 滚动登记（最近 10 条）
    # L4：[{name(角色名), player_name(花名册昵称), occupation, hp, hp_max, san,
    #      san_max, skills: {技能名: 值}}]（BP3）；工具 target 只认 player_name
    investigators: list[dict] = field(default_factory=list)
    # L5 会话窗口：[{sender, role, text}]，时间升序（旧 → 新）
    session_window: list[dict] = field(default_factory=list)
    latest_action: str = ''              # 触发本轮的行动原文
    focus: str = ''                      # KP 插话/附加指令


_ANCHOR_MEMORY = '已掌握剧情记忆与模组基调。'
_ANCHOR_TURN = '了解。我将按协议推进本轮剧情。'


def build_auto_messages(ctx: AutoContext) -> list[dict]:
    """按缓存感知三段式组装 messages（借鉴 AiChatTrpg CachedPrompt，goal §6.1 增补）。

      system            = BP1（字节稳定，跨回合命中缓存）
      user  [剧情记忆]   = BP2（记忆/场景不变时字节稳定）→ assistant 锚定划界
      user  [本回合]     = BP3（每轮变化）→ assistant 锚定 → 最终 user 指令

    取舍：record_events 的滚动事件每轮变化，故放 BP3 而非 BP2——4.3 场景级
    摘要落地后事件快照转为低频更新，再并入 BP2 提升缓存命中率。
    """
    system = f'[提示词版本 {AUTO_PROMPT_VERSION}]\n{AUTO_PROTOCOL}'

    # ---- BP2：剧情记忆（模组骨架 + 场景 + 记忆五要素） ----
    memory_sections: list[str] = []
    if ctx.style:
        # L2 风格放 BP2 而非 system（BP1）：风格可切，放 system 会作废跨回合字节稳定的 BP1
        memory_sections.append(f'【KP 风格】\n{ctx.style}')
    if ctx.scenario:
        memory_sections.append(f'【模组骨架】\n{ctx.scenario}')
    scene = ctx.scene_title or '（未设置）'
    if ctx.scene_desc:
        scene += f' — {ctx.scene_desc}'
    memory_sections.append(f'【当前场景】{scene}')
    memory_sections.append(f'【房间】{ctx.room_name or "（未命名）"}')

    if ctx.scene_summaries:
        memory_sections.append('【此前场景摘要】（旧 → 新，公开版）\n'
                               + '\n'.join(f'- {s}' for s in ctx.scene_summaries[-5:]))
    if ctx.clues:
        memory_sections.append('【线索档案】（编号 · 可见性 · 验证状态；引用编号时遵守可见性）\n'
                               + '\n'.join(f'- {c}' for c in ctx.clues))
    if ctx.clocks:
        memory_sections.append('【威胁时钟】\n' + '\n'.join(f'- {c}' for c in ctx.clocks))
    if ctx.threads:
        memory_sections.append('【未结算伏笔】（仅 KP 可知，公开叙事禁止提及）\n'
                               + '\n'.join(f'- {t}' for t in ctx.threads))
    if ctx.npcs:
        memory_sections.append('【NPC 档案】（动机/误导/逼问反应仅 KP 可知）\n'
                               + '\n'.join(f'- {n}' for n in ctx.npcs))

    # ---- BP3：本回合上下文 ----
    turn_sections: list[str] = []
    if ctx.events:
        lines = '\n'.join(f'- {e}' for e in ctx.events[-10:])
        turn_sections.append(f'【已登记关键事件】（旧 → 新）\n{lines}')

    if ctx.investigators:
        lines = [_investigator_line(p) for p in ctx.investigators]
        turn_sections.append(
            '【在场调查员】（括号外是**玩家昵称**——request_check / san_check / '
            'update_status / get_card 的 target 必须填它，填角色卡名会被拒；'
            '技能值拿不准先 get_card 查）\n' + '\n'.join(lines))

    if ctx.session_window:
        lines = []
        for m in ctx.session_window[-SESSION_WINDOW_SIZE:]:
            sender = m.get('sender') or '?'
            role = m.get('role')
            label = f'KP·{sender}' if role == 'kp' else sender
            text = (m.get('text') or '').strip()[:_LINE_MAX]
            lines.append(f'[{label}] {text}')
        turn_sections.append('【近期剧情】（旧 → 新）\n' + '\n'.join(lines))

    if ctx.focus:
        turn_sections.append(f'【KP 插话/指令】{ctx.focus}')
    if ctx.latest_action:
        turn_sections.append(f'【最新剧情推进】{ctx.latest_action[:_LINE_MAX]}')

    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': '[剧情记忆]\n' + '\n\n'.join(memory_sections)},
        {'role': 'assistant', 'content': _ANCHOR_MEMORY},
        {'role': 'user', 'content': '[本回合]\n' + '\n\n'.join(turn_sections)},
        {'role': 'assistant', 'content': _ANCHOR_TURN},
        {'role': 'user', 'content':
            '请推进本轮剧情：需要检定/数值变更时先叙事铺垫再调用工具；'
            '全部工具结束后，按最终输出协议只输出一个 JSON 终稿。'},
    ]


def parse_auto_turn(raw: str) -> dict:
    """解析全自动终稿 JSON → {narration_public, keeper_notes, options}；非法抛 ValueError。

    容错与 parse_suggestions 同款：剥围栏 → 截 JSON → 剥尾逗号。
    """
    text = _FENCE_RE.sub('', raw or '').strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ValueError('LLM 终稿中未找到 JSON 对象')
    try:
        data = json.loads(_TRAILING_COMMA_RE.sub('', text[start:end + 1]))
    except json.JSONDecodeError as exc:
        raise ValueError(f'LLM 终稿不是合法 JSON：{exc}') from exc
    if not isinstance(data, dict):
        raise ValueError('LLM 终稿必须是 JSON 对象')

    narration = (data.get('narration_public') or '').strip()
    if not narration:
        raise ValueError('LLM 终稿缺少 narration_public')
    keeper = (data.get('keeper_notes') or '').strip()

    options: list[str] = []
    raw_options = data.get('options')
    if isinstance(raw_options, list):
        for opt in raw_options[:4]:
            text_opt = str(opt).strip()[:100]
            if text_opt:
                options.append(text_opt)
    if len(options) < 2:
        raise ValueError('LLM 终稿的 options 少于 2 条')

    return {'narration_public': narration[:2000], 'keeper_notes': keeper[:1500], 'options': options}
