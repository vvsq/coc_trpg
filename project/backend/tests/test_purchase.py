"""购点法服务端校验测试 — gen_mode=purchase 时 Σ=460 与单项 15~90 在服务端拦截。

验收口径（阶段 2.5①）：合法 460 通过；总和 459 被拒；STR=10 被拒；STR=95 被拒；
边界 15/90 与 LUK=5 通过（LUK 不受 15~90 约束，它是单独 3D6×5 掷的）。
错误信息必须指明是哪项不对。
职业用精神病医生：无"或"公式、free_picks=0（会计师 free_picks=2，会被 ④ 的校验拦）。
"""
from fastapi.testclient import TestClient

from app.rules.occupation import get_occupation

# 八项属性 Σ=460、单项全在 15~90 的合法购点组合
VALID_ATTRS = {
    'STR': 55, 'CON': 55, 'SIZ': 55, 'DEX': 55, 'APP': 55,
    'INT': 60, 'POW': 60, 'EDU': 65,
}


def _post_card(client: TestClient, occ_id: int, credit: int, attrs: dict):
    payload = {
        'name': '购点员', 'gender': '女', 'age': 25, 'era': 'modern',
        'occupation_id': occ_id,
        'credit': credit,
        'attributes': {**attrs, 'LUK': attrs.get('LUK', 45)},
        'skills': [],
        'gen_mode': 'purchase',
    }
    return client.post('/api/cards', json=payload)


def test_purchase_valid_460_passes(client, seed_occupation):
    (occ_id,) = seed_occupation('精神病医生')
    occ = get_occupation('精神病医生')
    res = _post_card(client, occ_id, occ.credit_min, VALID_ATTRS)
    assert res.status_code == 201, res.text
    assert res.json()['name'] == '购点员'


def test_purchase_sum_459_rejected(client, seed_occupation):
    (occ_id,) = seed_occupation('精神病医生')
    attrs = {**VALID_ATTRS, 'EDU': 64}  # 460 - 1
    res = _post_card(client, occ_id, get_occupation('精神病医生').credit_min, attrs)
    assert res.status_code == 400
    detail = res.json()['detail']
    assert '460' in detail and '459' in detail


def test_purchase_str_10_rejected(client, seed_occupation):
    (occ_id,) = seed_occupation('精神病医生')
    # STR=10 但其余补足 Σ=460：只该报 STR 越界，不该报总和
    attrs = {**VALID_ATTRS, 'STR': 10, 'EDU': 90, 'INT': 80}
    res = _post_card(client, occ_id, get_occupation('精神病医生').credit_min, attrs)
    assert res.status_code == 400
    assert 'STR' in res.json()['detail']


def test_purchase_str_95_rejected(client, seed_occupation):
    (occ_id,) = seed_occupation('精神病医生')
    attrs = {**VALID_ATTRS, 'STR': 95, 'SIZ': 90, 'CON': 60}  # Σ 仍 460
    res = _post_card(client, occ_id, get_occupation('精神病医生').credit_min, attrs)
    assert res.status_code == 400
    assert 'STR' in res.json()['detail']


def test_purchase_boundary_15_90_and_luk_5_passes(client, seed_occupation):
    (occ_id,) = seed_occupation('精神病医生')
    attrs = {
        'STR': 15, 'CON': 15, 'SIZ': 15, 'DEX': 90,
        'APP': 90, 'POW': 90, 'INT': 65, 'EDU': 80,
    }  # 15×3 + 90×3 + 65 + 80 = 460
    res = _post_card(client, occ_id, get_occupation('精神病医生').credit_min, attrs)
    assert res.status_code == 201, res.text
