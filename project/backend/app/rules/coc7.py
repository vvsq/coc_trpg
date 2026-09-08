import random
from typing import Literal

from app.schemas.investigator import Attributes, Derived
from .dice import D100Roll, resolve_d100


# 说明：Attributes/Derived 复用 schemas.investigator 的 Pydantic 定义（字段大写，
# 与角色卡契约同源）。不再各自维护一套 dataclass，避免 API 层手写字段转换。


# ============================================================================
# DB / BUILD 查表（规则书 P37，严格 9 档 + 外推）
# ============================================================================
DB_BUILD_BASE = [
    (2, 64, "-2", -2),
    (65, 84, "-1", -1),
    (85, 124, "0", 0),
    (125, 164, "+1D4", 1),
    (165, 204, "+1D6", 2),
    (205, 284, "+2D6", 3),
    (285, 364, "+3D6", 4),
    (365, 444, "+4D6", 5),
    (445, 524, "+5D6", 6),
]


def get_db_build(sum_str_siz: int) -> tuple[str, int]:
    """
    根据 STR+SIZ 返回 (DB字符串, BUILD值)
    超 524 后每 80 增加 +1D6 和 +1 体格
    """
    for low, high, db_str, build_val in DB_BUILD_BASE:
        if low <= sum_str_siz <= high:
            return db_str, build_val

    # 超出 524
    extra = sum_str_siz - 524
    steps = (extra + 79) // 80          # 不足 80 按 80 算
    total_d6 = 5 + steps
    return f"+{total_d6}D6", 6 + steps


# ============================================================================
# 属性生成
# ============================================================================
def roll_sum_d6_times(count: int, offset: int = 0, rng: random.Random | None = None) -> int:
    if rng is None:
        rng = random.Random()
    total = sum(rng.randint(1, 6) for _ in range(count))
    total += offset
    return total * 5


def roll_3d6_times_5(rng: random.Random | None = None) -> int:
    return roll_sum_d6_times(3, 0, rng)


def roll_2d6_plus_6_times_5(rng: random.Random | None = None) -> int:
    return roll_sum_d6_times(2, 6, rng)


def roll_attributes(rng: random.Random | None = None) -> Attributes:
    if rng is None:
        rng = random.Random()

    def _3() -> int:
        return roll_3d6_times_5(rng)

    def _2p6() -> int:
        return roll_2d6_plus_6_times_5(rng)

    return Attributes(
        STR=_3(),
        CON=_3(),
        POW=_3(),
        DEX=_3(),
        APP=_3(),
        SIZ=_2p6(),
        INT=_2p6(),
        EDU=_2p6(),
        LUK=_3(),
    )


# ============================================================================
# 购点法校验（Σ=460，单项 15~90）
# ============================================================================
POINT_BUY_TOTAL = 460
POINT_BUY_RANGE = (15, 90)

# 购点法可分配的八项属性。LUK 不在内：它是单独 3D6×5 掷的，不受 460 总量与
# 15~90 区间约束（LUK 允许任意值，如 5）。
POINT_BUY_ATTRS = ('STR', 'CON', 'SIZ', 'DEX', 'APP', 'INT', 'POW', 'EDU')


def validate_point_buy(attrs: Attributes, total: int = POINT_BUY_TOTAL) -> list[str]:
    """购点法属性校验，返回问题列表（空列表 = 合法）。

    每条问题都指明是哪项不对：总和一条、越界属性各一条，便于 400 原样返回给玩家。
    """
    problems: list[str] = []
    actual = sum(getattr(attrs, name) for name in POINT_BUY_ATTRS)
    if actual != total:
        problems.append(f'购点法八项属性总和应为 {total}，当前 {actual}')
    low, high = POINT_BUY_RANGE
    for name in POINT_BUY_ATTRS:
        value = getattr(attrs, name)
        if not low <= value <= high:
            problems.append(f'{name}={value} 超出购点法范围 [{low}, {high}]')
    return problems


# ============================================================================
# 年龄调整（按 rules.md §0.4）
# ============================================================================
def _distribute_reduction(total: int, count: int) -> list[int]:
    """将 total 平均分配到 count 个项，返回每项减量列表（非负）"""
    if total <= 0:
        return [0] * count
    base = total // count
    extra = total % count
    return [base + (1 if i < extra else 0) for i in range(count)]


def apply_age_adj(attrs: Attributes, age: int, rng: random.Random | None = None) -> Attributes:
    if rng is None:
        rng = random.Random()

    new = Attributes(
        STR=attrs.STR,
        CON=attrs.CON,
        POW=attrs.POW,
        DEX=attrs.DEX,
        APP=attrs.APP,
        SIZ=attrs.SIZ,
        INT=attrs.INT,
        EDU=attrs.EDU,
        LUK=attrs.LUK,
    )

    edu_checks = 0
    if 15 <= age <= 19:
        new.STR = max(1, new.STR - 2)
        new.SIZ = max(1, new.SIZ - 3)
        new.EDU = max(1, new.EDU - 5)
        luk1 = roll_3d6_times_5(rng)
        luk2 = roll_3d6_times_5(rng)
        new.LUK = max(luk1, luk2)
        edu_checks = 0
    elif 20 <= age <= 39:
        edu_checks = 1
    elif 40 <= age <= 49:
        red = _distribute_reduction(5, 3)
        new.STR = max(1, new.STR - red[0])
        new.CON = max(1, new.CON - red[1])
        new.DEX = max(1, new.DEX - red[2])
        new.APP = max(1, new.APP - 5)
        edu_checks = 2
    elif 50 <= age <= 59:
        red = _distribute_reduction(10, 3)
        new.STR = max(1, new.STR - red[0])
        new.CON = max(1, new.CON - red[1])
        new.DEX = max(1, new.DEX - red[2])
        new.APP = max(1, new.APP - 10)
        edu_checks = 3
    elif 60 <= age <= 69:
        red = _distribute_reduction(20, 3)
        new.STR = max(1, new.STR - red[0])
        new.CON = max(1, new.CON - red[1])
        new.DEX = max(1, new.DEX - red[2])
        new.APP = max(1, new.APP - 15)
        edu_checks = 4
    elif 70 <= age <= 79:
        red = _distribute_reduction(40, 3)
        new.STR = max(1, new.STR - red[0])
        new.CON = max(1, new.CON - red[1])
        new.DEX = max(1, new.DEX - red[2])
        new.APP = max(1, new.APP - 20)
        edu_checks = 4
    elif 80 <= age <= 89:
        red = _distribute_reduction(80, 3)
        new.STR = max(1, new.STR - red[0])
        new.CON = max(1, new.CON - red[1])
        new.DEX = max(1, new.DEX - red[2])
        new.APP = max(1, new.APP - 25)
        edu_checks = 4
    else:
        # 其他年龄（0-14 或 ≥90）无调整
        edu_checks = 0

    # EDU 增强检定
    for _ in range(edu_checks):
        if rng.randint(1, 100) > new.EDU:
            new.EDU = min(99, new.EDU + rng.randint(1, 10))

    # 保底
    for attr in ('STR', 'CON', 'POW', 'DEX', 'APP', 'SIZ', 'INT', 'EDU', 'LUK'):
        if getattr(new, attr) < 1:
            setattr(new, attr, 1)

    return new


# ============================================================================
# 衍生值计算
# ============================================================================
def compute_mov(str_: int, dex: int, siz: int, age: int, armor_penalty: int = 0) -> int:
    if str_ < siz and dex < siz:
        base = 7
    elif str_ > siz and dex > siz:
        base = 9
    else:
        base = 8

    if age >= 80:
        age_pen = 5
    elif age >= 70:
        age_pen = 4
    elif age >= 60:
        age_pen = 3
    elif age >= 50:
        age_pen = 2
    elif age >= 40:
        age_pen = 1
    else:
        age_pen = 0

    mov = base - age_pen - armor_penalty
    return max(1, mov)


def derive(attrs: Attributes, age: int = 20, _mythos_skill: int = 0, armor_penalty: int = 0) -> Derived:
    hp = (attrs.CON + attrs.SIZ) // 10
    mp = attrs.POW // 5
    san = attrs.POW
    db, build = get_db_build(attrs.STR + attrs.SIZ)
    mov = compute_mov(attrs.STR, attrs.DEX, attrs.SIZ, age, armor_penalty)

    return Derived(
        HP=hp,
        MP=mp,
        SAN=san,
        DB=db,
        build=build,
        MOV=mov,
    )


# ============================================================================
# 检定判定
# ============================================================================
Difficulty = Literal['standard', 'hard', 'extreme']
SuccessLevel = Literal['critical', 'extreme', 'hard', 'regular', 'fail', 'fumble']


def judge(dice: int, value: int, difficulty: Difficulty = 'standard') -> SuccessLevel:
    """D100 检定结果判定。

    规则依据 coc7-rules.md §2.1/§2.3/§3.2：
      - 难度决定目标值 target（常规=全值 / 困难=半值 / 极难=1/5，向下取整）
      - dice <= target 才成功；成功等级按原值分档：01 大成功、≤1/5 极难、≤1/2 困难、其余常规
      - 失败后按 target 判大失败：target>=50 仅 100；target<50 则 96~100
    """
    target = target_for(value, difficulty)

    if dice <= target:
        # 成功分支
        if dice == 1:
            return 'critical'
        if dice <= value // 5:
            return 'extreme'
        if dice <= value // 2:
            return 'hard'
        return 'regular'

    # 失败分支 → 大失败判定基于「目标值」而非原值（§3.2 关键：困难检定 96 也算大失败）
    if target >= 50:
        return 'fumble' if dice == 100 else 'fail'
    return 'fumble' if dice >= 96 else 'fail'


def target_for(value: int, difficulty: Difficulty = 'standard') -> int:
    if difficulty == 'standard':
        return value
    if difficulty == 'hard':
        return value // 2
    if difficulty == 'extreme':
        return value // 5
    raise ValueError(f"未知难度: {difficulty}")


def check(
    value: int,
    difficulty: Difficulty = 'standard',
    bonus: int = 0,
    penalty: int = 0,
    rng: random.Random | None = None,
    ) -> tuple[SuccessLevel, D100Roll]:

    if rng is None:
        rng = random.Random()

    # 奖惩骰先净抵消：1 奖励 + 1 惩罚 = 普通检定
    net = bonus - penalty
    units = rng.randint(0, 9)
    num_tens = 1 + abs(net)
    tens_list = [rng.randint(0, 9) for _ in range(num_tens)]

    # 净奖励/净惩罚才传给 resolve_d100，避免多掷无效十位骰
    eff_bonus = net if net > 0 else 0
    eff_penalty = -net if net < 0 else 0
    roll_value = resolve_d100(units, tens_list, eff_bonus, eff_penalty)
    d100_roll = D100Roll(units=units, tens=tens_list, value=roll_value,
                         bonus=eff_bonus, penalty=eff_penalty)

    # 统一判定：成功等级与大失败都在 judge 内完成，不再二次补救
    level = judge(roll_value, value, difficulty)
    return level, d100_roll


# ============================================================================
# 自测
# ============================================================================
if __name__ == '__main__':
    print("=== DB/BUILD 表 ===")
    for s in (50, 90, 150, 170, 600, 605):
        db, build = get_db_build(s)
        print(f"STR+SIZ={s} -> DB={db}, BUILD={build}")

    print("\n=== HP 向下取整 ===")
    print(f"(62+63)//10 = {(62+63)//10}")

    print("\n=== MOV ===")
    mov = compute_mov(70, 60, 65, 52)
    print(f"STR=70, DEX=60, SIZ=65, age=52 -> MOV={mov}")

    print("\n=== judge ===")
    for dice in (1, 10, 27, 50, 55, 56, 96, 100):
        print(f"dice={dice:3d}, value=55 -> {judge(dice, 55)}")

    print("\n=== check (奖励骰) ===")
    rng = random.Random(42)
    level, roll_obj = check(55, bonus=1, rng=rng)
    print(f"check(55, bonus=1) -> level={level}, units={roll_obj.units}, tens={roll_obj.tens}, value={roll_obj.value}")

    print("\n=== 属性生成与年龄调整 ===")
    attrs = roll_attributes(rng)
    print(f"原始属性: {attrs}")
    attrs_adj = apply_age_adj(attrs, 25, rng)
    print(f"25岁调整: {attrs_adj}")
    derived = derive(attrs_adj, 25)
    print(f"衍生值: {derived}")