"""存量库增量迁移：新建 room_usage 表（2026-09-10 用户反馈 #3）。

背景：LlmUsage 是全局单行总账，回答不了"一局团花了多少"。本表按 room_id 累计
建房→解散期间的 token 消耗（含缓存命中），KP 台设置面板展示。

为什么不用 init_db.py --force：那会连房间 / 消息 / 存档一起清掉。
本脚本幂等，可重复执行；老库跑一次即可（不跑也能启动，只是本场统计恒为 0）。

用法（backend/ 下）：
  python -X utf8 scripts/migrate_47.py
"""
from __future__ import annotations

import sys

from pathlib import Path

# 保证能 import app.* ：无论从哪个目录启动，都把 backend/ 根加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlmodel import SQLModel

from app.db import DB_PATH, engine, init_db
from app.models import RoomUsage


def main() -> None:
    if not DB_PATH.exists():
        print(f'数据库不存在（{DB_PATH}），直接 init_db 建全新结构即可')
        init_db()
        return

    # create_all 只创建缺失的表，已有表与数据不受影响
    SQLModel.metadata.create_all(engine, tables=[RoomUsage.__table__])
    print('新表 room_usage 就绪')
    init_db()


if __name__ == '__main__':
    main()
