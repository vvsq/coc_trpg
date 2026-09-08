import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { getBudget, getOccupation, listOccupations, listSkills, type OccupationLite } from '@/api/cards'
import type { Attributes, CreateCardPayload } from '@/types/investigator'
import type { AttrKey, Occupation } from '@/types/occupation'
import type { SkillRow } from '@/types/skill'

/** 建卡草稿基础字段（不含技能分配行——那是向导的 UI 状态） */
export interface CardDraftBase {
  name: string
  gender: string
  age: number
  era: 'classical' | 'modern'
  occupation_id: number | null
  credit: number
  attributes: Attributes
  attribute_choices: Record<number, AttrKey>
}

const defaultAttributes = (): Attributes => ({
  STR: 50, CON: 50, SIZ: 50, DEX: 50, APP: 50, INT: 50, POW: 50, EDU: 50, LUK: 50,
})

const defaultDraft = (): CardDraftBase => ({
  name: '',
  gender: '',
  age: 25,
  era: 'modern',
  occupation_id: null,
  credit: 0,
  attributes: defaultAttributes(),
  attribute_choices: {},
})

export const useCardStore = defineStore('card', () => {
  // ---------- 静态数据（进建卡向导加载一次） ----------
  const occupations = ref<OccupationLite[]>([])
  const occupationMap = ref<Record<number, Occupation>>({})
  const skills = ref<SkillRow[]>([])

  // ---------- 草稿 ----------
  const draft = reactive<CardDraftBase>(defaultDraft())

  /** 属性生成方式（'none'=向导第 2 步尚未选择），提交时映射为 payload.gen_mode */
  const attrMode = ref<'none' | 'roll' | 'buy'>('none')

  // ---------- 预算（由后端公式计算，前端不复制规则） ----------
  const budget = ref<{ occupation_points: number; interest_points: number }>({
    occupation_points: 0,
    interest_points: 0,
  })
  const budgetLoading = ref(false)

  // ---------- 加载 ----------
  async function loadBaseData() {
    const [occList, skillList] = await Promise.all([listOccupations(), listSkills()])
    occupations.value = occList
    skills.value = skillList
  }

  async function loadOccupation(id: number) {
    if (!occupationMap.value[id]) {
      occupationMap.value[id] = await getOccupation(id)
    }
    return occupationMap.value[id]
  }

  /** 职业变化时清空旧缓存引用并刷新预算 */
  async function selectOccupation(id: number) {
    draft.occupation_id = id
    draft.attribute_choices = {}
    const occ = await loadOccupation(id)
    if (occ.point_formula.some((t) => t.candidates.length > 1)) {
      // 有"或"选项：由向导逐项询问后写入 draft.attribute_choices
    }
    await refreshBudget()
  }

  /** 属性或公式选项变化后调用，刷新点数预算 */
  async function refreshBudget() {
    if (!draft.occupation_id) return
    budgetLoading.value = true
    try {
      const res = await getBudget({
        occupation_id: draft.occupation_id,
        attributes: { ...draft.attributes },
        attribute_choices: { ...draft.attribute_choices },
      })
      budget.value = {
        occupation_points: res.occupation_points,
        interest_points: res.interest_points,
      }
    } finally {
      budgetLoading.value = false
    }
  }

  function resetDraft() {
    Object.assign(draft, defaultDraft())
    attrMode.value = 'none'
    budget.value = { occupation_points: 0, interest_points: 0 }
  }

  /** 当前选中职业（可能为 null） */
  function getSelectedOccupation(): Occupation | null {
    return draft.occupation_id ? occupationMap.value[draft.occupation_id] ?? null : null
  }

  /** 提交构建 payload（occupation_id 换回后端所需字段） */
  function buildPayload(skills: CreateCardPayload['skills'], freePicks: string[] = []): CreateCardPayload {
    if (!draft.occupation_id) throw new Error('未选择职业')
    if (attrMode.value === 'none') throw new Error('未选择属性生成方式')
    return {
      name: draft.name,
      gender: draft.gender,
      age: draft.age,
      era: draft.era,
      occupation_id: draft.occupation_id,
      credit: draft.credit,
      attributes: { ...draft.attributes },
      skills,
      attribute_choices:
        Object.keys(draft.attribute_choices).length > 0 ? { ...draft.attribute_choices } : undefined,
      gen_mode: attrMode.value === 'buy' ? 'purchase' : 'roll',
      free_picks: freePicks,
    }
  }

  return {
    occupations,
    occupationMap,
    skills,
    draft,
    attrMode,
    budget,
    budgetLoading,
    loadBaseData,
    selectOccupation,
    refreshBudget,
    resetDraft,
    getSelectedOccupation,
    buildPayload,
  }
})
