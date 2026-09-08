<script setup lang="ts">
/**
 * KP 风格面板（4.4，goal §6.2）——风格只影响表达，不影响公平。
 *
 * 数据流（D5：只上报意图，回显由广播驱动）：
 *   - 切换：PUT /rooms/{id}/kp-style → kp_style_changed 全员广播回显 + 系统行
 *   - 当前风格回显：房间详情（KPConsoleView onMounted）/ state 快照 / 切换广播 三路驱动
 *   - 自定义：POST /kp-styles（新建 = 导入 JSON 同一入口）、DELETE /kp-styles/{id}
 *   - 导出：把内置或自定义风格序列化成 JSON 文本（复制到剪贴板）
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createKpStyle,
  deleteKpStyle,
  listKpStyles,
  setRoomStyle,
  type KpStyleItem,
  type KpStyleList,
} from '@/api/agent'
import { getRoom } from '@/api/rooms'
import { useRoomStore } from '@/stores/room'
import type { KpStyleParams } from '@/types/ws'

const room = useRoomStore()

const styles = ref<KpStyleList>({ builtins: [], customs: [] })
const loading = ref(false)
const switching = ref(false)

const isKp = computed(() => room.myRole === 'kp')
const currentId = computed(() => room.kpStyle?.style_id ?? 'balanced')

/** 下拉选项：内置 + 自定义（value=id，切风格与回显共用） */
const allOptions = computed<{ id: string; name: string; builtin: boolean }[]>(() => [
  ...styles.value.builtins.map((s: KpStyleItem) => ({ id: s.id, name: s.name, builtin: true })),
  ...styles.value.customs.map((s: KpStyleItem) => ({ id: s.id, name: s.name, builtin: false })),
])

const currentDesc = computed(() => {
  const hit = [...styles.value.builtins, ...styles.value.customs]
    .find((s: KpStyleItem) => s.id === currentId.value)
  return hit?.description ?? ''
})

watch(
  () => room.roomId,
  async (rid) => {
    if (!rid) return
    loading.value = true
    try {
      styles.value = await listKpStyles()
    } catch {
      // 拦截器已提示；切换仍可用内置 id
    } finally {
      loading.value = false
    }
    // 面板先于详情到达时兜底拉一次房间回显（正常由 KPConsoleView 的 detail 驱动）
    if (!room.kpStyle) {
      try {
        const detail = await getRoom(rid)
        room.kpStyle = { style_id: detail.style.style_id, style_name: detail.style.style_name }
      } catch {
        // 拦截器已提示；等 kp_style_changed 广播回填
      }
    }
  },
  { immediate: true },
)

async function switchStyle(styleId: string): Promise<void> {
  if (styleId === currentId.value || switching.value) return
  switching.value = true
  try {
    await setRoomStyle(room.roomId, { kp_name: room.playerName, style_id: styleId })
    // 回显由 kp_style_changed 广播驱动（全员可见提示），不在本地先改
  } catch {
    // 拦截器已提示
  } finally {
    switching.value = false
  }
}

// ---------- 自定义风格管理 ----------
const dialogVisible = ref(false)
const form = ref<KpStyleParams & { name: string }>({
  name: '',
  narrative_density: 'medium',
  rule_explanation: 'medium',
  hidden_roll_transparency: 'medium',
  option_granularity: 'medium',
  note: '',
})

const KNOB_META = [
  { key: 'narrative_density', label: '叙事密度', options: ['high', 'medium', 'low'], hints: ['高·多感官描写', '中', '低·精炼直给'] },
  { key: 'rule_explanation', label: '规则解释', options: ['high', 'medium', 'low'], hints: ['高·每次检定附讲解', '中', '低·只报结果'] },
  { key: 'hidden_roll_transparency', label: '暗骰透明度', options: ['high', 'medium', 'low'], hints: ['高·坦承有隐藏判定', '中', '低·完全保密'] },
  { key: 'option_granularity', label: '选项颗粒度', options: ['fine', 'medium', 'coarse'], hints: ['细·手把手', '中', '粗·开放式'] },
] as const

function openManage(): void {
  // 以当前风格为底稿（四旋钮从列表里找当前风格参数；找不到用中档）
  const hit = [...styles.value.builtins, ...styles.value.customs]
    .find((s: KpStyleItem) => s.id === currentId.value)
  const p = hit?.params
  form.value = {
    name: hit && !hit.description ? `${hit.name}·改` : '我的风格',
    narrative_density: p?.narrative_density ?? 'medium',
    rule_explanation: p?.rule_explanation ?? 'medium',
    hidden_roll_transparency: p?.hidden_roll_transparency ?? 'medium',
    option_granularity: p?.option_granularity ?? 'medium',
    note: p?.note ?? '',
  }
  dialogVisible.value = true
}

async function saveCustom(): Promise<void> {
  const name = form.value.name.trim()
  if (!name) {
    ElMessage.warning('给风格起个名字')
    return
  }
  try {
    const res = await createKpStyle(name, {
      narrative_density: form.value.narrative_density,
      rule_explanation: form.value.rule_explanation,
      hidden_roll_transparency: form.value.hidden_roll_transparency,
      option_granularity: form.value.option_granularity,
      note: form.value.note?.trim() || undefined,
    } as KpStyleParams)
    if (res.created) {
      styles.value = { builtins: res.builtins, customs: res.customs }
      ElMessage.success(`已保存自定义风格「${res.created.name}」，可在下拉框选用`)
    }
    dialogVisible.value = false
  } catch {
    // 拦截器已提示
  }
}

/** 导入：粘贴导出的 JSON（{name, params}）→ 存为新的自定义风格 */
const importText = ref('')
async function doImport(): Promise<void> {
  try {
    const data = JSON.parse(importText.value) as { name?: string; params?: KpStyleParams }
    if (!data.name || !data.params) throw new Error('缺少 name 或 params 字段')
    const res = await createKpStyle(data.name, data.params)
    styles.value = { builtins: res.builtins, customs: res.customs }
    ElMessage.success(`已导入风格「${data.name}」`)
    importText.value = ''
  } catch (e) {
    ElMessage.error(`导入失败：${e instanceof Error ? e.message : 'JSON 格式不对'}`)
  }
}

/** 导出：当前选中的风格序列化为 JSON（复制到剪贴板，可直接分享/存档） */
async function exportCurrent(): Promise<void> {
  const hit = [...styles.value.builtins, ...styles.value.customs]
    .find((s: KpStyleItem) => s.id === currentId.value)
  if (!hit) {
    ElMessage.warning('当前风格不在列表中，切换后再导出')
    return
  }
  const text = JSON.stringify(
    { name: hit.name, params: hit.params },
    null, 2,
  )
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`已复制「${hit.name}」的导出 JSON 到剪贴板`)
  } catch {
    ElMessage.info('剪贴板不可用，请手动复制：' + text)
  }
}

async function removeCustom(item: KpStyleItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除自定义风格「${item.name}」？引用它的房间会回退到平衡 Keeper。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteKpStyle(item.id)
    styles.value = await listKpStyles()
    ElMessage.success('已删除')
  } catch {
    // 拦截器已提示
  }
}
</script>

<template>
  <div class="style-panel">
    <el-select
      :model-value="currentId"
      size="small"
      class="style-select"
      :loading="loading"
      :disabled="switching || !isKp"
      @change="switchStyle"
    >
      <el-option-group label="内置风格">
        <el-option v-for="s in styles.builtins" :key="s.id" :label="s.name" :value="s.id" />
      </el-option-group>
      <el-option-group v-if="styles.customs.length" label="自定义">
        <el-option v-for="s in styles.customs" :key="s.id" :label="s.name" :value="s.id" />
      </el-option-group>
    </el-select>

    <p v-if="currentDesc" class="style-desc">{{ currentDesc }}</p>
    <p class="style-note">
      风格只影响 AI 的表达方式（叙事密度/规则讲解/暗骰保密/选项粗细），骰子与数值仍由系统产生。
      切换全员可见。
    </p>

    <div v-if="isKp" class="style-btns">
      <el-button size="small" class="grow" @click="openManage">自定义风格</el-button>
      <el-button size="small" class="grow" @click="exportCurrent">导出 JSON</el-button>
    </div>

    <!-- 自定义风格管理：以当前风格为底稿调四旋钮 / 粘贴 JSON 导入 / 删除自定义 -->
    <el-dialog v-model="dialogVisible" title="自定义 KP 风格" width="440px">
      <el-form label-width="86px" label-position="left" size="small">
        <el-form-item label="风格名称">
          <el-input v-model="form.name" maxlength="30" placeholder="如：悬疑沉浸" />
        </el-form-item>
        <el-form-item v-for="k in KNOB_META" :key="k.key" :label="k.label">
          <el-radio-group v-model="form[k.key]">
            <el-radio-button v-for="(opt, i) in k.options" :key="opt" :value="opt">
              {{ k.hints[i] }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="补充要求">
          <el-input
            v-model="form.note"
            type="textarea"
            :rows="2"
            maxlength="200"
            show-word-limit
            placeholder="可选，一句话自由补充（如：偏克苏鲁式slow burn）"
          />
        </el-form-item>
      </el-form>

      <el-divider content-position="left">导入</el-divider>
      <el-input
        v-model="importText"
        type="textarea"
        :rows="3"
        placeholder='粘贴导出的 JSON：{"name": "...", "params": {...}}'
      />
      <el-button size="small" class="import-btn" :disabled="!importText.trim()" @click="doImport">
        导入为新风格
      </el-button>

      <template v-if="styles.customs.length">
        <el-divider content-position="left">已保存的自定义</el-divider>
        <div v-for="c in styles.customs" :key="c.id" class="custom-row">
          <span class="custom-name">{{ c.name }}</span>
          <el-button size="small" text type="danger" @click="removeCustom(c)">删除</el-button>
        </div>
      </template>

      <template #footer>
        <el-button size="small" @click="dialogVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="saveCustom">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.style-select {
  width: 100%;
}

.style-desc {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #8da2c0;
}

.style-note {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: #6b7c93;
}

.style-btns {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.grow {
  flex: 1;
}

.import-btn {
  margin-top: 8px;
}

.custom-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
}

.custom-name {
  font-size: 12px;
  color: #d8e0ea;
}
</style>
