"""卡片编辑 PATCH 测试 — 2.5③：背景八要素 / 随身物品 / 武器的部分更新。

口径：PATCH 只覆写请求体中出现的块，其余整卡字段（技能/属性/姓名）不动；
GET /weapons 返回 seed 武器表；空请求体 400；未知卡 404；非法武器 422。
"""
import pytest
from fastapi.testclient import TestClient

from app.rules.occupation import get_occupation

FULL_BACKGROUND = {
    'personal_description': '高瘦，总穿旧呢子大衣',
    'ideology_beliefs': '真相值得一切代价',
    'significant_people': '导师 老周',
    'meaningful_location': '米斯卡塔尼克大学图书馆',
    'treasured_possession': '父亲的怀表',
    'traits': '沉着',
    'scars_injuries': '左臂旧伤',
    'cash_assets': '存款 500 美元',
}


@pytest.fixture()
def card_id(client, seed_occupation) -> str:
    (occ_id,) = seed_occupation('精神病医生')
    occ = get_occupation('精神病医生')
    res = client.post('/api/cards', json={
        'name': '编辑员', 'age': 25, 'era': 'modern',
        'occupation_id': occ_id, 'credit': occ.credit_min,
        'attributes': {'STR': 55, 'CON': 55, 'SIZ': 55, 'DEX': 55, 'APP': 55,
                       'INT': 60, 'POW': 60, 'EDU': 65, 'LUK': 45},
        'skills': [],
    })
    assert res.status_code == 201, res.text
    return res.json()['id']


def test_patch_background_keeps_other_fields(client, card_id):
    res = client.patch(f'/api/cards/{card_id}', json={'background': FULL_BACKGROUND})
    assert res.status_code == 200, res.text
    card = res.json()
    assert card['background'] == FULL_BACKGROUND
    # 部分更新语义：其余字段原样保留
    assert card['name'] == '编辑员'
    assert card['skills'] == []
    assert card['possessions'] == ''

    # 落库可查（不只是响应体里改了）
    assert client.get(f'/api/cards/{card_id}').json()['background'] == FULL_BACKGROUND


def test_patch_possessions(client, card_id):
    res = client.patch(f'/api/cards/{card_id}', json={'possessions': '手电筒、笔记本'})
    assert res.status_code == 200, res.text
    card = res.json()
    assert card['possessions'] == '手电筒、笔记本'
    # 背景未随此次 PATCH 变化
    assert card['background']['personal_description'] == ''


def test_patch_weapons_int_and_str_ammo(client, card_id):
    weapons = [
        # 标准表形（ammo 为数字）
        {'name': '.32(7.65mm)左轮手枪', 'skill_name': '手枪', 'damage': '1D8',
         'rng': '15', 'attacks': '1(3)', 'ammo': 6, 'malfunction': 100},
        # 武器表原始值形（ammo 非整数）+ 自定义武器
        {'name': 'MP18I/MP28II', 'skill_name': '冲锋枪', 'damage': '1D10',
         'rng': '20', 'attacks': '1(2)or全自动', 'ammo': '20/30/32', 'malfunction': 96},
        {'name': '祖传猎刀', 'skill_name': '斗殴', 'damage': '1D6+DB',
         'rng': '接触', 'attacks': '1', 'ammo': 0, 'malfunction': 100},
    ]
    res = client.patch(f'/api/cards/{card_id}', json={'weapons': weapons})
    assert res.status_code == 200, res.text
    got = res.json()['weapons']
    assert [w['name'] for w in got] == ['.32(7.65mm)左轮手枪', 'MP18I/MP28II', '祖传猎刀']
    assert got[1]['ammo'] == '20/30/32'
    assert got[0]['ammo'] == 6


def test_patch_card_not_found(client):
    assert client.patch('/api/cards/NOPE', json={'possessions': 'x'}).status_code == 404


def test_patch_empty_body_rejected(client, card_id):
    res = client.patch(f'/api/cards/{card_id}', json={})
    assert res.status_code == 400
    assert '可更新字段' in res.json()['detail']


def test_patch_invalid_weapon_422(client, card_id):
    res = client.patch(f'/api/cards/{card_id}', json={'weapons': [{'skill_name': '斗殴'}]})
    assert res.status_code == 422  # Weapon.name 必填


def test_get_weapons_seed(client):
    res = client.get('/api/weapons')
    assert res.status_code == 200
    weapons = res.json()
    assert len(weapons) >= 100
    bow = next(w for w in weapons if w['name'] == '弓箭')
    assert bow['damage'] == '1D6+半DB' and bow['era'] == '1920s、现代'
    assert {'id', 'name', 'skill_name', 'damage', 'rng', 'attacks',
            'ammo', 'malfunction', 'era', 'price', 'category'} <= set(bow.keys())
