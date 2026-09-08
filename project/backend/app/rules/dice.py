import re
import random
from dataclasses import dataclass


@dataclass
class D100Roll:
    """D100 掷骰结果数据类"""
    units: int                # 个位数 (0~9)
    tens: list[int]           # 十位数列表（可能包含多个奖励/惩罚骰）
    value: int                # 最终读数
    bonus: int = 0            # 奖励骰数量
    penalty: int = 0          # 惩罚骰数量


def roll(expr: str, rng: random.Random | None = None) -> int:
    """
    通用骰子表达式掷骰，支持格式： [N]dM[±X]（大小写均可，如 1D6 / 1d6）
    示例： "2d6+3", "1d100", "d4"
    """
    if rng is None:
        rng = random.Random()

    expr = expr.strip()
    pattern = r'^(\d*)[dD](\d+)([+-]\d+)?$'
    match = re.match(pattern, expr)
    if not match:
        raise ValueError(f"无效的骰子表达式: {expr}")

    num_str, faces_str, mod_str = match.groups()
    num = int(num_str) if num_str else 1
    faces = int(faces_str)
    mod = int(mod_str) if mod_str else 0

    if num <= 0 or faces <= 0:
        raise ValueError("骰子数量与面数必须为正整数")

    total = sum(rng.randint(1, faces) for _ in range(num))
    total += mod
    return total


def resolve_d100(units: int, tens_list: list[int], bonus: int, penalty: int) -> int:
    """
    纯函数：根据个位、十位列表以及奖励/惩罚骰数量，计算最终 D100 读数。
    规则：
      - 奖励骰（bonus > penalty）：取十位列表中的最小值（数值小更优）
      - 惩罚骰（penalty > bonus）：取十位列表中的最大值（数值大更差）
      - 抵消（bonus == penalty）：只使用第一个十位（常规情况）
    特殊处理：十位 0 且个位 0 → 读作 100
    """
    if bonus > penalty:
        tens = min(tens_list)        # 奖励取最优（最小）
    elif penalty > bonus:
        tens = max(tens_list)        # 惩罚取最差（最大）
    else:
        tens = tens_list[0]          # 抵消或普通掷骰，使用第一个十位

    value = tens * 10 + units
    if tens == 0 and units == 0:
        value = 100
    return value


def roll_d100(
    units: int | None = None,
    tens_list: list[int] | None = None,
    rng: random.Random | None = None,
) -> D100Roll:
    """
    标准 D100 掷骰：掷一个位骰和一个十位骰（无奖励/惩罚）。
    参数为 None 时自动随机生成；传入固定值或 rng 用于测试。
    返回 D100Roll 数据类，包含个位、十位列表、最终值等。
    """
    if rng is None:
        rng = random.Random()
    if units is None:
        units = rng.randint(0, 9)
    if tens_list is None:
        tens_list = [rng.randint(0, 9)]

    # 标准掷骰无奖励/惩罚
    value = resolve_d100(units, tens_list, bonus=0, penalty=0)
    return D100Roll(units=units, tens=tens_list, value=value, bonus=0, penalty=0)


# =================== 自测代码 ===================
if __name__ == '__main__':
    print("=== 测试 roll ===")
    print(f"roll('2d6+3') = {roll('2d6+3')}")
    print(f"roll('1d100') = {roll('1d100')}")
    print(f"roll('d4')    = {roll('d4')}")

    print("\n=== 测试 resolve_d100 (边界条件) ===")
    # 00 + 0 → 100
    print(f"resolve_d100(0, [0], 0, 0) = {resolve_d100(0, [0], 0, 0)}")
    # 00 + 3 → 3
    print(f"resolve_d100(3, [0], 0, 0) = {resolve_d100(3, [0], 0, 0)}")
    # 惩罚骰：十位 [4,2]，个位3 → 取最大十位 4 → 43
    print(f"resolve_d100(3, [4,2], 0, 1) = {resolve_d100(3, [4,2], 0, 1)}")
    # 奖励骰：十位 [4,2]，个位3 → 取最小十位 2 → 23
    print(f"resolve_d100(3, [4,2], 1, 0) = {resolve_d100(3, [4,2], 1, 0)}")
    # 抵消：bonus=1, penalty=1 → 取第一个十位 4 → 43
    print(f"resolve_d100(3, [4,2], 1, 1) = {resolve_d100(3, [4,2], 1, 1)}")

    print("\n=== 测试 roll_d100 (固定值注入) ===")
    # 固定个位 0，十位 [0] → 应为 100
    roll_fixed = roll_d100(units=0, tens_list=[0])
    print(f"roll_d100(units=0, tens_list=[0]) -> units={roll_fixed.units}, tens={roll_fixed.tens}, value={roll_fixed.value}")
    # 固定个位 5，十位 [3] → 应为 35
    roll_fixed2 = roll_d100(units=5, tens_list=[3])
    print(f"roll_d100(units=5, tens_list=[3]) -> units={roll_fixed2.units}, tens={roll_fixed2.tens}, value={roll_fixed2.value}")