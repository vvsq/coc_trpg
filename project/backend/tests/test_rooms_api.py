"""房间 API 测试 — 开团状态流转与解散广播（阶段3修复回归）。

项目此前只有规则引擎单测，无 API 测试基建；本文件用 TestClient +
tmp SQLite 覆盖 get_session 起步。WS 广播在无连接时是安全空操作，
因此 dissolve 的广播/close_room 分支不需要真实 WebSocket 即可测。
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401  确保全部 table=True 模型注册进 metadata
from app.db import get_session
from app.main import app


@pytest.fixture()
def client(tmp_path):
    """每个测试一个独立临时库：覆盖 get_session 后经 TestClient 走完整路由栈。"""
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)

    def override():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _create_room(client: TestClient, name: str = '测试房', kp: str = '老周') -> str:
    res = client.post('/api/rooms', json={'name': name, 'kp_name': kp})
    assert res.status_code == 201
    return res.json()['room_id']


# ---------- 开团：waiting → playing（Bug4 修复） ----------

def test_start_game_forbidden_for_non_kp(client):
    room_id = _create_room(client)
    res = client.put(f'/api/rooms/{room_id}/start', json={'kp_name': '路人'})
    assert res.status_code == 403
    # 状态未被改动
    assert client.get(f'/api/rooms/{room_id}').json()['status'] == 'waiting'


def test_start_game_flow_and_lobby_filter(client):
    room_id = _create_room(client)
    assert client.get('/api/rooms').json()[0]['room_id'] == room_id  # waiting 时在大厅

    res = client.put(f'/api/rooms/{room_id}/start', json={'kp_name': '老周'})
    assert res.status_code == 200
    assert res.json() == {'status': 'playing', 'already_started': False}

    detail = client.get(f'/api/rooms/{room_id}').json()
    assert detail['status'] == 'playing'
    # 开团后大厅不再展示（list_waiting_rooms 只列 waiting）
    assert client.get('/api/rooms').json() == []

    # 幂等：重复开团不报错、不重复落库
    res = client.put(f'/api/rooms/{room_id}/start', json={'kp_name': '老周'})
    assert res.json() == {'status': 'playing', 'already_started': True}


def test_start_room_not_found(client):
    res = client.put('/api/rooms/NOPE0000/start', json={'kp_name': '老周'})
    assert res.status_code == 404


# ---------- 解散：广播 + 数据清理（Bug3 修复） ----------

def test_dissolve_room_forbidden_for_non_kp(client):
    room_id = _create_room(client)
    res = client.delete(f'/api/rooms/{room_id}', params={'kp_name': '路人'})
    assert res.status_code == 403
    assert client.get(f'/api/rooms/{room_id}').status_code == 200


def test_dissolve_room_cleans_up(client):
    room_id = _create_room(client)
    client.post(f'/api/rooms/{room_id}/join', json={'player_name': '陈默'})

    res = client.delete(f'/api/rooms/{room_id}', params={'kp_name': '老周'})
    assert res.status_code == 204
    assert client.get(f'/api/rooms/{room_id}').status_code == 404
    # 成员表与房间一起被清：重新加入等同新房，不残留旧花名册语义
    assert client.get(f'/api/rooms/{room_id}/state').status_code == 404


def test_join_room_roster_and_idempotent_rejoin(client):
    room_id = _create_room(client)
    members = client.post(
        f'/api/rooms/{room_id}/join', json={'player_name': '陈默'}
    ).json()
    assert {'player_name': '老周', 'role': 'kp', 'card_id': None} in members
    assert {'player_name': '陈默', 'role': 'player', 'card_id': None} in members

    # 同名重进幂等（断线重连语义）：不产生重复行
    members_again = client.post(
        f'/api/rooms/{room_id}/join', json={'player_name': '陈默'}
    ).json()
    assert members_again == members


# ---------- 存档列表鉴权（4.4 实测修复：原先漏了 kp_name 校验） ----------

def test_list_saves_requires_kp_name(client):
    room_id = _create_room(client)
    client.post(f'/api/rooms/{room_id}/save', json={'kp_name': '老周', 'name': '第一章'})

    # KP：正常拿到列表
    ok = client.get(f'/api/rooms/{room_id}/saves', params={'kp_name': '老周'})
    assert ok.status_code == 200 and [s['name'] for s in ok.json()] == ['第一章']

    # 玩家 / 匿名：403（存档名也属 KP 信息）
    assert client.get(f'/api/rooms/{room_id}/saves').status_code == 403
    assert client.get(f'/api/rooms/{room_id}/saves', params={'kp_name': '陈默'}).status_code == 403


def test_list_saves_room_not_found(client):
    res = client.get('/api/rooms/NOPE0000/saves', params={'kp_name': '老周'})
    assert res.status_code == 404
