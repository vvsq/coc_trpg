"""理智规则单元测试（4.2）：公式解析 / 损失计算 / 疯狂判定 / 症状表查找。

纯函数测试，rng 固定种子；不动 DB、不发网络。
"""
import random

import pytest

from app.rules import sanity


# ---------- 损失公式解析 ----------

def test_parse_loss_formula():
    assert sanity.parse_loss_formula('0/1D6') == ('0', '1D6')
    assert sanity.parse_loss_formula('1 / 1D4+1') == ('1', '1D4+1')  # 空格剥离
    assert sanity.parse_loss_formula('1D3/1D6') == ('1D3', '1D6')
    assert sanity.parse_loss_formula('1/1') == ('1', '1')  # 纯数字固定损失


@pytest.mark.parametrize('bad', ['1D6', '', '0/', '/1D6', '0/abc'])
def test_parse_loss_formula_rejects(bad: str):
    with pytest.raises(ValueError):
        sanity.parse_loss_formula(bad)


# ---------- 损失掷骰 ----------

def test_roll_loss_success_takes_success_expr():
    rng = random.Random(42)
    for _ in range(10):
        assert sanity.roll_loss('0', '1D6', success=True, rng=rng) == 0
        assert sanity.roll_loss('1', '1D6', success=True, rng=rng) == 1  # 固定值


def test_roll_loss_fail_in_dice_range():
    rng = random.Random(7)
    for _ in range(30):
        assert 1 <= sanity.roll_loss('0', '1D6', success=False, rng=rng) <= 6


def test_roll_loss_max():
    assert sanity.roll_loss_max('1D6') == 6
    assert sanity.roll_loss_max('2D6+1') == 13
    assert sanity.roll_loss_max('1') == 1
    assert sanity.roll_loss_max('0') == 0


# ---------- 疯狂判定 ----------

def test_temporary_madness_on_int_success():
    """单次损失 ≥5 且智力检定成功 → 临时疯狂（规则书反直觉：成功=理解真相=崩溃）。"""
    r = sanity.determine_madness(5, 50, 45, 100, rng=random.Random(7))  # INT 100 必成功
    assert r.kind == 'temporary'
    assert r.int_check is not None and r.int_check['success'] is True
    assert r.symptom and r.symptom['name']
    assert '【临时性疯狂】' in r.summary()  # KP 可读中文标签，不出现英文枚举值


def test_temporary_madness_needs_int_success():
    """INT 检定失败 → 不发疯（多种种子下必须存在无发作情形）。"""
    kinds = {sanity.determine_madness(5, 50, 45, 1, rng=random.Random(i)).kind
             for i in range(40)}  # INT 1：只有掷出 1 才成功
    assert '' in kinds


def test_small_loss_no_madness():
    r = sanity.determine_madness(2, 50, 48, 50, rng=random.Random(1))
    assert r.kind == '' and r.symptom is None and r.int_check is None


def test_indefinite_madness_by_day_loss():
    """当日累计损失（含本次）≥ 1/5 当前 SAN → 不定性疯狂（50//5=10）。"""
    r = sanity.determine_madness(6, 50, 44, 100, day_loss_before=5, rng=random.Random(1))
    assert r.kind == 'indefinite'
    assert r.day_loss_before == 5 and r.day_loss_after == 11
    assert r.symptom and r.symptom['phase'] == 'immediate'


def test_permanent_madness_at_zero():
    r = sanity.determine_madness(6, 5, 0, 50, rng=random.Random(1))
    assert r.kind == 'permanent' and r.symptom is None


def test_summary_phase_when_alone():
    r = sanity.determine_madness(6, 50, 44, 100, day_loss_before=5,
                                 alone_or_all=True, rng=random.Random(1))
    assert r.kind == 'indefinite'
    assert r.symptom['phase'] == 'summary'


# ---------- 症状表 ----------

def test_roll_symptom_links_d100_tables():
    rng = random.Random(3)
    seen_fear = seen_mania = False
    for _ in range(80):
        s = sanity.roll_symptom(immediate=True, rng=rng)
        assert 1 <= s['roll'] <= 10 and s['phase'] == 'immediate'
        if s['roll'] == 9:
            assert '恐惧症检定' in s['extra']
            seen_fear = True
        if s['roll'] == 10:
            assert '躁狂症检定' in s['extra']
            seen_mania = True
    assert seen_fear and seen_mania


def test_madness_tables_complete():
    t = sanity._tables()
    assert len(t['immediate_symptoms']) == 10
    assert len(t['summary_symptoms']) == 10
    assert len(t['phobias']) == 100
    assert len(t['manias']) == 100
    assert t['immediate_symptoms']['1']['name'] == '失忆'
