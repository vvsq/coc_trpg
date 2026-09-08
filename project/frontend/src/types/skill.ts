/**
 * 后端 /api/skills 返回的技能行 —— 与 backend SkillRow 表列一一对应。
 */

export interface SkillRow {
  id: number
  name: string
  slot: number // 分类技能实例序号：技艺① → 1
  detail: string
  modern_only: boolean
  pick: number // 需从候选里选几个：1 = 选一；0 = 非分组技能
  candidates: string[] // 分组技能的候选项，如技艺的 [表演, 美术, 摄影, …]
  base: number | null // 基础值；表达式基础值（DEX/2、EDU）时为 null
  base_expr: string // 表达式基础值，如 "DEX/2"、"EDU"；普通技能为空串
  description: string // 技能说明（txt 里 - 行）
}
