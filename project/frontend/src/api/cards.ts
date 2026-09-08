import { client } from './client'
import type { Background, Investigator, CreateCardPayload, Weapon } from '@/types/investigator'
import type { Occupation } from '@/types/occupation'
import type { SkillRow } from '@/types/skill'
import type { Attributes } from '@/types/investigator'
import type { AttrKey, PointBudget } from '@/types/occupation'

// ---------- 轻量职业列表项（与后端 /occupations 响应一致） ----------
export interface OccupationLite {
  id: number
  name: string
  era: 'classical' | 'modern' | null
}

// ---------- 预算预览请求（POST /cards/budget） ----------
export interface BudgetRequest {
  occupation_id: number
  attributes: Attributes
  attribute_choices?: Record<number, AttrKey>
}

// ---------- API 函数 ----------
// 说明：响应拦截器已返回 response.data，故统一用 axios 第二泛型取响应体：
// client.get<T, T>(url) 的类型是 Promise<T>，无需再写 `as`。

/** 获取职业列表（轻量） */
export async function listOccupations(): Promise<OccupationLite[]> {
  return client.get<OccupationLite[], OccupationLite[]>('/occupations')
}

/** 获取职业详情（含技能点公式、本职技能列表等） */
export async function getOccupation(id: number): Promise<Occupation> {
  return client.get<Occupation, Occupation>(`/occupations/${id}`)
}

/** 获取全部技能列表 */
export async function listSkills(): Promise<SkillRow[]> {
  return client.get<SkillRow[], SkillRow[]>('/skills')
}

/** 预算预览：按职业公式 + 当前属性算职业点/兴趣点（向导每步刷新调用） */
export async function getBudget(payload: BudgetRequest): Promise<PointBudget> {
  return client.post<PointBudget, PointBudget>('/cards/budget', payload)
}

/** 掷骰生成全套属性（投点法全用；购点法只取 LUK），规则在后端 rules/coc7 */
export async function rollAttributes(): Promise<Attributes> {
  return client.post<Attributes, Attributes>('/dice/attributes')
}

/** 角色卡列表项（轻量，与 GET /cards 响应一致） */
export interface CardListItem {
  id: string
  name: string
  occupation: string
  era: string
}

/** 获取角色卡列表（轻量） */
export async function listCards(): Promise<CardListItem[]> {
  return client.get<CardListItem[], CardListItem[]>('/cards')
}

/** 创建角色卡 */
export async function createCard(payload: CreateCardPayload): Promise<Investigator> {
  return client.post<Investigator, Investigator>('/cards', payload)
}

/** 根据 ID 获取角色卡详情 */
export async function getCard(id: string): Promise<Investigator> {
  return client.get<Investigator, Investigator>(`/cards/${id}`)
}

/** 删除角色卡 */
export async function deleteCard(id: string): Promise<void> {
  await client.delete(`/cards/${id}`)
}

// ---------- 卡面编辑（2.5③：背景八要素 / 随身物品 / 武器） ----------

/** PATCH /cards/{id} 请求体：只带需要更新的块，其余块不动 */
export interface PatchCardPayload {
  background?: Background
  possessions?: string
  weapons?: Weapon[]
}

/** 部分更新角色卡，返回更新后的整卡 */
export async function updateCard(id: string, payload: PatchCardPayload): Promise<Investigator> {
  return client.patch<Investigator, Investigator>(`/cards/${id}`, payload)
}

/** GET /weapons 标准武器行（seed/weapons.json，伤害/装弹量/价格等保留原始写法） */
export interface StandardWeapon {
  id: number
  name: string
  skill_name: string
  damage: string
  rng: string
  penetrate: string // 贯穿 ×/√
  attacks: string
  ammo: number | string
  malfunction: number | null // "——" 时为 null，入卡时默认 100
  era: string // 常见时代，如 "1920s、现代"
  price: string
  invented: string
  category: string
  era_tags: string // 不合时代 / 罕见 等
  notes?: string[]
}

/** 标准武器表全量（卡面编辑"标准表选"数据源，时代过滤在前端做） */
export async function listStandardWeapons(): Promise<StandardWeapon[]> {
  return client.get<StandardWeapon[], StandardWeapon[]>('/weapons')
}
