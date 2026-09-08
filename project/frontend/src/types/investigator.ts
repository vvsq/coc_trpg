/**
 * 角色卡（调查员）数据 schema — 阶段 1 定稿。
 *
 * 与 backend/app/schemas/investigator.py 字段一一对应，改动必须双侧同步。
 * 设计依据：goal.md §5.1 + coc七版规则空白卡.xlsx 技能清单。
 */

import type { AttrKey } from './occupation'

export type Era = 'classical' | 'modern' // 古典(1920s) / 现代

/** 八项属性 + 幸运。标准生成：STR/CON/DEX/APP/POW/LUK=3D6×5；SIZ/INT/EDU=(2D6+6)×5 */
export interface Attributes {
  STR: number // 力量
  CON: number // 体质
  SIZ: number // 体型
  DEX: number // 敏捷
  APP: number // 外貌
  INT: number // 智力
  POW: number // 意志
  EDU: number // 教育
  LUK: number // 幸运
}

/** 衍生值——由后端规则引擎计算，前端只读展示 */
export interface Derived {
  HP: number // 生命值 = (CON+SIZ)/10 向下取整
  MP: number // 魔法值 = POW/5 向下取整
  SAN: number // 理智 = POW
  DB: string // 伤害加值，如 "-2"、"none"、"1d4"
  build: number // 体格等级 -2~4
  MOV: number // 移动率
}

/** 技能。分类技能（格斗/射击/外语/科学/生存/学问/技艺/驾驶）可多实例，实例细分放入 detail */
export interface Skill {
  name: string // 如 "图书馆使用"、"格斗①"
  detail: string // 分类技能细分，如 "斗殴"、"英语"
  base: number // 基础值（规则书标准值）
  increment: number // 分配的成长值（职业点+兴趣点）
  occupation: boolean // 是否本职业可选技能
}

export interface Weapon {
  name: string
  skill_name: string // 关联技能名
  damage: string // 伤害表达式，如 "1d10+2"
  rng: string // 射程
  attacks: string // 每轮攻击次数
  ammo: number | string // 装弹量（武器表原始值可能是 "20/30/32" 等）
  malfunction: number // 故障值 1~100，标准表"——"时默认 100
}

/** 背景故事八要素（第七版标准） */
export interface Background {
  personal_description: string
  ideology_beliefs: string
  significant_people: string
  meaningful_location: string
  treasured_possession: string
  traits: string
  scars_injuries: string
  cash_assets: string
}

/** 游戏中变化的状态（与创建时的固定值分离，存档/同步只动这里） */
export interface InvestigatorState {
  current_hp: number
  current_mp: number
  current_sanity: number
  current_luck: number
  temp_insanity: boolean // 临时疯狂
  indefinite_insanity: boolean // 不定性疯狂
}

/** 调查员角色卡完整结构 */
export interface Investigator {
  id: string | null
  name: string
  gender: string
  age: number // 15~90
  era: Era
  occupation: string
  residence: string
  birthplace: string
  credit: number // 信用评级（创建时须落在职业区间内）
  attributes: Attributes
  derived: Derived
  skills: Skill[]
  weapons: Weapon[]
  armor: number // 护甲值
  possessions: string // 随身物品（玩家自填文本，2.5 PATCH 可编辑；老卡缺省视为 ''）
  background: Background
  state: InvestigatorState
}

/** 当前技能值 = 基础值 + 成长值 */
export function skillValue(skill: Skill): number {
  return skill.base + skill.increment
}

/** 时代展示名（详情页/整卡抽屉共用；存储值为 modern / classical） */
export function eraLabel(era: string): string {
  return era === 'classical' ? '古典(1920s)' : '现代'
}


/** 职业点数分配记录：与 backend rules/occupation.py 的 SkillAllocation 对应 */
export interface SkillAllocation {
  name: string
  slot: number // 分类技能实例序号：技艺①→1；0=普通技能
  detail: string
  base: number // 基础值（建卡向导由后端按技能表权威返回）
  occupation_points: number
  interest_points: number
  is_occupation_skill: boolean
}

export interface CreateCardPayload {
  name: string
  gender?: string
  age: number
  era: Era
  occupation_id: number // 职业 id（后端据 id 还原职业名）
  credit: number // 信用评级
  attributes: Attributes
  skills: SkillAllocation[] // ← 注意不是 Skill[]
  attribute_choices?: Record<number, AttrKey> // "力量还是敏捷"的选择，如 {0:'STR'}
  gen_mode: 'roll' | 'purchase' // 属性生成方式，purchase 时后端校验 Σ=460 与 15~90
  free_picks: string[] // 任意特长：标记为本职的技能名列表（0 项职业传空数组）
}
