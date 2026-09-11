<script setup lang="ts">
/**
 * 首次配置引导条 — 阶段 6.1（goal §7 6.1「.env.example + 首次配置向导」）。
 *
 * 目标（用户决策 2026-09-11，方案 A）：**没配 key 也要能直接进演示**。
 * 逻辑很薄：进大厅查一次 GET /llm/status，未配置且非 mock 时亮出引导条，
 * 两个出口——
 *   「启用演示模式」→ PUT /llm/config { model: 'mock' }（4.1+ 的 MockLLMClient，
 *     不发真实网络请求，AI 返回固定演示内容，断网/无 key 都能演）
 *   「去配置」→ 打开大厅的 API / 模型配置弹窗（复用 LlmSettingsDialog）
 *
 * 只做观感与入口，不碰任何业务逻辑：配置权威仍是 llm_config 表（4.4）。
 * 演示模式只是把 model 临时写成 mock，随时可在设置里改回真实模型。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getLlmStatus, saveLlmConfig } from '@/api/agent'

const emit = defineEmits<{ configure: [] }>()

const visible = ref(false)
const loading = ref(false)
const enabling = ref(false)

/** 拉一次状态决定显不显示；失败静默（后端没起来时不该在大厅刷错误弹窗） */
async function refresh(): Promise<void> {
  loading.value = true
  try {
    const status = await getLlmStatus()
    visible.value = !status.enabled && !status.mock_mode
  } catch {
    visible.value = false
  } finally {
    loading.value = false
  }
}

/** 一键启用演示模式：写 llm_config（model=mock），成功后收起引导条 */
async function enableMock(): Promise<void> {
  enabling.value = true
  try {
    await saveLlmConfig({ model: 'mock' })
    visible.value = false
    ElMessage.success('已启用演示模式：AI 用本地固定内容主持，不发真实请求')
  } catch {
    // 错误提示已由 axios 拦截器统一弹出
  } finally {
    enabling.value = false
  }
}

onMounted(refresh)

// 供父组件在「设置弹窗关闭后」重新检测配置状态
defineExpose({ refresh })
</script>

<template>
  <div v-if="visible" class="guide">
    <div class="guide-text">
      <strong>还没有配置大模型 API Key</strong>
      <span>
        不影响开团：可以先启用<em>演示模式</em>跑通全流程，或现在填一个真实 Key。
      </span>
    </div>
    <div class="guide-actions">
      <el-button size="small" type="primary" :loading="enabling" @click="enableMock">
        启用演示模式
      </el-button>
      <el-button size="small" plain @click="emit('configure')">去配置</el-button>
    </div>
  </div>
</template>

<style scoped>
.guide {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 640px;
  margin: 0 auto 24px;
  padding: 12px 16px;
  text-align: left;
  background: rgba(230, 162, 60, 0.1);
  border: 1px solid rgba(230, 162, 60, 0.45);
  border-left: 3px solid #e6a23c;
  border-radius: 8px;
}

.guide-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  line-height: 1.6;
}

.guide-text strong {
  color: #e6a23c;
  font-size: 14px;
}

.guide-text span {
  color: #c0c4cc;
}

.guide-text em {
  color: #e6a23c;
  font-style: normal;
}

.guide-actions {
  display: flex;
  flex-shrink: 0;
  gap: 8px;
}
</style>
