<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'
import { useCardStore } from '@/stores/cards'
import { createCard, rollAttributes } from '@/api/cards'
import { formatPointFormula, formatSkillSlot } from '@/types/occupation'
import type { Occupation, PointTerm, SkillGroup, SkillSlot } from '@/types/occupation'
import type { SkillRow } from '@/types/skill'
import type { Attributes } from '@/types/investigator'

const router = useRouter()
const store = useCardStore()

// ---------- 步骤控制 ----------
const activeStep = ref(0)

// ---------- 属性标签 ----------
const attributeLabels: Record<keyof Attributes, string> = {
  STR: '力量', CON: '体质', POW: '意志', DEX: '敏捷', APP: '外貌',
  SIZ: '体型', INT: '智力', EDU: '教育', LUK: '幸运',
}
const ATTR_ORDER: (keyof Attributes)[] = ['STR', 'CON', 'SIZ', 'DEX', 'APP', 'INT', 'POW', 'EDU', 'LUK']

// ---------- 基本信息（姓名/性别/年龄/时代） ----------
const genderOptions = [
  { label: '男', value: '男' },
  { label: '女', value: '女' },
  { label: '其他', value: '其他' },
]
const eraOptions = [
  { label: '现代', value: 'modern' },
  { label: '古典 (1920s)', value: 'classical' },
]

/** 按当前时代过滤职业（era=null 表示两代通用） */
const filteredOccupations = computed(() =>
  store.occupations.filter(
    (o) => o.era === null || o.era === store.draft.era,
  ),
)

/** 时代变化：旧职业若不属于新时代则清空，连带清空公式属性选择 */
function onEraChange() {
  const cur = store.draft.occupation_id
  if (cur !== null && !filteredOccupations.value.some((o) => o.id === cur)) {
    store.draft.occupation_id = null
    store.draft.attribute_choices = {}
    rows.value = []
    groupSelections.value = {}
  }
}

/** 技能下拉 label：同名分类技能用 ①②③ 序号区分，如 "技艺①" */
function skillLabel(s: { name: string; slot: number; detail: string }): string {
  const suffix = s.slot > 0 ? '①②③'[s.slot - 1] ?? '' : ''
  const name = s.name + suffix
  return s.detail ? `${name}（${s.detail}）` : name
}

// ---------- 职业 ----------
const occ = computed<Occupation | null>(() => store.getSelectedOccupation())
const pointFormulaText = computed(() =>
  occ.value ? formatPointFormula(occ.value.point_formula) : ''
)

/** point_formula 中需要玩家从候选里选一个的项（带真实下标，attribute_choices 的键） */
const formulaChoices = computed<Array<{ index: number; term: PointTerm }>>(() =>
  (occ.value?.point_formula ?? [])
    .map((term, index) => ({ index, term }))
    .filter(({ term }) => term.candidates.length > 1)
)

function attrCn(key: string): string {
  return attributeLabels[key as keyof Attributes] ?? key
}

// ---------- 属性生成模式（投点法 / 购点法） ----------
const POINT_BUY_TOTAL = 460
// attrMode 放在 store 里：提交时 buildPayload 映射为 payload.gen_mode 供服务端校验
const { attrMode } = storeToRefs(store)
const attrLocked = ref(false) // 离开属性步骤后锁定：可回看，不可修改
const rolling = ref(false)

/** 购点法涉及的八项属性（不含幸运） */
const BUY_KEYS: (keyof Attributes)[] = ['STR', 'CON', 'SIZ', 'DEX', 'APP', 'INT', 'POW', 'EDU']

/** 购点法已用点数（八项合计） */
const buyUsed = computed(() => {
  const a = store.draft.attributes
  return BUY_KEYS.reduce((s, k) => s + a[k], 0)
})
const buyRemain = computed(() => POINT_BUY_TOTAL - buyUsed.value)

/** 投点法：后端掷骰 → 填入全部属性 → 直接进入下一步并锁定 */
async function useRollMode() {
  rolling.value = true
  try {
    const attrs = await rollAttributes()
    Object.assign(store.draft.attributes, attrs)
    store.refreshBudget()
    attrMode.value = 'roll'
    attrLocked.value = true
    activeStep.value = 2
  } finally {
    rolling.value = false
  }
}

/** 购点法：八项预填 50，幸运由后端随机生成并锁定 */
async function useBuyMode() {
  rolling.value = true
  try {
    const attrs = await rollAttributes()
    const a = store.draft.attributes
    for (const k of BUY_KEYS) a[k] = 50
    a.LUK = attrs.LUK
    store.refreshBudget()
    attrMode.value = 'buy'
  } finally {
    rolling.value = false
  }
}

/** 属性输入（仅购点法可编辑）：单项 15~90，八项总和不得超过 460 */
function onAttrInput(k: keyof Attributes, v: number | undefined) {
  const a = store.draft.attributes
  const val = Math.min(90, Math.max(15, Math.floor(v ?? 15)))
  const others = buyUsed.value - a[k]
  const allowed = POINT_BUY_TOTAL - others
  if (val > allowed) {
    ElMessage.warning(`总点数不能超过 ${POINT_BUY_TOTAL} 点`)
    a[k] = Math.max(15, allowed)
    return
  }
  a[k] = val
}

// 属性 / 公式待选项变化时刷新预算
watch(
  () => ({ ...store.draft.attributes }),
  () => { if (occ.value) store.refreshBudget() },
)
watch(
  () => ({ ...store.draft.attribute_choices }),
  () => { if (occ.value) store.refreshBudget() },
)

// ---------- 技能分配 ----------
let uidSeq = 0
function rowKey(name: string, slot: number, detail: string): string {
  return `${name}__${slot}__${detail}`
}

/** 一个分配行 = 一个 SkillAllocation + 行标识 */
interface AllocRow {
  uid: number // 稳定行标识：改细分/改名后不变，用于增删
  key: string // 唯一性判定：name__slot__detail
  name: string
  slot: number
  detail: string
  base: number
  is_occupation_skill: boolean
  inherent_occ: boolean // 来源即本职（固定技能/组技能），"本职特长"开关不可关
  free_marked: boolean // 任意特长开关（2.5④）：标记后该行可投职业点
  occupation_points: number
  interest_points: number
  removable: boolean
  candidates: string[] // 分类技能细分候选（非空且未选 detail 时需二级选择）
  is_custom: boolean // 自定义技能：需手填技能名
}

const rows = ref<AllocRow[]>([])
const groupSelections = ref<Record<string, number[]>>({}) // 组 mark -> 已选技能下标（在组 options 内）
const groupRowUid = ref<Record<string, Record<number, number>>>({}) // 组 mark -> 下标 -> 行 uid（取消勾选时按 uid 删行）

function skillBase(name: string, slot: number): number {
  const s = store.skills.find((x) => x.name === name && x.slot === slot)
  return s?.base ?? 0
}

/** 添加分配行（同 key 已存在时复用；自定义技能可重复添加且名字由玩家填写） */
function pushRow(slot: SkillSlot, isOcc: boolean, removable = false): AllocRow {
  const isCustom = slot.name === '自定义技能'
  const key = rowKey(slot.name, slot.slot, slot.detail)
  const existing = isCustom ? undefined : rows.value.find((r) => r.key === key)
  if (existing) return existing
  const meta = store.skills.find((x) => x.name === slot.name && x.slot === slot.slot)
  const row: AllocRow = {
    uid: ++uidSeq,
    key,
    name: isCustom ? '' : slot.name,
    slot: slot.slot,
    detail: slot.detail,
    base: isCustom ? 1 : skillBase(slot.name, slot.slot),
    is_occupation_skill: isOcc,
    inherent_occ: isOcc,
    free_marked: false,
    occupation_points: 0,
    interest_points: 0,
    removable,
    candidates: (meta?.pick ?? 0) > 0 ? meta?.candidates ?? [] : [],
    is_custom: isCustom,
  }
  rows.value.push(row)
  return row
}

/** 职业变化：重建固定技能行 + 技能组候选，信用评级回到职业下限。
 *  immediate：草稿残留同职业时（SPA 二次进入）occ 无变化也必须建行 */
watch(occ, (o) => {
  rows.value = []
  groupSelections.value = {}
  groupRowUid.value = {}
  if (!o) {
    store.draft.credit = 0
    return
  }
  store.draft.credit = o.credit_min
  o.fixed_skills.forEach((s) => pushRow(s, true, false))
  o.skill_groups.forEach((g) => {
    groupSelections.value[g.mark] = []
  })
}, { immediate: true })

/** 组技能勾选：勾选 pick 个后解锁对应行 */
function toggleGroupOption(g: SkillGroup, optIdx: number, checked: boolean) {
  const sel = groupSelections.value[g.mark]
  const opt = g.options[optIdx]
  if (!sel || !opt) return
  // checkbox-group 的 update 回调是全量重放（对每个选项都调一次），已选项不能重复 push
  if (checked && sel.includes(optIdx)) return
  if (checked) {
    if (sel.length >= g.pick) {
      ElMessage.warning(`本组最多选 ${g.pick} 个`)
      return
    }
    sel.push(optIdx)
    const row = pushRow(opt, true, true)
    ;(groupRowUid.value[g.mark] ??= {})[optIdx] = row.uid
  } else {
    const i = sel.indexOf(optIdx)
    if (i >= 0) sel.splice(i, 1)
    const uid = groupRowUid.value[g.mark]?.[optIdx]
    if (uid !== undefined) rows.value = rows.value.filter((r) => r.uid !== uid)
  }
}

/** 分类技能细分选择/填写（allow-create 支持手填，兼容外语、生存这类占位候选） */
function onDetailChange(row: AllocRow, v: string) {
  const detail = (v ?? '').trim()
  const nk = rowKey(row.name, row.slot, detail)
  if (rows.value.some((r) => r.uid !== row.uid && r.key === nk)) {
    ElMessage.warning('该技能细分已存在')
    return
  }
  row.detail = detail
  row.key = nk
}

/** 自定义技能命名（el-input change 触发，失焦/回车生效） */
function onCustomName(row: AllocRow, v: string) {
  const name = (v ?? '').trim()
  if (!name) return
  const nk = rowKey(name, row.slot, row.detail)
  if (rows.value.some((r) => r.uid !== row.uid && r.key === nk)) {
    ElMessage.warning('已存在同名技能')
    return
  }
  row.name = name
  row.key = nk
}

// ---------- 自由添加技能 ----------
const freeSearch = ref<number | null>(null)
function onPickFreeSkill(id: number | undefined) {
  if (id === undefined || id === null) return
  const skill = store.skills.find((x) => x.id === id)
  if (skill) pushRow(skill, false, true)
  freeSearch.value = null
}

function removeRow(row: AllocRow) {
  rows.value = rows.value.filter((r) => r.uid !== row.uid)
}

// ---------- 任意特长（2.5④）：把已分配技能标记为本职 ----------
const freeMarkedCount = computed(() => rows.value.filter((r) => r.free_marked).length)

function toggleFreeMark(row: AllocRow, checked: boolean) {
  if (!occ.value) return
  if (checked && freeMarkedCount.value >= occ.value.free_picks) {
    ElMessage.warning(`任意特长最多标记 ${occ.value.free_picks} 个`)
    return
  }
  row.free_marked = checked
  row.is_occupation_skill = row.inherent_occ || checked
  if (!checked) row.occupation_points = 0 // 取消本职后职业点失效，归零避免脏提交
}

// ---------- 点预算展示 ----------
const occupationUsed = computed(() =>
  rows.value.reduce((s, r) => s + r.occupation_points, 0))
const interestUsed = computed(() =>
  rows.value.reduce((s, r) => s + r.interest_points, 0))
const occRemain = computed(() => store.budget.occupation_points - occupationUsed.value)
const intRemain = computed(() => store.budget.interest_points - interestUsed.value)

/**
 * 单技能创建上限（与后端 `rules/occupation.py::SKILL_MAX_AT_CREATION` 同步）。
 * 规则书第三章未载明该上限，取 KP 裁定值 90；`base` 本身已超上限的技能
 * （母语 = EDU）不参与拦截，与后端判定口径一致。
 */
const SKILL_MAX_AT_CREATION = 90

function rowTotal(row: AllocRow): number {
  return row.base + row.occupation_points + row.interest_points
}

/** 被点数推过上限才算违规（母语 = EDU 那种基础值超限不算） */
function isOverCap(row: AllocRow): boolean {
  return rowTotal(row) > SKILL_MAX_AT_CREATION && row.base <= SKILL_MAX_AT_CREATION
}

/** 一个技能投职业点时需是本职业技能；超预算/超上限时拦截 */
function onOccInput(row: AllocRow, v: number | undefined) {
  const val = Math.max(0, v ?? 0)
  const delta = val - row.occupation_points
  if (delta > 0 && occRemain.value < delta) {
    ElMessage.warning('职业点不足')
    return
  }
  if (row.base + val + row.interest_points > SKILL_MAX_AT_CREATION
      && row.base <= SKILL_MAX_AT_CREATION) {
    ElMessage.warning(
      `单技能创建上限 ${SKILL_MAX_AT_CREATION}（当前 ${row.base + val + row.interest_points}）`,
    )
    return
  }
  row.occupation_points = val
}
function onIntInput(row: AllocRow, v: number | undefined) {
  const val = Math.max(0, v ?? 0)
  const delta = val - row.interest_points
  if (delta > 0 && intRemain.value < delta) {
    ElMessage.warning('兴趣点不足')
    return
  }
  if (row.base + row.occupation_points + val > SKILL_MAX_AT_CREATION
      && row.base <= SKILL_MAX_AT_CREATION) {
    ElMessage.warning(
      `单技能创建上限 ${SKILL_MAX_AT_CREATION}（当前 ${row.base + row.occupation_points + val}）`,
    )
    return
  }
  row.interest_points = val
}

// ---------- 步骤导航 ----------
async function nextStep() {
  if (activeStep.value === 0) {
    if (!store.draft.name.trim()) { ElMessage.warning('请填写姓名'); return }
    if (!store.draft.occupation_id) { ElMessage.warning('请先选择职业'); return }
    const missing = formulaChoices.value.filter(
      ({ index }) => store.draft.attribute_choices[index] === undefined,
    )
    if (missing.length) {
      ElMessage.warning(`还有 ${missing.length} 项公式属性未选择`)
      return
    }
  }
  if (activeStep.value === 1) {
    if (attrMode.value === 'none') {
      ElMessage.warning('请先选择属性生成方式')
      return
    }
    if (attrMode.value === 'buy' && buyRemain.value > 0) {
      ElMessage.warning(`还有 ${buyRemain.value} 点未分配`)
      return
    }
    attrLocked.value = true
  }
  activeStep.value++
}

// ---------- 提交 ----------
const submitting = ref(false)
async function submitCard() {
  if (!store.draft.name.trim()) { ElMessage.warning('请填写姓名'); return }
  if (!store.draft.occupation_id) { ElMessage.warning('请先选择职业'); return }
  // 组技能未选满校验（职业要求的本职技能）；去重后比较，防历史脏数组误判
  const unfinished = (occ.value?.skill_groups ?? []).some(
    (g) => new Set(groupSelections.value[g.mark] ?? []).size < g.pick,
  )
  if (unfinished) {
    ElMessage.warning('仍有技能组未选满，请先完成组技能选择')
    return
  }
  // 二级选择未完成：分类技能未选细分 / 自定义技能未命名
  const noDetail = rows.value.find((r) => r.candidates.length > 0 && !r.detail)
  if (noDetail) {
    ElMessage.warning(`请为「${noDetail.name}」选择具体细分`)
    return
  }
  if (rows.value.some((r) => r.is_custom && !r.name)) {
    ElMessage.warning('请填写自定义技能的名称')
    return
  }
  // 任意特长必须选满（free_picks=0 的职业 free_marked 恒为 false，空数组直接过）
  const freePicks = rows.value.filter((r) => r.free_marked).map((r) => r.name)
  if (occ.value && freePicks.length !== occ.value.free_picks) {
    ElMessage.warning(`任意特长需标记 ${occ.value.free_picks} 个，当前 ${freePicks.length} 个`)
    return
  }
  // 组装 payload：全部行都保存（0 点的本职技能也入卡，详情页展示基础值）
  const skills = rows.value
    .map((r) => ({
      name: r.name,
      slot: r.slot,
      detail: r.detail,
      base: r.base,
      occupation_points: r.occupation_points,
      interest_points: r.interest_points,
      is_occupation_skill: r.is_occupation_skill,
    }))
  try {
    submitting.value = true
    const payload = store.buildPayload(skills, freePicks)
    const created = await createCard(payload)
    ElMessage.success('角色卡创建成功')
    router.push(`/cards/${created.id}`)
  } catch (e) {
    // 错误已在 client 拦截器里提示
    console.error(e)
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  // 新建页一律从空白草稿开始（清掉 SPA 内残留的上次草稿）
  store.resetDraft()
  if (!store.occupations.length) await store.loadBaseData()
})
</script>

<template>
  <div class="card-create">
    <el-card class="step-card">
      <el-steps :active="activeStep" finish-status="success" align-center>
        <el-step title="基本信息与职业" />
        <el-step title="属性与掷骰" />
        <el-step title="技能分配" />
      </el-steps>

      <div class="step-content">
        <!-- ========== 步骤 1：基本信息 + 选职业 ========== -->
        <div v-show="activeStep === 0">
          <!-- 基本信息 -->
          <el-form label-width="70px" class="base-form">
            <div class="base-grid">
              <el-form-item label="姓名" required>
                <el-input v-model="store.draft.name" placeholder="调查员姓名" maxlength="50" />
              </el-form-item>
              <el-form-item label="性别">
                <el-select v-model="store.draft.gender" placeholder="选择" clearable style="width: 110px">
                  <el-option v-for="g in genderOptions" :key="g.value" :label="g.label" :value="g.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="年龄">
                <el-input-number v-model="store.draft.age" :min="15" :max="90" controls-position="right" />
              </el-form-item>
              <el-form-item label="时代">
                <el-radio-group v-model="store.draft.era" @change="onEraChange">
                  <el-radio v-for="e in eraOptions" :key="e.value" :value="e.value">
                    {{ e.label }}
                  </el-radio>
                </el-radio-group>
              </el-form-item>
            </div>
          </el-form>

          <el-divider content-position="left">选择职业</el-divider>

          <el-form label-width="70px">
            <el-form-item label="职业">
              <el-select
                v-model="store.draft.occupation_id"
                placeholder="请选择职业"
                filterable
                style="width: 320px"
                @change="store.selectOccupation"
              >
                <el-option
                  v-for="occ in filteredOccupations"
                  :key="occ.id"
                  :label="occ.name"
                  :value="occ.id"
                />
              </el-select>
            </el-form-item>
          </el-form>

          <div v-if="occ" class="occupation-info">
            <h3>{{ occ.name }}</h3>
            <p v-if="occ.intro" class="intro">{{ occ.intro }}</p>
            <p><strong>技能点公式：</strong>{{ pointFormulaText }}</p>
            <p v-if="occ.free_picks > 0">
              任意特长：本职业还可另选 {{ occ.free_picks }} 个技能作为本职（职业点可投），
              在第 3 步"分配明细"里用「本职特长」开关标记。
            </p>

            <!-- 公式中有"或"的待选属性，逐项选择 -->
            <div v-for="({ index, term }, i) in formulaChoices" :key="index" class="choice-line">
              <span>公式第 {{ index + 1 }} 项（×{{ term.multiplier }}）请选择属性：</span>
              <el-radio-group v-model="store.draft.attribute_choices[index]">
                <el-radio v-for="c in term.candidates" :key="c" :value="c">
                  {{ attrCn(c) }}
                </el-radio>
              </el-radio-group>
            </div>

            <!-- 信用评级：范围由职业决定 -->
            <div class="choice-line">
              <span>信用评级（{{ occ.credit_min }} ~ {{ occ.credit_max }}）：</span>
              <el-input-number
                v-model="store.draft.credit"
                :min="occ.credit_min"
                :max="occ.credit_max"
                controls-position="right"
              />
            </div>
          </div>
        </div>

        <!-- ========== 步骤 2：属性 ========== -->
        <div v-show="activeStep === 1">
          <!-- 生成方式选择（未选定时） -->
          <div v-if="attrMode === 'none'" class="mode-select">
            <h4>选择属性生成方式</h4>
            <p class="mode-desc">
              投点法：STR/CON/DEX/APP/POW 掷 3D6×5，SIZ/INT/EDU 掷 (2D6+6)×5，
              掷完直接进入下一步，不可反悔。<br />
              购点法：总计 460 点自由分配八项属性（单项 15~90）。<br />
              两种方式的幸运均为随机 3D6×5，生成后不可修改。
            </p>
            <el-button type="primary" :loading="rolling" @click="useRollMode">使用投点法</el-button>
            <el-button type="success" :loading="rolling" @click="useBuyMode">使用购点法</el-button>
          </div>

          <!-- 属性数值区（选定方式后展示） -->
          <div v-else>
            <div class="budget-info">
              <el-tag type="success">职业点：{{ store.budget.occupation_points }}</el-tag>
              <el-tag type="warning">兴趣点：{{ store.budget.interest_points }}</el-tag>
              <el-tag v-if="attrMode === 'buy'" :type="buyRemain === 0 ? 'info' : 'danger'">
                购点剩余：{{ buyRemain }} / {{ POINT_BUY_TOTAL }}
              </el-tag>
            </div>

            <el-alert
              v-if="attrLocked"
              title="属性已锁定，返回仅可查看，不可修改"
              type="info"
              :closable="false"
              class="lock-tip"
            />

            <el-form label-width="60px">
              <div class="attribute-grid">
                <el-form-item v-for="k in ATTR_ORDER" :key="k" :label="attributeLabels[k]">
                  <el-input-number
                    :model-value="store.draft.attributes[k]"
                    :min="15" :max="90"
                    :disabled="attrLocked || k === 'LUK'"
                    controls-position="right"
                    @update:model-value="onAttrInput(k, $event)"
                  />
                </el-form-item>
              </div>
            </el-form>
          </div>
        </div>

        <!-- ========== 步骤 3：技能分配 ========== -->
        <div v-show="activeStep === 2">
          <div class="budget-info">
            <el-tag type="success">职业点剩余：{{ occRemain }} / {{ store.budget.occupation_points }}</el-tag>
            <el-tag type="warning">兴趣点剩余：{{ intRemain }} / {{ store.budget.interest_points }}</el-tag>
            <el-tag v-if="occ && occ.free_picks > 0" :type="freeMarkedCount === occ.free_picks ? 'success' : 'info'">
              任意特长：已标记 {{ freeMarkedCount }} / {{ occ.free_picks }}
            </el-tag>
            <el-tag type="info">单技能上限 {{ SKILL_MAX_AT_CREATION }}</el-tag>
          </div>

          <!-- 技能组：先勾选，加入分配明细 -->
          <div v-if="occ?.skill_groups.length" class="skill-section">
            <h4>技能组（每组选满才能加入分配）</h4>
            <div v-for="g in occ.skill_groups" :key="g.mark" class="group-box">
              <p class="group-title">
                从以下选 {{ g.pick }} 个：
              </p>
              <el-checkbox-group
                :model-value="groupSelections[g.mark] ?? []"
                @update:model-value="(ids: number[]) => {
                  const sel = new Set(ids)
                  g.options.forEach((opt, i) => toggleGroupOption(g, i, sel.has(i)))
                }"
              >
                <el-checkbox v-for="(opt, i) in g.options" :key="`${g.mark}-${i}`" :value="i">
                  {{ formatSkillSlot(opt) }}
                </el-checkbox>
              </el-checkbox-group>
            </div>
          </div>

          <!-- 自由添加技能 -->
          <div class="skill-section">
            <h4>自由添加技能（兴趣点）</h4>
            <el-select
              :model-value="freeSearch"
              filterable
              placeholder="搜索技能添加"
              style="width: 280px"
              @update:model-value="onPickFreeSkill"
            >
              <el-option v-for="s in store.skills" :key="s.id" :label="skillLabel(s)" :value="s.id" />
            </el-select>
          </div>

          <!-- 已分配（全部行统一编辑） -->
          <div v-if="rows.length" class="skill-section">
            <h4>分配明细</h4>
            <el-table :data="rows" border>
              <el-table-column label="技能" min-width="240">
                <template #default="{ row }">
                  <!-- 自定义技能：先填名字 -->
                  <el-input
                    v-if="row.is_custom && !row.name"
                    :model-value="row.name"
                    size="small"
                    placeholder="填写自定义技能名称"
                    style="width: 180px"
                    @change="(v: string) => onCustomName(row, v)"
                  />
                  <template v-else>
                    {{ row.detail ? `${row.name}（${row.detail}）` : row.name }}
                    <el-tag v-if="row.is_occupation_skill" size="small" type="success" class="tag">本职</el-tag>
                  </template>
                  <!-- 分类技能：选/填具体细分 -->
                  <div v-if="row.candidates.length > 0 && !row.detail" class="detail-pick">
                    <el-select
                      :model-value="row.detail"
                      filterable
                      allow-create
                      default-first-option
                      size="small"
                      placeholder="选择/填写具体细分"
                      style="width: 180px"
                      @update:model-value="(v: string) => onDetailChange(row, v)"
                    >
                      <el-option v-for="c in row.candidates" :key="c" :label="c" :value="c" />
                    </el-select>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="基础" width="80">
                <template #default="{ row }">{{ row.base }}</template>
              </el-table-column>
              <el-table-column label="职业点" width="140">
                <template #default="{ row }">
                  <el-input-number
                    v-if="row.is_occupation_skill"
                    :model-value="row.occupation_points"
                    :min="0" :max="999" size="small" controls-position="right"
                    @update:model-value="onOccInput(row, $event)"
                  />
                  <span v-else class="muted">—</span>
                </template>
              </el-table-column>
              <el-table-column label="兴趣点" width="140">
                <template #default="{ row }">
                  <el-input-number
                    :model-value="row.interest_points"
                    :min="0" :max="999" size="small" controls-position="right"
                    @update:model-value="onIntInput(row, $event)"
                  />
                </template>
              </el-table-column>
              <!-- 合计 = 基础 + 职业点 + 兴趣点；超创建上限标红（后端同口径拦截） -->
              <el-table-column label="合计" width="90">
                <template #default="{ row }">
                  <span :class="{ 'over-cap': isOverCap(row) }">
                    {{ rowTotal(row) }}
                    <template v-if="isOverCap(row)">⚠</template>
                  </span>
                </template>
              </el-table-column>
              <!-- 任意特长（2.5④）：非本职行标记为本职，选满后其余禁用 -->
              <el-table-column v-if="occ && occ.free_picks > 0" label="本职特长" width="90">
                <template #default="{ row }">
                  <el-switch
                    :model-value="row.inherent_occ || row.free_marked"
                    :disabled="row.inherent_occ || (!row.free_marked && freeMarkedCount >= occ.free_picks)"
                    @update:model-value="(v: boolean) => toggleFreeMark(row, v)"
                  />
                </template>
              </el-table-column>
              <el-table-column v-if="rows.some(r => r.removable)" label="" width="80">
                <template #default="{ row }">
                  <el-button v-if="row.removable" size="small" type="danger" text @click="removeRow(row)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>

      <!-- 底部按钮 -->
      <div class="step-actions">
        <el-button v-if="activeStep > 0" @click="activeStep--">上一步</el-button>
        <span class="flex-spacer" />
        <el-button v-if="activeStep < 2" type="primary" @click="nextStep">下一步</el-button>
        <el-button v-else type="success" :loading="submitting" @click="submitCard">提交创建</el-button>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.card-create { max-width: 960px; margin: 20px auto; }
.step-card { padding: 8px; }
.step-content { min-height: 420px; margin: 20px 0; }
.occupation-info { margin-top: 12px; padding: 16px; background: #f5f7fa; border-radius: 6px; }
.intro { color: #606266; font-size: 13px; line-height: 1.7; }
.choice-line { margin-top: 10px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.attribute-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 24px; }
.mode-select h4 { margin: 0 0 8px; }
.mode-desc { color: #606266; font-size: 13px; line-height: 1.8; margin: 0 0 14px; }
.lock-tip { margin-bottom: 12px; }
.budget-info { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
.skill-section { margin-top: 18px; }
.group-box { padding: 12px; border: 1px solid #ebeef5; border-radius: 6px; margin-bottom: 12px; }
.group-title { margin: 0 0 8px; font-weight: 500; }
.detail-pick { margin-top: 4px; }
.tag { margin-left: 6px; }
.muted { color: #c0c4cc; }
/* 超过单技能创建上限：红字加粗（后端同口径会 400 拒绝） */
.over-cap { color: #f56c6c; font-weight: 600; }
.step-actions { display: flex; align-items: center; margin-top: 16px; }
.flex-spacer { flex: 1; }
</style>
