"""角色卡与静态规则数据接口 — 阶段 2。

职责边界：
  - GET 三个只读接口只查库，无副作用
  - POST /cards 是唯一写接口：客户端只上报"选择"（属性/职业/技能点分配），
    衍生值一律由规则引擎后端计算；技能点校验复用 rules/occupation.py
    （build_budget + validate_allocation），不在本层重复写业务判断。
  - PATCH /cards/{id}（2.5③）与 GET /weapons：卡面编辑（背景八要素/随身物品/
    武器），武器标准表来自 seed/weapons.json（scripts/parse_weapons.py 生成）。
"""
import json
from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.db import get_session
from app.models import Card, OccupationRow, SkillRow, save_card
from app.rules.coc7 import derive, validate_point_buy
from app.rules.occupation import (
    SKILL_MAX_AT_CREATION,
    SkillAllocation,
    build_budget,
    validate_allocation,
    validate_credit,
    validate_free_picks,
)
from app.schemas.investigator import (
    Attributes, Background, Era, Investigator, InvestigatorState, Skill, Weapon,
)
from app.schemas.occupation import AttrKey, Occupation

router = APIRouter()

WEAPONS_SEED_PATH = Path(__file__).resolve().parents[1] / 'seed' / 'weapons.json'


# ============================================================================
# 静态规则数据（建卡向导的数据源）
# ============================================================================


@router.get('/occupations')
def list_occupations(session: Session = Depends(get_session)):
    """全部职业的轻量列表（下拉框用，不带点公式/技能等大 JSON）。"""
    rows = session.exec(select(OccupationRow)).all()
    return [{'id': r.id, 'name': r.name, 'era': r.era} for r in rows]


@router.get('/skills')
def list_skills(session: Session = Depends(get_session)):
    """技能表全量（建卡向导做技能底子用）。"""
    return session.exec(select(SkillRow)).all()


@lru_cache(maxsize=1)
def _load_weapons_seed() -> list[dict]:
    return json.loads(WEAPONS_SEED_PATH.read_text(encoding='utf-8'))


@router.get('/weapons')
def list_weapons():
    """标准武器表（coc七版武器列表 seed，卡面编辑"标准表选"的数据源）。

    原始字符串保留（damage 的"1D6+半DB"、ammo 的"20/30/32"、价格"N/A"等），
    时代过滤由前端按卡面 era 与 weapon.era 字段自行判断。
    """
    return _load_weapons_seed()


# ============================================================================
# 角色卡 CRUD
# ============================================================================

@router.get('/occupations/{occ_id}')
def get_occupation(occ_id: int, session: Session = Depends(get_session)):
    row = session.get(OccupationRow, occ_id)
    if not row:
        raise HTTPException(status_code=404, detail='职业不存在')
    return row.data


@router.get('/cards')
def list_cards(session: Session = Depends(get_session)):
    """角色卡列表（列表页展示投影列即可，不带整卡 JSON）。"""
    rows = session.exec(select(Card)).all()
    return [{'id': r.id, 'name': r.name, 'occupation': r.occupation, 'era': r.era} for r in rows]


@router.get('/cards/{card_id}')
def get_card(card_id: str, session: Session = Depends(get_session)):
    """角色卡详情：card_data 是权威整卡，原样返回。"""
    row = session.get(Card, card_id)
    if not row:
        raise HTTPException(status_code=404, detail='角色卡不存在')
    return row.card_data


class BudgetRequest(BaseModel):
    """建卡向导"预算预览"请求：职业 id + 属性 + 公式待选项。"""

    occupation_id: int
    attributes: Attributes
    attribute_choices: dict[int, AttrKey] | None = None


@router.post('/cards/budget')
def card_budget(payload: BudgetRequest, session: Session = Depends(get_session)):
    """按职业公式算职业点/兴趣点预算（前端属性每变一次调一次）。

    职业点数公式只在此处（rules/occupation.py）维护，前端不复制规则。
    """
    occ_row = session.get(OccupationRow, payload.occupation_id)
    if not occ_row:
        raise HTTPException(status_code=404, detail='职业不存在')
    occ = Occupation.model_validate(occ_row.data)
    return build_budget(occ, payload.attributes, payload.attribute_choices)


class CardCreate(BaseModel):
    """建卡请求体。

    skills 用 SkillAllocation（职业点/兴趣点分离），这样 validate_allocation
    能校验两类点的独立上限；落库时再合并成 Skill.increment。
    attribute_choices: 职业点数公式含"或"选项时的选择，如 {0: 'STR'} 表示
    公式第 0 项选择力量。缺省时若职业公式带"或"会返回 400。
    """

    name: str = Field(min_length=1, max_length=50)
    gender: str = ''
    age: int = Field(default=25, ge=15, le=90)
    era: Era = 'modern'
    occupation_id: int
    credit: int = Field(default=0, ge=0, description='信用评级，须落在职业区间内')
    attributes: Attributes
    skills: list[SkillAllocation] = Field(default_factory=list)
    attribute_choices: dict[int, AttrKey] | None = None
    gen_mode: Literal['roll', 'purchase'] | None = Field(
        default=None,
        description='属性生成方式：purchase 时服务端校验 Σ=460 与单项 15~90；roll/缺省不校验',
    )
    free_picks: list[str] | None = Field(
        default=None,
        description='任意特长：标记为本职的技能名列表，长度须恰为职业 free_picks',
    )


def _resolve_skill_base(session: Session, alloc: SkillAllocation) -> int:
    """技能基础值权威化：以 skill 表为准，自定义技能（查不到）才用客户端提交值。"""
    row = session.exec(
        select(SkillRow).where(
            SkillRow.name == alloc.name,
            SkillRow.slot == alloc.slot,
        )
    ).first()
    if row is not None and row.base is not None:
        return row.base
    return alloc.base


@router.post('/cards', status_code=201)
def create_card(payload: CardCreate, session: Session = Depends(get_session)):
    # 1) 查职业，还原成规则引擎用的 Occupation 对象
    occ_row = session.get(OccupationRow, payload.occupation_id)
    if not occ_row:
        raise HTTPException(status_code=404, detail='职业不存在')
    occ = Occupation.model_validate(occ_row.data)

    # 1.5) 购点法属性校验：尽早拒绝，不浪费后面的预算/技能校验
    if payload.gen_mode == 'purchase':
        purchase_problems = validate_point_buy(payload.attributes)
        if purchase_problems:
            raise HTTPException(status_code=400, detail='；'.join(purchase_problems))

    # 1.6) 任意特长数量校验：尽早拒绝；名字与分配行的匹配在技能组装时处理
    free_names = payload.free_picks or []
    free_problems = validate_free_picks(occ, free_names)
    if free_problems:
        raise HTTPException(status_code=400, detail='；'.join(free_problems))

    # 2) 技能基础值权威化：skill 表为准，查不到(自定义)才用客户端值。
    #    名字命中 free_picks 的行标记为本职（自定义技能按名字匹配），必须
    #    先于 validate_allocation——否则职业点投给刚标记的技能会被误判超权限。
    free_set = set(free_names)
    allocations = [
        SkillAllocation(
            name=s.name, slot=s.slot, detail=s.detail,
            base=_resolve_skill_base(session, s),
            occupation_points=s.occupation_points,
            interest_points=s.interest_points,
            is_occupation_skill=s.is_occupation_skill or s.name in free_set,
        )
        for s in payload.skills
    ]
    if free_set:
        allocated_names = {a.name for a in allocations}
        missing = [n for n in free_names if n not in allocated_names]
        if missing:
            raise HTTPException(
                status_code=400,
                detail='任意特长技能不在分配的技能行中：' + '、'.join(missing),
            )

    # 3) 职业点数预算：先确认公式中的"或"属性已选齐
    budget = build_budget(occ, payload.attributes, payload.attribute_choices)
    if budget.pending:
        raise HTTPException(
            status_code=400,
            detail='职业点公式含待选项，请先选择属性: '
                   + '、'.join('|'.join(c.options) for c in budget.pending),
        )

    # 4) 技能点分配校验（超支/克苏鲁神话用兴趣点/职业点投非本职技能/单技能创建上限等）
    #    credit 一并计入职业点占用（规则书 3.3：信用评级初始 0，投入点数 = 最终值）
    problems = validate_allocation(
        occ, payload.attributes, allocations, payload.attribute_choices,
        max_skill_value=SKILL_MAX_AT_CREATION,
        credit=payload.credit,
    )
    if problems:
        raise HTTPException(status_code=400, detail='；'.join(problems))

    # 5) 信用评级必须落在职业区间内
    credit_problems = validate_credit(occ, payload.credit)
    if credit_problems:
        raise HTTPException(status_code=400, detail='；'.join(credit_problems))

    # 6) 衍生值由后端算（客户端不可信）。derive 现在直接返回 schema 版 Derived
    derived = derive(payload.attributes, payload.age)

    # 7) 组装整卡：SkillAllocation(分离来源) -> Skill(合并 increment)
    card_id = str(uuid4())
    skills = [
        Skill(
            name=s.name,
            detail=s.detail,
            base=s.base,
            increment=s.occupation_points + s.interest_points,
            occupation=s.is_occupation_skill,
        )
        for s in allocations
    ]
    investigator = Investigator(
        id=card_id,
        name=payload.name,
        gender=payload.gender,
        age=payload.age,
        era=payload.era,
        occupation=occ.name,
        credit=payload.credit,
        attributes=payload.attributes,
        derived=derived,
        skills=skills,
        background=Background(),
        state=InvestigatorState(
            current_hp=derived.HP,
            current_mp=derived.MP,
            current_sanity=derived.SAN,
            current_luck=payload.attributes.LUK,
        ),
    )

    # 8) 落库：card_data 存权威整卡，投影列经 save_card 单一入口同步
    card = Card(
        id=card_id,
        owner='local',  # TODO: 接入房间/成员后改为真实玩家标识（models.Card.owner）
    )
    save_card(card, investigator.model_dump(mode='json'))
    session.add(card)
    session.commit()
    session.refresh(card)
    return card.card_data


@router.delete('/cards/{card_id}', status_code=204)
def delete_card(card_id: str, session: Session = Depends(get_session)):
    """删除角色卡。"""
    row = session.get(Card, card_id)
    if not row:
        raise HTTPException(status_code=404, detail='角色卡不存在')
    session.delete(row)
    session.commit()


class CardPatch(BaseModel):
    """卡面编辑请求体（2.5③）：仅背景八要素 / 随身物品 / 武器三块可改。

    属性、技能、职业等建卡时确定的字段不在可编辑范围。None = 该块不更新
    （PATCH 部分更新语义；前端编辑器每次全量带三块也没问题）。
    """

    background: Background | None = None
    possessions: str | None = Field(default=None, max_length=4000)
    weapons: list[Weapon] | None = None


@router.patch('/cards/{card_id}')
def patch_card(card_id: str, payload: CardPatch, session: Session = Depends(get_session)):
    """部分更新角色卡：只覆写请求体中出现的块，整卡过 Investigator 校验后落库。"""
    row = session.get(Card, card_id)
    if not row:
        raise HTTPException(status_code=404, detail='角色卡不存在')
    if payload.background is None and payload.possessions is None and payload.weapons is None:
        raise HTTPException(status_code=400, detail='请求体不含任何可更新字段（background/possessions/weapons）')

    investigator = Investigator.model_validate(row.card_data)
    if payload.background is not None:
        investigator.background = payload.background
    if payload.possessions is not None:
        investigator.possessions = payload.possessions
    if payload.weapons is not None:
        investigator.weapons = payload.weapons

    # 整卡 JSON 单一写入口（save_card 同步投影列），row 已在 session 中
    save_card(row, investigator.model_dump(mode='json'))
    session.commit()
    session.refresh(row)
    return row.card_data
