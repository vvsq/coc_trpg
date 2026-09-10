"""提示词组装器与输出解析单元测试 — L1 基座 + L5 会话窗口（阶段 4.1）。

纯函数测试，无 DB / 无网络。
"""
import pytest

from app.agent.assembler import (
    SESSION_WINDOW_SIZE,
    SuggestionContext,
    build_suggestion_messages,
    parse_suggestions,
)
from app.agent.prompts.l1_base import PROMPT_VERSION


def _ctx(**kwargs) -> SuggestionContext:
    defaults = dict(
        room_name='雾都疑云',
        scene_title='码头仓库 · 深夜',
        scene_desc='雨下个不停',
        investigators=[
            {'name': '张三', 'occupation': '会计师', 'hp': 9, 'hp_max': 12, 'san': 42, 'san_max': 50},
        ],
        session_window=[
            {'sender': 'KP老王', 'role': 'kp', 'text': '仓库门吱呀打开。'},
            {'sender': '张三', 'role': 'player', 'text': '我举灯照向角落。'},
        ],
        latest_action='我举灯照向角落。',
        focus='偏悬疑',
    )
    defaults.update(kwargs)
    return SuggestionContext(**defaults)


# ---------- build_suggestion_messages ----------

def test_messages_structure_and_layers():
    msgs = build_suggestion_messages(_ctx())
    assert [m['role'] for m in msgs] == ['system', 'user']
    system, user = msgs[0]['content'], msgs[1]['content']
    # L1 基座：版本号 + 输出协议 + 检定速查都在 system
    assert PROMPT_VERSION in system
    assert '输出协议' in system and 'check_hint' in system
    assert '孤注一掷' in system  # CoC7 规则速查已注入
    # user 上下文：场景 / 调查员 / 窗口 / focus / 最新行动
    assert '码头仓库 · 深夜' in user
    assert '张三（会计师）HP 9/12' in user
    assert '[KP·KP老王] 仓库门吱呀打开。' in user
    assert '【KP 附加指令】偏悬疑' in user
    assert '【最新剧情推进】我举灯照向角落。' in user


def test_session_window_truncated_to_last_n():
    rows = [{'sender': f'p{i}', 'role': 'player', 'text': f'行动{i}'} for i in range(SESSION_WINDOW_SIZE + 5)]
    user = build_suggestion_messages(_ctx(session_window=rows))[1]['content']
    assert '行动0' not in user  # 旧消息被窗口截掉
    assert f"行动{SESSION_WINDOW_SIZE + 4}" in user  # 最新一条保留
    assert user.count('[p') == SESSION_WINDOW_SIZE


def test_investigator_line_shows_player_name_when_it_differs_from_card_name():
    """4.4 实测修复：工具 target 只认玩家昵称（room_member.player_name）。

    昵称 ≠ 卡名时必须两个都进提示词，且**昵称在括号外**（LLM 照抄那个当 target），
    卡名放括号内做对照——否则 AI 会拿卡名当 target，request_check 直接报「不在房间内」。
    """
    ctx = _ctx(investigators=[
        {'name': 'test', 'player_name': '玩家甲', 'occupation': '拳击手',
         'hp': 8, 'hp_max': 12, 'san': 31, 'san_max': 35},
    ])
    user = build_suggestion_messages(ctx)[1]['content']
    assert '玩家甲（拳击手｜角色名 test）' in user


def test_investigator_line_falls_back_when_player_name_absent():
    """旧上下文（无 player_name）渲染不炸，退化为只显示角色名（兼容既有调用）。"""
    user = build_suggestion_messages(_ctx())[1]['content']
    assert '张三（会计师）HP 9/12' in user
    assert '角色名' not in user


def test_auto_bp3_investigator_line_carries_player_name_and_target_hint():
    """全自动 BP3 同一渲染 + 明确写出「target 必须填玩家昵称」。"""
    from app.agent.assembler import AutoContext, build_auto_messages

    ctx = AutoContext(investigators=[
        {'name': 'test', 'player_name': '玩家甲', 'occupation': '拳击手',
         'hp': 8, 'hp_max': 12, 'san': 31, 'san_max': 35, 'skills': {'侦查': 95}},
    ])
    turn = next(m['content'] for m in build_auto_messages(ctx) if m['content'].startswith('[本回合]'))
    assert '玩家甲（拳击手｜角色名 test）' in turn
    assert '技能：侦查 95' in turn
    assert 'target 必须填它' in turn


def test_optional_layers_skipped_when_none():
    """L2/L3/L4 与可空段落为 None/空时不留空标题（下层不重复上层内容）。"""
    bare = _ctx(
        room_name='', scene_title='', scene_desc='', investigators=[],
        session_window=[], latest_action='', focus='',
    )
    user = build_suggestion_messages(bare)[1]['content']
    assert '【在场调查员】' not in user
    assert '【近期剧情】' not in user
    assert '【KP 附加指令】' not in user
    assert '【当前场景】（未设置）' in user
    # L2/L3/L4 预留字段注入
    styled = _ctx(style='叙事密度：高', scenario='模组骨架文本', card_detail='背景钩子')
    user2 = build_suggestion_messages(styled)
    assert '当前 KP 风格' in user2[0]['content']
    assert '模组骨架文本' in user2[1]['content'] and '背景钩子' in user2[1]['content']


# ---------- parse_suggestions：容错解析 ----------

def test_parse_plain_and_fenced_json():
    body = '{"suggestions": [{"text": "推进一", "check_hint": null}, {"text": "推进二", "check_hint": {"skill": "侦查", "difficulty": "hard", "stake": "惊动守夜人"}}]}'
    assert parse_suggestions(body) == [
        {'text': '推进一', 'check_hint': None},
        {'text': '推进二', 'check_hint': {'skill': '侦查', 'difficulty': 'hard', 'stake': '惊动守夜人'}},
    ]
    fenced = f'好的，以下是建议：\n```json\n{body}\n```\n'
    assert len(parse_suggestions(fenced)) == 2  # 围栏 + 前后缀都能剥掉


def test_parse_normalizes_bad_items():
    raw = (
        '{"suggestions": ['
        '{"text": "", "check_hint": null},'  # 空文本 → 丢弃
        '{"text": "缺 skill 的 hint", "check_hint": {"difficulty": "hard"}},'  # hint 置 null
        '{"text": "非法难度回退", "check_hint": {"skill": "图书馆使用", "difficulty": "疯狂", "stake": "x"}},'
        '{"text": "' + '超长' * 250 + '", "check_hint": null}'  # 500 字 → 截断 400
        ']}'
    )
    out = parse_suggestions(raw)
    assert len(out) == 3
    assert out[0]['check_hint'] is None
    assert out[1]['check_hint'] == {'skill': '图书馆使用', 'difficulty': 'standard', 'stake': 'x'}
    assert len(out[2]['text']) == 400


def test_parse_caps_at_three():
    items = ''.join(f'{{"text": "建议{i}", "check_hint": null}},' for i in range(6))
    assert len(parse_suggestions('{"suggestions": [' + items.rstrip(',') + ']}')) == 3


@pytest.mark.parametrize(
    'raw',
    [
        '完全不是 JSON 的一段话',
        '{"other": 1}',  # 缺 suggestions
        '{"suggestions": []}',  # 空列表
        '{"suggestions": [{"text": ""}]}',  # 全部无效
    ],
)
def test_parse_rejects_garbage(raw: str):
    with pytest.raises(ValueError):
        parse_suggestions(raw)
