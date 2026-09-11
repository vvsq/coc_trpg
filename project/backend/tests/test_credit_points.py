"""信用评级占用职业点 — CoC7 规则第三章 3.3（2026-09-11 用户实测反馈）。

口径来源：《第七版守秘人规则书 Version2002》
- P31「3.3 第三步：决定技能并分配技能点」：本职技能点"也可以分配给信用评级…
  你可以在信用评级上任意投入技能点，只要不超过职业给定的范围就好"；
  同页「信用评级」小节："调查员的信用评级初始为 0"。
- P32 示例：记者"妹子首先在信用评级上分配了 41 点本职技能点"。

即信用评级的最终值**全额**占用职业点（不是从职业下限起算的差额）。
落地：`validate_allocation(credit=)` 把 credit 计入职业点占用；
`api/cards.py` 传入 `payload.credit`。
"""
from fastapi.testclient import TestClient

from app.rules.occupation import (
    SkillAllocation,
    build_budget,
    get_occupation,
    validate_allocation,
)
from app.schemas.investigator import Attributes

# 八项属性 Σ=460 的合法购点组合（与 test_skill_cap.py / test_purchase.py 同一口径）
VALID_ATTRS = {
    'STR': 55, 'CON': 55, 'SIZ': 55, 'DEX': 55, 'APP': 55,
    'INT': 60, 'POW': 60, 'EDU': 65, 'LUK': 45,
}


def _parts(total: int) -> list[int]:
    """把 total 点职业点分摊成若干行，每行 ≤85（base 5 → 合计 90 不碰创建上限）。"""
    out: list[int] = []
    while total > 0:
        take = min(85, total)
        out.append(take)
        total -= take
    return out


def _allocs(total: int) -> list[SkillAllocation]:
    return [
        SkillAllocation(name=f'技能{i}', base=5, occupation_points=p, is_occupation_skill=True)
        for i, p in enumerate(_parts(total))
    ]


def _skill_row(i: int, occ_pts: int) -> dict:
    return {'name': f'技能{i}', 'slot': 0, 'detail': '', 'base': 5,
            'occupation_points': occ_pts, 'interest_points': 0,
            'is_occupation_skill': True}


def _post(client: TestClient, occ_id: int, credit: int, skills: list[dict]):
    return client.post('/api/cards', json={
        'name': '信用员', 'gender': '女', 'age': 25, 'era': 'modern',
        'occupation_id': occ_id,
        'credit': credit,
        'attributes': VALID_ATTRS,
        'skills': skills,
    })


def test_credit_fully_counts_toward_occupation_points():
    """技能占满 (预算-信用) 时信用评级正好花完预算 → 合法；再多 1 点即超支并点名。"""
    occ = get_occupation('精神病医生')
    attrs = Attributes(**VALID_ATTRS)
    budget = build_budget(occ, attrs)
    credit = occ.credit_min  # 10

    exact = _allocs(budget.occupation_points - credit)
    assert validate_allocation(occ, attrs, exact, credit=credit) == []

    over = _allocs(budget.occupation_points - credit + 1)
    problems = validate_allocation(occ, attrs, over, credit=credit)
    assert any('信用评级占用 10' in p for p in problems)


def test_credit_default_zero_keeps_legacy_behavior():
    """credit 缺省（0）时行为与历史一致：超支文案不出现信用评级字样（兼容老调用）。"""
    occ = get_occupation('精神病医生')
    attrs = Attributes(**VALID_ATTRS)
    budget = build_budget(occ, attrs)

    problems = validate_allocation(occ, attrs, _allocs(budget.occupation_points + 1))
    assert any('职业点超支' in p for p in problems)
    assert not any('信用评级' in p for p in problems)


def test_create_card_includes_credit_in_budget(client, seed_occupation):
    """端到端：技能 + 信用 = 预算 → 201；技能多占 5 点 → 400 且点名信用评级占用。"""
    (occ_id,) = seed_occupation('精神病医生')
    occ = get_occupation('精神病医生')
    budget = build_budget(occ, Attributes(**VALID_ATTRS))
    credit = occ.credit_min  # 10

    ok_skills = [_skill_row(i, p) for i, p in enumerate(_parts(budget.occupation_points - credit))]
    res = _post(client, occ_id, credit, ok_skills)
    assert res.status_code == 201, res.text

    bad_skills = [
        _skill_row(i, p) for i, p in enumerate(_parts(budget.occupation_points - credit + 5))
    ]
    res2 = _post(client, occ_id, credit, bad_skills)
    assert res2.status_code == 400, res2.text
    assert '信用评级占用 10' in res2.json()['detail']
