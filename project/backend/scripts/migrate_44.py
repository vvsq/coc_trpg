"""阶段 4.4 存量库增量迁移：不动 coc.db 已有数据的前提下补齐 4.4 结构。

内容：
  1. room 表补 style_id 列（默认 balanced）
  2. 建新表 kp_style / llm_config / llm_usage（create_all 只建不存在的表）

用法（backend/ 下）：
  python -X utf8 scripts/migrate_44.py
"""
from __future__ import annotations

import sqlite3

from sqlmodel import SQLModel

from app.db import DB_PATH, engine, init_db
from app.models import LlmConfig, LlmUsage, KpStyle


def main() -> None:
    if not DB_PATH.exists():
        print(f'数据库不存在（{DB_PATH}），直接 init_db 建全新结构即可')
        init_db()
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {row[1] for row in conn.execute('PRAGMA table_info(room)')}
        if 'style_id' not in cols:
            conn.execute(
                "ALTER TABLE room ADD COLUMN style_id VARCHAR NOT NULL DEFAULT 'balanced'"
            )
            conn.commit()
            print('room 表已补 style_id 列')
        else:
            print('room.style_id 已存在，跳过')
    finally:
        conn.close()

    # 新表：create_all 只创建缺失的表，已有表不受影响
    SQLModel.metadata.create_all(
        engine, tables=[LlmConfig.__table__, LlmUsage.__table__, KpStyle.__table__],
    )
    print('新表 kp_style / llm_config / llm_usage 就绪')
    print('llm_config 首次访问时会自动从 backend/.env seed（无感迁移）')


if __name__ == '__main__':
    main()
