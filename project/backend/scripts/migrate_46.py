"""存量库增量迁移：llm_usage 补 cached_tokens 列（2026-09-10 token 缓存观测）。

背景：实测 DashScope 隐式前缀缓存自动生效（同前缀第二次调用命中率 ~99%），
但记账只存了 prompt_tokens，导致面板上的「输入 27.9 万」是**名义值**、命中率黑盒。
本次补齐 usage.prompt_tokens_details.cached_tokens 的落库与展示。

为什么不用 init_db.py --force：那会连房间 / 消息 / 存档一起清掉。
本脚本幂等，可重复执行；老库跑一次即可（不跑也能启动，只是命中数恒为 0）。

用法（backend/ 下）：
  python -X utf8 scripts/migrate_46.py
"""
from __future__ import annotations

import sqlite3
import sys

from pathlib import Path

# 保证能 import app.* ：无论从哪个目录启动，都把 backend/ 根加入 sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import DB_PATH, init_db


def main() -> None:
    if not DB_PATH.exists():
        print(f'数据库不存在（{DB_PATH}），直接 init_db 建全新结构即可')
        init_db()
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        # 表可能尚未建（首次启动就迁库）：PRAGMA 返回空集合，跳过 ALTER
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if 'llm_usage' not in tables:
            print('llm_usage 表尚不存在，将由 init_db 建表（含新列）')
        else:
            cols = {row[1] for row in conn.execute('PRAGMA table_info(llm_usage)')}
            if 'cached_tokens' not in cols:
                # NOT NULL + 默认 0：历史累计行自动补 0，口径向后兼容
                conn.execute('ALTER TABLE llm_usage ADD COLUMN cached_tokens INTEGER NOT NULL DEFAULT 0')
                conn.commit()
                print('llm_usage 表已补 cached_tokens 列')
            else:
                print('llm_usage.cached_tokens 已存在，跳过')
    finally:
        conn.close()

    init_db()  # 只创建缺失的表，已有数据不受影响
    print('结构就绪')


if __name__ == '__main__':
    main()
