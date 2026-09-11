<script setup lang="ts">
/**
 * 结构化结果校对器 — 阶段 5。
 *
 * 分块折叠展示 LLM 抽取结果，每块可进入就地编辑并**只提交该块**
 * （后端 PUT /modules/{id} 是局部覆盖语义，未提交的键保留原值）。
 *
 * 保存走父组件传入的 saveHandler（返回 Promise）：这样保存中能显示加载态、
 * 失败时保持编辑态不丢用户输入——比 emit 后再靠 props 变化关弹窗更可靠。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  DIFFICULTY_LABEL,
  type ModuleParsed,
} from '@/types/module'

type ListKey = 'acts' | 'npcs' | 'clues' | 'clocks' | 'endings' | 'key_checks'
type SectionKey = 'summary' | ListKey

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'textarea' | 'number' | 'select'
  width?: number
  /** 守秘字段（仅 KP 可见的信息，用暗红边标出，提醒不要写进公开叙事） */
  keeper?: boolean
  options?: { label: string; value: string }[]
}

interface SectionDef {
  key: ListKey
  title: string
  fields: FieldDef[]
}

const props = defineProps<{
  parsed: ModuleParsed
  saveHandler: (patch: Partial<ModuleParsed>) => Promise<void>
}>()

const SECTIONS: SectionDef[] = [
  {
    key: 'acts',
    title: '分幕',
    fields: [
      { key: 'order', label: '序', type: 'number', width: 70 },
      { key: 'title', label: '幕名', type: 'text', width: 150 },
      { key: 'summary', label: '梗概', type: 'textarea' },
      { key: 'public_goal', label: '玩家可见目标', type: 'textarea' },
      { key: 'keeper_goal', label: '守秘目标', type: 'textarea', keeper: true },
      { key: 'key_clues', label: '关键线索', type: 'textarea' },
    ],
  },
  {
    key: 'npcs',
    title: 'NPC 档案',
    fields: [
      { key: 'name', label: '姓名', type: 'text', width: 150 },
      { key: 'public_identity', label: '公开身份', type: 'textarea' },
      { key: 'hidden_motive', label: '隐藏动机', type: 'textarea', keeper: true },
      { key: 'player_clues', label: '玩家可得线索', type: 'textarea' },
      { key: 'misdirection', label: '误导', type: 'textarea', keeper: true },
      { key: 'pressed_reaction', label: '被逼问反应', type: 'textarea', keeper: true },
      { key: 'exit_plan', label: '离场方案', type: 'textarea', keeper: true },
    ],
  },
  {
    key: 'clues',
    title: '线索',
    fields: [
      { key: 'code', label: '编号', type: 'text', width: 110 },
      { key: 'content', label: '内容', type: 'textarea' },
      {
        key: 'visibility',
        label: '可见性',
        type: 'select',
        width: 120,
        options: [
          { label: '公开', value: 'public' },
          { label: '仅 KP', value: 'keeper' },
        ],
      },
      { key: 'points_to', label: '指向', type: 'textarea' },
    ],
  },
  {
    key: 'clocks',
    title: '威胁时钟',
    fields: [
      { key: 'name', label: '名称', type: 'text', width: 160 },
      { key: 'target', label: '总格数', type: 'number', width: 90 },
      { key: 'note', label: '走满后果', type: 'textarea', keeper: true },
    ],
  },
  {
    key: 'endings',
    title: '结局',
    fields: [
      { key: 'name', label: '结局名', type: 'text', width: 180 },
      { key: 'condition', label: '触发条件', type: 'textarea', keeper: true },
    ],
  },
  {
    key: 'key_checks',
    title: '关键检定',
    fields: [
      { key: 'skill', label: '技能', type: 'text', width: 140 },
      {
        key: 'difficulty',
        label: '难度',
        type: 'select',
        width: 110,
        options: [
          { label: '常规', value: 'standard' },
          { label: '困难', value: 'hard' },
          { label: '极难', value: 'extreme' },
        ],
      },
      { key: 'scene', label: '幕次/场景', type: 'text', width: 140 },
      { key: 'stake', label: '失败后果', type: 'textarea' },
    ],
  },
]

const openSections = ref<string[]>(['summary', 'npcs'])
const editing = ref<SectionKey | null>(null)
const saving = ref(false)
const draftRows = ref<Record<string, unknown>[]>([])
const draftSummary = ref({ title: '', background: '', tone: '', hook: '' })

function rowsOf(key: ListKey): Record<string, unknown>[] {
  return (props.parsed[key] as unknown as Record<string, unknown>[]) ?? []
}

function startEdit(key: SectionKey): void {
  editing.value = key
  if (key === 'summary') {
    draftSummary.value = {
      title: props.parsed.title,
      background: props.parsed.background,
      tone: props.parsed.tone,
      hook: props.parsed.hook,
    }
    return
  }
  draftRows.value = rowsOf(key).map((row) => ({ ...row }))
  if (!openSections.value.includes(key)) openSections.value.push(key)
}

function addRow(section: SectionDef): void {
  const blank: Record<string, unknown> = {}
  for (const field of section.fields) blank[field.key] = field.type === 'number' ? 0 : ''
  draftRows.value.push(blank)
}

function removeRow(index: number): void {
  draftRows.value.splice(index, 1)
}

async function saveSection(key: SectionKey): Promise<void> {
  saving.value = true
  try {
    await props.saveHandler(
      key === 'summary' ? { ...draftSummary.value } : { [key]: draftRows.value },
    )
    editing.value = null
    ElMessage.success('已保存')
  } catch {
    // 拦截器已提示错误，保持编辑态让用户重试
  } finally {
    saving.value = false
  }
}

function cellText(row: Record<string, unknown>, field: FieldDef): string {
  const value = row[field.key]
  if (field.key === 'difficulty') return DIFFICULTY_LABEL[value as keyof typeof DIFFICULTY_LABEL] ?? String(value ?? '')
  if (field.key === 'visibility') return value === 'public' ? '公开' : '仅 KP'
  return String(value ?? '')
}
</script>

<template>
  <div class="editor">
    <el-alert
      v-if="parsed.warnings.length"
      type="warning"
      show-icon
      :closable="false"
      class="warn-block"
      title="以下字段解析不确定，建议优先校对"
      :description="parsed.warnings.join(' ｜ ')"
    />

    <el-collapse v-model="openSections">
      <!-- 摘要 -->
      <el-collapse-item name="summary">
        <template #title><span class="sec-title">摘要</span></template>
        <div v-if="editing !== 'summary'" class="summary">
          <p><b>标题</b>{{ parsed.title || '—' }}</p>
          <p><b>基调</b>{{ parsed.tone || '—' }}</p>
          <p><b>开场钩子</b>{{ parsed.hook || '—' }}</p>
          <p class="block"><b>背景</b>{{ parsed.background || '—' }}</p>
        </div>
        <div v-else class="summary-edit">
          <el-input v-model="draftSummary.title" size="small" placeholder="标题" />
          <el-input v-model="draftSummary.tone" size="small" placeholder="基调" />
          <el-input v-model="draftSummary.hook" size="small" type="textarea" :rows="2" placeholder="开场钩子" />
          <el-input v-model="draftSummary.background" size="small" type="textarea" :rows="5" placeholder="背景" />
        </div>
        <div class="actions">
          <template v-if="editing !== 'summary'">
            <el-button size="small" @click="startEdit('summary')">编辑</el-button>
          </template>
          <template v-else>
            <el-button size="small" :disabled="saving" @click="editing = null">取消</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="saveSection('summary')">
              保存
            </el-button>
          </template>
        </div>
      </el-collapse-item>

      <!-- 列表区块：列定义驱动，避免六段几乎一样的模板 -->
      <el-collapse-item v-for="section in SECTIONS" :key="section.key" :name="section.key">
        <template #title>
          <span class="sec-title">
            {{ section.title }}
            <span class="count">{{ parsed[section.key].length }}</span>
          </span>
        </template>

        <p v-if="!parsed[section.key].length && editing !== section.key" class="empty">（空）</p>

        <el-table
          v-if="parsed[section.key].length || editing === section.key"
          :data="editing === section.key ? draftRows : rowsOf(section.key)"
          size="small"
          border
        >
          <el-table-column
            v-for="field in section.fields"
            :key="field.key"
            :label="field.label"
            :width="field.width"
            :class-name="field.keeper ? 'keeper-cell' : ''"
          >
            <template #default="{ row }">
              <template v-if="editing === section.key">
                <el-input
                  v-if="field.type === 'text'"
                  size="small"
                  :model-value="String(row[field.key] ?? '')"
                  @update:model-value="(v: string) => (row[field.key] = v)"
                />
                <el-input
                  v-else-if="field.type === 'textarea'"
                  size="small"
                  type="textarea"
                  :rows="2"
                  :model-value="String(row[field.key] ?? '')"
                  @update:model-value="(v: string) => (row[field.key] = v)"
                />
                <el-select
                  v-else-if="field.type === 'select'"
                  size="small"
                  :model-value="String(row[field.key] ?? '')"
                  @update:model-value="(v: string) => (row[field.key] = v)"
                >
                  <el-option
                    v-for="opt in field.options"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>
                <el-input-number
                  v-else
                  size="small"
                  controls-position="right"
                  :min="1"
                  :max="99"
                  :model-value="Number(row[field.key] ?? 0)"
                  @update:model-value="(v: number | undefined) => (row[field.key] = v ?? 0)"
                />
              </template>
              <span v-else class="cell" :class="{ keeper: field.keeper }">
                {{ cellText(row, field) || '—' }}
              </span>
            </template>
          </el-table-column>

          <el-table-column v-if="editing === section.key" label="操作" width="80">
            <template #default="{ $index }">
              <el-button size="small" type="danger" text @click="removeRow($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="actions">
          <template v-if="editing !== section.key">
            <el-button size="small" @click="startEdit(section.key)">编辑</el-button>
          </template>
          <template v-else>
            <el-button size="small" @click="addRow(section)">新增一行</el-button>
            <el-button size="small" :disabled="saving" @click="editing = null">取消</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="saveSection(section.key)">
              保存
            </el-button>
          </template>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.editor {
  padding: 4px 0;
}

.warn-block {
  margin-bottom: 12px;
}

.sec-title {
  font-size: 14px;
  color: #e8eaed;
}

.count {
  margin-left: 6px;
  font-size: 12px;
  color: var(--coc-text-muted);
}

.summary p {
  margin: 0 0 8px;
  font-size: 13px;
  color: #c7ccd4;
  line-height: 1.7;
}

.summary p b {
  display: inline-block;
  min-width: 62px;
  margin-right: 8px;
  color: var(--coc-text-muted);
  font-weight: 500;
}

.summary .block b {
  vertical-align: top;
}

.summary-edit {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 10px;
}

.empty {
  margin: 0;
  font-size: 13px;
  color: var(--coc-text-muted);
}

.cell {
  font-size: 13px;
  color: #c7ccd4;
  white-space: pre-wrap;
  word-break: break-word;
}

.cell.keeper {
  color: #e08b8b;
}

:deep(.keeper-cell) {
  background: rgba(245, 108, 108, 0.06);
}

:deep(.el-collapse-item__header) {
  background: transparent;
  color: #e8eaed;
  border-bottom-color: #2c3e50;
}

:deep(.el-collapse-item__wrap) {
  background: transparent;
  border-bottom-color: #2c3e50;
}

:deep(.el-collapse) {
  border-top-color: #2c3e50;
  border-bottom-color: #2c3e50;
}
</style>
