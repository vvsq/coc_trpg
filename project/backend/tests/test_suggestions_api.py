"""协同建议 API 与引擎测试 — 模式切换 / 手动触发 / 降级与自动回退（阶段 4.1）。

引擎依赖全局 db.engine（与 WS 层同款"现场开 Session"），测试用
monkeypatch 把 app.agent.suggest.engine 换成 tmp 引擎；LLM 客户端换成
FakeClient，不发起真实请求。WS 广播在无连接时是安全空操作。
"""
import asyncio
import json
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
import pytest

import app.models  # noqa: F401  确保全部 table=True 模型注册进 metadata
import app.agent.module_context as module_context
import app.agent.suggest as suggest_mod
from app.agent.suggest import suggestion_engine
from app.db import get_session
from app.llm.provider import LLMUnavailableError
from app.main import app
from app.models import Card, Message, Room, RoomMember, save_card


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


def _make_env(tmp_path, monkeypatch):
    """tmp 引擎同时用于：REST get_session 覆盖 + suggest 模块全局替换。

    （引擎与 WS 层同款"现场开 Session(app.db.engine)"，不走请求级依赖，
    所以 REST 的 override 覆盖不到它，必须单独 monkeypatch。）
    """
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(test_engine)

    def override():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    monkeypatch.setattr(suggest_mod, 'engine', test_engine)
    return test_engine


class FakeClient:
    """替身 LLM 客户端：chat 返回预设文本或抛 LLMUnavailableError。

    delay 用于单飞合并测试：让 chat 挂住足够久，保证第二个请求落在在途窗口内。
    """

    def __init__(self, reply: str | None = None, error: LLMUnavailableError | None = None,
                 delay: float = 0.0, probe_models: list[str] | None = None):
        self.reply = reply
        self.error = error
        self.delay = delay
        self.calls: list[dict] = []
        self.probe_models = probe_models or []

    async def chat(self, messages, **kwargs):
        self.calls.append({'messages': messages, **kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.reply

    async def ping(self):
        if self.error is not None:
            raise self.error
        return 12

    async def list_models(self):
        if self.error is not None:
            raise self.error
        return self.probe_models


GOOD_REPLY = json.dumps({'suggestions': [
    {'text': '稳妥推进：你们搜索仓库货架。', 'check_hint': {'skill': '侦查', 'difficulty': 'hard', 'stake': '惊动守夜人'}},
    {'text': '冒险深入：直接撬开内室的铁柜。', 'check_hint': None},
]}, ensure_ascii=False)


def _seed_room(engine, mode: str = 'collab') -> str:
    with Session(engine) as session:
        room = Room(name='雾都疑云', kp_name='老周', agent_mode=mode)
        session.add(room)
        card = Card(owner='张三')
        save_card(card, {'name': '张三', 'occupation': '会计师',
                         'derived': {'HP': 12, 'SAN': 50},
                         'state': {'current_hp': 9, 'current_sanity': 42}})
        session.add(card)
        session.commit()
        session.refresh(room)
        session.refresh(card)
        session.add(RoomMember(room_id=room.id, player_name='张三', role='player', card_id=card.id))
        session.add(Message(room_id=room.id, channel='narrative', sender='老周',
                            content='仓库的门吱呀打开。', payload={'role': 'kp'}))
        session.add(Message(room_id=room.id, channel='narrative', sender='张三',
                            content='我举灯照向角落。', payload={'role': 'player'}))
        session.commit()
        return room.id


# ---------- 模式切换 REST ----------

def test_agent_mode_requires_kp(client, tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine, mode='manual')
    res = client.put(f'/api/rooms/{room_id}/agent-mode', json={'kp_name': '路人', 'mode': 'collab'})
    assert res.status_code == 403
    assert client.get(f'/api/rooms/{room_id}').json()['agent_mode'] == 'manual'


def test_agent_mode_switch_and_broadcast(client, tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine, mode='manual')
    res = client.put(f'/api/rooms/{room_id}/agent-mode', json={'kp_name': '老周', 'mode': 'collab'})
    assert res.status_code == 200 and res.json() == {'agent_mode': 'collab'}
    detail = client.get(f'/api/rooms/{room_id}').json()
    assert detail['agent_mode'] == 'collab'
    # sys 消息已落库（全员可见提示）
    with Session(engine) as session:
        rows = session.exec(
            select(Message).where(Message.room_id == room_id, Message.type == 'sys')
        ).all()
    assert any('开启了协同建议模式' in m.content for m in rows)
    # 幂等：重复设置返回 unchanged
    res = client.put(f'/api/rooms/{room_id}/agent-mode', json={'kp_name': '老周', 'mode': 'collab'})
    assert res.json() == {'agent_mode': 'collab', 'unchanged': True}
    # 非法模式被 pydantic 拦下（4.2 起 auto 是合法档位，改用未定义值验证）
    assert client.put(
        f'/api/rooms/{room_id}/agent-mode', json={'kp_name': '老周', 'mode': 'wizard'},
    ).status_code == 422
    # 4.2：auto 档可开启，sys 文案随模式变化
    res = client.put(f'/api/rooms/{room_id}/agent-mode', json={'kp_name': '老周', 'mode': 'auto'})
    assert res.status_code == 200 and res.json() == {'agent_mode': 'auto'}
    with Session(engine) as session:
        rows = session.exec(
            select(Message).where(Message.room_id == room_id, Message.type == 'sys')
        ).all()
    assert any('开启了全自动主持模式' in m.content for m in rows)


# ---------- 手动触发生成 REST ----------

def test_generate_requires_kp_and_mode(client, tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine, mode='manual')

    res = client.post(f'/api/rooms/{room_id}/suggestions/generate', json={'kp_name': '路人'})
    assert res.status_code == 403
    # 模式未开启时手动触发被 400 拦截
    res = client.post(f'/api/rooms/{room_id}/suggestions/generate', json={'kp_name': '老周'})
    assert res.status_code == 400

    # collab 下触发：202 + request_id（生成在后台协程，用替身引擎避免真调 LLM）
    with Session(engine) as session:
        room = session.get(Room, room_id)
        room.agent_mode = 'collab'
        session.add(room)
        session.commit()

    class FakeEngine:
        def __init__(self):
            self.calls = []

        async def generate_and_broadcast(self, room_id, **kwargs):
            self.calls.append({'room_id': room_id, **kwargs})

    fake = FakeEngine()
    monkeypatch.setattr('app.api.suggestions.suggestion_engine', fake)
    res = client.post(
        f'/api/rooms/{room_id}/suggestions/generate',
        json={'kp_name': '老周', 'focus': '偏悬疑'},
    )
    assert res.status_code == 202
    assert res.json()['request_id']
    # create_task 已被事件循环调度（TestClient portal），稍候断言参数
    for _ in range(50):
        if fake.calls:
            break
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.01))
    assert fake.calls and fake.calls[0]['room_id'] == room_id
    assert fake.calls[0]['request_id'] == res.json()['request_id']
    assert fake.calls[0]['trigger'] == 'manual'
    assert fake.calls[0]['focus'] == '偏悬疑'


# ---------- 引擎：真实生成 / 降级 / 自动回退（直连 await，绕过 create_task） ----------

@pytest.fixture(autouse=True)
def _reset_engine_state():
    """单例引擎的房间状态在用例间清零。"""
    suggestion_engine._inflight.clear()
    suggestion_engine._pending.clear()
    suggestion_engine._failures.clear()
    yield
    suggestion_engine._inflight.clear()
    suggestion_engine._pending.clear()
    suggestion_engine._failures.clear()


def test_engine_generates_and_normalizes(tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    fake = FakeClient(reply=GOOD_REPLY)
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    payload = asyncio.run(
        suggestion_engine.generate_and_broadcast(room_id, focus='偏悬疑', trigger='auto')
    )
    assert payload['status'] == 'ok' and payload['trigger'] == 'auto'
    assert len(payload['suggestions']) == 2
    assert payload['suggestions'][0]['check_hint'] == {
        'skill': '侦查', 'difficulty': 'hard', 'stake': '惊动守夜人',
    }
    # 上下文组装包含场景与最新玩家行动（L1+L5 链路）
    sent = fake.calls[0]['messages']
    assert sent[0]['role'] == 'system'
    assert '仓库的门吱呀打开。' in sent[1]['content']
    assert '我举灯照向角落。' in sent[1]['content']
    assert '张三（会计师）HP 9/12' in sent[1]['content']
    assert '偏悬疑' in sent[1]['content']


def test_engine_degrades_on_llm_failure(tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    fake = FakeClient(error=LLMUnavailableError('network', '无法连接 LLM 服务（网络异常）'))
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert payload['status'] == 'degraded'
    assert payload['category'] == 'network'
    assert '无法连接' in payload['error']
    assert payload['suggestions'] == []
    # 单次失败不切模式
    with Session(engine) as session:
        assert session.get(Room, room_id).agent_mode == 'collab'


def test_engine_auto_fallback_after_consecutive_failures(tmp_path, monkeypatch):
    """连续 3 次失败 → 自动回退 manual + 系统消息落库（断网降级验收）。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    fake = FakeClient(error=LLMUnavailableError('auth', 'API Key 无效或未授权（401）'))
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    for _ in range(3):
        payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
        assert payload['status'] == 'degraded'

    with Session(engine) as session:
        assert session.get(Room, room_id).agent_mode == 'manual'
        sys_rows = session.exec(
            select(Message).where(Message.room_id == room_id, Message.type == 'sys')
        ).all()
    assert any('自动回退纯人工主持' in m.content for m in sys_rows)


def test_engine_failure_counter_resets_on_success(tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    flaky = FakeClient(error=LLMUnavailableError('network', '网络抖动'))
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: flaky)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: flaky)
    asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert suggestion_engine._failures[room_id] == 2

    flaky.error = None
    flaky.reply = GOOD_REPLY
    payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert payload['status'] == 'ok'
    assert room_id not in suggestion_engine._failures  # 成功清零，不会累计误降级


def test_engine_parses_garbage_as_degraded(tmp_path, monkeypatch):
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    fake = FakeClient(reply='模型固执地输出了一段散文，毫无 JSON 结构。')
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)
    payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert payload['status'] == 'degraded'
    assert payload['category'] == 'bad_response'


def test_engine_uses_newest_player_action_as_latest(tmp_path, monkeypatch):
    """回归：latest_action 必须是窗口内"最新"的玩家消息而非最旧
    （曾因遍历方向写反导致建议永远回应第一轮行动）。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    with Session(engine) as session:
        session.add(Message(room_id=room_id, channel='narrative', sender='张三',
                            content='行动甲：我去搜货架。', payload={'role': 'player'}))
        session.add(Message(room_id=room_id, channel='narrative', sender='老周',
                            content='KP 推进：货架后有什么。', payload={'role': 'kp'}))
        session.add(Message(room_id=room_id, channel='narrative', sender='张三',
                            content='行动乙：我改去撬铁柜。', payload={'role': 'player'}))
        session.commit()

    _, ok = suggestion_engine._collect_context(room_id, focus='')
    assert ok
    # 直接断言上下文（不走 LLM）：先再触发一次生成并检查发送内容
    fake = FakeClient(reply=GOOD_REPLY)
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)
    asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    sent = fake.calls[0]['messages'][1]['content']
    assert '【最新剧情推进】行动乙：我改去撬铁柜。' in sent
    assert '【最新剧情推进】行动甲' not in sent


def test_engine_injects_scenario_brief(tmp_path, monkeypatch):
    """L3 模组骨架：房间未挂模组时回退 data/scenario_brief.txt（5.4：搬到 module_context）。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    brief = tmp_path / 'scenario_brief.txt'
    brief.write_text('【模组】测试模组骨架：时间循环在8月22日。', encoding='utf-8')
    monkeypatch.setattr(module_context, '_SCENARIO_PATH', brief)
    fake = FakeClient(reply=GOOD_REPLY)
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert payload['status'] == 'ok'
    assert '时间循环在8月22日' in fake.calls[0]['messages'][1]['content']
    # 文件不存在时不注入、不报错
    brief.unlink()
    payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert payload['status'] == 'ok'
    assert '时间循环在8月22日' not in fake.calls[1]['messages'][1]['content']


def test_engine_single_flight_coalesces(tmp_path, monkeypatch):
    """同房间在途生成时的新请求并入 pending，完成后补跑一次（不并发轰炸 LLM）。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    fake = FakeClient(reply=GOOD_REPLY, delay=0.3)  # 挂住，保证第二笔落在在途窗口
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    async def scenario():
        task = asyncio.ensure_future(suggestion_engine.generate_and_broadcast(room_id))
        await asyncio.sleep(0.05)  # 等 in-flight 置位
        merged = await suggestion_engine.generate_and_broadcast(room_id)  # 并入 → None
        assert merged is None
        await task
        await asyncio.sleep(0.5)  # 等补跑任务结束
        return fake.calls

    calls = asyncio.run(scenario())
    assert len(calls) == 2  # 原始一次 + 补跑一次
    assert suggestion_engine._failures.get(room_id, 0) == 0


# ---------- LLM 状态接口 ----------

def test_llm_status_and_test_endpoints(client, monkeypatch):
    monkeypatch.setattr('app.api.suggestions.get_settings', lambda: type('S', (), {
        'enabled': True, 'provider': 'dashscope', 'base_url': 'https://x/v1',
        'model': 'qwen-flash', 'api_key_masked': 'sk-ws***DEIg',
        'timeout': 30.0, 'retries': 2, 'mock_mode': False, 'disable_thinking': False,
        'light_base_url': '', 'light_model': '', 'light_api_key_masked': '',
    })())
    monkeypatch.setattr('app.api.suggestions.get_usage',
                        lambda: {'calls': 3, 'prompt_tokens': 1200, 'completion_tokens': 800})
    fake = FakeClient(reply='OK')
    monkeypatch.setattr('app.api.suggestions.get_client', lambda: fake)

    status = client.get('/api/llm/status').json()
    assert status['enabled'] is True and status['model'] == 'qwen-flash'
    assert status['api_key_masked'] == 'sk-ws***DEIg'  # 永不回明文 key
    assert status['usage']['calls'] == 3  # 4.4：token 总账随 status 透出

    test_res = client.post('/api/llm/test').json()
    assert test_res['ok'] is True and test_res['latency_ms'] == 12

    fake.error = LLMUnavailableError('timeout', 'LLM 请求超时（30s）')
    test_res = client.post('/api/llm/test').json()
    assert test_res['ok'] is False and test_res['category'] == 'timeout'


# ---------- LLM 设置面板 API（4.4：PUT /llm/config 写 llm_config 表、GET /llm/models） ----------

def _isolated_config(tmp_path, monkeypatch):
    """config 模块的 DB 引擎指到 tmp 库 + 清掉真实环境变量（隔离 seed 来源）。"""
    import app.llm.config as config_mod
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'cfg.db'}", connect_args={'check_same_thread': False},
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(config_mod, 'engine', test_engine)
    for key in config_mod._ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    config_mod.reset_settings_cache()
    return test_engine


def test_llm_config_saves_to_db_and_keeps_key(client, tmp_path, monkeypatch):
    """保存写 llm_config 表；不传 api_key = 保持现有 key；掩码回显、明文永不回传。"""
    from app.models import LlmConfig
    engine = _isolated_config(tmp_path, monkeypatch)
    # 预置种子行（模拟已从 .env 迁移）
    with Session(engine) as session:
        session.add(LlmConfig(id=1, base_url='https://old.example.com/v1',
                              api_key='sk-ws-real-key-98765', model='qwen-flash'))
        session.commit()

    resp = client.put('/api/llm/config', json={
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen-plus',
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['model'] == 'qwen-plus' and body['provider'] == 'dashscope'
    assert body['api_key_masked'] == 'sk-ws***8765'  # 明文永不回传
    assert body['mock_mode'] is False
    assert len(body['presets']) == 4  # 静态预设表随 status 透出（设置面板快捷填充）
    # DB 行已更新且 key 原样保留
    with Session(engine) as session:
        row = session.get(LlmConfig, 1)
        assert row.model == 'qwen-plus' and row.api_key == 'sk-ws-real-key-98765'
        assert row.base_url == 'https://dashscope.aliyuncs.com/compatible-mode/v1'


def test_llm_config_light_fields(client, tmp_path, monkeypatch):
    """轻任务分级路由：light_* 写库 + 回显；空串 = 清除（跟随主模型）。"""
    from app.models import LlmConfig
    engine = _isolated_config(tmp_path, monkeypatch)
    with Session(engine) as session:
        session.add(LlmConfig(id=1, api_key='sk-main', model='deepseek-v4-pro',
                              base_url='https://api.deepseek.com/v1'))
        session.commit()

    body = client.put('/api/llm/config', json={
        'light_base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'light_api_key': 'sk-ws-light-key-12345678',
        'light_model': 'qwen-flash',
    }).json()
    assert body['light_model'] == 'qwen-flash'
    assert body['light_api_key_masked'] == 'sk-ws***5678'

    with Session(engine) as session:
        row = session.get(LlmConfig, 1)
        assert row.light_model == 'qwen-flash' and row.light_api_key.startswith('sk-ws-light')

    # 空串清除
    body = client.put('/api/llm/config', json={'light_model': ''}).json()
    assert body['light_model'] == ''
    with Session(engine) as session:
        assert session.get(LlmConfig, 1).light_model == ''


def test_llm_config_bad_base_url_rejected(client, tmp_path, monkeypatch):
    _isolated_config(tmp_path, monkeypatch)
    assert client.put('/api/llm/config', json={'base_url': 'ftp://x'}).status_code == 400
    assert client.put('/api/llm/config', json={'model': ''}).status_code == 400
    assert client.put('/api/llm/config', json={'light_base_url': 'ftp://x'}).status_code == 400


def test_llm_config_mock_mode_switch(client, tmp_path, monkeypatch):
    """model=mock 即演示模式：status 带 mock_mode=true（断网兜底验收线）。"""
    _isolated_config(tmp_path, monkeypatch)
    body = client.put('/api/llm/config', json={'model': 'mock'}).json()
    assert body['model'] == 'mock' and body['mock_mode'] is True and body['enabled'] is True


def test_llm_models_endpoint(client, monkeypatch):
    # 未配置：ok=false 提示配置
    monkeypatch.setattr('app.api.suggestions.get_settings', lambda: type('S', (), {
        'enabled': False, 'provider': '', 'model': '', 'mock_mode': False,
    })())
    body = client.get('/api/llm/models').json()
    assert body['ok'] is False and body['category'] == 'not_configured' and body['models'] == []

    # 已配置：透传探测结果
    fake = FakeClient(reply='OK', probe_models=['b-model', 'a-model'])
    monkeypatch.setattr('app.api.suggestions.get_settings', lambda: type('S', (), {
        'enabled': True, 'provider': 'dashscope', 'model': 'qwen-flash', 'mock_mode': False,
    })())
    monkeypatch.setattr('app.api.suggestions.get_client', lambda: fake)
    body = client.get('/api/llm/models').json()
    assert body['ok'] is True and body['models'] == ['b-model', 'a-model']
    assert body['provider'] == 'dashscope'

    # 探测失败（供应商不支持 /models 等）：ok=false 带中文原因，前端手填兜底
    fake.error = LLMUnavailableError('not_found', '接口不存在（404）')
    body = client.get('/api/llm/models').json()
    assert body['ok'] is False and body['category'] == 'not_found'


# ---------- 自动触发 debounce（4.1+ 可选项） ----------

def test_debounce_merges_rapid_messages(tmp_path, monkeypatch):
    """静默期内连发两条：取消重排，停止发言后只生成一次。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    monkeypatch.setattr(suggest_mod, 'AUTO_DEBOUNCE_SECONDS', 0.05)
    fake = FakeClient(reply=GOOD_REPLY)
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    async def scenario():
        suggestion_engine.schedule_auto_generate(room_id)
        await asyncio.sleep(0.01)  # 计时挂起中
        suggestion_engine.schedule_auto_generate(room_id)  # 静默期内再来 → 取消重排
        await asyncio.sleep(0.4)  # 等静默期 + 生成结束

    asyncio.run(scenario())
    assert len(fake.calls) == 1
    assert not suggestion_engine._debounce_tasks


def test_debounce_cancelled_by_manual_trigger(tmp_path, monkeypatch):
    """手动触发取消未到期的静默期计时：不产生额外一次自动生成。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    monkeypatch.setattr(suggest_mod, 'AUTO_DEBOUNCE_SECONDS', 5.0)  # 长静默期，不会自然到期
    fake = FakeClient(reply=GOOD_REPLY)
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: fake)
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: fake)

    async def scenario():
        suggestion_engine.schedule_auto_generate(room_id)
        await asyncio.sleep(0.02)
        payload = await suggestion_engine.generate_and_broadcast(room_id, trigger='manual')
        assert payload['trigger'] == 'manual'
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert len(fake.calls) == 1
    assert not suggestion_engine._debounce_tasks


def test_mock_client_end_to_end(tmp_path, monkeypatch):
    """mock 模式端到端：引擎走 MockLLMClient 全流程，无需网络。"""
    engine = _make_env(tmp_path, monkeypatch)
    room_id = _seed_room(engine)
    from app.llm.mock import MockLLMClient
    monkeypatch.setattr(suggest_mod, 'get_client', lambda: MockLLMClient())
    monkeypatch.setattr(suggest_mod, 'get_light_client', lambda: MockLLMClient())

    payload = asyncio.run(suggestion_engine.generate_and_broadcast(room_id))
    assert payload['status'] == 'ok'
    assert 1 <= len(payload['suggestions']) <= 3
    assert all(s['text'] for s in payload['suggestions'])
    assert suggestion_engine._failures.get(room_id, 0) == 0
