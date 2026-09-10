"""职业点数计算与技能分配校验 — CoC7 规则引擎（纯函数，便于 pytest）。

从 app/seed/occupations.json 加载职业数据，不直接读 xlsx。
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Iterable
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.investigator import Attributes
from app.schemas.occupation import AttrChoice, AttrKey, Occupation, PointBudget, PointTerm


SEED_PATH = Path(__file__).resolve().parents[1] / 'seed' / 'occupations.json'


# ---------------------------------------------------------------- 加载


@lru_cache(maxsize=1)
def load_occupations(path: str | Path = SEED_PATH) -> tuple[Occupation, ...]:
    """加载全部职业（进程内缓存一次）。"""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return tuple(Occupation.model_validate(item) for item in data)


def get_occupation(name_or_id: str | int) -> Occupation:
    """按名称或 id 取职业，找不到抛 KeyError。"""
    for occ in load_occupations():
        if str(occ.id) == str(name_or_id) or occ.name == name_or_id or name_or_id in occ.aliases:
            return occ
    raise KeyError(f'未找到职业: {name_or_id}')


# ---------------------------------------------------------------- 点数计算


def interest_points(attrs: Attributes) -> int:
    """兴趣点 = INT×2（与职业无关）。"""
    return attrs.INT * 2


def resolve_formula(
    formula: Iterable[PointTerm],
    attrs: Attributes,
    choices: Mapping[int, AttrKey] | None = None,
) -> tuple[int, list[AttrChoice]]:
    """计算公式值。

    返回 (已确定的点数, 待确认项)。候选属性多于一个且未指定时，该项计入 pending 且不参与求和。
    """
    total = 0
    pending: list[AttrChoice] = []
    for i, term in enumerate(formula):
        if len(term.candidates) == 1:
            total += getattr(attrs, term.candidates[0]) * term.multiplier
            continue
        chosen = (choices or {}).get(i)
        if chosen is None or chosen not in term.candidates:
            pending.append(AttrChoice(index=i, options=list(term.candidates)))
            continue
        total += getattr(attrs, chosen) * term.multiplier
    return total, pending


def auto_choices(formula: Iterable[PointTerm], attrs: Attributes) -> dict[int, AttrKey]:
    """自动为每个待选项挑属性值最高的那个（AI 快速建卡用，别混进主流程）。"""
    picks: dict[int, AttrKey] = {}
    for i, term in enumerate(formula):
        if len(term.candidates) > 1:
            picks[i] = max(term.candidates, key=lambda a: getattr(attrs, a))
    return picks


def build_budget(
    occ: Occupation,
    attrs: Attributes,
    choices: Mapping[int, AttrKey] | None = None,
) -> PointBudget:
    """职业点 + 兴趣点预算。pending 非空时 occupation_points 为 0，前端需先让玩家选属性。"""
    points, pending = resolve_formula(occ.point_formula, attrs, choices)
    return PointBudget(
        occupation_points=0 if pending else points,
        interest_points=interest_points(attrs),
        pending=pending,
    )


# ---------------------------------------------------------------- 分配校验


# 单技能创建上限（百分比）。
#
# **规则书未载明**：已通读《第七版守秘人规则书 Version2002》第三章「创建调查员」
# 全节（3.1~3.6，含第三步「决定技能并分配技能点」正文与章末「快速参考：创建调查员」），
# 只规定职业点/兴趣点预算、信用评级范围与未分配点数作废，**没有**技能创建上限这条；
# 全库检索 `不得超过 / 上限 / 80% / 90%` 亦无关（6→7 版转换章节仅提过「KP 可以
# 规定 75% 上限」）。故此处取 KP 裁定值 90（用户 2026-09-10 决策）。
#
# 需要更严格时改成 80 即可——校验逻辑与数值无关；母语=EDU 这类基础值本身已超过
# 上限的技能不会被误报（见 validate_allocation 的判定条件）。
SKILL_MAX_AT_CREATION = 90


class SkillAllocation(BaseModel):
    """一次技能点的投入记录（建卡向导提交 / 存档里的分配结果）。

    后续若把这两个字段合进 investigator.Skill，本模型可直接删掉。
    """

    name: str
    slot: int = Field(default=0, ge=0, description='分类技能实例序号：技艺①→1；0=普通技能')
    detail: str = Field(default='')
    base: int = Field(default=0, ge=0, description='基础值')
    occupation_points: int = Field(default=0, ge=0)
    interest_points: int = Field(default=0, ge=0)
    is_occupation_skill: bool = Field(default=False, description='是否本职业可选技能')

    @property
    def value(self) -> int:
        return self.base + self.occupation_points + self.interest_points


def validate_allocation(
    occ: Occupation,
    attrs: Attributes,
    allocations: list[SkillAllocation],
    choices: Mapping[int, AttrKey] | None = None,
    *,
    max_skill_value: int | None = None,
) -> list[str]:
    """校验分配是否合法，返回问题列表（空列表 = 合法）。

    max_skill_value：单技能创建上限，见模块常量 SKILL_MAX_AT_CREATION 的说明
    （规则书未载明，取 KP 裁定值）。判定只针对**被点数推过上限**的技能：
    `base` 本身已超过上限的（母语 = EDU，EDU 可到 99）不算违规，否则会误报。
    """
    problems: list[str] = []
    budget = build_budget(occ, attrs, choices)

    if budget.pending:
        problems.append('职业点数尚未确定：还有属性未选择')
        return problems

    occ_used = sum(a.occupation_points for a in allocations)
    int_used = sum(a.interest_points for a in allocations)

    if occ_used > budget.occupation_points:
        problems.append(f'职业点超支：已用 {occ_used} / 上限 {budget.occupation_points}')
    if int_used > budget.interest_points:
        problems.append(f'兴趣点超支：已用 {int_used} / 上限 {budget.interest_points}')

    for a in allocations:
        if a.occupation_points and not a.is_occupation_skill:
            problems.append(f'职业点不能投给非本职业技能：{a.name}{a.detail and f"（{a.detail}）"}')
        if a.name == '克苏鲁神话' and a.interest_points:
            problems.append('克苏鲁神话不能用兴趣点提升')
        if (max_skill_value is not None and a.value > max_skill_value
                and a.base <= max_skill_value):
            problems.append(
                f'{a.name}{f"（{a.detail}）" if a.detail else ""} '
                f'超过创建上限 {max_skill_value}（当前 {a.value}）'
            )

    return problems


def validate_group_selection(occ: Occupation, picked: Mapping[str, list[str]]) -> list[str]:
    """校验 N 选 M 分组是否已选够。picked: {分组标记: [已选技能名]}。"""
    problems: list[str] = []
    for group in occ.skill_groups:
        names = picked.get(group.mark, [])
        if len(names) != group.pick:
            problems.append(
                f'技能组 {group.mark} 需选 {group.pick} 项，当前 {len(names)} 项'
                f'（可选：{"、".join(o.name for o in group.options)}）'
            )
    if len(picked.get('free', [])) != occ.free_picks:
        problems.append(f'任意特长需选 {occ.free_picks} 项，当前 {len(picked.get("free", []))} 项')
    return problems


def validate_free_picks(occ: Occupation, names: list[str]) -> list[str]:
    """校验任意特长选择数量（2.5④）。

    只看数量不看名单内容（名单与分配行的匹配在建卡 API 做）。
    不并入 validate_group_selection 使用：组选择目前只在前端拦截，若把不含
    组键的 picked 传进那边，带 skill_groups 的职业会被误报"组技能未选"。
    """
    if occ.free_picks == 0:
        return [f'{occ.name} 没有任意特长，不能提交'] if names else []
    if len(names) != occ.free_picks:
        return [f'任意特长需选 {occ.free_picks} 项，当前 {len(names)} 项']
    return []


def validate_credit(occ: Occupation, credit_value: int) -> list[str]:
    """信用评级初始值必须落在职业的信誉区间内。"""
    if not occ.credit_min <= credit_value <= occ.credit_max:
        return [f'信用评级 {credit_value} 超出 {occ.name} 的区间 [{occ.credit_min}, {occ.credit_max}]']
    return []


# ---------------------------------------------------------------- 自测示例


if __name__ == '__main__':
    demo = Attributes(STR=50, CON=60, SIZ=60, DEX=70, APP=50, INT=70, POW=60, EDU=80, LUK=50)
    for key in ('会计师', '杂技演员', '事务所侦探'):
        occ = get_occupation(key)
        b1 = build_budget(occ, demo)
        b2 = build_budget(occ, demo, auto_choices(occ.point_formula, demo))
        print(f'{occ.name}: 待选={[c.options for c in b1.pending]} -> 职业点={b2.occupation_points}, 兴趣点={b2.interest_points}')
