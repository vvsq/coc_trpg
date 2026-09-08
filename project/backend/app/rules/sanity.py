"""理智检定联动规则（4.2 规则库常量前移，goal §7）。

规则依据 docs/coc7-rules.md §6（阶段 1 已对照守秘人规则书 PDF 核实）：
  - 检定：1D100 ≤ 当前 SAN 即成功；奖惩骰不适用
  - 损失写法「成功值/失败值」（SAN 0/1D6：成功不损失，失败 1D6）
  - 大失败的理智检定 → 损失该遭遇的**最大**值（失败式骰 max）
  - 一次失败的理智检定总让调查员瞬间失控行动（叙事素材，不进数值）
  - 三种疯狂：临时（单次损失 ≥5 且**智力检定成功**→发疯，反直觉）/
    不定（一天内损失 ≥1/5 当前 SAN）/ 永久（SAN 0）
  - 发作症状：有同伴 → 即时症状（1D10 战斗轮）；独处/全场 → 总结症状（1D10 小时）
  - 症状 9/10 → 查恐惧/躁狂 D100 表

纯函数 + 固定数据表，rng 可注入（测试与工具层共用）。
"""
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from app.rules.dice import roll as roll_expr

_TABLES_PATH = Path(__file__).resolve().parent / 'data' / 'madness_tables.json'
_TABLES: dict | None = None

# 触发临时性疯狂的单次损失阈值（SAN 点）
TEMPORARY_LOSS_THRESHOLD = 5


def _tables() -> dict:
    global _TABLES
    if _TABLES is None:
        _TABLES = json.loads(_TABLES_PATH.read_text(encoding='utf-8'))
    return _TABLES


@dataclass
class MadnessResult:
    """一次理智检定的疯狂判定结果。kind 取 ''（无发作）/'temporary'/'indefinite'/'permanent'。"""

    kind: str = ''
    int_check: dict | None = None  # 临时疯狂判定的智力检定细节（None=未触发）
    symptom: dict | None = None  # 发作症状 {name, desc, phase, extra}
    day_loss_before: int = 0  # 不定性判定用的当日累计损失（检定前）
    day_loss_after: int = 0

    @property
    def has_breakdown(self) -> bool:
        return self.kind != ''

    # kind → KP 可读的中文标签（summary 输出进 keeper 层，不出现英文枚举值）
    KIND_LABELS = {'temporary': '临时性', 'indefinite': '不定性', 'permanent': '永久性'}

    def summary(self) -> str:
        """面向 KP 的可读一行（进 keeper 层，不进公开剧情流）。"""
        if not self.has_breakdown:
            return ''
        label = self.KIND_LABELS.get(self.kind, self.kind)
        parts = [f'【{label}疯狂】']
        if self.int_check is not None:
            parts.append(f"智力检定 {self.int_check['roll']} vs {self.int_check['target']}（成功即发疯）")
        if self.symptom:
            extra = f"；{self.symptom['extra']}" if self.symptom.get('extra') else ''
            parts.append(f"发作症状：{self.symptom['name']}——{self.symptom['desc']}{extra}")
        return '；'.join(parts)


def parse_loss_formula(formula: str) -> tuple[str, str]:
    """解析「成功损失/失败损失」写法（如 0/1D6、1/1D4+1、1D3/1D6）。

    返回 (成功式, 失败式)；两个式子都走 dice.roll 的表达式语法。
    非法输入抛 ValueError（工具层捕获后让 LLM 澄清，D3）。
    """
    text = (formula or '').strip().replace(' ', '').upper()
    if '/' not in text:
        raise ValueError(f'理智损失写法必须是「成功/失败」两段式，如 0/1D6，收到：{formula!r}')
    success, fail = text.split('/', 1)
    for part in (success, fail):
        if not re_expr_ok(part):
            raise ValueError(f'理智损失式 {part!r} 不是合法骰子表达式（如 1、1D6、1D4+1）')
    return success, fail


def re_expr_ok(expr: str) -> bool:
    """dice.roll 表达式的宽松预校验（纯数字或 N d M (+/-k)，大小写均可）。"""
    if not expr:
        return False
    return bool(re.fullmatch(r'\d*[dD]\d+([+-]\d+)?|\d+', expr))


def _roll_loss_expr(expr: str, rng: random.Random | None) -> int:
    """掷损失式：纯数字（固定损失，如 1）直接取值，骰子表达式走 dice.roll。"""
    if expr.isdigit():
        return int(expr)
    return roll_expr(expr, rng)


def roll_loss(success_expr: str, fail_expr: str, *, success: bool, rng: random.Random | None = None) -> int:
    """按检定结果掷损失（成功掷成功式、失败掷失败式；大失败最大值用 roll_loss_max）。"""
    return _roll_loss_expr(success_expr if success else fail_expr, rng)


def roll_loss_max(fail_expr: str, rng: random.Random | None = None) -> int:
    """大失败：失败式能取到的最大值（骰子部分取面值上限；固定损失取原值）。"""
    if fail_expr.isdigit():
        return int(fail_expr)
    m = re.fullmatch(r'(\d*)[dD](\d+)([+-]\d+)?', fail_expr)
    if not m:
        return roll_expr(fail_expr, rng)
    count = int(m.group(1) or 1)
    faces = int(m.group(2))
    mod = int(m.group(3) or 0)
    return count * faces + mod


def determine_madness(
    loss: int,
    san_before: int,
    san_after: int,
    int_value: int,
    *,
    day_loss_before: int = 0,
    alone_or_all: bool = False,
    rng: random.Random | None = None,
) -> MadnessResult:
    """判定一次理智损失引发的疯狂（§6.4/§6.5/§6.6）。

    - 永久：SAN 降至 0
    - 不定：当日累计损失 ≥ 1/5 当前 SAN（san_before 的五分之一，向下取整，≥1 才有意义）
    - 临时：单次损失 ≥ 5 且随后的智力检定**成功**（成功=理解真相=崩溃，规则书反直觉）
    - 永久优先；已永久时不掷症状（角色退出玩家控制）
    - alone_or_all：独处或全场同时发疯 → 总结症状，否则即时症状
    """
    rng = rng or random.Random()
    result = MadnessResult(day_loss_before=day_loss_before, day_loss_after=day_loss_before + loss)

    if san_after <= 0:
        result.kind = 'permanent'
        result.symptom = None
        return result

    # 不定性：一天内累计损失 ≥ 1/5 当前 SAN（以检定前的 SAN 计）
    threshold = max(1, san_before // 5)
    if day_loss_before + loss >= threshold:
        result.kind = 'indefinite'
        result.symptom = roll_symptom(immediate=not alone_or_all, rng=rng)
        return result

    # 临时性：单次损失 ≥ 5 → 智力检定，成功 = 发疯（INT 检定常规难度、无奖惩骰）
    if loss >= TEMPORARY_LOSS_THRESHOLD:
        from app.rules.coc7 import check as coc7_check

        level, d100 = coc7_check(int_value, 'standard', rng=rng)
        success = level != 'fail' and level != 'fumble'
        result.int_check = {
            'roll': d100.value, 'target': int_value, 'success': success,
            'level': level,
        }
        if success:
            result.kind = 'temporary'
            result.symptom = roll_symptom(immediate=not alone_or_all, rng=rng)
    return result


def roll_symptom(*, immediate: bool, rng: random.Random | None = None) -> dict:
    """掷 1D10 症状；命中 9/10 时联动查恐惧/躁狂 D100 表（§6.5 第 9/10 项）。"""
    rng = rng or random.Random()
    tables = _tables()
    roll = rng.randint(1, 10)
    table = tables['immediate_symptoms'] if immediate else tables['summary_symptoms']
    entry = table[str(roll)]
    symptom = {
        'name': entry['name'],
        'desc': entry['desc'],
        'phase': 'immediate' if immediate else 'summary',
        'roll': roll,
        'extra': '',
    }
    if roll == 9:
        sub = tables['phobias'][str(rng.randint(1, 100))]
        symptom['extra'] = f"恐惧症检定：{sub['name']}（{sub['desc']}）"
    elif roll == 10:
        sub = tables['manias'][str(rng.randint(1, 100))]
        symptom['extra'] = f"躁狂症检定：{sub['name']}（{sub['desc']}）"
    return symptom
