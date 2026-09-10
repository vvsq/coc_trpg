"""模组库 API 测试 — 阶段 5（goal §7）：上传 / 列表 / 详情 / 校对 / 删除 / 解析。

用 conftest 的 client + test_engine（临时库 + 覆盖 get_session）。
解析端点全程用替身（假 LLM + 假后台任务 + 假配置），不花真钱、不联网。
"""
import asyncio
import io
import zipfile
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

import app.api.modules as modules_api
from app.llm.provider import LLMUnavailableError
from app.models import ModuleScenario, Room


def _docx_bytes(paragraphs: list[str]) -> bytes:
    body = ''.join(f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('word/document.xml', xml)
    return buf.getvalue()


def _upload(client, filename: str, data: bytes):
    return client.post('/api/modules', files={'file': (filename, data)})


def _make_room(test_engine, *, kp: str = '老周') -> str:
    with Session(test_engine) as session:
        room = Room(name='模组测试房', kp_name=kp)
        session.add(room)
        session.commit()
        session.refresh(room)
        return room.id


# ---------- 上传 ----------

def test_upload_txt_creates_pending_module(client):
    res = _upload(client, '雪盲.txt', '第一幕：罗恩\n挂钟停在十一点四十七分。'.encode('utf-8'))
    assert res.status_code == 201
    body = res.json()
    assert body['name'] == '雪盲'          # 默认取文件名主干
    assert body['source_type'] == 'txt'
    assert body['source_filename'] == '雪盲.txt'
    assert body['parse_status'] == 'pending'  # 上传不自动解析
    assert body['has_parsed'] is False
    assert body['parsed'] is None
    assert body['char_count'] > 0
    assert '第一幕：罗恩' in body['raw_text']


def test_upload_docx_extracts_paragraphs(client):
    res = _upload(client, 'Sabrina-雪盲.docx', _docx_bytes(['旧宅', '白霜', 'Kaldt']))
    assert res.status_code == 201
    assert res.json()['source_type'] == 'docx'
    assert res.json()['raw_text'].split('\n') == ['旧宅', '白霜', 'Kaldt']


def test_upload_rejects_unsupported_and_empty_and_damaged(client):
    assert _upload(client, '模组.exe', b'x').status_code == 400
    assert _upload(client, '空.txt', b'').status_code == 400
    assert _upload(client, '坏.docx', b'not a zip').status_code == 400
    bad_pdf = _upload(client, '坏.pdf', b'%PDF-1.4 broken')
    assert bad_pdf.status_code == 400
    # 失败的上传不留下半条记录
    assert client.get('/api/modules').json() == []


# ---------- 列表 / 详情 ----------

def test_list_is_lightweight_and_newest_first(client):
    _upload(client, 'a.txt', '甲'.encode('utf-8'))
    _upload(client, 'b.txt', '乙'.encode('utf-8'))
    rows = client.get('/api/modules').json()
    assert [row['name'] for row in rows] == ['b', 'a']  # 新的在前
    for row in rows:
        assert 'raw_text' not in row and 'parsed' not in row  # 列表不拖大字段
        assert row['char_count'] == 1


def test_detail_returns_raw_text_and_parsed(client):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    body = client.get(f'/api/modules/{module_id}').json()
    assert body['raw_text'] == '内容'
    assert body['parsed'] is None


def test_detail_and_update_404_for_unknown_module(client):
    assert client.get('/api/modules/999').status_code == 404
    assert client.put('/api/modules/999', json={'name': 'x'}).status_code == 404
    assert client.delete('/api/modules/999').status_code == 404


# ---------- 人工校对 ----------

def test_update_name_and_parsed_normalized(client):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    res = client.put(f'/api/modules/{module_id}', json={
        'name': '雪盲（校对版）',
        'parsed': {
            'title': '雪盲',
            'acts': [{'order': 2, 'title': '第二幕'}, {'order': 1, 'title': '第一幕'}],
            'npcs': [{'name': '斯考格医师', 'hidden_motive': '销毁病例', 'junk': 1}],
            'not_a_key': 'drop me',
        },
    })
    assert res.status_code == 200
    parsed = res.json()['parsed']
    assert res.json()['name'] == '雪盲（校对版）'
    assert [act['title'] for act in parsed['acts']] == ['第一幕', '第二幕']
    assert parsed['npcs'][0]['name'] == '斯考格医师'
    assert 'junk' not in parsed['npcs'][0]
    assert 'not_a_key' not in parsed
    assert parsed['hook'] == ''  # 缺字段补空，前端不必防御


def test_update_rejects_empty_name(client):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    assert client.put(f'/api/modules/{module_id}', json={'name': ''}).status_code == 422


def test_update_parsed_is_partial_patch(client):
    """前端按「块」保存（只发被编辑的那一段）时，其它区块必须原样保留。"""
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    client.put(f'/api/modules/{module_id}', json={'parsed': {
        'title': '雪盲', 'npcs': [{'name': '斯考格医师', 'hidden_motive': '销毁病例'}],
        'clocks': [{'name': '寒灾', 'target': 4}],
    }})

    res = client.put(f'/api/modules/{module_id}', json={'parsed': {
        'npcs': [{'name': '斯考格医师', 'hidden_motive': '销毁病例并伪造死亡证明'}],
    }})
    parsed = res.json()['parsed']
    assert parsed['npcs'][0]['hidden_motive'] == '销毁病例并伪造死亡证明'
    assert parsed['title'] == '雪盲'                      # 未提交的键保留
    assert parsed['clocks'][0]['name'] == '寒灾'


# ---------- 删除与解绑 ----------

def test_delete_module(client, test_engine):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    assert client.delete(f'/api/modules/{module_id}').status_code == 204
    assert client.get(f'/api/modules/{module_id}').status_code == 404
    assert client.get('/api/modules').json() == []


def test_delete_module_unbinds_referencing_rooms(client, test_engine):
    """删除被引用的模组要顺手解绑，否则房间会指向一个不存在的模组（回退失效）。"""
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    room_id = _make_room(test_engine)
    with Session(test_engine) as session:
        room = session.get(Room, room_id)
        room.module_id = module_id
        session.add(room)
        session.commit()

    assert client.delete(f'/api/modules/{module_id}').status_code == 204
    with Session(test_engine) as session:
        assert session.get(Room, room_id).module_id is None
        assert session.exec(select(ModuleScenario)).all() == []


# ---------- 结构化解析（5.2：手动触发 + 可选模型 + 状态机） ----------

@pytest.fixture(autouse=True)
def _clean_parsing_registry():
    """进程内 _PARSING 集合跨测试共享，而每个测试的临时库 id 都从 1 开始——
    不清空会让上一条测试的 1 号模组把下一条的 1 号模组误判成"解析中"。"""
    modules_api._PARSING.clear()
    yield
    modules_api._PARSING.clear()


def _stub_parse_env(
    monkeypatch, test_engine, *, enabled: bool = True,
    parsed: dict | None = None, error: Exception | None = None,
) -> dict:
    """替换解析链路上的外部依赖：引擎 / 配置 / LLM 抽取 / 后台任务。"""
    monkeypatch.setattr(modules_api, 'engine', test_engine)
    monkeypatch.setattr(
        modules_api, 'get_settings',
        lambda: SimpleNamespace(enabled=enabled, model='主模型', light_model='轻模型',
                                light_ready=True, light_base_url='', light_api_key=''),
    )
    monkeypatch.setattr(
        modules_api, 'resolve_parse_model',
        lambda model: (model or '轻模型').strip(),
    )

    async def fake_extract(raw_text: str, *, model: str | None = None):
        if error is not None:
            raise error
        return parsed if parsed is not None else {'title': '雪盲', 'acts': [{'title': '第一幕'}]}, \
            (model or '轻模型')

    monkeypatch.setattr(modules_api, 'extract_module', fake_extract)

    captured: dict = {}

    def fake_spawn(coro, *, name):
        captured['coro'] = coro
        captured['name'] = name
        return None

    monkeypatch.setattr(modules_api, 'spawn_background', fake_spawn)
    return captured


def test_parse_requires_llm_configuration(client, test_engine, monkeypatch):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    _stub_parse_env(monkeypatch, test_engine, enabled=False)
    res = client.post(f'/api/modules/{module_id}/parse', json={})
    assert res.status_code == 400
    assert 'LLM' in res.json()['detail']
    # 未配置时不落 parsing 状态，也不产生后台任务
    assert client.get(f'/api/modules/{module_id}').json()['parse_status'] == 'pending'


def test_parse_flow_sets_parsing_then_ready(client, test_engine, monkeypatch):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    captured = _stub_parse_env(monkeypatch, test_engine)

    res = client.post(f'/api/modules/{module_id}/parse', json={'model': '强模型'})
    assert res.status_code == 202
    assert res.json() == {'module_id': module_id, 'parse_status': 'parsing',
                          'parse_model': '强模型'}
    assert captured['name'] == f'module-parse-{module_id}'

    parsing = client.get(f'/api/modules/{module_id}').json()
    assert parsing['parse_status'] == 'parsing'
    assert parsing['parse_model'] == '强模型'  # 记录本次实际使用的模型
    assert parsing['parsed'] is None

    asyncio.run(captured['coro'])

    ready = client.get(f'/api/modules/{module_id}').json()
    assert ready['parse_status'] == 'ready'
    assert ready['parse_error'] == ''
    assert ready['parsed']['title'] == '雪盲'
    assert ready['parsed']['hook'] == ''      # 归一化补齐空字段
    assert ready['has_parsed'] is True
    assert ready['parsed_at'] is not None
    assert module_id not in modules_api._PARSING  # 完成后必须解锁


def test_parse_default_model_falls_back_to_light(client, test_engine, monkeypatch):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    captured = _stub_parse_env(monkeypatch, test_engine)
    res = client.post(f'/api/modules/{module_id}/parse', json={})
    assert res.status_code == 202
    assert res.json()['parse_model'] == '轻模型'
    asyncio.run(captured['coro'])
    assert client.get(f'/api/modules/{module_id}').json()['parse_model'] == '轻模型'


def test_parse_conflict_while_parsing(client, test_engine, monkeypatch):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    captured = _stub_parse_env(monkeypatch, test_engine)
    assert client.post(f'/api/modules/{module_id}/parse', json={}).status_code == 202

    second = client.post(f'/api/modules/{module_id}/parse', json={})
    assert second.status_code == 409
    assert '解析中' in second.json()['detail']

    # 解析失败/完成后可重试
    asyncio.run(captured['coro'])
    assert client.post(f'/api/modules/{module_id}/parse', json={}).status_code == 202
    asyncio.run(captured['coro'])


def test_parse_failure_records_readable_error(client, test_engine, monkeypatch):
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    captured = _stub_parse_env(
        monkeypatch, test_engine,
        error=LLMUnavailableError('auth', 'API Key 无效或未授权（401）'),
    )
    assert client.post(f'/api/modules/{module_id}/parse', json={}).status_code == 202
    asyncio.run(captured['coro'])

    failed = client.get(f'/api/modules/{module_id}').json()
    assert failed['parse_status'] == 'failed'
    assert 'API Key 无效' in failed['parse_error']
    assert module_id not in modules_api._PARSING


def test_parse_rejects_module_without_raw_text(client, test_engine, monkeypatch):
    with Session(test_engine) as session:
        row = ModuleScenario(name='空壳', raw_text='', parse_status='pending')
        session.add(row)
        session.commit()
        session.refresh(row)
        module_id = row.id
    _stub_parse_env(monkeypatch, test_engine)
    res = client.post(f'/api/modules/{module_id}/parse', json={})
    assert res.status_code == 400
    assert '原文' in res.json()['detail']


def test_parse_404_for_unknown_module(client, test_engine, monkeypatch):
    _stub_parse_env(monkeypatch, test_engine)
    assert client.post('/api/modules/999/parse', json={}).status_code == 404


def test_parse_overwrites_previous_result_and_model(client, test_engine, monkeypatch):
    """换模型重解析：parsed 与 parse_model 都要被覆盖成最新一次的结果。"""
    module_id = _upload(client, '雪盲.txt', '内容'.encode('utf-8')).json()['id']
    captured = _stub_parse_env(monkeypatch, test_engine, parsed={'title': '第一次'})
    client.post(f'/api/modules/{module_id}/parse', json={'model': '弱模型'})
    asyncio.run(captured['coro'])
    assert client.get(f'/api/modules/{module_id}').json()['parse_model'] == '弱模型'

    captured = _stub_parse_env(monkeypatch, test_engine, parsed={'title': '第二次'})
    client.post(f'/api/modules/{module_id}/parse', json={'model': '强模型'})
    asyncio.run(captured['coro'])
    detail = client.get(f'/api/modules/{module_id}').json()
    assert detail['parse_model'] == '强模型'
    assert detail['parsed']['title'] == '第二次'
