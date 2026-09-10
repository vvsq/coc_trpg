"""房间挂载模组与注入替换测试 — 阶段 5.4（goal §7）。

覆盖三件事：
  1. render_module_brief 的分层渲染（公开层 / 仅 KP 层）与超预算截断
  2. load_module_brief 的取值优先级（挂载且已就绪 > scenario_brief.txt 回退）
  3. PUT /rooms/{id}/module 的鉴权、状态校验、落库与回显
"""
import pytest
from sqlmodel import Session, select

import app.agent.module_context as module_context
from app.agent.keeper import _keeper_markers
from app.agent.module_context import (
    load_module_brief,
    module_keeper_markers,
    render_module_brief,
)
from app.models import Message, ModuleScenario, Room

SAMPLE_PARSED = {
    'title': '雪盲',
    'tone': '挽歌基调、克制恐怖',
    'hook': '一封旧信把调查员引向费勒斯村',
    'background': '兰莫丽芙因悲痛而成为白色哀悼者，现实被磕开一道裂缝。',
    'acts': [
        {'order': 1, 'title': '专家', 'summary': '抵达费勒斯', 'public_goal': '弄清寒潮来源',
         'keeper_goal': '先让玩家看见异常再看见源头', 'key_clues': '停摆的挂钟'},
    ],
    'npcs': [
        {'name': '斯考格医师', 'public_identity': '退休村医',
         'hidden_motive': '替教团销毁病例记录', 'player_clues': '病例本缺页',
         'misdirection': '把嫌疑引向外乡人', 'pressed_reaction': '避而不谈',
         'exit_plan': '连夜离开并留下一封信', 'stats': {}},
    ],
    'clues': [
        {'code': '线索-01', 'content': '霜水下有更早的刻痕', 'visibility': 'public',
         'points_to': '泪湖'},
        {'code': '线索-02', 'content': '白色哀悼者已非兰莫丽芙本人', 'visibility': 'keeper',
         'points_to': '高维空间'},
    ],
    'clocks': [{'name': '寒灾蔓延', 'target': 5, 'note': '满格则村子彻底冻结'}],
    'endings': [{'name': '传统救赎', 'condition': '把兰莫丽芙带回现实'}],
    'key_checks': [{'skill': '侦查', 'difficulty': 'hard', 'scene': '第一幕',
                    'stake': '错过霜下的刻痕'}],
    'warnings': ['第三幕线索偏少，建议 KP 补一条'],
}


def _add_module(session: Session, *, status: str = 'ready', name: str = '雪盲') -> ModuleScenario:
    module = ModuleScenario(name=name, source_type='txt', source_filename=f'{name}.txt',
                            raw_text='原文', parse_status=status,
                            parsed=SAMPLE_PARSED if status == 'ready' else None)
    session.add(module)
    session.commit()
    session.refresh(module)
    return module


def _add_room(session: Session, *, kp: str = '老周', module_id: int | None = None) -> Room:
    room = Room(name='挂载测试房', kp_name=kp, module_id=module_id)
    session.add(room)
    session.commit()
    session.refresh(room)
    return room


# ---------- 渲染分层 ----------

def test_render_brief_splits_public_and_keeper_layers():
    text = render_module_brief(SAMPLE_PARSED)
    assert '【模组骨架·公开层】' in text
    assert '【模组骨架·仅KP】' in text
    assert '雪盲' in text and '挽歌基调' in text
    assert '霜水下有更早的刻痕' in text

    keeper_at = text.index('【模组骨架·仅KP】')
    for secret in ('替教团销毁病例记录', '白色哀悼者已非兰莫丽芙本人',
                   '把兰莫丽芙带回现实', '满格则村子彻底冻结'):
        assert secret in text
        assert text.index(secret) > keeper_at, f'{secret} 出现在公开层'


def test_render_brief_truncates_low_priority_sections():
    """超预算时按优先级丢弃后段，并明确告知已截断（KP 才知道要回模组库看全文）。"""
    heavy = dict(SAMPLE_PARSED)
    heavy['npcs'] = [
        {'name': f'NPC{i}', 'hidden_motive': '动机' * 100, 'public_identity': '身份'}
        for i in range(30)
    ]
    text = render_module_brief(heavy, max_chars=1200)
    assert '【模组骨架·公开层】' in text       # 高优先级段一定保留
    assert '已按优先级截断' in text
    assert len(text) < 1500


def test_render_brief_handles_empty_and_bad_input():
    assert render_module_brief({}) == ''
    assert render_module_brief(None) == ''
    assert render_module_brief('不是字典') == ''


# ---------- 取值优先级 ----------

def _patch_fallback(monkeypatch, tmp_path, content: str | None):
    path = tmp_path / 'scenario_brief.txt'
    if content is None:
        path = tmp_path / 'not_exists.txt'
    else:
        path.write_text(content, encoding='utf-8')
    monkeypatch.setattr(module_context, '_SCENARIO_PATH', path)


def test_load_brief_prefers_ready_mounted_module(test_engine, tmp_path, monkeypatch):
    _patch_fallback(monkeypatch, tmp_path, '回退骨架内容')
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session, module_id=module.id)
        text = load_module_brief(session, room.id)
        assert '【模组骨架·公开层】' in text
        assert '回退骨架内容' not in text


def test_load_brief_falls_back_when_not_ready_or_unbound(test_engine, tmp_path, monkeypatch):
    _patch_fallback(monkeypatch, tmp_path, '回退骨架内容')
    with Session(test_engine) as session:
        module = _add_module(session, status='parsing')
        room = _add_room(session, module_id=module.id)
        assert load_module_brief(session, room.id) == '回退骨架内容'

        module.parse_status = 'ready'
        module.parsed = None
        session.add(module)
        session.commit()
        assert load_module_brief(session, room.id) == '回退骨架内容'  # 有状态无内容也回退

        module.parsed = SAMPLE_PARSED
        session.add(module)
        session.commit()
        room.module_id = None
        session.add(room)
        session.commit()
        assert load_module_brief(session, room.id) == '回退骨架内容'  # 解绑回退


def test_load_brief_returns_none_without_fallback_file(test_engine, tmp_path, monkeypatch):
    _patch_fallback(monkeypatch, tmp_path, None)
    with Session(test_engine) as session:
        room = _add_room(session)
        assert load_module_brief(session, room.id) is None


# ---------- 守秘标记（防剧透兜底） ----------

def test_module_keeper_markers_pick_only_sentences(test_engine):
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session, module_id=module.id)
        markers = module_keeper_markers(session, room.id)
        assert '替教团销毁病例记录' in markers          # NPC 隐藏动机
        assert '把兰莫丽芙带回现实' in markers          # 结局条件
        assert '满格则村子彻底冻结' in markers          # 时钟后果
        assert '白色哀悼者已非兰莫丽芙本人' in markers   # 仅 KP 线索
        assert '霜水下有更早的刻痕' not in markers       # 公开线索不算
        assert all(len(m) >= 8 for m in markers)


def test_keeper_markers_include_module_fields(test_engine):
    """filter_final_visibility 的依据必须带上模组守秘字段（刚挂模组时的过滤盲区）。"""
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session, module_id=module.id)
        markers = _keeper_markers(session, room.id)
        assert '替教团销毁病例记录' in markers


# ---------- 挂载接口 ----------

def test_set_room_module_forbidden_for_non_kp(client, test_engine):
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session)
        room_id, module_id = room.id, module.id
    res = client.put(f'/api/rooms/{room_id}/module',
                     json={'kp_name': '路人', 'module_id': module_id})
    assert res.status_code == 403
    with Session(test_engine) as session:
        assert session.get(Room, room_id).module_id is None


def test_set_room_module_validates_room_and_module(client, test_engine):
    with Session(test_engine) as session:
        room = _add_room(session)
        pending = _add_module(session, status='pending', name='未解析模组')
        room_id, pending_id = room.id, pending.id
    assert client.put('/api/rooms/NOPE0000/module',
                      json={'kp_name': '老周', 'module_id': 1}).status_code == 404
    assert client.put(f'/api/rooms/{room_id}/module',
                      json={'kp_name': '老周', 'module_id': 999}).status_code == 404
    res = client.put(f'/api/rooms/{room_id}/module',
                     json={'kp_name': '老周', 'module_id': pending_id})
    assert res.status_code == 400
    assert '尚未解析完成' in res.json()['detail']


def test_set_room_module_flow_and_echo(client, test_engine):
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session)
        room_id, module_id = room.id, module.id

    res = client.put(f'/api/rooms/{room_id}/module',
                     json={'kp_name': '老周', 'module_id': module_id})
    assert res.status_code == 200
    assert res.json()['module'] == {'module_id': module_id, 'module_name': '雪盲',
                                    'parse_status': 'ready'}

    # 详情接口回显（前端面板初次加载用）
    assert client.get(f'/api/rooms/{room_id}').json()['module']['module_id'] == module_id

    # 落系统消息（历史可回放）
    with Session(test_engine) as session:
        rows = session.exec(select(Message).where(Message.room_id == room_id)).all()
    assert any('雪盲' in m.content and m.type == 'sys' for m in rows)

    # 幂等：重复挂同一个模组不改动、不重复落消息
    again = client.put(f'/api/rooms/{room_id}/module',
                       json={'kp_name': '老周', 'module_id': module_id})
    assert again.json()['unchanged'] is True


def test_unbind_room_module(client, test_engine):
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session, module_id=module.id)
        room_id = room.id

    res = client.put(f'/api/rooms/{room_id}/module', json={'kp_name': '老周', 'module_id': None})
    assert res.status_code == 200
    assert res.json()['module'] is None
    assert client.get(f'/api/rooms/{room_id}').json()['module'] is None

    with Session(test_engine) as session:
        rows = session.exec(select(Message).where(Message.room_id == room_id)).all()
    assert any('回退默认方案' in m.content for m in rows)

    # 本来就未挂载：幂等返回
    assert client.put(f'/api/rooms/{room_id}/module',
                      json={'kp_name': '老周', 'module_id': None}).json()['unchanged'] is True


def test_delete_module_unbinds_room_with_system_message(client, test_engine):
    with Session(test_engine) as session:
        module = _add_module(session)
        room = _add_room(session, module_id=module.id)
        room_id, module_id = room.id, module.id

    assert client.delete(f'/api/modules/{module_id}').status_code == 204
    with Session(test_engine) as session:
        assert session.get(Room, room_id).module_id is None
        rows = session.exec(select(Message).where(Message.room_id == room_id)).all()
    assert any('挂载的模组已被删除' in m.content for m in rows)
    assert client.get(f'/api/rooms/{room_id}').json()['module'] is None
