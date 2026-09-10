"""全自动主持引擎测试（4.2）：工具循环 / 终稿双通道分发 / 泄漏防线 / 降级。

FakeAutoClient 脚本化 chat_with_tools 与 chat 的返回序列（AssistantTurn）；
DB 用 tmp 引擎 monkeypatch（keeper.engine + tools.engine），manager 广播在
无连接时是安全空操作。可见性断言走 REST history（viewer 视角过滤）。
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
import app.agent.keeper as keeper_mod
import app.agent.tools as tools_mod
from app.agent.keeper import auto_keeper
from app.db import get_session
from app.llm.provider import AssistantTurn, LLMUnavailableError
from app.main import app
from app.models import Card, Message, Room, RoomMember, save_card
from app.rules.dice import D100Roll

GOOD_FINAL = json.dumps({
    'narration_public': '灯影晃动间，你们看清了帆布下的货箱，箱面印着褪色的航司标志。',
    'keeper_notes': '（KP 专享）货箱里是走私的文物，下一轮可安排守夜人接近。',
    'options': ['掀开货箱查看', '原路退出货仓', '守在暗处观察动静'],
}, ensure_ascii=False)

TOOL_TURN = AssistantTurn(content='', tool_calls=[
    {'id': 'call-1', 'name': 'roll_dice',
     'arguments': {'expr': '1D6', 'reason': '决定货仓深处异响的次数'}},
])


class FakeAutoClient:
    """脚本化客户端：chat_with_tools / chat 依次弹出脚本项。delay 模拟生成耗时。"""

    def __init__(self, script, delay: float = 0.0):
        self.script = list(script)
        self.delay = delay
        self.calls: list[dict] = []

    async def chat_with_tools(self, messages, *, tools, tool_choice='auto', **kw):
        self.calls.append({'messages': [dict(m) for m in messages], 'tools': tools})
        item = self.script.pop(0)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(item, Exception):
            raise item
        return item

    async def chat(self, messages, **kw):
        self.calls.append({'messages': [dict(m) for m in messages]})
        item = self.script.pop(0)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else item.content


@pytest.fixture()
def env(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", connect_args={'check_same_thread': False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(keeper_mod, 'engine', test_engine)
    monkeypatch.setattr(tools_mod, 'engine', test_engine)

    def override():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    with Session(test_engine) as s:
        room = Room(name='雾都疑云', kp_name='老周', agent_mode='auto')
        s.add(room)
        card = Card(owner='张三')
        save_card(card, {
            'name': '张三', 'occupation': '会计师',
            'attributes': {'INT': 65, 'POW': 60},
            'derived': {'HP': 11, 'SAN': 60},
            'state': {'current_hp': 11, 'current_sanity': 60},
            'skills': [{'name': '侦查', 'slot': 0, 'detail': '', 'base': 25,
                        'occupation_points': 25, 'interest_points': 0}],
        })
        s.add(card)
        s.commit()
        s.refresh(room)
        s.refresh(card)
        s.add(RoomMember(room_id=room.id, player_name='张三', role='player', card_id=card.id))
        s.commit()
        rid = room.id
    yield test_engine, rid
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_keeper_state():
    auto_keeper._inflight.clear()
    auto_keeper._pending.clear()
    auto_keeper._failures.clear()
    yield
    auto_keeper._inflight.clear()
    auto_keeper._pending.clear()
    auto_keeper._failures.clear()


# ---------- 正常一轮：工具循环 + 双通道分发 ----------

def test_auto_turn_tool_loop_and_dispatch(env, monkeypatch):
    engine, rid = env
    fake = FakeAutoClient([
        TOOL_TURN,
        AssistantTurn(content=GOOD_FINAL),
    ])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)

    payload = asyncio.run(auto_keeper.run_turn(rid))
    assert payload['status'] == 'ok'
    assert payload['turn']['narration_public'].startswith('灯影晃动间')
    assert len(payload['turn']['options']) == 3

    # 第 2 次调用前，工具结果已回喂（末条消息 role=tool）
    second = fake.calls[1]['messages']
    assert second[-1]['role'] == 'tool'
    result = json.loads(second[-1]['content'])
    assert result['expr'] == '1D6' and 1 <= result['result'] <= 6
    # 掷骰消息已由工具落库（明骰）
    with Session(engine) as s:
        rows = s.exec(select(Message).where(Message.room_id == rid, Message.type == 'text')).all()
        assert any('1D6' in m.content for m in rows)


def test_final_dispatch_dual_channel(env, monkeypatch):
    engine, rid = env
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    asyncio.run(auto_keeper.run_turn(rid))

    with Session(engine) as s:
        rows = s.exec(select(Message).where(Message.room_id == rid)).all()
    public = [m for m in rows if not m.secret and m.type == 'text']
    keeper = [m for m in rows if m.secret]
    assert any(m.payload.get('ai') is True and m.payload.get('options') for m in public)
    assert len(keeper) == 1 and '货箱里是走私的文物' in keeper[0].content
    assert keeper[0].payload['keeper'] is True


def test_keeper_notes_hidden_from_player_history(env, monkeypatch):
    engine, rid = env
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    asyncio.run(auto_keeper.run_turn(rid))

    client = TestClient(app)
    as_player = client.get(f'/api/rooms/{rid}/history?viewer=张三').json()['messages']
    as_kp = client.get(f'/api/rooms/{rid}/history?viewer=老周').json()['messages']
    # 玩家： keeper 笔记与暗骰一律不可见；KP：可见
    assert all('走私的文物' not in m['content'] for m in as_player)
    assert any('走私的文物' in m['content'] for m in as_kp)


# ---------- 缓存感知布局 ----------

def test_bp_layout_messages(env, monkeypatch):
    _, rid = env
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    asyncio.run(auto_keeper.run_turn(rid))

    msgs = fake.calls[0]['messages']
    assert [m['role'] for m in msgs] == ['system', 'user', 'assistant', 'user', 'assistant', 'user']
    assert msgs[0]['content'].startswith('[提示词版本 l1-v3-auto]')
    assert msgs[1]['content'].startswith('[剧情记忆]')
    assert msgs[3]['content'].startswith('[本回合]')
    assert '技能' in msgs[3]['content'] and '侦查' in msgs[3]['content']  # 调查员技能表内联
    assert '请推进本轮剧情' in msgs[5]['content']
    assert fake.calls[0]['tools']  # 工具 schema 随请求下发


def test_secret_rows_marked_and_excluded_from_latest_action(env, monkeypatch):
    """2026-09-10：secret 行不得充当【最新剧情推进】，但要在窗口里标「·仅KP」。

    真实踩坑：全自动每轮结尾都会落一条 keeper 笔记（secret=True，与叙事同
    channel），旧的 `recent[0].content` 会把 AI 自己的守秘笔记当成玩家行动
    喂回去（实测 BP3 里出现过「卡面无话术，已改用心理学…」）。
    """
    engine, rid = env
    with Session(engine) as s:
        s.add(Message(room_id=rid, channel='narrative', sender='张三',
                      content='我举灯照向帆布下的货箱。', payload={'role': 'player'}))
        s.add(Message(room_id=rid, channel='narrative', sender='AI主持',
                      content='keeper 笔记：货箱里其实只有压舱石，真正的文物在船底夹层。',
                      secret=True, payload={'role': 'kp'}))
        s.commit()

    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    asyncio.run(auto_keeper.run_turn(rid))

    turn = fake.calls[0]['messages'][3]['content']  # BP3 本回合
    assert '【最新剧情推进】我举灯照向帆布下的货箱。' in turn
    assert '【最新剧情推进】keeper 笔记' not in turn
    assert '[KP·AI主持·仅KP] keeper 笔记' in turn          # 窗口内显式标注
    assert '标「·仅KP」的行玩家看不到' in turn


# ---------- 失败与降级 ----------

def test_three_failures_fallback_manual(env, monkeypatch):
    engine, rid = env
    fake = FakeAutoClient([LLMUnavailableError('network', '无法连接 LLM 服务（网络异常）')] * 3)
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    for _ in range(3):
        payload = asyncio.run(auto_keeper.run_turn(rid))
        assert payload['status'] == 'degraded'
    with Session(engine) as s:
        room = s.get(Room, rid)
        assert room.agent_mode == 'manual'
        sys_rows = s.exec(select(Message).where(Message.room_id == rid, Message.type == 'sys')).all()
    assert any('回退纯人工主持' in m.content for m in sys_rows)


def test_two_failures_keeps_auto(env, monkeypatch):
    engine, rid = env
    fake = FakeAutoClient([LLMUnavailableError('network', 'x')] * 2)
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    for _ in range(2):
        asyncio.run(auto_keeper.run_turn(rid))
    with Session(engine) as s:
        assert s.get(Room, rid).agent_mode == 'auto'


def test_tool_round_cap_forces_final(env, monkeypatch):
    _, rid = env
    # 5 轮工具调用耗尽上限 → 强制无工具 chat() 收口
    fake = FakeAutoClient([TOOL_TURN] * 5 + [GOOD_FINAL])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    payload = asyncio.run(auto_keeper.run_turn(rid))
    assert payload['status'] == 'ok'
    assert fake.script == []  # 第 6 步 chat() 被调用


def test_bad_final_repaired_once(env, monkeypatch):
    _, rid = env
    garbage = '好的，我来推进剧情：本轮没有发生什么特别的事情。'
    fake = FakeAutoClient([
        AssistantTurn(content=garbage),  # 无工具调用且非 JSON → 触发修复重问
        GOOD_FINAL,                      # chat()（temperature=0.2, json_mode）返回修复稿
    ])
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)
    payload = asyncio.run(auto_keeper.run_turn(rid))
    assert payload['status'] == 'ok'
    # 修复调用带上了原输出与修复指令
    repair_msgs = fake.calls[1]['messages']
    assert any('不是合法终稿' in m.get('content', '') for m in repair_msgs)


def test_run_turn_missing_room(env, monkeypatch):
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: FakeAutoClient([]))
    payload = asyncio.run(auto_keeper.run_turn('NOPE0000'))
    assert payload['status'] == 'degraded' and payload['category'] == 'no_room'


def test_single_flight_merges(env, monkeypatch):
    _, rid = env
    # 两轮脚本（无工具轮 → 每轮恰 1 次 chat_with_tools）：原始一轮 + pending 补跑一轮
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)] * 2, delay=0.1)
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)

    async def scenario():
        first = asyncio.ensure_future(auto_keeper.run_turn(rid))
        await asyncio.sleep(0.02)  # 等在途置位（fake 延迟 0.1s，此时必在途）
        merged = await auto_keeper.run_turn(rid)  # 并入 → None
        assert merged is None
        await first
        await asyncio.sleep(0.5)  # 等补跑任务结束
        return fake.calls

    calls = asyncio.run(scenario())
    assert len(calls) == 2


# ---------- 静默期 debounce（4.3 前置小修：防频率，与协同建议同款） ----------

def test_debounce_merges_rapid_player_actions(env, monkeypatch):
    """静默期内玩家连发：取消重排，只开一轮。"""
    _, rid = env
    monkeypatch.setattr(keeper_mod, 'AUTO_DEBOUNCE_SECONDS', 0.05)
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)], delay=0.05)
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)

    async def scenario():
        auto_keeper.schedule_turn(rid)
        await asyncio.sleep(0.01)  # 计时挂起中
        auto_keeper.schedule_turn(rid)  # 静默期内再来 → 取消重排
        await asyncio.sleep(0.5)  # 等静默期 + 轮次结束

    asyncio.run(scenario())
    assert len(fake.calls) == 1
    assert not auto_keeper._debounce_tasks


def test_run_immediately_cancels_pending_debounce(env, monkeypatch):
    """KP 插话：取消未到期的静默期计时立即开轮，不产生额外一轮。"""
    _, rid = env
    monkeypatch.setattr(keeper_mod, 'AUTO_DEBOUNCE_SECONDS', 5.0)  # 长静默期不会自然到期
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)], delay=0.02)
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)

    async def scenario():
        auto_keeper.schedule_turn(rid)
        await asyncio.sleep(0.02)  # 计时挂起中
        auto_keeper.run_immediately(rid)  # KP 插话 → 立即开轮
        await asyncio.sleep(0.3)

    asyncio.run(scenario())
    assert len(fake.calls) == 1  # 只有立即那一轮
    assert not auto_keeper._debounce_tasks


def test_run_turn_cancels_pending_debounce(env, monkeypatch):
    """直接开轮（如补跑路径）同样取消未到期计时。"""
    _, rid = env
    monkeypatch.setattr(keeper_mod, 'AUTO_DEBOUNCE_SECONDS', 5.0)
    fake = FakeAutoClient([AssistantTurn(content=GOOD_FINAL)], delay=0.02)
    monkeypatch.setattr(keeper_mod, 'get_client', lambda: fake)

    async def scenario():
        auto_keeper.schedule_turn(rid)
        await asyncio.sleep(0.02)
        await auto_keeper.run_turn(rid)
        await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert len(fake.calls) == 1
    assert not auto_keeper._debounce_tasks
