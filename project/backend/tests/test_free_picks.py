"""free_picks 任意特长本职测试 — 2.5④。

口径：选不够 N → 400；选超 N → 400；free_picks=0 的职业却传了 → 400；
合法恰好 N → 201，且被标记技能 occupation=true（自带职业点以证明
"先标记后校验"的顺序——否则职业点投非本职技能会先被误判）。
职业用会计师：free_picks=2、无分组（组选择维持仅前端拦截）、公式 EDU×4 无"或"。
"""
import pytest
from fastapi.testclient import TestClient

from app.rules.occupation import get_occupation

ATTRS = {'STR': 55, 'CON': 55, 'SIZ': 55, 'DEX': 55, 'APP': 55,
         'INT': 60, 'POW': 60, 'EDU': 65, 'LUK': 45}


def _skill(name: str, base: int, occ_pts: int = 0, int_pts: int = 0, is_occ: bool = False) -> dict:
    return {'name': name, 'slot': 0, 'detail': '', 'base': base,
            'occupation_points': occ_pts, 'interest_points': int_pts,
            'is_occupation_skill': is_occ}


def _post(client: TestClient, occ_id: int, credit: int, skills: list[dict], free_picks: list[str]):
    return client.post('/api/cards', json={
        'name': '特长员', 'age': 25, 'era': 'modern',
        'occupation_id': occ_id, 'credit': credit,
        'attributes': ATTRS, 'skills': skills, 'free_picks': free_picks,
    })


# 会计师（EDU×4=260 职业点、INT×2=120 兴趣点）的常规技能行：
# 会计是固定本职；心理分析/母语原本非本职，由 free_picks 标记。
SKILLS = [
    _skill('会计', 5, occ_pts=40, is_occ=True),
    _skill('心理分析', 10, occ_pts=30),
    _skill('母语', 70, int_pts=10),
]


@pytest.fixture()
def accountant_ids(client, seed_occupation) -> tuple[int, int]:
    occ = get_occupation('会计师')
    (occ_id,) = seed_occupation('会计师')
    return occ_id, occ.credit_min


def test_free_picks_too_few_rejected(client, accountant_ids):
    occ_id, credit = accountant_ids
    res = _post(client, occ_id, credit, SKILLS, ['心理分析'])
    assert res.status_code == 400
    detail = res.json()['detail']
    assert '任意特长需选 2 项，当前 1 项' in detail


def test_free_picks_too_many_rejected(client, accountant_ids):
    occ_id, credit = accountant_ids
    res = _post(client, occ_id, credit, SKILLS, ['心理分析', '母语', '会计'])
    assert res.status_code == 400
    assert '当前 3 项' in res.json()['detail']


def test_free_picks_zero_occupation_rejected(client, seed_occupation):
    (occ_id,) = seed_occupation('精神病医生')  # free_picks=0
    res = _post(client, occ_id, get_occupation('精神病医生').credit_min, SKILLS, ['心理分析'])
    assert res.status_code == 400
    assert '没有任意特长' in res.json()['detail']


def test_free_picks_exact_passes_and_flags_occupation(client, accountant_ids):
    occ_id, credit = accountant_ids
    res = _post(client, occ_id, credit, SKILLS, ['心理分析', '母语'])
    assert res.status_code == 201, res.text
    skills = {s['name']: s for s in res.json()['skills']}
    # 被标记技能落卡为本职
    assert skills['心理分析']['occupation'] is True
    assert skills['母语']['occupation'] is True
    assert skills['会计']['occupation'] is True
    # 心理分析的职业点 30 被正常接受（标记先于 validate_allocation）
    assert skills['心理分析']['increment'] == 30


def test_free_picks_name_not_allocated_rejected(client, accountant_ids):
    occ_id, credit = accountant_ids
    res = _post(client, occ_id, credit, SKILLS, ['心理分析', '神秘学'])
    assert res.status_code == 400
    assert '不在分配的技能行中' in res.json()['detail']
