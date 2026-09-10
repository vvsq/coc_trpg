"""技能基础值解析（规则层纯函数）。

存在的理由（2026-09-10 实测反馈修复）：此前「检定下放」只能点名玩家**卡上已加点**
的技能——`tools._skill_value` 只在 `card_data['skills']` 里找，找不到直接报
「技能表里没有该技能」。这与规则书相悖：**任何技能都可以尝试**，没加点就是它的
基础值（聆听 20、侦查 25、闪避 = DEX/2）。

规则书依据：技能基础值以技能表为准（`app/seed/skills.json` → `skill` 表 `base` 列）；
少数技能的基础值由属性表达式给出（`base_expr`，见 `scripts/parse_seed_data.py`）：
  - 闪避 = DEX / 2（向下取整，规则书第四章「闪避」）
  - 母语 = EDU（规则书第三章 EDU 属性说明）
其余形式（含 base 与 base_expr 都为空的「自定义技能」）返回 None，由调用方决定
是拒绝还是放行。
"""
from __future__ import annotations

import re
from typing import Mapping

# 表达式形式：三字母属性名，或 属性名/正整数（目前只有 DEX/2）
_EXPR_RE = re.compile(r'^([A-Z]{3})(?:/(\d+))?$')


def base_expr_value(expr: str, attrs: Mapping[str, int] | None) -> int | None:
    """把 `'DEX/2'` / `'EDU'` 解析成具体基础值；无法解析或属性缺失返回 None。

    纯函数、不查库：调用方负责把技能行的 base_expr 与角色属性传进来。
    """
    token = (expr or '').strip().upper().replace(' ', '')
    if not token:
        return None
    match = _EXPR_RE.match(token)
    if not match:
        return None
    key, divisor = match.group(1), match.group(2)
    raw = (attrs or {}).get(key)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if divisor:
        value //= int(divisor)
    return max(0, value)
