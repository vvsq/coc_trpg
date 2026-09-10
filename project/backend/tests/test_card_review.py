"""检卡（2026-09-10 用户反馈 #5）：输入组装 / 输出规整 / 鉴权 / 玩家名对齐。

口径：只给建议不拦截开团；LLM 走轻任务模型；解析失败带原输出重问一次
（重问逻辑与 suggest/keeper 同款，这里只测「解析规整 + 玩家名对齐」这些专属点）。
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
import app.agent.card_review as review_mod
from app.agent.card_review import build_review_messages, parse_review, review_room_cards
from app.db import get_session
from app.main import app
from app.models import Card, Room, RoomMember, save_card


class FakeClient:
    """脚本化轻任务客户端：chat 返回预置回复（或抛异常）。"""

    def __init__(self, reply):
        self.reply = reply
        self.calls: list[list[dict]] = []

    async def chat(self, messages, **kw):
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture()
def env(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", connect_args={'check_same_thread': False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(review_mod, 'engine', test_engine)

    def override():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    with Session(test_engine) as s:
        room = Room(name='雾都疑云', kp_name='老周')
        s.add(room)
        s.commit()
        s.refresh(room)
        card = Card(owner='local')
        save_card(card, {
            'name': '张三', 'occupation': '会计师', 'age': 32, 'era': 'classical',
            'credit': 40,
            'attributes': {'STR': 40, 'CON': 50, 'SIZ': 55, 'DEX': 65,
                           'APP': 50, 'INT': 70, 'POW': 60, 'EDU': 75},
            'derived': {'HP': 10, 'SAN': 60, 'MP': 12},
            'state': {'current_hp': 10, 'current_sanity': 60},
            'skills': [
                {'name': '侦查', 'slot': 0, 'detail': '', 'base': 25, 'increment': 45},
                {'name': '格斗', 'slot': 0, 'detail': '斗殴', 'base': 25, 'increment': 55},
            ],
            'possessions': '笔记本电脑、智能手机',
            'background': {'personal_description': '文弱的大学讲师，从不运动'},
            'weapons': [{'name': '撬棍', 'skill_name': '格斗', 'damage': '1d6+1'}],
        })
        s.add(card)
        s.commit()
        s.refresh(card)
        s.add(RoomMember(room_id=room.id, player_name='玩家甲', role='player', card_id=card.id))
        s.commit()
        rid = room.id
    yield test_engine, rid
    app.dependency_overrides.clear()


# ---------- 输入组装 ----------

def test_build_review_messages_carries_card_and_module():
    payload = {
        'room_name': '雾都疑云',
        'scene_title': '码头仓库 · 深夜',
        'module': '模组：雪盲\n基调：挽歌',
        'players': [{'player_name': '玩家甲', 'card': '角色名：张三｜职业：会计师'}],
    }
    msgs = build_review_messages(payload)
    assert msgs[0]['role'] == 'system' and 'JSON' in msgs[0]['content']
    user = msgs[1]['content']
    assert '玩家昵称：玩家甲' in user and '角色名：张三' in user
    assert '模组：雪盲' in user
    assert 'player_name 必须原样照抄' in user


def test_build_review_messages_says_no_module():
    user = build_review_messages({'players': [{'player_name': '甲', 'card': 'x'}]})[1]['content']
    assert '未挂载模组' in user


# ---------- 输出规整 ----------

def test_parse_review_aligns_overall_with_issues():
    """LLM 常见自相矛盾：overall=ok 却列出问题 → 以 issues 为准。"""
    raw = json.dumps({'players': [
        {'player_name': '玩家甲', 'overall': 'ok',
         'issues': [{'severity': 'major', 'title': '物品与时代冲突',
                     'detail': '1920s 带智能手机', 'advice': '删除该物品'}]},
        {'player_name': '玩家乙', 'overall': 'major', 'issues': []},
    ]}, ensure_ascii=False)
    out = parse_review(raw)
    first, second = out['players']
    assert first['overall'] == 'major'
    assert first['issues'][0]['detail'].startswith('1920s')
    assert second['overall'] == 'ok' and second['issues'] == []


def test_parse_review_strips_fence_and_trailing_comma():
    raw = '```json\n{"players":[{"player_name":"甲","overall":"suggestion",' \
          '"issues":[{"severity":"suggestion","title":"背景单薄","detail":"","advice":""},]},]}\n```'
    out = parse_review(raw)
    assert out['players'][0]['issues'][0]['title'] == '背景单薄'


def test_parse_review_rejects_garbage():
    for bad in ('这不是 JSON', '{"foo": 1}', '{"players": []}'):
        with pytest.raises(ValueError):
            parse_review(bad)


# ---------- 端到端（假客户端） ----------

REPLY = json.dumps({'players': [
    {'player_name': '玩家甲', 'overall': 'major',
     'issues': [{'severity': 'major', 'title': '物品与时代冲突',
                 'detail': '古典时代不应有笔记本电脑', 'advice': '换成笔记与钢笔'}]},
    {'player_name': '幻觉玩家', 'overall': 'suggestion',
     'issues': [{'severity': 'suggestion', 'title': 'x', 'detail': '', 'advice': ''}]},
]}, ensure_ascii=False)


def test_review_filters_hallucinated_players(env, monkeypatch):
    engine, rid = env
    fake = FakeClient(REPLY)
    monkeypatch.setattr(review_mod, 'get_light_client', lambda: fake)
    out = asyncio.run(review_room_cards(rid))
    names = [p['player_name'] for p in out['players']]
    assert names == ['玩家甲']          # 杜撰的玩家名被丢弃
    assert out['players'][0]['issues'][0]['severity'] == 'major'
    assert out['model']                # 记了用的哪个模型
    # 输入里带上卡摘要与（此处未挂模组的）说明
    assert '笔记本电脑' in fake.calls[0][1]['content']


def test_review_attributed_to_room(env, monkeypatch):
    """检卡是房间内的 KP 动作：LLM 调用要落在 usage_room 上下文里（计入本场消耗）。"""
    from app.llm.usage import _current_room

    _, rid = env
    seen: dict = {}

    class Probe(FakeClient):
        async def chat(self, messages, **kw):
            seen['room'] = _current_room.get()
            return await super().chat(messages, **kw)

    monkeypatch.setattr(review_mod, 'get_light_client', lambda: Probe(REPLY))
    asyncio.run(review_room_cards(rid))
    assert seen['room'] == rid


def test_review_skips_llm_when_no_players(env, monkeypatch):
    """没有已绑卡的玩家时不浪费一次 LLM 调用。"""
    _, rid = env
    fake = FakeClient(REPLY)
    monkeypatch.setattr(review_mod, 'get_light_client', lambda: fake)
    with Session(review_mod.engine) as s:
        for row in s.exec(select(RoomMember)).all():
            s.delete(row)
        s.commit()
    out = asyncio.run(review_room_cards(rid))
    assert out['players'] == [] and not fake.calls


# ---------- REST 鉴权 ----------

def test_card_review_api_auth(env, monkeypatch):
    _, rid = env
    fake = FakeClient(REPLY)
    monkeypatch.setattr(review_mod, 'get_light_client', lambda: fake)
    client = TestClient(app)

    denied = client.post(f'/api/rooms/{rid}/card-review', json={'kp_name': '路人'})
    assert denied.status_code == 403
    assert client.post('/api/rooms/NOPE/card-review', json={'kp_name': '老周'}).status_code == 404

    ok = client.post(f'/api/rooms/{rid}/card-review', json={'kp_name': '老周'})
    assert ok.status_code == 200, ok.text
    assert ok.json()['players'][0]['player_name'] == '玩家甲'


def test_card_review_api_reports_llm_unavailable(env, monkeypatch):
    from app.llm.provider import LLMUnavailableError

    _, rid = env
    monkeypatch.setattr(review_mod, 'get_light_client',
                        lambda: FakeClient(LLMUnavailableError('auth', 'API Key 无效')))
    client = TestClient(app)
    res = client.post(f'/api/rooms/{rid}/card-review', json={'kp_name': '老周'})
    assert res.status_code == 503 and 'API Key' in res.json()['detail']
