<script setup lang="ts">
/**
 * LLM 设置对话框（4.4：llm_config 入库后的 KP 设置页）。
 *
 * - 配置写 llm_config 表（DB 权威，全局生效）；.env 仅首次 seed 不再是运行时来源
 * - key 永不回传明文：只显示掩码，留空 = 保持现有 key
 * - 轻任务分级路由（4.4）：light_* 三字段配置建议/摘要等低风险调用的快模型，留空=跟随主模型
 * - 模型选择三重兜底（D11）：GET /llm/models 实时探测 → 静态预设推荐 → 手填
 * - 测试连通 / 探测模型作用于「已保存配置」；表单有改动时先确认保存再执行
 * - Token 消耗全局总账（4.4）展示
 */
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getLlmStatus,
  probeLlmModels,
  saveLlmConfig,
  testLlm,
  type LlmStatus,
  type ProviderPreset,
} from '@/api/agent'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ 'update:visible': [value: boolean] }>()

const form = ref({
  base_url: '', api_key: '', model: '',
  light_base_url: '', light_api_key: '', light_model: '',
  timeout: 600,
  thinking: 'off' as 'on' | 'off', // 混合推理模型（qwen3/DeepSeek 系）思考开关
})
const loaded = ref<LlmStatus | null>(null) // 打开时的已保存配置快照（判断脏）
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const probing = ref(false)
const testResult = ref<{ ok: boolean; text: string } | null>(null)
const probedModels = ref<string[]>([])
const probingOk = ref<boolean | null>(null) // null=未探测

const PRESET_LABELS: Record<string, string> = {
  zhipu: '智谱 GLM',
  deepseek: 'DeepSeek',
  dashscope: '百炼千问',
  openai: 'OpenAI',
}

const providerLabel = computed(() => {
  const p = loaded.value?.provider ?? ''
  return p === 'custom' ? '自定义供应商' : (PRESET_LABELS[p] ?? '未识别')
})

function fmtNum(n: number): string {
  return n >= 10000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

/** 选项 = 探测结果优先，否则按 Base URL 匹配的静态推荐（D11：手填始终可用） */
const modelOptions = computed(() => {
  if (probingOk.value && probedModels.value.length) return probedModels.value
  const preset = (loaded.value?.presets ?? []).find(
    (p: ProviderPreset) => !!p.base_url && form.value.base_url.startsWith(p.base_url),
  )
  return preset?.models ?? (loaded.value?.presets ?? []).flatMap((p: ProviderPreset) => p.models)
})

const dirty = computed(() => {
  if (!loaded.value) return false
  return (
    form.value.base_url !== loaded.value.base_url ||
    form.value.model !== loaded.value.model ||
    form.value.api_key.trim() !== '' ||
    form.value.light_base_url !== (loaded.value.light_base_url || '') ||
    form.value.light_model !== (loaded.value.light_model || '') ||
    form.value.light_api_key.trim() !== '' ||
    form.value.timeout !== loaded.value.timeout ||
    (loaded.value.disable_thinking ? 'off' : 'on') !== form.value.thinking
  )
})

const isMock = computed(() => form.value.model.trim().toLowerCase() === 'mock')

watch(
  () => props.visible,
  async (open) => {
    if (!open) return
    loading.value = true
    testResult.value = null
    probedModels.value = []
    probingOk.value = null
    try {
      const status = await getLlmStatus()
      loaded.value = status
      form.value.base_url = status.base_url
      form.value.model = status.model
      form.value.api_key = ''
      form.value.light_base_url = status.light_base_url || ''
      form.value.light_model = status.light_model || ''
      form.value.light_api_key = ''
      form.value.timeout = status.timeout ?? 600
      form.value.thinking = status.disable_thinking ? 'off' : 'on'
    } catch {
      // 拦截器已提示；对话框仍可填写（保存时后端会校验）
    } finally {
      loading.value = false
    }
  },
)

function close(): void {
  emit('update:visible', false)
}

function pickPreset(preset: ProviderPreset, light = false): void {
  if (light) {
    form.value.light_base_url = preset.base_url
    if (!probingOk.value) form.value.light_model = preset.models[0] ?? form.value.light_model
    return
  }
  form.value.base_url = preset.base_url
  if (!probingOk.value) form.value.model = preset.models[0] ?? form.value.model
}

async function persist(): Promise<boolean> {
  const base_url = form.value.base_url.trim()
  if (base_url && !/^https?:\/\//.test(base_url)) {
    ElMessage.warning('Base URL 必须以 http:// 或 https:// 开头')
    return false
  }
  const light_base_url = form.value.light_base_url.trim()
  if (light_base_url && !/^https?:\/\//.test(light_base_url)) {
    ElMessage.warning('轻任务 Base URL 必须以 http:// 或 https:// 开头')
    return false
  }
  if (!form.value.model.trim()) {
    ElMessage.warning('请填写模型名（不知道就点「探测模型」或选一个推荐）')
    return false
  }
  saving.value = true
  try {
    const body: Record<string, unknown> = {
      base_url,
      model: form.value.model.trim(),
      // light_* 始终显式提交（含空串=清除，跟随主模型）
      light_base_url,
      light_model: form.value.light_model.trim(),
      // 运行时参数（4.4+）：超时秒数 + 混合推理模型思考开关
      timeout: form.value.timeout,
      disable_thinking: form.value.thinking === 'off',
    }
    if (form.value.api_key.trim()) body.api_key = form.value.api_key.trim()
    if (form.value.light_api_key.trim()) body.light_api_key = form.value.light_api_key.trim()
    const status = await saveLlmConfig(body)
    loaded.value = status
    form.value.base_url = status.base_url
    form.value.model = status.model
    form.value.api_key = ''
    form.value.light_base_url = status.light_base_url || ''
    form.value.light_model = status.light_model || ''
    form.value.light_api_key = ''
    form.value.timeout = status.timeout
    form.value.thinking = status.disable_thinking ? 'off' : 'on'
    testResult.value = null
    ElMessage.success('已保存（写入 llm_config 数据库，全局生效）')
    return true
  } catch {
    return false // 拦截器已提示
  } finally {
    saving.value = false
  }
}

/** 测试 / 探测作用于已保存配置：有未保存修改时先确认保存 */
async function ensureSaved(): Promise<boolean> {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('有未保存的修改，先保存再执行？', '提示', {
      confirmButtonText: '保存并执行',
      cancelButtonText: '取消',
      type: 'info',
    })
  } catch {
    return false
  }
  return persist()
}

async function runTest(): Promise<void> {
  if (!(await ensureSaved())) return
  testing.value = true
  testResult.value = null
  try {
    const res = await testLlm()
    let text = `连通正常 · 延迟 ${res.latency_ms}ms · ${res.model}`
    if (res.light_model) {
      // 轻任务模型一并测试（消盲区）：不通时明确提示建议链路仍会失败
      text += res.light_ok !== false
        ? ` · 轻模型 ${res.light_model} ${res.light_latency_ms}ms`
        : ` · ⚠ 轻模型 ${res.light_model} 不通：${res.light_error ?? '未知原因'}`
    }
    testResult.value = res.ok
      ? { ok: res.light_ok !== false, text }
      : { ok: false, text: res.error ?? '测试失败' }
  } catch {
    testResult.value = { ok: false, text: '请求失败' } // 拦截器已提示
  } finally {
    testing.value = false
  }
}

async function runProbe(): Promise<void> {
  if (!(await ensureSaved())) return
  probing.value = true
  try {
    const res = await probeLlmModels()
    if (res.ok && res.models.length) {
      probedModels.value = res.models
      probingOk.value = true
      ElMessage.success(`探测到 ${res.models.length} 个模型，已在下拉框列出`)
    } else {
      probingOk.value = false
      ElMessage.warning(`探测失败（${res.error ?? '未知原因'}），可直接手填模型名`)
    }
  } catch {
    probingOk.value = false // 拦截器已提示
  } finally {
    probing.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="LLM 设置（全局）"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
  >
    <div v-loading="loading" class="llm-form">
      <p class="llm-tip">
        当前供应商：<b>{{ providerLabel }}</b>
        <el-tag v-if="loaded?.mock_mode" size="small" type="warning" class="mock-tag">演示模式（Mock）</el-tag>
        <el-tag v-else-if="loaded?.enabled" size="small" type="success" class="mock-tag">已启用</el-tag>
        <el-tag v-else size="small" type="info" class="mock-tag">未配置</el-tag>
      </p>

      <el-form label-width="88px" label-position="left" size="small">
        <el-form-item label="供应商预设">
          <div class="preset-row">
            <el-tag
              v-for="p in loaded?.presets ?? []"
              :key="p.key"
              class="preset-tag"
              :type="form.base_url === p.base_url ? 'primary' : 'info'"
              effect="plain"
              @click="pickPreset(p)"
            >
              {{ p.label }}
            </el-tag>
          </div>
        </el-form-item>

        <el-form-item label="Base URL">
          <el-input
            v-model="form.base_url"
            placeholder="https://…（OpenAI 兼容地址）"
            clearable
          />
        </el-form-item>

        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="
              loaded?.api_key_masked
                ? `已配置（${loaded.api_key_masked}），留空保持不变`
                : '粘贴供应商 API Key'
            "
            autocomplete="new-password"
          />
        </el-form-item>

        <el-form-item label="主模型">
          <el-select
            v-model="form.model"
            filterable
            allow-create
            default-first-option
            placeholder="点下方「探测模型」拉取，或直接手填"
            style="width: 100%"
          >
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>

        <!-- 运行时参数（4.4+）：超时与思考开关，此前 DB 权威后改不了导致 30s 超时无法自救 -->
        <el-form-item label="请求超时">
          <div class="timeout-row">
            <el-input-number
              v-model="form.timeout"
              :min="30"
              :max="3600"
              :step="30"
              controls-position="right"
              size="small"
            />
            <span class="timeout-unit">秒（推理模型/长上下文建议 ≥300）</span>
          </div>
        </el-form-item>
        <el-form-item label="思考模式">
          <el-select v-model="form.thinking" size="small" style="width: 100%">
            <el-option label="关闭思考（qwen3 / DeepSeek 混合推理建议关闭，非流式更快）" value="off" />
            <el-option label="开启思考（模型深度推理，耗时明显变长）" value="on" />
          </el-select>
        </el-form-item>
      </el-form>

      <!-- 轻任务分级路由（4.4）：建议生成 / 场景摘要等低风险调用走快模型 -->
      <el-divider content-position="left" class="light-divider">
        轻任务模型（可选，留空 = 跟随主模型）
      </el-divider>
      <el-form label-width="88px" label-position="left" size="small">
        <el-form-item label="供应商预设">
          <div class="preset-row">
            <el-tag
              v-for="p in loaded?.presets ?? []"
              :key="p.key"
              class="preset-tag"
              :type="form.light_base_url === p.base_url ? 'primary' : 'info'"
              effect="plain"
              @click="pickPreset(p, true)"
            >
              {{ p.label }}
            </el-tag>
          </div>
        </el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.light_base_url" placeholder="留空 = 用主模型的地址" clearable />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.light_api_key"
            type="password"
            show-password
            :placeholder="
              loaded?.light_api_key_masked
                ? `已配置（${loaded.light_api_key_masked}），留空保持不变`
                : '留空 = 用主模型的 Key'
            "
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="轻模型">
          <el-select
            v-model="form.light_model"
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="如 qwen-flash / deepseek-v4-flash（建议与摘要等轻任务用）"
            style="width: 100%"
          >
            <el-option v-for="m in modelOptions" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="isMock"
        class="mock-alert"
        type="warning"
        :closable="false"
        show-icon
        title="演示模式：不发真实网络请求，AI 会返回固定的演示建议（无 API Key 也能跑通全流程）"
      />

      <div v-if="testResult" class="test-result" :class="testResult.ok ? 'is-ok' : 'is-bad'">
        {{ testResult.ok ? '✓ ' : '✗ ' }}{{ testResult.text }}
      </div>

      <!-- Token 消耗全局总账（4.4） -->
      <div v-if="loaded?.usage" class="usage-row">
        <span class="usage-label">Token 总账</span>
        <span>{{ loaded.usage.calls }}</span> 次调用 ·
        输入 <span>{{ fmtNum(loaded.usage.prompt_tokens) }}</span> ·
        输出 <span>{{ fmtNum(loaded.usage.completion_tokens) }}</span> tokens
      </div>

      <p class="llm-note">
        配置写入 llm_config 数据库并立即生效，对所有房间通用；
        key 只保存在本机，页面永远只显示掩码。
      </p>
    </div>

    <template #footer>
      <div class="footer-btns">
        <el-button size="small" :loading="probing" @click="runProbe">探测模型</el-button>
        <el-button size="small" :loading="testing" @click="runTest">测试连通</el-button>
        <el-button size="small" type="primary" :loading="saving" @click="persist">保存</el-button>
        <el-button size="small" @click="close">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.llm-tip {
  margin: 0 0 12px;
  font-size: 12px;
  color: #8da2c0;
}

.mock-tag {
  margin-left: 8px;
}

.preset-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.timeout-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.timeout-unit {
  font-size: 11px;
  color: #909399;
}

.preset-tag {
  cursor: pointer;
}

.light-divider {
  margin: 18px 0 12px;

  :deep(.el-divider__text) {
    font-size: 12px;
    color: #8da2c0;
  }
}

.usage-row {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(64, 158, 255, 0.08);
  border: 1px solid rgba(64, 158, 255, 0.2);
  font-size: 12px;
  color: #8da2c0;

  span {
    font-weight: 600;
    color: #409eff;
  }
}

.usage-label {
  margin-right: 8px;
  color: #6b7c93;
  font-weight: 400 !important;
}

.mock-alert {
  margin-top: 10px;
  --el-alert-font-size: 12px;
}

.test-result {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-all;
}

.test-result.is-ok {
  background: rgba(103, 194, 58, 0.1);
  color: #95d475;
}

.test-result.is-bad {
  background: rgba(245, 108, 108, 0.1);
  color: #f89898;
}

.llm-note {
  margin: 10px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: #6b7c93;
}

.footer-btns {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
