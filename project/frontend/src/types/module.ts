/**
 * 模组库类型 — 阶段 5（与后端 app/agent/module_parser.py 的 schema 一一对应）。
 *
 * 字段名与后端 PARSED_KEYS 严格同名：后端 normalize_parsed 会把缺失键补空、
 * 非法值降级，所以前端可以假定结构完整，不必逐字段防御。
 */

/** 解析生命周期：仅提取待解析 / 解析中 / 已就绪 / 失败可重试 */
export type ParseStatus = 'pending' | 'parsing' | 'ready' | 'failed'

export type SourceType = 'txt' | 'pdf' | 'docx'

export type Difficulty = 'standard' | 'hard' | 'extreme'

/** 列表项（不含 raw_text / parsed 大字段） */
export interface ModuleMeta {
  id: number
  name: string
  source_type: SourceType
  source_filename: string
  char_count: number
  has_parsed: boolean
  parse_status: ParseStatus
  parse_error: string
  parse_model: string
  parsed_at: string | null
  created_at: string
}

export interface ModuleNpc {
  name: string
  public_identity: string
  hidden_motive: string
  player_clues: string
  misdirection: string
  pressed_reaction: string
  exit_plan: string
  stats: Record<string, unknown>
}

export interface ModuleAct {
  order: number
  title: string
  summary: string
  public_goal: string
  keeper_goal: string
  key_clues: string
}

export interface ModuleClue {
  code: string
  content: string
  visibility: 'public' | 'keeper'
  points_to: string
}

export interface ModuleClock {
  name: string
  target: number
  note: string
}

export interface ModuleEnding {
  name: string
  condition: string
}

export interface ModuleCheck {
  skill: string
  difficulty: Difficulty
  scene: string
  stake: string
}

/** 结构化剧情骨架（LLM 产出 + KP 人工校对） */
export interface ModuleParsed {
  title: string
  background: string
  tone: string
  hook: string
  acts: ModuleAct[]
  npcs: ModuleNpc[]
  clues: ModuleClue[]
  clocks: ModuleClock[]
  endings: ModuleEnding[]
  key_checks: ModuleCheck[]
  warnings: string[]
}

export interface ModuleDetail extends ModuleMeta {
  raw_text: string
  parsed: ModuleParsed | null
}

export const PARSE_STATUS_LABEL: Record<ParseStatus, string> = {
  pending: '待解析',
  parsing: '解析中',
  ready: '已就绪',
  failed: '解析失败',
}

/** 状态徽章配色（对应 el-tag 的 type） */
export const PARSE_STATUS_TAG: Record<ParseStatus, 'info' | 'primary' | 'success' | 'danger'> = {
  pending: 'info',
  parsing: 'primary',
  ready: 'success',
  failed: 'danger',
}

export const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  txt: 'TXT',
  pdf: 'PDF',
  docx: 'DOCX',
}

export const DIFFICULTY_LABEL: Record<Difficulty, string> = {
  standard: '常规',
  hard: '困难',
  extreme: '极难',
}

/** parsed 为空时的占位骨架（详情页在未解析时也能渲染出结构） */
export const EMPTY_PARSED: ModuleParsed = {
  title: '',
  background: '',
  tone: '',
  hook: '',
  acts: [],
  npcs: [],
  clues: [],
  clocks: [],
  endings: [],
  key_checks: [],
  warnings: [],
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  return iso.slice(0, 16).replace('T', ' ')
}
