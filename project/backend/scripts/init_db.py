"""初始化数据库：建表 + 灌入职业/技能种子数据。

用法:
  python -X utf8 scripts/init_db.py             # 已存在 coc.db 时报错退出（防手滑）
  python -X utf8 scripts/init_db.py --force     # 先删旧库再重建（迁移约定的唯一手段）

前提: 先跑过 parse_seed_data.py 生成 app/seed/occupations.json 与 skills.json。
"""
from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from sqlmodel import Session

from app.models import OccupationRow, SkillRow

# 保证能 import app.* ：脚本在 backend/ 下运行时，PYTHONPATH 需包含 backend/
# （示例命令已带 cd backend && set PYTHONPATH=.）
from app.db import DB_PATH, engine, init_db
from app.schemas.occupation import Occupation

SEED_DIR = Path(__file__).resolve().parents[1] / "app" / "seed"


def main() -> None:
    parser = argparse.ArgumentParser(description='初始化 SQLite 数据库')
    parser.add_argument('--force', action='store_true', help='删除已有数据库后重建')
    args = parser.parse_args()

    if DB_PATH.exists():
        if not args.force:
            print(f'数据库已存在: {DB_PATH}')
            print('表结构改动后用 --force 删库重建（当前无增量迁移）。')
            sys.exit(1)
        DB_PATH.unlink()
        print('已删除旧数据库')

    # 1) 建表
    init_db()

    # 2) 灌种子数据
    occ_file = SEED_DIR / 'occupations.json'
    skill_file = SEED_DIR / 'skills.json'
    if not occ_file.exists() or not skill_file.exists():
        print('缺少种子文件，请先运行: python -X utf8 scripts/parse_seed_data.py')
        sys.exit(1)

    occ_items = json.loads(occ_file.read_text(encoding='utf-8'))
    skill_items = json.loads(skill_file.read_text(encoding='utf-8'))

    # 导入前先做一次 schema 校验，坏数据直接失败而不是入库后炸
    occupations = [Occupation.model_validate(item) for item in occ_items]

    with Session(engine) as session:
        # 职业：占位对象先落库拿不到自增没关系（主键是 xlsx 序号），直接构造
        for occ in occupations:
            session.add(
                OccupationRow(
                    id=occ.id,
                    name=occ.name,
                    era=occ.era,
                    data=occ.model_dump(mode='json'),
                )
            )

        # 技能：逐行插入
        for s in skill_items:
            session.add(SkillRow(**s))

        session.commit()

        print(f'建库完成: {DB_PATH}')
        print(f'职业 {len(occupations)} 条 -> occupation 表')
        print(f'技能 {len(skill_items)} 条 -> skill 表')
        print(f'基础值缺失 {sum(1 for s in skill_items if s.get("base") is None)} 条（需规则书补齐）')


if __name__ == '__main__':
    main()
