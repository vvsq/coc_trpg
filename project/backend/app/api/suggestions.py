"""协同建议接口 — 阶段 4.1（goal §7；模式开关 + 手动触发 + LLM 状态/连通性）。

职责边界（鉴权沿用 kp.py 的轻量模式：body 带 kp_name 明文比对，403 保护）：
  - PUT  /rooms/{id}/agent-mode          KP 切换 Agent 模式（manual/collab），
                                          sys 消息落库 + agent_mode_changed 全员广播
  - POST /rooms/{id}/suggestions/generate KP 手动触发生成：立即 202 返回 request_id，
                                          结果经 WS suggestions 信封只发 KP（不阻塞）
  - GET  /llm/status                     供应商配置状态（key 掩码）+ 预设表 + token 总账
  - PUT  /llm/config                     KP 设置面板保存（4.4 起写 llm_config 表，DB 权威）
  - GET  /llm/models                     实时探测供应商可用模型（client.models.list()）
  - POST /llm/test                       最小连通性测试（KP 验证配置用）
4.4 KP 风格（§6.2）：
  - GET/POST /kp-styles、DELETE /kp-styles/{id}   内置 + 自定义风格的查询/保存/删除
  - PUT /rooms/{id}/kp-style                     房间实时切换风格（全员广播 kp_style_changed）

自动触发在 app/ws/rooms.py 的 chat_send 分支（剧情推进 → debounce 后台生成）。
"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.agent.kp_styles import (
    create_custom_style,
    delete_custom_style,
    get_style,
    list_styles,
    style_echo,
)
from app.agent.suggest import suggestion_engine
from app.db import get_session
from app.llm.config import get_settings, save_settings
from app.llm.providers import PROVIDER_PRESETS
from app.llm.provider import LLMUnavailableError, get_client
from app.llm.usage import get_usage
from app.models import Message, Room
from app.tasks import spawn_background
from app.ws.manager import build_envelope, manager

router = APIRouter()

# 决策 D10：4.1 两档 + 4.2 加 auto 全自动主持
AGENT_MODES = ('manual', 'collab', 'auto')

# 模式切换的系统提示文案（键为目标模式）
_MODE_LABELS = {
    'manual': '关闭了协同建议模式',
    'collab': '开启了协同建议模式',
    'auto': '开启了全自动主持模式（AI KP 接管叙事，可随时切回）',
}


class AgentModeRequest(BaseModel):
    """模式切换请求体。mode：manual 纯人工 / collab 协同建议 / auto 全自动主持。"""

    kp_name: str = Field(min_length=1, max_length=50)
    mode: str = Field(pattern='^(manual|collab|auto)$')


class SuggestionGenerateRequest(BaseModel):
    """手动生成请求体。focus 是 KP 的可选附加指令（如「偏向悬疑」）。"""

    kp_name: str = Field(min_length=1, max_length=50)
    focus: str = Field(default='', max_length=200)


class LlmConfigRequest(BaseModel):
    """KP 设置面板保存体。字段均可选；api_key 空 = 保持现有（掩码语义）。

    4.4：light_* 是轻任务分级路由（留空=跟随主模型）；写 llm_config 表（DB 权威）。
    4.4+：timeout/retries/disable_thinking 运行时可调（此前只能在首次 seed 生效，
    DB 权威后设置面板改不了导致混合推理模型 30s 超时无法自救——用户实测反馈修复）。
    """

    base_url: str | None = Field(default=None, max_length=300)
    api_key: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=100)
    light_base_url: str | None = Field(default=None, max_length=300)
    light_api_key: str | None = Field(default=None, max_length=300)
    light_model: str | None = Field(default=None, max_length=100)
    timeout: float | None = Field(default=None, ge=5, le=3600)
    retries: int | None = Field(default=None, ge=0, le=5)
    disable_thinking: bool | None = None


class KpStyleCreateRequest(BaseModel):
    """自定义风格保存体（新建与导入 JSON 同一入口）。params 为四旋钮 JSON。"""

    name: str = Field(min_length=1, max_length=30)
    params: dict


class KpStyleSwitchRequest(BaseModel):
    """房间切换风格请求体。style_id = 内置 id 或 kp_style 表 id。"""

    kp_name: str = Field(min_length=1, max_length=50)
    style_id: str = Field(min_length=1, max_length=40)


def _status_payload(s) -> dict:
    """GET /llm/status 与 PUT /llm/config 共用的响应结构（key 永不回传明文）。"""
    return {
        'enabled': s.enabled,
        'provider': s.provider,
        'base_url': s.base_url,
        'model': s.model,
        'api_key_masked': s.api_key_masked,
        'timeout': s.timeout,
        'retries': s.retries,
        'disable_thinking': s.disable_thinking,
        'mock_mode': s.mock_mode,
        'light_base_url': s.light_base_url,
        'light_model': s.light_model,
        'light_api_key_masked': s.light_api_key_masked,
        'usage': get_usage(),
        'presets': [
            {
                'key': key,
                'label': preset['label'],
                'base_url': preset['base_url'],
                'models': preset['models'],
                'key_hint': preset['key_hint'],
            }
            for key, preset in PROVIDER_PRESETS.items()
        ],
    }


@router.put('/rooms/{room_id}/agent-mode')
async def set_agent_mode(
    room_id: str,
    body: AgentModeRequest,
    session: Session = Depends(get_session),
):
    """KP 切换 Agent 模式：写列 + sys 消息 + agent_mode_changed 全员广播
    （照 3.3 场景接口范式：不在本地自改，回显由广播驱动）。"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能切换 Agent 模式')
    if body.mode == room.agent_mode:
        return {'agent_mode': room.agent_mode, 'unchanged': True}

    room.agent_mode = body.mode
    session.add(room)
    session.add(Message(
        room_id=room_id, channel='system', type='sys', sender='system',
        content=f'KP {body.kp_name} {_MODE_LABELS[body.mode]}',
    ))
    session.commit()
    suggestion_engine.cancel_auto(room_id)  # 切模式后不保留未到期的自动生成计时
    await manager.broadcast(room_id, build_envelope(
        'agent_mode_changed', room_id, 'system', 'system',
        {'agent_mode': body.mode, 'operator': body.kp_name},
    ))
    return {'agent_mode': body.mode}


@router.post('/rooms/{room_id}/suggestions/generate', status_code=202)
async def generate_suggestions(
    room_id: str,
    body: SuggestionGenerateRequest,
    session: Session = Depends(get_session),
):
    """KP 手动触发建议生成：校验后把生成丢进后台协程，立即返回 202。

    结果统一走 WS suggestions 信封（与自动触发同一条通路），KP 面板按
    request_id 丢弃过期批次。生成期间聊天与其他面板完全不受阻塞（验收项）。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能触发建议生成')
    if room.agent_mode != 'collab':
        raise HTTPException(status_code=400, detail='协同建议模式未开启')

    request_id = uuid.uuid4().hex[:12]
    spawn_background(
        suggestion_engine.generate_and_broadcast(
            room_id, request_id=request_id, focus=body.focus.strip(), trigger='manual',
        ),
        name=f'suggestions-manual-{room_id}',
    )
    return {'request_id': request_id, 'status': 'generating'}


@router.get('/llm/status')
async def llm_status():
    """LLM 供应商配置状态（key 只回掩码）+ 静态预设表（设置面板快捷填充用）。"""
    return _status_payload(get_settings())


@router.put('/llm/config')
async def llm_config(body: LlmConfigRequest):
    """KP 设置面板保存（4.4）：写 llm_config 表（DB 权威，.env 仅首次 seed）。

    api_key/light_api_key 空 = 保持现有 key（前端只回掩码，明文从不落接口日志）；
    light_* 留空 = 清除轻任务配置（跟随主模型）；model=mock 启用 MockLLMClient。
    """
    updates: dict[str, str] = {}
    if body.base_url is not None:
        value = body.base_url.strip()
        if value and not re.match(r'^https?://', value):
            raise HTTPException(status_code=400, detail='base_url 必须以 http:// 或 https:// 开头')
        updates['base_url'] = value
    if body.api_key:  # 空串/缺省 = 保持现有
        updates['api_key'] = body.api_key.strip()
    if body.model is not None:
        value = body.model.strip()
        if not value:
            raise HTTPException(status_code=400, detail='model 不能为空')
        updates['model'] = value
    # 轻任务：显式传 None 不动；传空串 = 清除（跟随主模型）
    for field in ('light_base_url', 'light_api_key', 'light_model'):
        value = getattr(body, field)
        if value is not None:
            v = value.strip()
            if field.endswith('base_url') and v and not re.match(r'^https?://', v):
                raise HTTPException(
                    status_code=400, detail='light_base_url 必须以 http:// 或 https:// 开头',
                )
            updates[field] = v
    # 运行时参数（4.4+）：timeout/retries/disable_thinking 直通 save_settings
    if body.timeout is not None:
        updates['timeout'] = float(body.timeout)
    if body.retries is not None:
        updates['retries'] = int(body.retries)
    if body.disable_thinking is not None:
        updates['disable_thinking'] = bool(body.disable_thinking)
    s = save_settings(updates) if updates else get_settings()
    return _status_payload(s)


@router.get('/llm/models')
async def llm_models():
    """实时探测供应商可用模型（D11：静态表必过期，探测 + 手填兜底）。

    供应商不支持 /models 时返回 ok=false + 中文原因，前端回退预设推荐 + 手填。
    """
    s = get_settings()
    if not s.enabled:
        return {'ok': False, 'category': 'not_configured', 'models': [],
                'error': '未配置 LLM_API_KEY / LLM_MODEL（backend/.env）'}
    try:
        models = await get_client().list_models()
    except LLMUnavailableError as exc:
        return {'ok': False, 'category': exc.category, 'models': [], 'error': exc.message}
    return {'ok': True, 'models': models, 'provider': s.provider}


@router.post('/llm/test')
async def llm_test():
    """最小连通性测试：真实打一次 LLM。失败也 200，ok=false 带中文原因。

    4.4+：单独配置了轻任务模型时一并 ping（此前轻模型是测试盲区——
    主模型 ping 通过而建议链路超时，KP 无从分辨）。
    """
    from app.llm.provider import get_light_client

    s = get_settings()
    if not s.enabled:
        return {'ok': False, 'category': 'not_configured',
                'error': '未配置 LLM_API_KEY / LLM_MODEL（llm_config / .env）'}
    try:
        latency = await get_client().ping()
    except LLMUnavailableError as exc:
        return {'ok': False, 'category': exc.category, 'error': exc.message}
    result: dict = {'ok': True, 'latency_ms': latency, 'model': s.model, 'provider': s.provider}
    if getattr(s, 'light_ready', False):  # getattr：兼容测试用轻量 fake 配置
        try:
            result['light_latency_ms'] = await get_light_client().ping()
            result['light_model'] = s.light_model
        except LLMUnavailableError as exc:
            result['light_ok'] = False
            result['light_error'] = exc.message
    return result


# ==================== 4.4：KP 风格系统（goal §6.2） ====================

@router.get('/kp-styles')
def kp_styles_list(session: Session = Depends(get_session)):
    """内置 + 自定义风格列表（KP 风格面板与自定义管理弹窗的数据源）。"""
    return list_styles(session)


@router.post('/kp-styles')
def kp_styles_create(body: KpStyleCreateRequest, session: Session = Depends(get_session)):
    """保存自定义风格（新建 / 导入 JSON 同一入口）。返回完整列表便于前端刷新。"""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail='风格名称不能为空')
    row = create_custom_style(session, body.name, body.params)
    result = list_styles(session)
    result['created'] = {'id': row.id, 'name': row.name, 'params': row.params}
    return result


@router.delete('/kp-styles/{style_id}')
def kp_styles_delete(style_id: str, session: Session = Depends(get_session)):
    """删除自定义风格（内置 id 405）；引用它的房间自动回退平衡 Keeper。"""
    if style_id in ('balanced', 'immersive', 'teaching'):
        raise HTTPException(status_code=405, detail='内置风格不能删除')
    if not delete_custom_style(session, style_id):
        raise HTTPException(status_code=404, detail='自定义风格不存在')
    return {'deleted': style_id}


@router.put('/rooms/{room_id}/kp-style')
async def set_room_style(
    room_id: str,
    body: KpStyleSwitchRequest,
    session: Session = Depends(get_session),
):
    """KP 切换房间 KP 风格：写列 + sys 消息落库 + kp_style_changed 全员广播
    （goal §6.2：房间内实时切换且全员可见提示；不在本地自改，回显由广播驱动）。"""
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能切换 KP 风格')
    style = get_style(session, body.style_id)
    if style is None:
        raise HTTPException(status_code=400, detail='风格不存在')
    if body.style_id == room.style_id:
        return {'style': style_echo(session, room), 'unchanged': True}

    room.style_id = body.style_id
    session.add(room)
    session.add(Message(
        room_id=room_id, channel='system', type='sys', sender='system',
        content=f'KP {body.kp_name} 将 KP 风格切换为「{style["name"]}」',
    ))
    session.commit()
    await manager.broadcast(room_id, build_envelope(
        'kp_style_changed', room_id, 'system', 'system',
        {**style_echo(session, room), 'operator': body.kp_name},
    ))
    return {'style': style_echo(session, room)}
