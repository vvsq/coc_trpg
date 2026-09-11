<script setup lang="ts">
/**
 * 主持模式开关（顶栏常驻）— 阶段 6.2②。
 *
 * 从 AiSuggestionPanel 上提到顶栏（样例图里每个界面都能切模式），因此**回显职责也搬过来**：
 * 房间详情接口给初值，之后一律由 `agent_mode_changed` 广播驱动（沿用 D5「不自改本地状态」）。
 *
 * 权限：只有 KP 可点；玩家看到只读 chip（模式仍对全员可见，与后端广播语义一致）。
 */
import { computed, ref, watch } from 'vue'
import { setAgentMode } from '@/api/agent'
import { getRoom } from '@/api/rooms'
import { useRoomStore } from '@/stores/room'
import CocIcon from '@/components/common/CocIcon.vue'
import type { IconName } from '@/components/common/cocIcons'
import { AGENT_MODE_LABELS, type AgentMode } from '@/types/ws'

const room = useRoomStore()
const switching = ref(false)

const MODE_OPTIONS: { value: AgentMode; icon: IconName }[] = [
  { value: 'manual', icon: 'users' },
  { value: 'collab', icon: 'sparkles' },
  { value: 'auto', icon: 'skull' },
]

const inRoom = computed(() => !!room.roomId)
const isKp = computed(() => room.myRole === 'kp')
const currentLabel = computed(() => AGENT_MODE_LABELS[room.agentMode])

// 子组件先于视图守卫挂载，roomId 由守卫异步写入——必须 watch 而非 onMounted
watch(
  () => room.roomId,
  async (rid) => {
    if (!rid) return
    try {
      const detail = await getRoom(rid)
      room.agentMode = detail.agent_mode
    } catch {
      // 拦截器已提示；等 agent_mode_changed 广播回填
    }
  },
  { immediate: true },
)

async function pick(mode: AgentMode): Promise<void> {
  if (!isKp.value || switching.value || mode === room.agentMode) return
  switching.value = true
  try {
    await setAgentMode(room.roomId, { kp_name: room.playerName, mode })
    // 回显由广播驱动，未广播前 UI 保持原值
  } catch {
    // 拦截器已提示
  } finally {
    switching.value = false
  }
}
</script>

<template>
  <div
    v-if="inRoom && isKp"
    class="mode-switch"
    :class="{ 'is-busy': switching }"
    role="group"
    aria-label="主持模式"
  >
    <button
      v-for="opt in MODE_OPTIONS"
      :key="opt.value"
      type="button"
      class="seg"
      :class="{ 'seg--active': room.agentMode === opt.value }"
      :title="AGENT_MODE_LABELS[opt.value]"
      :disabled="switching"
      @click="pick(opt.value)"
    >
      <CocIcon :name="opt.icon" :size="14" />
      <span>{{ AGENT_MODE_LABELS[opt.value] }}</span>
    </button>
  </div>

  <span v-else-if="inRoom" class="mode-readonly coc-chip coc-chip--accent" :title="'当前主持模式（由 KP 控制）'">
    <CocIcon name="sparkles" :size="13" />
    {{ currentLabel }}
  </span>
</template>

<style scoped>
.mode-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-full);
  background: rgba(11, 18, 32, 0.55);
}

.seg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border: none;
  border-radius: var(--coc-radius-full);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  line-height: 1;
  cursor: pointer;
  transition: background var(--coc-dur-fast) var(--coc-ease), color var(--coc-dur-fast) var(--coc-ease),
    box-shadow var(--coc-dur-fast) var(--coc-ease);
}

.seg:hover:not(:disabled) {
  color: var(--coc-text);
}

.seg--active {
  background: linear-gradient(180deg, rgba(34, 211, 238, 0.22), rgba(14, 165, 233, 0.16));
  color: var(--coc-accent);
  box-shadow: inset 0 0 0 1px var(--coc-border-glow), var(--coc-glow);
}

.seg:disabled {
  cursor: default;
  opacity: 0.75;
}

.mode-readonly {
  gap: 6px;
}

/* 阶段 6.2⑩：手机端顶栏空间有限，模式开关收成 icon-only（title 提供文字说明） */
@media (max-width: 768px) {
  .seg {
    padding: 6px 10px;
  }

  .seg span {
    display: none;
  }
}
</style>
