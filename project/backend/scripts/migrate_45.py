"""阶段 5 存量库增量迁移：不动 coc.db 已有数据的前提下补齐模组库结构。

内容：
  1. room 表补 module_id 列（可空；空 = 该房间回退 scenario_brief.txt 兜底）
  2. 建新表 module_scenario（create_all 只建不存在的表）

为什么不用 init_db.py --force：那会连房间 / 消息 / 存档一起清掉。
本脚本幂等，可重复执行。

用法（backend/ 下）：
  python -X utf8 scripts/migrate_45.py
"""
from __future__ import annotations

import sqlite3
import sys

from pathlib import Path

# 保证能 import app.* ：无论从哪个目录启动，都把 backend/ 根加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlmodel import SQLModel

from app.db import DB_PATH, engine, init_db
from app.models import ModuleScenario


def main() -> None:
    if not DB_PATH.exists():
        print(f'数据库不存在（{DB_PATH}），直接 init_db 建全新结构即可')
        init_db()
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {row[1] for row in conn.execute('PRAGMA table_info(room)')}
        if 'module_id' not in cols:
            # 不写 REFERENCES：SQLite 的 ADD COLUMN 不允许带外键约束，
            # 且 SQLite 默认不强制外键；解绑逻辑在应用层显式执行
            # （api/modules.py::_unbind_rooms）
            conn.execute('ALTER TABLE room ADD COLUMN module_id INTEGER')
            conn.commit()
            print('room 表已补 module_id 列')
        else:
            print('room.module_id 已存在，跳过')
    finally:
        conn.close()

    # 新表：create_all 只创建缺失的表，已有表不受影响
    SQLModel.metadata.create_all(engine, tables=[ModuleScenario.__table__])
    print('新表 module_scenario 就绪')


if __name__ == '__main__':
    main()
