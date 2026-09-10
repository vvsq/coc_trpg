"""单技能创建上限校验（2026-09-10，用户实测反馈 #6）。

口径来源：已通读《第七版守秘人规则书 Version2002》第三章「创建调查员」全节
（3.1~3.6，含第三步「决定技能并分配技能点」正文与章末「快速参考：创建调查员」），
**规则书未载明技能创建上限**（只规定职业点/兴趣点预算、信用评级范围、未分配点数作废），
故采用 KP 裁定值 SKILL_MAX_AT_CREATION = 90，做成常量以便回退到 80。

判定范围：只拦「被点数推过上限」的技能；`base` 本身已超上限的（母语 = EDU，EDU 可到 99）
不误报——否则 EDU 90 以上的角色建卡必挂。
"""
from fastapi.testclient import TestClient

from app.rules.occupation import (
    SKILL_MAX_AT_CREATION,
    SkillAllocation,
    get_occupation,
    validate_allocation,
)
from app.schemas.investigator import Attributes

# 八项属性 Σ=460 的合法购点组合（与 test_purchase.py 同一口径）
VALID_ATTRS = {
    'STR': 55, 'CON': 55, 'SIZ': 55, 'DEX': 55, 'APP': 55,
    'INT': 60, 'POW': 60, 'EDU': 65, 'LUK': 45,
}


def _post(client: TestClient, occ_id: int, credit: int, skills: list[dict]):
    return client.post('/api/cards', json={
        'name': '上限员', 'gender': '女', 'age': 25, 'era': 'modern',
        'occupation_id': occ_id,
        'credit': credit,
        'attributes': VALID_ATTRS,
        'skills': skills,
        'gen_mode': 'purchase',
    })


def _skill(name: str, base: int, *, interest: int = 0, occ_pts: int = 0,
           is_occ: bool = False) -> dict:
    return {'name': name, 'slot': 0, 'detail': '', 'base': base,
            'occupation_points': occ_pts, 'interest_points': interest,
            'is_occupation_skill': is_occ}


def test_skill_over_cap_rejected(client, seed_occupation):
    """兴趣点把侦查从 25 推到 95 → 400，且错误信息点明上限与当前值。"""
    (occ_id,) = seed_occupation('精神病医生')
    credit = get_occupation('精神病医生').credit_min
    # INT 60 → 兴趣点 120，足够把侦查推到 95
    over = 25 + (SKILL_MAX_AT_CREATION + 5 - 25)
    res = _post(client, occ_id, credit, [_skill('侦查', 25, interest=over - 25)])
    assert res.status_code == 400, res.text
    detail = res.json()['detail']
    assert '侦查' in detail and str(SKILL_MAX_AT_CREATION) in detail and '95' in detail


def test_skill_at_cap_passes(client, seed_occupation):
    """正好等于上限（90）放行——边界值不该被拦。"""
    (occ_id,) = seed_occupation('精神病医生')
    credit = get_occupation('精神病医生').credit_min
    res = _post(client, occ_id, credit,
                [_skill('侦查', 25, interest=SKILL_MAX_AT_CREATION - 25)])
    assert res.status_code == 201, res.text
    assert {s['name']: s for s in res.json()['skills']}['侦查']['increment'] == SKILL_MAX_AT_CREATION - 25


def test_validate_allocation_ignores_skill_base_above_cap():
    """基础值本身超过上限的技能（母语 = EDU 95）不算违规，否则高 EDU 角色必挂。"""
    occ = get_occupation('精神病医生')
    allocations = [
        SkillAllocation(name='母语', base=95, occupation_points=2, interest_points=0,
                        is_occupation_skill=True),
    ]
    problems = validate_allocation(
        occ, Attributes(**VALID_ATTRS), allocations,
        max_skill_value=SKILL_MAX_AT_CREATION,
    )
    assert not any('母语' in p and '上限' in p for p in problems)


def test_validate_allocation_still_flags_points_pushing_over_cap():
    """同一函数在"点数推过上限"时照常报错（上一条的对照组）。"""
    occ = get_occupation('精神病医生')
    allocations = [
        SkillAllocation(name='侦查', base=25, occupation_points=0, interest_points=70,
                        is_occupation_skill=False),
    ]
    problems = validate_allocation(
        occ, Attributes(**VALID_ATTRS), allocations,
        max_skill_value=SKILL_MAX_AT_CREATION,
    )
    assert any('侦查' in p and '上限' in p for p in problems)


def test_cap_is_configurable_and_default_90():
    """常量必须显式存在（便于回退 80），且当前取用户裁定的 90。"""
    assert SKILL_MAX_AT_CREATION == 90
