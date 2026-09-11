<script setup lang="ts">
/**
 * 解析面板 — 阶段 5。
 *
 * 职责：手动触发结构化解析（可选模型）+ 解析进度轮询 + 失败原因展示。
 * - 模型下拉来自供应商实时探测（GET /llm/models），探测失败则手填兜底；
 *   留空 = 后端默认走轻任务模型（未配则主模型）。
 * - 解析是后台任务（202 立即返回），这里每 2s 轮询一次详情，离开 parsing 即停。
 * - 组件卸载必须清理定时器，否则切页后仍在打接口。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getLlmStatus, probeLlmModels, testLlm } from '@/api/agent'
import { getModule, parseModule } from '@/api/modules'
import type { ModuleDetail } from '@/types/module'

const props = defineProps<{ module: ModuleDetail }>()
const emit = defineEmits<{ refresh: [ModuleDetail] }>()

const POLL_MS = 2000

const models = ref<string[]>([])
const model = ref('')
const submitting = ref(false)
const elapsed = ref(0)
let pollTimer: number | undefined
let tickTimer: number | undefined
let pollFailures = 0

// 连通性检测门禁（2026-09-10 用户反馈 #1）：解析会真花钱，先确认模型可用再允许点解析
const testing = ref(false)
const tested = ref(false)
const testText = ref('')
/** 当前全局配置摘要（只读）：改配置去大厅「API / 模型配置」或 KP 台设置 */
const configSummary = ref('')

const parsing = computed(() => props.module.parse_status === 'parsing')
const defaultModelHint = ref('轻任务模型')

/** 解析按钮门禁：必须检测通过，且当前没有任务在跑 */
const canParse = computed(() => tested.value && !parsing.value && !submitting.value)

async function checkModel(): Promise<void> {
  testing.value = true
  testText.value = ''
  try {
    const res = await testLlm()
    tested.value = res.ok
    if (res.ok) {
      const light = res.light_model
        ? `｜轻任务模型 ${res.light_model} ${res.light_ok === false ? '不通（' + (res.light_error ?? '') + '）' : '通'}`
        : ''
      testText.value = `可用：${res.model ?? ''} ${res.latency_ms ?? '-'}ms${light}`
      ElMessage.success('模型可用，可以开始解析')
    } else {
      testText.value = `不可用：${res.error ?? '未知原因'}`
      ElMessage.error(testText.value)
    }
  } catch {
    // 拦截器已提示（网络层失败）
    tested.value = false
    testText.value = '检测请求失败'
  } finally {
    testing.value = false
  }
}

function stopTimers(): void {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
  if (tickTimer !== undefined) window.clearInterval(tickTimer)
  pollTimer = undefined
  tickTimer = undefined
}

function startPolling(): void {
  stopTimers()
  const startedAt = Date.now()
  elapsed.value = 0
  pollFailures = 0
  tickTimer = window.setInterval(() => {
    elapsed.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)
  pollTimer = window.setInterval(async () => {
    try {
      const detail = await getModule(props.module.id)
      pollFailures = 0
      emit('refresh', detail)
      if (detail.parse_status === 'ready') {
        stopTimers()
        ElMessage.success('解析完成，可在「结构化结果」页签校对')
      } else if (detail.parse_status === 'failed') {
        stopTimers()
        ElMessage.error('解析失败，详情见下方原因')
      }
    } catch {
      pollFailures += 1
      if (pollFailures >= 3) stopTimers()
    }
  }, POLL_MS)
}

onMounted(async () => {
  try {
    const status = await getLlmStatus()
    defaultModelHint.value = status.light_model || status.model || '未配置模型'
    configSummary.value = [status.provider, status.model, status.base_url]
      .filter(Boolean)
      .join(' · ')
  } catch {
    // 状态拿不到不影响解析能力，仅提示文案退化
  }
  try {
    const probed = await probeLlmModels()
    if (probed.ok) models.value = probed.models
  } catch {
    // 探测失败（供应商不支持 /models）：退化为手填，不打扰用户
  }
  if (parsing.value) startPolling()
})

watch(parsing, (value: boolean) => {
  if (value) startPolling()
  else stopTimers()
})

onUnmounted(stopTimers)

async function trigger(): Promise<void> {
  submitting.value = true
  try {
    const res = await parseModule(props.module.id, model.value.trim())
    emit('refresh', {
      ...props.module,
      parse_status: 'parsing',
      parse_model: res.parse_model,
      parse_error: '',
    })
    startPolling()
  } catch {
    // 409/400 等由拦截器提示
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="parse-panel">
    <div class="row">
      <span class="label">解析模型</span>
      <el-select
        v-model="model"
        class="model-select"
        size="small"
        filterable
        allow-create
        default-first-option
        clearable
        :placeholder="`留空 = ${defaultModelHint}`"
      >
        <el-option v-for="m in models" :key="m" :label="m" :value="m" />
      </el-select>
      <el-button size="small" :loading="testing" @click="checkModel">检测模型</el-button>
      <el-button
        type="primary"
        size="small"
        :loading="submitting || parsing"
        :disabled="!canParse"
        @click="trigger"
      >
        {{ module.parse_status === 'ready' ? '重新解析' : '开始解析' }}
      </el-button>
      <span v-if="parsing" class="elapsed">解析中… 已耗时 {{ elapsed }}s</span>
      <el-tag v-else-if="tested" type="success" size="small">已检测可用</el-tag>
      <span v-else-if="module.parsed_at" class="elapsed">
        上次解析：{{ module.parse_model || '默认模型' }}
      </span>
    </div>

    <p v-if="testText" class="test-result" :class="tested ? 'is-ok' : 'is-bad'">
      {{ testText }}
    </p>

    <p class="hint">
      解析会真实调用 LLM 并消耗 token，因此上传后不会自动触发；长模组会分块解析，耗时可能数分钟。
      <br />
      当前全局配置：{{ configSummary || '未配置' }}（改配置去大厅「API / 模型配置」或 KP 台设置）。
      <strong>先点「检测模型」确认可用，才能开始解析。</strong>
    </p>

    <el-alert
      v-if="module.parse_status === 'failed'"
      type="error"
      show-icon
      :closable="false"
      class="err"
      title="解析失败"
      :description="module.parse_error || '未返回失败原因'"
    />
  </section>
</template>

<style scoped>
.parse-panel {
  padding: 12px 16px;
  border: 1px solid #2c3e50;
  border-radius: 8px;
  background: #222d3d;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.label {
  font-size: 13px;
  color: var(--coc-text-muted);
}

.model-select {
  width: 240px;
}

.elapsed {
  font-size: 12px;
  color: #e6a23c;
}

.hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--coc-text-muted);
  line-height: 1.6;
}

.test-result {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
}

.test-result.is-ok {
  color: #67c23a;
}

.test-result.is-bad {
  color: #f56c6c;
}

.err {
  margin-top: 10px;
}
</style>
