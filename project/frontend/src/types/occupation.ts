/**
 * 职业数据 schema — 阶段 1。
 *
 * 与 backend/app/schemas/occupation.py 字段一一对应，改动必须双侧同步。
 * 由 backend/scripts/parse_seed_data.py 从角色卡 xlsx 生成，前端通过 API 获取，不内置全量数据。
 */

export type AttrKey = 'STR' | 'CON' | 'SIZ' | 'DEX' | 'APP' | 'INT' | 'POW' | 'EDU' | 'LUK'

/** 点数公式一项：candidates 长度 > 1 表示玩家需任选其一 */
export interface PointTerm {
  multiplier: number
  candidates: AttrKey[]
}

export interface SkillSlot {
  name: string
  slot: number // 分类技能实例序号：技艺① → 1
  detail: string // 细分："表演" / "斗殴" / "动物学"
  modern_only: boolean
}

/** N 选 M 分组技能，如「一项社交技能（取悦、话术、恐吓、说服）」 */
export interface SkillGroup {
  mark: string // '☯' | '☆' | '⊙' | '※'
  pick: number
  options: SkillSlot[]
}

export interface Occupation {
  id: number
  name: string
  aliases: string[]
  era: 'classical' | 'modern' | null
  credit_min: number
  credit_max: number
  point_formula: PointTerm[]
  fixed_skills: SkillSlot[]
  skill_groups: SkillGroup[]
  free_picks: number
  contacts: string
  intro: string
}

/** 待玩家确认的属性选择（如「力量还是敏捷」） */
export interface AttrChoice {
  index: number
  options: AttrKey[]
  chosen: AttrKey | null
}

export interface PointBudget {
  occupation_points: number // pending 非空时为 0
  interest_points: number
  pending: AttrChoice[]
}

/** 点数公式转可读文本，如「教育×4＋力量或敏捷×2」（仅展示用，不含计算） */
export function formatPointFormula(terms: PointTerm[]): string {
  return terms
    .map((t) => {
      const attr = t.candidates.length > 1 ? t.candidates.join('或') : t.candidates[0]
      return `${attr}×${t.multiplier}`
    })
    .join('＋')
}

/** 格式化一个技能位，如 {name:'格斗',detail:'斗殴'} -> '格斗(斗殴)' */
export function formatSkillSlot(slot: SkillSlot): string {
  return slot.detail ? `${slot.name}（${slot.detail}）` : slot.name
}
