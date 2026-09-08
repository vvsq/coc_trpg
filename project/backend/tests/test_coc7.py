import random
import pytest
from app.rules.coc7 import (
    Attributes, Derived,
    get_db_build, compute_mov, derive,
    roll_attributes, apply_age_adj,
    judge, target_for, check
)


# ---------- 固定种子 ----------
SEED = 42


def test_db_build_table():
    """验证 DB/BUILD 表边界"""
    assert get_db_build(90) == ("0", 0)
    assert get_db_build(170) == ("+1D6", 2)
    assert get_db_build(600) == ("+6D6", 7)   # 524+76 -> +1档


def test_judge_boundary():
    """测试 judge 成功等级判定（默认常规难度）"""
    assert judge(1, 55) == 'critical'
    assert judge(11, 55) == 'extreme'   # 55//5 = 11
    assert judge(27, 55) == 'hard'      # 55//2 = 27
    assert judge(55, 55) == 'regular'
    assert judge(56, 55) == 'fail'      # 超过全值
    assert judge(100, 55) == 'fumble'   # 目标 55>=50 → 仅 100 大失败
    assert judge(99, 55) == 'fail'      # 目标 55>=50 → 99 只是失败


def test_judge_hard_difficulty():
    """难度=困难时：目标为半值；大失败范围扩大为 96-100（§3.2）"""
    # 55 的困难目标 = 27
    assert judge(27, 55, 'hard') == 'hard'    # 等于目标值=成功
    assert judge(28, 55, 'hard') == 'fail'    # 超过半值即失败
    assert judge(96, 55, 'hard') == 'fumble'  # 目标 27<50 → 96 也大失败
    assert judge(100, 55, 'hard') == 'fumble'
    assert judge(95, 55, 'hard') == 'fail'    # 95 不在 96-100，仅失败


def test_judge_extreme_difficulty():
    """难度=极难时：目标为 1/5 值"""
    assert judge(11, 55, 'extreme') == 'extreme'  # 55//5 = 11
    assert judge(12, 55, 'extreme') == 'fail'
    assert judge(96, 55, 'extreme') == 'fumble'   # 目标 11<50


def test_target_for():
    assert target_for(55, 'standard') == 55
    assert target_for(55, 'hard') == 27
    assert target_for(55, 'extreme') == 11


def test_hp_and_mov():
    """测试 HP 向下取整和 MOV 计算"""
    attrs = Attributes(STR=50, CON=62, SIZ=63, POW=60, DEX=70, APP=50, INT=70, EDU=80, LUK=50)
    derived = derive(attrs, 25)
    assert derived.HP == 12          # (62+63)//10

    # MOV 测试：两者皆大于 SIZ → 9
    assert compute_mov(70, 70, 65, 25) == 9
    # 皆小于 SIZ → 7
    assert compute_mov(50, 50, 65, 25) == 7
    # 一≥ 或 皆= → 8 (此处DEX=60 <65, STR=70≥65 → 8)
    assert compute_mov(70, 60, 65, 25) == 8
    # 年龄52 -> 基础9 (STR=70,DEX=70,SIZ=65) 减去2 → 7
    assert compute_mov(70, 70, 65, 52) == 7


def test_roll_attributes_fixed_seed():
    """使用固定种子生成属性，结果可重复（快照值，改动实现需重跑确认）"""
    rng = random.Random(SEED)
    attrs = roll_attributes(rng)
    expected = Attributes(
        STR=40, CON=55, POW=50, DEX=65, APP=55,
        SIZ=55, INT=40, EDU=50, LUK=55
    )
    assert attrs == expected


def test_apply_age_adj_fixed():
    """测试年龄调整（15-19 LUK两次取高，EDU增强等；快照值）"""
    rng = random.Random(SEED)
    attrs = roll_attributes(rng)   # 使用上面固定结果
    # 测试17岁调整
    adjusted = apply_age_adj(attrs, 17, rng)
    expected = Attributes(
        STR=38, CON=55, POW=50, DEX=65, APP=55,
        SIZ=52, INT=40, EDU=45, LUK=85
    )
    assert adjusted == expected

    # 测试25岁调整（EDU增强1次）
    adjusted2 = apply_age_adj(attrs, 25, rng)
    expected2 = Attributes(
        STR=40, CON=55, POW=50, DEX=65, APP=55,
        SIZ=55, INT=40, EDU=54, LUK=55
    )
    assert adjusted2 == expected2


def test_derive_after_age():
    """测试年龄调整后的衍生值（快照值）"""
    rng = random.Random(SEED)
    attrs = roll_attributes(rng)
    adjusted = apply_age_adj(attrs, 25, rng)
    derived = derive(adjusted, 25)
    # HP = (55+55)//10 = 11
    assert derived.HP == 11
    # MP = POW//5 = 50//5 = 10
    assert derived.MP == 10
    # SAN = POW = 50
    assert derived.SAN == 50
    # DB/BUILD: STR+SIZ=40+55=95 -> 查表 85-124 得 ("0",0)
    assert derived.DB == "0"
    assert derived.build == 0
    # MOV: STR=40, DEX=65, SIZ=55 → 任一 >=SIZ → 基础8, 年龄25无减值 → 8
    assert derived.MOV == 8