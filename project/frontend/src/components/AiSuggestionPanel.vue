<script setup lang="ts">
/**
 * AI 主持面板（4.1 协同建议 → 4.2 三档模式）— 决策 D10：LLM 无写权（collab）/工具写权（auto）。
 *
 * 数据流（沿用项目"只上报意图，结果由广播驱动"原则，D5）：
 *   - 模式切换：PUT agent-mode（manual/collab/auto）→ agent_mode_changed 广播回显
 *   - collab 生成触发：POST suggestions/generate（202 即回）→ 结果走 WS suggestions 信封；
 *     玩家剧情行动的自动触发由后端完成，store 在 chat_new 到达时置"生成中"
 *   - auto：剧情推进由后端 AutoKeeper 整轮主持，四段叙事经 chat_new 双通道到达
 *   - 采纳/编辑：直接走 room.sendChat('narrative', text)（现有 chat_send 通道）
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { generateSuggestions, setAgentMode } from '@/api/agent'
import { getRoom } from '@/api/rooms'
import { useRoomStore } from '@/stores/room'
import type { AgentMode, SuggestionItem } from '@/types/ws'

const room = useRoomStore()

const switching = ref(false)
const generating = ref(false)
const focus = ref('')

const MODE_OPTIONS: { value: AgentMode; label: string }[] = [
  { value: 'manual', label: '纯人工' },
  { value: 'collab', label: '协同建议' },
  { value: 'auto', label: '全自动' },
]

// 编辑态：一次只编辑一条；编辑文本独立暂存，取消即丢弃
const editingIdx = ref<number | null>(null)
const editText = ref('')

const DIFF_LABELS: Record<string, string> = {
  standard: '常规',
  hard: '困难',
  extreme: '极难',
}

const suggestions = computed<SuggestionItem[]>(() => room.lastSuggestions?.suggestions ?? [])
const degraded = computed(() => room.lastSuggestions?.status === 'degraded')
const degradedError = computed(() => room.lastSuggestions?.error ?? '未知原因')

// ---------- 思考等待时长（4.4+）：非流式下模型思考/生成期间前端只知"在等"，
// 用实时跳动的已等待秒数给出明确反馈（超时配置 ≥600s 后尤其必要） ----------
const thinkSeconds = ref(0)
let thinkTimer: number | null = null

function startThinkTimer(): void {
  stopThinkTimer()
  thinkSeconds.value = 0
  thinkTimer = window.setInterval(() => {
    thinkSeconds.value++
  }, 1000)
}

function stopThinkTimer(): void {
  if (thinkTimer !== null) {
    clearInterval(thinkTimer)
    thinkTimer = null
  }
}

watch(
  () => [room.suggestionsPending, room.keeperPending] as const,
  ([sug, keeper]) => {
    if (sug || keeper) startThinkTimer()
    else stopThinkTimer()
  },
)

onUnmounted(stopThinkTimer)

/** 面板挂载时拉一次房间详情回显 agent_mode。room.roomId 由 KP 控制台守卫
 * 异步写入（子组件先挂载），照 SkillCheckPanel 的 cardId 先例用 watch 等待 */
watch(
  () => room.roomId,
  async (rid) => {
    if (!rid) return
    try {
      const detail = await getRoom(rid)
      room.agentMode = detail.agent_mode
    } catch {
      // 拦截器已提示；面板仍可用，等 agent_mode_changed 广播回填
    }
  },
  { immediate: true },
)

async function switchMode(mode: AgentMode): Promise<void> {
  if (mode === room.agentMode || switching.value) return
  switching.value = true
  try {
    await setAgentMode(room.roomId, { kp_name: room.playerName, mode })
    // 回显由 agent_mode_changed 广播驱动；未广播前 UI 保持原值
  } catch {
    // 拦截器已提示
  } finally {
    switching.value = false
  }
}

/** 生成 / 重新生成：只触发，结果由 suggestions 信封送达 */
async function regenerate(): Promise<void> {
  if (!room.connected) {
    ElMessage.warning('连接已断开，正在重连…')
    return
  }
  generating.value = true
  room.suggestionsPending = true
  try {
    await generateSuggestions(room.roomId, {
      kp_name: room.playerName,
      focus: focus.value.trim() || undefined,
    })
  } catch {
    room.suggestionsPending = false // 拦截器已提示
  } finally {
    generating.value = false
  }
}

/** 采纳：文本走现有 chat_send 通道广播（服务端权威，D5）；
 * 本地将该条从面板移除——采纳即"用掉"，新批次由下一次生成整体替换 */
function adopt(item: SuggestionItem, idx: number): void {
  if (!room.connected) {
    ElMessage.warning('连接已断开，正在重连…')
    return
  }
  room.sendChat('narrative', item.text)
  room.lastSuggestions?.suggestions.splice(idx, 1)
  ElMessage.success('建议已发送到剧情流，等待新建议…')
}

function startEdit(idx: number): void {
  editingIdx.value = idx
  editText.value = suggestions.value[idx]?.text ?? ''
}

function cancelEdit(): void {
  editingIdx.value = null
  editText.value = ''
}

function sendEdit(): void {
  const text = editText.value.trim()
  if (!text || editingIdx.value === null) return
  if (!room.connected) {
    ElMessage.warning('连接已断开，正在重连…')
    return
  }
  room.sendChat('narrative', text)
  cancelEdit()
  ElMessage.success('编辑后的建议已发送到剧情流')
}
</script>

<template>
  <div class="ai-panel">
    <div class="mode-row">
      <span class="mode-label">主持模式</span>
      <el-radio-group
        :model-value="room.agentMode"
        size="small"
        :disabled="switching"
        @change="switchMode"
      >
        <el-radio-button v-for="opt in MODE_OPTIONS" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- 全自动（4.2）：AI KP 整轮主持，面板只显示状态与说明 -->
    <template v-if="room.agentMode === 'auto'">
      <div v-if="room.keeperPending" class="sug-loading">
        <el-skeleton :rows="2" animated />
        <p class="sug-loading-text">
          AI KP 正在主持本轮剧情（掷骰/状态由工具结算）…<template v-if="thinkSeconds > 2">
            · 已思考 {{ thinkSeconds }}s</template>
        </p>
      </div>
      <p v-else class="ai-empty">
        AI KP 待命：玩家或你在剧情流的每次推进都会触发整轮主持。四段叙事与行动切口
        直接出现在剧情流，你的插话也会被纳入下一轮。
      </p>
      <p class="ai-note">
        暗骰与 keeper 笔记只出现在本屏幕（紫色「仅 KP」行）；随时切回协同/纯人工接管。
      </p>
    </template>

    <template v-else-if="room.agentMode === 'collab'">
      <!-- 降级横幅（验收项：断网 LLM 自动降级并提示） -->
      <el-alert
        v-if="degraded"
        class="degraded-alert"
        type="error"
        :closable="false"
        show-icon
      >
        <template #title>LLM 暂不可用，已回退纯人工主持</template>
        {{ degradedError }}
      </el-alert>

      <!-- 生成中：骨架屏（不阻塞聊天与其他面板），显示已等待秒数 -->
      <div v-if="room.suggestionsPending" class="sug-loading">
        <el-skeleton :rows="2" animated />
        <p class="sug-loading-text">
          AI 正在根据最新剧情生成建议…<template v-if="thinkSeconds > 2">
            · 已思考 {{ thinkSeconds }}s</template>
        </p>
      </div>

      <!-- 候选建议列表 -->
      <template v-else-if="suggestions.length">
        <div
          v-for="(s, i) in suggestions"
          :key="(room.lastSuggestions?.request_id ?? 'batch') + i"
          class="sug-card"
        >
          <template v-if="editingIdx === i">
            <el-input
              v-model="editText"
              type="textarea"
              :rows="4"
              maxlength="500"
              show-word-limit
            />
            <div class="sug-actions">
              <el-button type="primary" size="small" @click="sendEdit">发送</el-button>
              <el-button size="small" @click="cancelEdit">取消</el-button>
            </div>
          </template>
          <template v-else>
            <p class="sug-text">{{ s.text }}</p>
            <p v-if="s.check_hint" class="sug-hint">
              检定：{{ s.check_hint.skill }}（{{ DIFF_LABELS[s.check_hint.difficulty] }}）
              <template v-if="s.check_hint.stake">· 失败则{{ s.check_hint.stake }}</template>
            </p>
            <div class="sug-actions">
              <el-button type="primary" size="small" @click="adopt(s, i)">采纳发送</el-button>
              <el-button size="small" @click="startEdit(i)">编辑</el-button>
            </div>
          </template>
        </div>
        <p class="sug-meta">
          {{ room.lastSuggestions?.trigger === 'auto' ? '随剧情自动刷新' : '手动生成' }}
          <template v-if="room.lastSuggestions?.created_at">
            · {{ room.lastSuggestions.created_at.slice(11, 16) }}
          </template>
          <template v-if="room.lastSuggestions?.model"> · {{ room.lastSuggestions.model }}</template>
        </p>
      </template>

      <p v-else class="ai-empty">
        暂无建议。KP 或玩家在剧情流推进后自动生成，也可点击下方按钮手动生成。
      </p>

      <el-input
        v-model="focus"
        class="focus-input"
        placeholder="附加指令（可选，如：偏悬疑、避免战斗）"
        size="small"
        maxlength="200"
        @keyup.enter="regenerate"
      />
      <el-button
        type="primary"
        class="tb-btn"
        size="small"
        :loading="generating"
        @click="regenerate"
      >
        生成 / 重新生成建议
      </el-button>
      <p class="ai-note">完全手写可用下方剧情输入框；采纳与手写走同一通道，全员可见。</p>
    </template>

    <p v-else class="ai-empty">
      当前为纯人工主持。开启后，玩家的剧情行动会自动生成 2~3 条推进建议（仅你可见），可采纳 / 编辑 / 弃用。
    </p>
  </div>
</template>

<style scoped>
.mode-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.mode-label {
  font-size: 12px;
  color: #8da2c0;
}

.ai-empty {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #7f8fa6;
}

.ai-note {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: #6b7c93;
}

.degraded-alert {
  margin-bottom: 10px;
  --el-alert-font-size: 12px;
}

.sug-loading {
  padding: 8px 0;
}

.sug-loading-text {
  margin: 6px 0 0;
  font-size: 12px;
  color: #7f8fa6;
}

.sug-card {
  padding: 10px;
  margin-bottom: 10px;
  background: rgba(230, 162, 60, 0.06);
  border: 1px solid rgba(230, 162, 60, 0.25);
  border-radius: 8px;
}

.sug-text {
  margin: 0 0 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #d8e0ea;
  white-space: pre-wrap;
  word-break: break-word;
}

.sug-hint {
  margin: 0 0 8px;
  font-size: 11px;
  color: #8da2c0;
}

.sug-actions {
  display: flex;
  gap: 8px;
}

.sug-meta {
  margin: 0 0 10px;
  font-size: 11px;
  color: #6b7c93;
  text-align: right;
}

.focus-input {
  margin-bottom: 10px;
}
</style>
