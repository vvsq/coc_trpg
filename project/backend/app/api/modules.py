"""模组库接口 — 阶段 5（goal §7）。

职责边界与鉴权取舍（显式决定，docstring 留痕）：
  模组库是**全局资源**（与 /kp-styles、/llm/test 同级），CRUD 不做房间级
  kp_name 校验——局域网单机部署可接受；上公网前必须收紧为登录态。
  **唯一例外**是房间绑定接口 PUT /rooms/{id}/module，它必须带 kp_name 403
  （见 api/kp.py 同款明文比对）。

端点：
  GET    /modules            列表（轻量：不含 raw_text / parsed 大字段）
  POST   /modules            multipart 上传 → 提取纯文本 → 201（只入库，不解析）
  GET    /modules/{id}       详情（含 raw_text 与 parsed）
  PUT    /modules/{id}       人工修正（name / parsed，校对通道）
  DELETE /modules/{id}       删除；被房间引用时先解绑（房间自动回退兜底骨架）
  POST   /modules/{id}/parse 手动触发 LLM 结构化解析（可选模型）→ 202 立即回包，
                             实际解析走 spawn_background，前端轮询详情看状态
  PUT    /rooms/{id}/module  房间挂载/解绑模组（kp_name 403）→ sys 消息 +
                             module_changed 全员广播（回显由广播驱动）
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.agent.module_parser import (
    MAX_UPLOAD_BYTES,
    PARSED_KEYS,
    describe_error,
    detect_source_type,
    extract_module,
    extract_text,
    normalize_parsed,
    resolve_parse_model,
)
from app.agent.module_context import module_echo
from app.db import engine, get_session
from app.llm.config import get_settings
from app.models import Message, ModuleScenario, Room
from app.tasks import spawn_background
from app.ws.manager import build_envelope, manager

router = APIRouter()

logger = logging.getLogger('app.api.modules')

# 正在解析中的模组 id（进程内）。用途有二：
#   1) 幂等：同模组重复点「开始解析」直接 409，不重复烧 token
#   2) 自愈：进程重启后集合为空，卡在 parsing 的历史行可以重新触发，
#      不会因为上一次解析中断而把模组永久锁死
_PARSING: set[int] = set()


# ==================== 请求体 ====================

class ModuleUpdateRequest(BaseModel):
    """人工修正请求体：字段均可选，只提交要改的部分。

    parsed 是**局部覆盖**语义：只提交出现的顶层键，未出现的键保留原值。
    这样前端按「块」保存（只发被编辑的那一段）不会把其它区块清空；
    整体保存也照常可用（把所有键都带上即可）。
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    parsed: dict | None = None


class ModuleParseRequest(BaseModel):
    """解析请求体。model 为空 = 轻任务模型（未配则主模型）。"""

    model: str | None = Field(default=None, max_length=100)


# ==================== 响应组装（前端展示与列表共用同一份字段语义） ====================

def _meta(row: ModuleScenario) -> dict:
    """列表项：不含大字段，但给出字数与是否已有结构化结果。"""
    return {
        'id': row.id,
        'name': row.name,
        'source_type': row.source_type,
        'source_filename': row.source_filename,
        'char_count': len(row.raw_text or ''),
        'has_parsed': bool(row.parsed),
        'parse_status': row.parse_status,
        'parse_error': row.parse_error,
        'parse_model': row.parse_model,
        'parsed_at': row.parsed_at.isoformat() if row.parsed_at else None,
        'created_at': row.created_at.isoformat(),
    }


def _detail(row: ModuleScenario) -> dict:
    """详情：meta + 原文 + 结构化结果。"""
    return {
        **_meta(row),
        'raw_text': row.raw_text or '',
        'parsed': row.parsed,
    }


def _get_module(session: Session, module_id: int) -> ModuleScenario:
    row = session.get(ModuleScenario, module_id)
    if not row:
        raise HTTPException(status_code=404, detail='模组不存在')
    return row


async def _unbind_rooms(session: Session, module_id: int) -> int:
    """把引用了该模组的房间解绑（回退 data/scenario_brief.txt 兜底骨架）。

    与 PUT /rooms/{id}/module 解绑同语义：落系统消息 + module_changed 广播，
    否则房间还挂在已删除的模组上、前端面板会一直显示旧名字。
    """
    rooms = session.exec(select(Room).where(Room.module_id == module_id)).all()
    if not rooms:
        return 0
    for room in rooms:
        room.module_id = None
        session.add(room)
        session.add(Message(
            room_id=room.id, channel='system', type='sys', sender='system',
            content='挂载的模组已被删除，剧情骨架回退默认方案',
        ))
    session.commit()
    for room in rooms:
        await manager.broadcast(room.id, build_envelope(
            'module_changed', room.id, 'system', 'system',
            {'module': None, 'operator': 'system'},
        ))
    return len(rooms)


# ==================== 端点 ====================

@router.get('/modules')
def list_modules(session: Session = Depends(get_session)):
    """模组列表（新的在前）。不含 raw_text/parsed，避免把整库文本拖进前端。"""
    rows = session.exec(select(ModuleScenario).order_by(ModuleScenario.id.desc())).all()
    return [_meta(row) for row in rows]


@router.post('/modules', status_code=201)
async def upload_module(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """上传模组文件 → 提取纯文本 → 入库（parse_status=pending，等 KP 手动解析）。

    上传即提取但不解析（用户决策 2026-09-10：解析要手动点按钮选模型）。
    """
    filename = (file.filename or '').strip()
    if not filename:
        raise HTTPException(status_code=400, detail='缺少文件名，无法判断格式')
    try:
        detect_source_type(filename)  # 先判格式，避免把 10MB 垃圾读进内存
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f'文件过大（上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB）',
        )
    try:
        source_type, text = extract_text(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stem = filename.rsplit('.', 1)[0].strip() or filename
    row = ModuleScenario(
        name=stem[:100],
        source_type=source_type,
        source_filename=filename[:200],
        raw_text=text,
        parse_status='pending',
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _detail(row)


@router.get('/modules/{module_id}')
def get_module(module_id: int, session: Session = Depends(get_session)):
    """模组详情（原文页签 + 结构化结果页签的数据源）。"""
    return _detail(_get_module(session, module_id))


@router.put('/modules/{module_id}')
def update_module(
    module_id: int,
    body: ModuleUpdateRequest,
    session: Session = Depends(get_session),
):
    """人工修正（校对通道）：改名 / 改结构化结果（局部覆盖）。

    parsed 先与库中现有值做键级合并，再走 normalize_parsed 归一（字段白名单 +
    类型降级 + 超长截断）——前端提交脏数据不会污染存储，漏提交的区块也不会被清空。
    """
    row = _get_module(session, module_id)
    if body.name is not None:
        row.name = body.name.strip()
    if body.parsed is not None:
        patch = {key: value for key, value in body.parsed.items() if key in PARSED_KEYS}
        row.parsed = normalize_parsed({**(row.parsed or {}), **patch})
    session.add(row)
    session.commit()
    session.refresh(row)
    return _detail(row)


@router.delete('/modules/{module_id}', status_code=204)
async def delete_module(module_id: int, session: Session = Depends(get_session)):
    """删除模组；被房间引用时先解绑（房间回退到 scenario_brief.txt 兜底骨架）。"""
    row = _get_module(session, module_id)
    await _unbind_rooms(session, module_id)
    session.delete(row)
    session.commit()


# ==================== 结构化解析（5.2：手动触发 + 可选模型） ====================

async def _run_parse(module_id: int, model: str | None) -> None:
    """后台解析协程：独立 Session（请求级 session 已随 202 响应结束）。

    成功 → parsed + parse_status=ready + parse_model/parsed_at；
    失败 → parse_status=failed + parse_error（原文可读原因，UI 直接展示）。
    无论如何都要把 module_id 从 _PARSING 摘掉，否则该模组被永久锁死。
    """
    try:
        with Session(engine) as session:
            stored = session.get(ModuleScenario, module_id)
            raw_text = stored.raw_text if stored else ''
        if not raw_text.strip():
            raise ValueError('模组原文为空，无法解析')

        parsed, used_model = await extract_module(raw_text, model=model)
    except Exception as exc:  # 解析失败必须落库说明，不能静默
        logger.warning('模组 %s 解析失败：%s', module_id, exc)
        with Session(engine) as session:
            row = session.get(ModuleScenario, module_id)
            if row:
                row.parse_status = 'failed'
                row.parse_error = describe_error(exc)
                session.add(row)
                session.commit()
        return
    finally:
        _PARSING.discard(module_id)

    with Session(engine) as session:
        row = session.get(ModuleScenario, module_id)
        if row:  # 解析期间被删除：什么都不做
            # 再归一一次：extract_module 已归一，但入库边界兜一道，
            # 保证 DB 里 parsed 的"结构恒定"这条不变量不依赖抽取器的实现
            row.parsed = normalize_parsed(parsed)
            row.parse_status = 'ready'
            row.parse_error = ''
            row.parse_model = used_model
            row.parsed_at = datetime.now()
            session.add(row)
            session.commit()


class RoomModuleRequest(BaseModel):
    """房间挂载请求体。module_id=None 表示解绑（回退默认骨架）。"""

    kp_name: str = Field(min_length=1, max_length=50)
    module_id: int | None = None


@router.put('/rooms/{room_id}/module')
async def set_room_module(
    room_id: str,
    body: RoomModuleRequest,
    session: Session = Depends(get_session),
):
    """KP 挂载 / 解绑房间模组（一个房间同时只挂 1 个，用户决策 2026-09-10）。

    写列 + sys 消息落库 + module_changed 全员广播；前端不在本地自改，
    回显由广播驱动（与 kp-style 同款范式）。
    """
    room = session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail='房间不存在')
    if body.kp_name != room.kp_name:
        raise HTTPException(status_code=403, detail='只有 KP 能切换房间模组')

    if body.module_id is None:
        if room.module_id is None:
            return {'module': None, 'unchanged': True}
        room.module_id = None
        content = f'KP {body.kp_name} 解绑了模组，剧情骨架回退默认方案'
        echo: dict | None = None
    else:
        module = session.get(ModuleScenario, body.module_id)
        if not module:
            raise HTTPException(status_code=404, detail='模组不存在')
        if module.parse_status != 'ready':
            raise HTTPException(status_code=400, detail='该模组尚未解析完成，无法挂载')
        if room.module_id == module.id:
            return {'module': module_echo(session, room), 'unchanged': True}
        room.module_id = module.id
        content = f'KP {body.kp_name} 将剧情骨架切换为模组「{module.name}」'
        echo = None

    session.add(room)
    session.add(Message(
        room_id=room_id, channel='system', type='sys', sender='system', content=content,
    ))
    session.commit()
    payload = module_echo(session, room)
    await manager.broadcast(room_id, build_envelope(
        'module_changed', room_id, 'system', 'system',
        {'module': payload, 'operator': body.kp_name},
    ))
    return {'module': payload}


@router.post('/modules/{module_id}/parse', status_code=202)
async def parse_module(
    module_id: int,
    body: ModuleParseRequest,
    session: Session = Depends(get_session),
):
    """手动触发结构化解析（用户决策 2026-09-10：上传不自动解析，解析要选模型）。

    body.model 为空 → 轻任务模型（未配则主模型）；显式传入 → 用该模型，
    便于"先便宜模型跑一遍，不满意换强模型重解析"。
    """
    row = _get_module(session, module_id)
    if module_id in _PARSING:
        raise HTTPException(status_code=409, detail='该模组正在解析中，请稍候')
    if not (row.raw_text or '').strip():
        raise HTTPException(status_code=400, detail='该模组没有可解析的原文，请重新上传')

    settings = get_settings()
    if not settings.enabled:
        raise HTTPException(
            status_code=400,
            detail='未配置 LLM，请先在 KP 控制台「LLM 设置」里填写 API Key 与模型',
        )

    used_model = resolve_parse_model(body.model)
    _PARSING.add(module_id)
    row.parse_status = 'parsing'
    row.parse_error = ''
    row.parse_model = used_model
    session.add(row)
    session.commit()

    spawn_background(_run_parse(module_id, body.model), name=f'module-parse-{module_id}')
    return {'module_id': module_id, 'parse_status': 'parsing', 'parse_model': used_model}
