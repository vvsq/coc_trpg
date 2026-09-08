"""WS 连接管理 — app/ws 包（阶段 3.1）。

职责边界：
  - manager.py 只管"谁在线、怎么广播"，不懂业务消息的含义
  - 信封构造 build_envelope() 也放这里，让 REST/WS 两层引用同一份协议格式（§5.3）

设计要点：
  - active 按 room_id 分组；broadcast 前先 list() 拷贝，广播途中断开的连接
    不会在遍历时抛 RuntimeError
  - 单个连接发送失败只摘除该连接，不让一个坏连接拖垮整个房间的广播
  - seq 序号与 room_state 全量补齐属阶段 3.4，信封先预留协议形态

3.4 补充（服务端心跳踢除）：vite ws 代理抖动时 close 帧可能不转发到服务端，
遗留僵尸连接重复收广播、把成员列表撑虚胖。last_seen 记录每连接最后一次
活跃时间（收到任何消息含 ping 即 touch），由 ws/rooms.py 的后台协程定期
踢除超时连接（客户端 15s ping，3 个周期无消息视为死链）。
"""
import time
from datetime import datetime

from fastapi import WebSocket


def build_envelope(
    msg_type: str,
    room_id: str,
    sender: str,
    channel: str,
    payload: dict,
) -> dict:
    """统一消息信封（goal.md §5.3）。

    channel: narrative 剧情流 / ooc 闲聊流 / system 系统提示。
    系统级消息（进出房/member_changed/pong/error）固定走 system 频道。
    """
    return {
        'type': msg_type,
        'room_id': room_id,
        'sender': sender,
        'channel': channel,
        'payload': payload,
        'ts': datetime.now().isoformat(timespec='seconds'),
    }


class ConnectionManager:
    """room_id → 该房间的全部活跃连接。

    identities 额外记录 id(ws) → join 注册的名字：room_member 表是持久
    花名册（离线不删），而 member_changed 要反映"当前在线"的成员，
    因此以连接为准、名字从这里查。
    """

    def __init__(self) -> None:
        self.active: dict[str, list[WebSocket]] = {}
        self.identities: dict[int, str] = {}
        self.last_seen: dict[int, float] = {}  # id(ws) → 最后活跃时间戳（秒）

    def connect(self, room_id: str, ws: WebSocket) -> None:
        self.active.setdefault(room_id, []).append(ws)
        self.last_seen[id(ws)] = time.monotonic()

    def touch(self, ws: WebSocket) -> None:
        """刷新连接活跃时间（服务端心跳踢除的判活依据）。"""
        self.last_seen[id(ws)] = time.monotonic()

    def set_identity(self, ws: WebSocket, player_name: str) -> None:
        """join 成功后登记连接对应的玩家名。"""
        self.identities[id(ws)] = player_name

    def disconnect(self, room_id: str, ws: WebSocket) -> None:
        """摘除连接；房间空了顺手清掉键，防止 dict 无限膨胀。"""
        conns = self.active.get(room_id)
        if conns is None:
            self.last_seen.pop(id(ws), None)
            return
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self.active.pop(room_id, None)
        self.identities.pop(id(ws), None)
        self.last_seen.pop(id(ws), None)

    def stale_connections(self, timeout: float) -> list[tuple[str, WebSocket]]:
        """返回超时未活跃的 (room_id, ws) 列表（供踢除协程扫描，不做摘除）。"""
        now = time.monotonic()
        stale: list[tuple[str, WebSocket]] = []
        for room_id, conns in self.active.items():
            for ws in list(conns):
                if now - self.last_seen.get(id(ws), now) > timeout:
                    stale.append((room_id, ws))
        return stale

    async def broadcast(self, room_id: str, message: dict) -> None:
        """向房间全员广播；失败的连接静默摘除，不影响其余成员。"""
        for ws in list(self.active.get(room_id, [])):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 连接已死/正在关闭，摘掉即可
                self.disconnect(room_id, ws)

    async def broadcast_except(self, room_id: str, message: dict, exclude_ws: WebSocket) -> None:
        """向房间全员广播但跳过 exclude_ws。

        用途：进房系统消息排除 joiner 本人——服务端先落库后广播，本人触发的
        历史回放与实时广播存在竞态，排除后本人只从回放里看到这一行，不双份。
        """
        for ws in list(self.active.get(room_id, [])):
            if ws is exclude_ws:
                continue
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 同 broadcast：坏连接摘除不拖垮他人
                self.disconnect(room_id, ws)

    async def close_room(self, room_id: str, code: int = 4404) -> None:
        """解散房间时关闭该房间全部连接：逐个 close + 清理登记表。

        code 用 4404（应用自定义段 4000-4999）：客户端可据此识别"房间已不存在"
        而放弃重连。房间没有连接时为安全空操作。
        """
        conns = self.active.pop(room_id, [])
        for ws in conns:
            self.identities.pop(id(ws), None)
            self.last_seen.pop(id(ws), None)
            try:
                await ws.close(code=code)
            except Exception:  # noqa: BLE001 连接已死，清理目的已达成
                pass

    async def broadcast_to_roles(self, room_id: str, message: dict, roles: set[str]) -> None:
        """定向广播（D8 收紧，3.3）：只发给 role 命中 roles 的连接。

        以 identities 对出 room_member 花名册的 role——花名册每次现查（离线
        成员无连接自然跳过，换角色/重进也总是新鲜值）；不在线或不配角色的
        连接一律不收。发送失败同样静默摘除。

        局部导入 db/models：manager 保持"只管谁在线、怎么广播"的基础设施定位，
        不在模块级依赖存储层。
        """
        from sqlmodel import Session, select

        from app.db import engine
        from app.models import RoomMember

        with Session(engine) as session:
            roster = {
                m.player_name: m.role
                for m in session.exec(
                    select(RoomMember).where(RoomMember.room_id == room_id)
                ).all()
            }
        for ws in list(self.active.get(room_id, [])):
            name = self.identities.get(id(ws))
            if not name or roster.get(name) not in roles:
                continue
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 同 broadcast：坏连接摘除不拖垮他人
                self.disconnect(room_id, ws)


# 全局唯一实例：与 db.engine 同级的进程级单例，路由层直接 import 使用
manager = ConnectionManager()
