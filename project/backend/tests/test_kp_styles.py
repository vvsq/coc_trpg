"""KP 风格系统测试（4.4，goal §6.2）：内置/自定义解析、参数规整、L2 渲染、
REST（列表/保存/删除/房间切换广播）、组装器注入、token 用量记账。

引擎依赖模块全局 engine，测试 monkeypatch 换 tmp 引擎；manager 广播在
无连接时是安全空操作。
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
import app.agent.kp_styles as styles_mod
from app.agent.assembler import AutoContext, build_auto_messages
from app.agent.kp_styles import (
    BUILTIN_IDS,
    create_custom_style,
    get_style,
    render_style_directive,
    validate_params,
)
from app.db import get_session
from app.llm.usage import get_usage, record_usage
from app.main import app
from app.models import KpStyle, LlmUsage, Message, Room


@pytest.fixture()
def env(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", connect_args={'check_same_thread': False},
    )
    SQLModel.metadata.create_all(test_engine)

    def override():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    with Session(test_engine) as s:
        room = Room(name='雾都疑云', kp_name='老周')
        s.add(room)
        s.commit()
        s.refresh(room)
        rid = room.id
    yield test_engine, rid
    app.dependency_overrides.clear()


# ---------- 模块层：解析 / 规整 / 渲染 ----------

def test_builtin_styles_present():
    assert BUILTIN_IDS == {'balanced', 'immersive', 'teaching'}
    for s in styles_mod.BUILTIN_STYLES:
        assert s['name'] and get_style(session=None, style_id=s['id']) is not None


def test_get_style_custom_and_missing(env):
    engine, _ = env
    row = create_custom_style(Session(engine), '悬疑沉浸', {'narrative_density': 'high'})
    got = get_style(Session(engine), row.id)
    assert got['name'] == '悬疑沉浸' and got['params']['narrative_density'] == 'high'
    assert get_style(Session(engine), 'custom-nothing') is None
    assert get_style(Session(engine), '') is None


def test_validate_params_normalizes():
    out = validate_params({'narrative_density': 'SUPER-HIGH', 'option_granularity': 'fine',
                           'note': 'x' * 500})
    assert out['narrative_density'] == 'medium'  # 非法回退中档
    assert out['option_granularity'] == 'fine'
    assert len(out['note']) == 200  # 截断
    assert validate_params(None)['rule_explanation'] == 'medium'  # 缺失补缺省


def test_render_directive_covers_knobs_and_fairness():
    text = render_style_directive({'id': 'teaching', 'name': '规则教学',
                                   'params': {'rule_explanation': 'high',
                                              'option_granularity': 'fine'}})
    assert '规则教学' in text and '公平' in text
    assert '规则解释' in text and '暗骰透明度' in text
    assert render_style_directive(None) is None


def test_delete_custom_style_resets_rooms(env):
    engine, rid = env
    with Session(engine) as session:
        row = create_custom_style(session, '短命风格', {})
        custom_id = row.id
        room = session.get(Room, rid)
        room.style_id = custom_id
        session.add(room)
        session.commit()
    assert styles_mod.delete_custom_style(Session(engine), custom_id) is True
    with Session(engine) as session:
        assert session.get(Room, rid).style_id == 'balanced'  # 引用房间回退默认


# ---------- REST ----------

def test_kp_styles_list_and_create(env):
    engine, _ = env
    client = TestClient(app)
    body = client.get('/api/kp-styles').json()
    assert [b['id'] for b in body['builtins']] == ['balanced', 'immersive', 'teaching']
    assert body['customs'] == []

    created = client.post('/api/kp-styles', json={
        'name': '悬疑沉浸', 'params': {'narrative_density': 'high', 'note': 'slow burn'},
    })
    assert created.status_code == 200
    assert created.json()['created']['params']['narrative_density'] == 'high'
    body = client.get('/api/kp-styles').json()
    assert len(body['customs']) == 1


def test_kp_styles_delete_rules(env):
    _, _ = env
    client = TestClient(app)
    assert client.delete('/api/kp-styles/balanced').status_code == 405  # 内置禁删
    assert client.delete('/api/kp-styles/custom-nothing').status_code == 404
    custom_id = client.post(
        '/api/kp-styles', json={'name': '待删', 'params': {}},
    ).json()['created']['id']
    assert client.delete(f'/api/kp-styles/{custom_id}').status_code == 200


def test_room_style_switch_broadcast(env):
    engine, rid = env
    client = TestClient(app)
    # KP 校验 / 风格存在性校验
    assert client.put(f'/api/rooms/{rid}/kp-style', json={
        'kp_name': '路人', 'style_id': 'immersive',
    }).status_code == 403
    assert client.put(f'/api/rooms/{rid}/kp-style', json={
        'kp_name': '老周', 'style_id': 'custom-x',
    }).status_code == 400
    # 正常切换：落库 + sys 消息（全员可见提示）
    res = client.put(f'/api/rooms/{rid}/kp-style', json={'kp_name': '老周', 'style_id': 'immersive'})
    assert res.status_code == 200
    assert res.json()['style'] == {'style_id': 'immersive', 'style_name': '剧情沉浸'}
    with Session(engine) as session:
        assert session.get(Room, rid).style_id == 'immersive'
        rows = session.exec(select(Message).where(Message.room_id == rid, Message.type == 'sys')).all()
    assert any('剧情沉浸' in m.content for m in rows)
    # 详情接口带风格回显
    assert client.get(f'/api/rooms/{rid}').json()['style']['style_id'] == 'immersive'


# ---------- 组装器注入（L2 层） ----------

def test_auto_context_style_in_bp2():
    ctx = AutoContext(style='当前 KP 风格：「剧情沉浸」…', room_name='测试房')
    msgs = build_auto_messages(ctx)
    assert msgs[1]['role'] == 'user'
    assert '【KP 风格】' in msgs[1]['content']
    assert '剧情沉浸' in msgs[1]['content']
    # 无风格时不注入该段
    plain = build_auto_messages(AutoContext())
    assert '【KP 风格】' not in plain[1]['content']


def test_suggestion_context_style_in_system():
    from app.agent.assembler import SuggestionContext, build_suggestion_messages
    msgs = build_suggestion_messages(SuggestionContext(style='当前 KP 风格：「规则教学」'))
    assert '规则教学' in msgs[0]['content']


# ---------- token 用量记账（4.4） ----------

def test_usage_record_and_read(env, monkeypatch):
    engine, _ = env
    import app.llm.usage as usage_mod
    monkeypatch.setattr(usage_mod, 'engine', engine)
    record_usage('qwen-flash', 100, 30)
    record_usage('deepseek-v4-pro', 500, 200)
    record_usage('qwen-flash', 0, 0)  # 全零不计
    assert get_usage() == {'calls': 2, 'prompt_tokens': 600, 'completion_tokens': 230}


def test_usage_never_raises(tmp_path, monkeypatch):
    """记账失败只记日志，不影响调用主流程（统计是锦上添花）。"""
    import app.llm.usage as usage_mod
    broken = create_engine('sqlite://')  # 内存库但未建表 → 写入失败
    monkeypatch.setattr(usage_mod, 'engine', broken)
    record_usage('m', 10, 10)  # 不应抛异常
    assert get_usage() == {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0}
