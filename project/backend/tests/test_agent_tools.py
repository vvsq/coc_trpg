"""LLM 工具集执行测试（4.2）：每个工具的落库 / 广播 payload / 错误回喂。

execute_tool 用模块全局 engine（与 WS 层同款「现场开 Session」），测试用
monkeypatch 换 tmp 引擎；理智检定的随机性通过替换 coc7_check / roll_loss
固定，疯狂判定替换 determine_madness 固定。广播在无连接时是安全空操作。
"""
import asyncio
import json

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401  确保全部 table=True 模型注册进 metadata
import app.agent.tools as tools_mod
from app.agent.tools import execute_tool
from app.models import Card, Message, Room, RoomMember, ScenarioState, save_card
from app.rules.dice import D100Roll


@pytest.fixture()
def env(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", connect_args={'check_same_thread': False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(tools_mod, 'engine', test_engine)
    with Session(test_engine) as s:
        room = Room(name='雾都疑云', kp_name='老周')
        s.add(room)
        card = Card(owner='张三')
        save_card(card, {
            'name': '张三', 'occupation': '会计师',
            'attributes': {'STR': 50, 'INT': 65, 'POW': 60},
            'derived': {'HP': 11, 'SAN': 60},
            'state': {'current_hp': 11, 'current_sanity': 60},
            'skills': [
                {'name': '侦查', 'slot': 0, 'detail': '', 'base': 25,
                 'occupation_points': 25, 'interest_points': 0},
                {'name': '图书馆使用', 'slot': 0, 'detail': '', 'base': 20,
                 'occupation_points': 35, 'interest_points': 0},
            ],
        })
        s.add(card)
        s.commit()
        s.refresh(room)
        s.refresh(card)
        s.add(RoomMember(room_id=room.id, player_name='张三', role='player', card_id=card.id))
        s.commit()
        rid = room.id
    yield test_engine, rid


def _msgs(engine, rid) -> list[Message]:
    with Session(engine) as s:
        return list(s.exec(select(Message).where(Message.room_id == rid)).all())


def _card_state(engine, rid):
    with Session(engine) as s:
        member = s.exec(select(RoomMember).where(RoomMember.room_id == rid)).first()
        card = s.get(Card, member.card_id)
        return card.card_data['state']


# ---------- roll_check ----------

def test_roll_check_ok_and_persisted(env):
    engine, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_check', {
        'skill_name': '守夜人的耳目', 'value': 50, 'difficulty': 'hard',
        'reason': 'NPC 察觉动静',
    }, rid)))
    assert 1 <= out['roll'] <= 100
    assert out['target'] == 25  # 50 的困难目标
    assert out['level_label'] in {'大成功', '极难成功', '困难成功', '常规成功', '失败', '大失败'}
    dice = [m for m in _msgs(engine, rid) if m.type == 'dice']
    assert len(dice) == 1
    assert dice[0].payload['skill_name'] == '守夜人的耳目' and dice[0].payload['secret'] is False


def test_roll_check_bad_difficulty_returns_error(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_check', {
        'skill_name': '侦查', 'value': 50, 'difficulty': 'super', 'reason': 'x',
    }, rid)))
    assert 'error' in out and '难度' in out['error']


def test_roll_check_with_target_forbidden(env):
    """4.4 遗留修复：调查员检定禁止 AI 代掷——带 target 一律拦截，引导 request_check。"""
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_check', {
        'skill_name': '侦查', 'value': 50, 'difficulty': 'standard',
        'target': '张三', 'reason': 'x',
    }, rid)))
    assert 'error' in out and 'request_check' in out['error']
    # 不留任何骰子行
    engine, rid2 = env
    assert not [m for m in _msgs(engine, rid2) if m.type == 'dice']


# ---------- roll_dice / secret_roll ----------

def test_roll_dice_public(env):
    engine, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_dice', {'expr': '1D6', 'reason': '随机数量'}, rid)))
    assert 1 <= out['result'] <= 6
    texts = [m for m in _msgs(engine, rid) if m.type == 'text' and not m.secret]
    assert any('1D6' in m.content for m in texts)


def test_secret_roll_only_keeper(env):
    engine, rid = env
    out = json.loads(asyncio.run(execute_tool('secret_roll', {'expr': '1D100', 'reason': '是否惊动守夜人'}, rid)))
    assert out['secret'] is True and 1 <= out['result'] <= 100
    keeper_rows = [m for m in _msgs(engine, rid) if m.secret]
    assert len(keeper_rows) == 1
    assert keeper_rows[0].payload['keeper'] is True
    # 公开流里没有暗骰结果
    assert all(str(out['result']) not in m.content for m in _msgs(engine, rid) if not m.secret)


def test_roll_dice_bad_expr_returns_error(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_dice', {'expr': '2x+1', 'reason': 'x'}, rid)))
    assert 'error' in out


# ---------- san_check（固定随机） ----------

def _force_check(level: str, value: int):
    tens = value // 10
    units = value % 10
    return lambda *a, **k: (level, D100Roll(units=units, tens=[tens], value=value))


def test_san_check_fail_applies_loss_and_today_tracking(env, monkeypatch):
    engine, rid = env
    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('fail', 90))
    monkeypatch.setattr(tools_mod.sanity, 'roll_loss', lambda *a, **k: 3)
    out = json.loads(asyncio.run(execute_tool('san_check', {
        'target': '张三', 'loss_formula': '0/1D6', 'reason': '目睹尸体',
    }, rid)))
    assert out['success'] is False and out['loss'] == 3 and out['san_after'] == 57
    assert out['madness'] == '无疯狂发作'
    assert _card_state(engine, rid)['current_sanity'] == 57
    with Session(engine) as s:
        row = s.get(ScenarioState, rid)
        assert row.data['san_today']['loss']['张三'] == 3
        assert row.data['san_today']['date']  # 带日期标记（跨天清零依据）
    kinds = [(m.type, m.secret) for m in _msgs(engine, rid)]
    assert ('dice', False) in kinds and ('status', False) in kinds
    assert not any(sec for _, sec in kinds)  # 无疯狂 → 无 keeper 行


def test_san_check_fumble_takes_max_loss(env, monkeypatch):
    engine, rid = env
    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('fumble', 100))
    monkeypatch.setattr(tools_mod.sanity, 'roll_loss_max', lambda expr, rng=None: 6)
    out = json.loads(asyncio.run(execute_tool('san_check', {
        'target': '张三', 'loss_formula': '0/1D6', 'reason': '直面旧日支配者',
    }, rid)))
    assert out['loss'] == 6 and out['san_after'] == 54


def test_san_check_success_no_loss(env, monkeypatch):
    engine, rid = env
    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('regular', 30))
    out = json.loads(asyncio.run(execute_tool('san_check', {
        'target': '张三', 'loss_formula': '0/1D6', 'reason': '强作镇定',
    }, rid)))
    assert out['success'] is True and out['loss'] == 0 and out['san_after'] == 60
    assert _card_state(engine, rid)['current_sanity'] == 60


def test_san_check_madness_goes_keeper_channel(env, monkeypatch):
    from app.rules.sanity import MadnessResult

    engine, rid = env
    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('fail', 90))
    monkeypatch.setattr(tools_mod.sanity, 'roll_loss', lambda *a, **k: 5)

    def fake_madness(*a, **k):
        return MadnessResult(
            kind='temporary', symptom={'name': '失忆', 'desc': '只记得最后身处的安全地点',
                                       'phase': 'immediate', 'roll': 1, 'extra': ''},
        )

    monkeypatch.setattr(tools_mod.sanity, 'determine_madness', fake_madness)
    out = json.loads(asyncio.run(execute_tool('san_check', {
        'target': '张三', 'loss_formula': '1/1D6', 'reason': '看见不该看的',
    }, rid)))
    assert 'temporary疯狂' in out['madness'] or '临时疯狂' in out['madness'] or '疯狂' in out['madness']
    keeper_rows = [m for m in _msgs(engine, rid) if m.secret]
    assert len(keeper_rows) == 1 and '失忆' in keeper_rows[0].content


def test_san_check_bad_formula_returns_error(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('san_check', {
        'target': '张三', 'loss_formula': '1D6', 'reason': 'x',
    }, rid)))
    assert 'error' in out and '成功/失败' in out['error']


def test_san_today_resets_across_days(env, monkeypatch):
    """回归测试（跨天清零 bug）：昨日累计损失不得计入今天的疯狂判定。

    SAN 60 → 不定性阈值 60//5=12。预置昨天桶累计 12 点：若不清零，
    本次失败损失 3 点后 12+3≥12 会误触发不定性疯狂；清零后 0+3<12 无疯狂。
    """
    engine, rid = env
    with Session(engine) as s:
        row = tools_mod.get_scenario(s, rid)  # 惰性创建：先拿到/初始化状态行
        row.data = {**row.data,
                    'san_today': {'date': '2000-01-01', 'loss': {'张三': 12}}}
        s.add(row)
        s.commit()
    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('fail', 90))
    monkeypatch.setattr(tools_mod.sanity, 'roll_loss', lambda *a, **k: 3)
    out = json.loads(asyncio.run(execute_tool('san_check', {
        'target': '张三', 'loss_formula': '0/1D6', 'reason': '次日再遇恐怖',
    }, rid)))
    assert out['loss'] == 3 and out['madness'] == '无疯狂发作'
    with Session(engine) as s:
        row = s.get(ScenarioState, rid)
        assert row.data['san_today']['date'] != '2000-01-01'  # 已重置为今天
        assert row.data['san_today']['loss'] == {'张三': 3}   # 从零累计


def test_san_today_same_day_accumulates(env, monkeypatch):
    """同一天内多次损失正常累计（跨天清零不能误伤同日累计）。"""
    engine, rid = env
    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('fail', 90))
    monkeypatch.setattr(tools_mod.sanity, 'roll_loss', lambda *a, **k: 3)
    for _ in range(2):
        json.loads(asyncio.run(execute_tool('san_check', {
            'target': '张三', 'loss_formula': '0/1D6', 'reason': '连环惊吓',
        }, rid)))
    with Session(engine) as s:
        row = s.get(ScenarioState, rid)
        assert row.data['san_today']['loss']['张三'] == 6


# ---------- update_status / set_scene / get_card / record_events ----------

def test_update_status_clamps(env):
    engine, rid = env
    out = json.loads(asyncio.run(execute_tool('update_status', {
        'target': '张三', 'hp': 999, 'reason': '治疗溢出防御',
    }, rid)))
    assert out['hp'] == 11 and out['hp_max'] == 11  # clamp 到上限
    assert _card_state(engine, rid)['current_hp'] == 11


def test_update_status_requires_reason(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('update_status', {'target': '张三', 'hp': 5}, rid)))
    assert 'error' in out


def test_set_scene_updates_room_and_scenario(env):
    engine, rid = env
    out = json.loads(asyncio.run(execute_tool('set_scene', {
        'scene_title': '仓库二层 · 深夜', 'scene_desc': '灰尘与霉味',
    }, rid)))
    assert out['scene_title'] == '仓库二层 · 深夜'
    with Session(engine) as s:
        room = s.get(Room, rid)
        assert room.scene_title == '仓库二层 · 深夜'
        row = s.get(ScenarioState, rid)
        assert row.data['scene']['scene_title'] == '仓库二层 · 深夜'


def test_get_card_summary(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('get_card', {'target': '张三'}, rid)))
    assert out['name'] == '张三' and out['attributes']['INT'] == 65
    skill = next(s for s in out['skills'] if s['name'] == '侦查')
    assert skill['value'] == 50  # 25 基础 + 25 职业


def test_record_events_rolling_cap(env):
    engine, rid = env
    for i in range(8):
        out = json.loads(asyncio.run(execute_tool('record_events', {
            'events': [f'事件{i}a', f'事件{i}b', f'事件{i}c'],
        }, rid)))
    # 第 8 次：存量已封顶 20，并入 3 条后 merged=23（total 报告并入前的长度），
    # 存储滚动截到最后 20 条
    assert out['total'] == 23
    with Session(engine) as s:
        row = s.get(ScenarioState, rid)
        assert len(row.data['events']) == 20  # 滚动上限
        assert row.data['events'][-1] == '事件7c'


def test_unknown_tool_returns_error(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('nope', {}, rid)))
    assert 'error' in out and '未知工具' in out['error']


# ---------- 记忆五要素工具（4.3） ----------

def test_add_clue_auto_code_and_keeper_channel(env):
    engine, rid = env
    out1 = json.loads(asyncio.run(execute_tool('add_clue', {
        'content': '墙上有新鲜的撬痕', 'source': '现场勘查', 'visibility': 'public',
    }, rid)))
    out2 = json.loads(asyncio.run(execute_tool('add_clue', {
        'content': '守夜人袖口的灰烬', 'source': '张三注意到',
    }, rid)))
    assert out1['code'] == '线索-01' and out1['visibility'] == 'public'
    assert out2['code'] == '线索-02' and out2['visibility'] == 'keeper'
    keeper_rows = [m for m in _msgs(engine, rid) if m.secret]
    assert len(keeper_rows) == 2  # 登记动作只进 KP 屏
    assert all('登记线索' in m.content for m in keeper_rows)


def test_update_clue_flow_and_errors(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('add_clue', {'content': '撕碎的车票'}, rid)))
    cid = out['clue_id']
    ok = json.loads(asyncio.run(execute_tool('update_clue', {'clue_id': cid, 'status': 'confirmed'}, rid)))
    assert ok['status'] == 'confirmed'
    bad = json.loads(asyncio.run(execute_tool('update_clue', {'clue_id': 999, 'status': 'confirmed'}, rid)))
    assert 'error' in bad and '不存在' in bad['error']
    bad2 = json.loads(asyncio.run(execute_tool('update_clue', {'clue_id': cid, 'status': 'maybe'}, rid)))
    assert 'error' in bad2 and 'pending/confirmed/excluded' in bad2['error']


def test_advance_clock_create_increment_full(env):
    engine, rid = env
    out1 = json.loads(asyncio.run(execute_tool('advance_clock', {
        'name': '教团仪式', 'target': 3, 'note': '仪式完成则献祭', 'by': 1,
    }, rid)))
    assert out1 == {'name': '教团仪式', 'progress': 1, 'target': 3, 'full': False}
    out2 = json.loads(asyncio.run(execute_tool('advance_clock', {'name': '教团仪式', 'by': 2}, rid)))
    assert out2['progress'] == 3 and out2['full'] is True  # 沿用首次 target，不重设
    keeper_rows = [m for m in _msgs(engine, rid) if m.secret]
    assert any('已走满' in m.content for m in keeper_rows)


def test_upsert_npc_create_update(env):
    _, rid = env
    out1 = json.loads(asyncio.run(execute_tool('upsert_npc', {
        'name': '守夜人老陈', 'public_identity': '仓库夜间看门人',
        'hidden_motive': '替教团看守入口', 'misdirection': '表现得过度热心',
    }, rid)))
    assert out1['action'] == '新建' and out1['status'] == 'active'
    out2 = json.loads(asyncio.run(execute_tool('upsert_npc', {
        'name': '守夜人老陈', 'pressed_reaction': '被逼问装傻转移话题',
    }, rid)))
    assert out2['action'] == '更新'
    out3 = json.loads(asyncio.run(execute_tool('upsert_npc', {
        'name': '守夜人老陈', 'status': 'gone',
    }, rid)))
    assert out3['status'] == 'gone'


def test_filter_final_visibility_moves_keeper_fragments():
    from app.agent.keeper import filter_final_visibility

    final = {
        'narration_public': '你潜入后台，发现线索-02 记录的真相——教团仪式就在今晚。',
        'keeper_notes': '',
        'options': ['立刻破坏教团仪式', '先撤离'],
    }
    out = filter_final_visibility(final, ['线索-02', '教团仪式'])
    assert '线索-02' not in out['narration_public'] and '教团仪式' not in out['narration_public']
    assert '（……）' in out['narration_public']
    assert out['options'][0] == '立刻破坏（……）' and out['options'][1] == '先撤离'
    assert '可见性过滤' in out['keeper_notes'] and '线索-02' in out['keeper_notes']


def test_build_auto_messages_renders_memory_sections():
    from app.agent.assembler import AutoContext, build_auto_messages

    ctx = AutoContext(
        clues=['[线索-01·公开·confirmed] 撬痕', '[线索-02·仅KP·pending] 袖口灰烬'],
        clocks=['教团仪式 2/3（仪式完成则献祭）'],
        threads=['#1 延迟 1D4 SAN'],
        npcs=['守夜人老陈（在场；身份：看门人）｜动机(仅KP)：替教团看守入口'],
        scene_summaries=['「仓库外」调查员抵达仓库'],
    )
    msgs = build_auto_messages(ctx)
    memory = next(m['content'] for m in msgs if m['content'].startswith('[剧情记忆]'))
    for frag in ('线索档案', '线索-02·仅KP', '威胁时钟', '教团仪式 2/3',
                 '未结算伏笔', 'NPC 档案', '动机(仅KP)', '此前场景摘要'):
        assert frag in memory, f'BP2 缺少 {frag}'


# ---------- roll_check 防代掷（4.4：原 D5 查卡取值职责已收敛进 request_check） ----------

def test_roll_check_target_ignores_llm_value(env, monkeypatch):
    """4.4：roll_check 带 target（哪怕 LLM 补了 value）一律报错——检定下放唯一入口。"""
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_check', {
        'skill_name': '侦查', 'value': 99,
        'difficulty': 'standard', 'target': '张三', 'reason': '搜索',
    }, rid)))
    assert 'error' in out and 'request_check' in out['error']


def test_roll_check_target_unknown_skill_returns_error(env):
    """同上：target 未知成员也先撞防代掷拦截（错误信息不再引导 get_card）。"""
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_check', {
        'skill_name': '驯兽', 'difficulty': 'standard', 'target': '路人甲', 'reason': 'x',
    }, rid)))
    assert 'error' in out and 'request_check' in out['error']


def test_roll_check_no_target_requires_value(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_check', {
        'skill_name': '侦查', 'difficulty': 'standard', 'reason': 'NPC 检定',
    }, rid)))
    assert 'error' in out and 'value' in out['error']


# ---------- 骰子表达式规模上限（防 LLM 幻觉超大表达式） ----------

def test_roll_dice_oversized_expr_returns_error(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_dice', {'expr': '999999d6', 'reason': 'x'}, rid)))
    assert 'error' in out and '规模过大' in out['error']


def test_secret_roll_oversized_expr_returns_error(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('secret_roll', {'expr': '1D999999', 'reason': 'x'}, rid)))
    assert 'error' in out and '规模过大' in out['error']


def test_roll_dice_uppercase_expr_ok(env):
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('roll_dice', {'expr': '1D6', 'reason': 'x'}, rid)))
    assert 1 <= out['result'] <= 6  # 大写 D 合法（dice.roll 大小写不敏感）


# ---------- target 归一化（4.4 实测修复：玩家昵称 ≠ 角色卡名） ----------
#
# 真实现场：玩家「玩家甲」带卡「test」。提示词里工具 target 要求填玩家昵称，
# 但 LLM 会照抄【在场调查员】里的角色卡名，导致 request_check / san_check /
# update_status 全部报「不在房间内」，整轮检定下放落空。修法两层：
#   1) 提示词侧：_investigator_line 把玩家昵称放括号外、卡名放括号内；
#   2) 工具侧：_load_member_card 昵称查不到时按卡名兜底，并归一成昵称回执。

def _add_member_with_distinct_names(
    engine, rid, *, player_name: str, card_name: str, skill_value: int = 95,
) -> None:
    """挂一名「昵称 ≠ 卡名」的成员（复现真实团最常见的命名方式）。"""
    with Session(engine) as s:
        card = Card(owner=player_name)
        save_card(card, {
            'name': card_name, 'occupation': '拳击手',
            'attributes': {'STR': 65, 'INT': 75, 'POW': 35},
            'derived': {'HP': 12, 'SAN': 35},
            'state': {'current_hp': 12, 'current_sanity': 35},
            'skills': [
                {'name': '侦查', 'slot': 0, 'detail': '', 'base': 25,
                 'occupation_points': skill_value - 25, 'interest_points': 0},
            ],
        })
        s.add(card)
        s.commit()
        s.refresh(card)
        s.add(RoomMember(room_id=rid, player_name=player_name, role='player', card_id=card.id))
        s.commit()


def test_request_check_card_name_falls_back_and_normalizes_to_player_name(env):
    engine, rid = env
    _add_member_with_distinct_names(engine, rid, player_name='玩家甲', card_name='test')
    out = json.loads(asyncio.run(execute_tool('request_check', {
        'target': 'test', 'skill_name': '侦查',
        'difficulty': 'standard', 'reason': '辨认钟摆背面的刻痕',
    }, rid)))
    assert out.get('status') == 'requested'
    assert out['target'] == '玩家甲'  # 回执归一成花名册昵称（LLM 下一轮就能学到正确名字）
    assert out['value'] == 95
    # 落库行的 target 也必须归一：前端按 target === 我的昵称 判定「谁能投」
    rows = [m for m in _msgs(engine, rid) if m.type == 'check_request']
    assert rows and rows[-1].payload['target'] == '玩家甲'


def test_request_check_unknown_target_error_hints_player_name(env):
    """昵称与卡名都对不上时才报错，且文案引导 LLM 改用玩家昵称（D3 自我纠正）。"""
    _, rid = env
    out = json.loads(asyncio.run(execute_tool('request_check', {
        'target': '查无此人', 'skill_name': '侦查',
        'difficulty': 'standard', 'reason': 'x',
    }, rid)))
    assert 'error' in out and '玩家昵称' in out['error']


def test_update_status_and_san_check_accept_card_name(env, monkeypatch):
    """同一处归一化覆盖 update_status / san_check（二者终归走 apply_status_change
    的 player_name 查找，不归一就会同样报「目标成员不在房间内」）。"""
    engine, rid = env
    _add_member_with_distinct_names(engine, rid, player_name='玩家甲', card_name='test')
    out = json.loads(asyncio.run(execute_tool('update_status', {
        'target': 'test', 'hp': 5, 'reason': '被碎石划伤',
    }, rid)))
    assert out.get('target') == '玩家甲' and out['hp'] == 5

    monkeypatch.setattr(tools_mod, 'coc7_check', _force_check('fail', 90))
    monkeypatch.setattr(tools_mod.sanity, 'roll_loss', lambda *a, **k: 1)
    scor = json.loads(asyncio.run(execute_tool('san_check', {
        'target': 'test', 'loss_formula': '0/1D3', 'reason': '目睹白霜异象',
    }, rid)))
    assert scor.get('target') == '玩家甲'


def test_add_clue_keeper_note_avoids_double_punctuation(env):
    """回执摘要裁掉 content 尾部标点 + 改用「｜」（4.4 实测：原「，来源：」会撞成「。，」）。"""
    engine, rid = env
    json.loads(asyncio.run(execute_tool('add_clue', {
        'content': '霜下的旧刻痕写着 Tårnsjø。', 'source': '钟摆背面', 'visibility': 'public',
    }, rid)))
    notes = [m.content for m in _msgs(engine, rid) if m.secret]
    assert notes and 'Tårnsjø' in notes[-1]
    assert '。，' not in notes[-1] and '。｜' not in notes[-1]
    assert '｜来源：钟摆背面' in notes[-1]
