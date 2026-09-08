"""把 other/table/coc七版武器列表.txt 的「##武器」区块解析成 app/seed/weapons.json。

数据源行格式（人工维护，※字段顺序行是权威列序）：
  `N.武器名,技能,伤害,射程,贯穿,每轮,装弹量,故障值,常见时代,价格,发明时间,类型分组,时代标记`
  `  - 说明文字` 行并入上一件武器的 notes（如电锯大失败、阔剑弹道等特殊规则）

解析约定：
  - 装弹量/价格/射程等列原样保留字符串（"20/30/32"、"——"、"1 or 2"），卡片侧
    Weapon.ammo 为 int|str，数字串由 Pydantic 归一；故障值解析 int，"——"置 None。
  - 只解析「##武器」到「##分组注释」之间的条目（分组注释/爆炸伤害衰减是规则说明，
    编号 105+ 不再是武器）。

用法: python -X utf8 scripts/parse_weapons.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # COC_project/
WEAPON_TXT = ROOT / 'other' / 'table' / 'coc七版武器列表.txt'
OUT_PATH = Path(__file__).resolve().parents[1] / 'app' / 'seed' / 'weapons.json'

FIELDS = ['name', 'skill_name', 'damage', 'rng', 'penetrate', 'attacks',
          'ammo', 'malfunction', 'era', 'price', 'invented', 'category', 'era_tags']


def parse_malfunction(raw: str) -> int | None:
    """'97' -> 97；'——'/'N/A' -> None（卡片侧默认 100）。"""
    raw = raw.strip()
    return int(raw) if raw.isdigit() else None


def parse_weapons(text: str) -> list[dict]:
    weapons: list[dict] = []
    in_weapon_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('##'):
            in_weapon_block = stripped == '##武器'
            continue
        if not in_weapon_block or stripped.startswith('※'):
            continue

        if stripped.startswith('-'):
            # 说明行：属于上一件武器的特殊规则
            if weapons:
                weapons[-1].setdefault('notes', []).append(stripped.lstrip('- ').strip())
            continue

        # 条目行：N.名称,技能,伤害,...
        head, _, rest = stripped.partition('.')
        cols = rest.split(',')
        if not head.strip().isdigit() or len(cols) < len(FIELDS) - 1:
            # 分组注释区的补充行等非武器条目，跳过
            continue
        cols += [''] * (len(FIELDS) - len(cols))  # 行尾空列容忍
        row = dict(zip(FIELDS, (c.strip() for c in cols)))
        row['id'] = int(head.strip())
        row['malfunction'] = parse_malfunction(row['malfunction'])
        weapons.append(row)
    return weapons


def main() -> None:
    text = WEAPON_TXT.read_text(encoding='utf-8')
    weapons = parse_weapons(text)
    OUT_PATH.write_text(
        json.dumps(weapons, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(f'{len(weapons)} 件武器 -> {OUT_PATH}')


if __name__ == '__main__':
    sys.exit(main())
