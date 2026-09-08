"""角色卡（调查员）数据 schema — 阶段 1 定稿。

与 frontend/src/types/investigator.ts 字段一一对应，改动必须双侧同步。
设计依据：goal.md §5.1 + coc七版规则空白卡.xlsx 技能清单。
"""
from typing import Literal

from pydantic import BaseModel, Field

Era = Literal['classical', 'modern']  # 古典(1920s) / 现代


class Attributes(BaseModel):
    """八项属性 + 幸运。标准生成：STR/CON/DEX/APP/POW/LUK=3D6×5；SIZ/INT/EDU=(2D6+6)×5。"""

    STR: int = Field(ge=0, le=400, description='力量')
    CON: int = Field(ge=0, le=400, description='体质')
    SIZ: int = Field(ge=0, le=400, description='体型')
    DEX: int = Field(ge=0, le=400, description='敏捷')
    APP: int = Field(ge=0, le=400, description='外貌')
    INT: int = Field(ge=0, le=400, description='智力')
    POW: int = Field(ge=0, le=400, description='意志')
    EDU: int = Field(ge=0, le=400, description='教育')
    LUK: int = Field(default=0, ge=0, le=400, description='幸运')


class Derived(BaseModel):
    """衍生值——由后端规则引擎计算，前端只读展示，不接受客户端写入。"""

    HP: int = Field(description='生命值 = (CON+SIZ)/10 向下取整')
    MP: int = Field(description='魔法值 = POW/5 向下取整')
    SAN: int = Field(description='理智 = POW')
    DB: str = Field(description='伤害加值，如 "-2"、"none"、"1d4"')
    build: int = Field(description='体格等级 -2~4')
    MOV: int = Field(description='移动率')


class Skill(BaseModel):
    """技能。分类技能（格斗/射击/外语/科学/生存/学问/技艺/驾驶）可多实例，实例细分放入 detail。"""

    name: str = Field(description='技能名，如 "图书馆使用"、"格斗①"')
    detail: str = Field(default='', description='分类技能细分，如 格斗(斗殴)、外语(英语)')
    base: int = Field(ge=0, description='基础值（规则书标准值）')
    increment: int = Field(default=0, ge=0, description='分配的成长值（职业点+兴趣点）')
    occupation: bool = Field(default=False, description='是否本职业可选技能（职业点只能投给 occupation=true）')

    @property
    def value(self) -> int:
        """当前技能值 = 基础值 + 成长值。"""
        return self.base + self.increment


class Weapon(BaseModel):
    name: str
    skill_name: str = Field(description='关联技能名，如 "射击①"')
    damage: str = Field(description='伤害表达式，如 "1d10+2"')
    rng: str = Field(default='', description='射程')
    attacks: str = Field(default='1', description='每轮攻击次数')
    # 装弹量保留原始写法（武器表有 "20/30/32"、"一次性" 等非整数），数字串由 Pydantic 归一为 int
    ammo: int | str = Field(default=0, description='装弹量，如 6、"20/30/32"、"一次性"')
    malfunction: int = Field(default=100, ge=1, le=100, description='故障值，武器表为"——"时默认 100')


class Background(BaseModel):
    """背景故事八要素（第七版标准）。"""

    personal_description: str = Field(default='', description='个人描述')
    ideology_beliefs: str = Field(default='', description='思想信念')
    significant_people: str = Field(default='', description='重要之人')
    meaningful_location: str = Field(default='', description='意义非凡之地')
    treasured_possession: str = Field(default='', description='宝贵之物')
    traits: str = Field(default='', description='特质')
    scars_injuries: str = Field(default='', description='伤疤与恐惧')
    cash_assets: str = Field(default='', description='资产')


class InvestigatorState(BaseModel):
    """游戏中变化的状态（与创建时的固定值分离，存档/同步只动这里）。"""

    current_hp: int = Field(ge=0)
    current_mp: int = Field(ge=0)
    current_sanity: int = Field(ge=0)
    current_luck: int = Field(ge=0)
    temp_insanity: bool = Field(default=False, description='临时疯狂标记')
    indefinite_insanity: bool = Field(default=False, description='不定性疯狂标记')


class Investigator(BaseModel):
    """调查员角色卡完整结构（创建信息 + 状态一体，序列化为 JSON 存储）。"""

    id: str | None = None
    name: str = Field(min_length=1, max_length=50)
    gender: str = ''
    age: int = Field(default=25, ge=15, le=90)
    era: Era = 'modern'
    occupation: str = ''
    residence: str = ''
    birthplace: str = ''
    credit: int = Field(default=0, ge=0, description='信用评级（创建时须落在职业区间内）')

    attributes: Attributes
    derived: Derived
    skills: list[Skill] = Field(default_factory=list)
    weapons: list[Weapon] = Field(default_factory=list)
    armor: int = Field(default=0, ge=0, description='护甲值')
    possessions: str = Field(default='', description='随身物品，玩家自填文本，2.5 PATCH 可编辑')

    background: Background = Field(default_factory=Background)
    state: InvestigatorState



def skill_total_increment(skills: list[Skill]) -> int:
    """已分配的技能点总数（校验用：不得超过职业点+兴趣点）。"""
    return sum(s.increment for s in skills)
