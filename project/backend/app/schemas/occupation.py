"""职业（Occupation）数据 schema — 阶段 1。

与 frontend/src/types/occupation.ts 字段一一对应，改动必须双侧同步。
数据来源：other/coc七版规则空白卡.xlsx
  - sheet「职业列表」：序号 / 职业名 / 信誉区间 / 点数公式 / 职业介绍 / 推荐关系人
  - sheet「本职技能」（隐藏）：职业 × 技能矩阵，★=本职，☯☆⊙※=N选1分组
由 scripts/parse_seed_data.py 生成 app/seed/occupations.json，运行时只读 JSON。
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.investigator import Era  # 若无 __init__.py 改为 from .investigator import ...

# 九项属性键，与 investigator.Attributes 字段同名
AttrKey = Literal['STR', 'CON', 'SIZ', 'DEX', 'APP', 'INT', 'POW', 'EDU', 'LUK']

# 解析脚本用：xlsx 里的中文属性名 → key
ATTR_CN_TO_KEY: dict[str, AttrKey] = {
    '力量': 'STR', '体质': 'CON', '体型': 'SIZ', '敏捷': 'DEX', '外貌': 'APP',
    '智力': 'INT', '意志': 'POW', '教育': 'EDU', '幸运': 'LUK',
}

# xlsx 里的分组标记（同一标记 = 同一组，组内选 pick 个）
GROUP_MARKS = ('☯', '☆', '⊙', '※')


class PointTerm(BaseModel):
    """点数公式的一项，如「教育×4」「力量或敏捷×2」。

    candidates 长度为 1 = 固定项；大于 1 = 玩家任选其一（建卡向导需要渲染单选）。
    """

    multiplier: int = Field(ge=0, description='系数，如 4')
    candidates: list[AttrKey] = Field(min_length=1, description='候选属性，长度>1 时需玩家选择')


class SkillSlot(BaseModel):
    """一个职业技能位。

    name 用 xlsx「本职技能」表的标准行名规范化后的结果（已去掉 ① 序号与 Ω 标记）。
    """

    name: str = Field(description='标准技能名，如 "图书馆使用"、"格斗"、"技艺"')
    slot: int = Field(default=0, ge=0, description='分类技能实例序号：技艺①→1，格斗①→1，0=分类头或普通技能')
    detail: str = Field(default='', description='细分，如 "表演"、"斗殴"、"动物学"')
    modern_only: bool = Field(default=False, description='是否现代专属技能（xlsx 中标 Ω）')


class SkillGroup(BaseModel):
    """N 选 1（或 N 选 M）的技能组，如「一项社交技能（取悦、话术、恐吓、说服）」."""

    mark: str = Field(description='分组标记：☯/☆/⊙/※')
    pick: int = Field(ge=1, description='该组需选几个')
    options: list[SkillSlot] = Field(default_factory=list)


class Occupation(BaseModel):
    """一个职业的完整种子数据。"""

    id: int = Field(description='xlsx 职业列表的序号，做主键')
    name: str = Field(description='职业名，如 "会计师"、"演员-戏剧演员"')
    aliases: list[str] = Field(default_factory=list, description='别名，如 "事务所侦探/保安" 拆出的两段')
    era: Era | None = Field(default=None, description='时代限定：古典/现代，None=两代通用')

    credit_min: int = Field(default=0, description='信用评级下限')
    credit_max: int = Field(default=0, description='信用评级上限')

    point_formula: list[PointTerm] = Field(description='职业点数公式，Σ(属性×系数)')

    fixed_skills: list[SkillSlot] = Field(default_factory=list, description='固定本职技能（★）')
    skill_groups: list[SkillGroup] = Field(default_factory=list, description='N 选 M 分组技能')
    free_picks: int = Field(default=0, ge=0, description='任意特长可选项数量')

    contacts: str = Field(default='', description='推荐关系人，可喂给背景生成 / AI KP')
    intro: str = Field(default='', description='职业介绍')


class AttrChoice(BaseModel):
    """待玩家确认的属性选择项（如「力量还是敏捷」）。"""

    index: int = Field(description='对应 point_formula 的下标')
    options: list[AttrKey]
    chosen: AttrKey | None = None


class PointBudget(BaseModel):
    """建卡时的技能点预算。pending 非空表示还有属性没选，点数未定。"""

    occupation_points: int = Field(description='职业点，0 表示尚未确定')
    interest_points: int = Field(description='兴趣点 = INT×2')
    pending: list[AttrChoice] = Field(default_factory=list, description='待确认的属性选择')

    @property
    def ready(self) -> bool:
        return not self.pending
