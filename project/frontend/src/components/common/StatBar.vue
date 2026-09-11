<script setup lang="ts">
/**
 * 状态条（HP / MP / SAN）— 阶段 6.2⑦（房间页与 KP 台共用，对齐样例的细条样式）。
 *
 * 替代原先的 `el-progress`：EP 进度条在暗色下要么过亮、要么需要逐处 :deep 覆写，
 * 而且无法表达「≤30% 预警」这类游戏语义。这里用纯 CSS 轨道 + 填充，
 * 配色走令牌，预警阈值与 KP 面板的红条口径一致（goal §7 3.3：≤30% 红色预警）。
 *
 * 纯展示组件：数值由调用方决定（服务端广播快照优先，见 stores/room.ts 的 cardStates）。
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: number
    max: number
    /** 语义配色：HP 红 / MP 青 / SAN 紫 / 其他中性 */
    tone?: 'hp' | 'mp' | 'san' | 'luk' | 'other'
    /** ≤30% 高亮为危险色（KP 面板与玩家侧栏共用同一阈值） */
    alertBelow?: number
    compact?: boolean
  }>(),
  { tone: 'other', alertBelow: 0.3, compact: false },
)

const ratio = computed(() => {
  if (props.max <= 0) return 0
  return Math.min(1, Math.max(0, props.value / props.max))
})

const percent = computed(() => Math.round(ratio.value * 100))
const alert = computed(() => ratio.value <= props.alertBelow)
</script>

<template>
  <div class="stat" :class="[`stat--${tone}`, compact && 'stat--compact', alert && 'stat--alert']">
    <span class="stat-label">{{ label }}</span>
    <span class="stat-track">
      <span class="stat-fill" :style="{ width: `${percent}%` }" />
    </span>
    <span class="stat-num">{{ value }}<span class="stat-max">/{{ max }}</span></span>
  </div>
</template>

<style scoped>
.stat {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  --stat-color: var(--coc-text-muted);
}

.stat--hp {
  --stat-color: var(--coc-danger);
}

.stat--mp {
  --stat-color: var(--coc-primary);
}

.stat--san {
  --stat-color: var(--coc-keeper);
}

.stat--luk {
  --stat-color: var(--coc-success);
}

.stat-label {
  flex-shrink: 0;
  width: 30px;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
  letter-spacing: 0.5px;
}

.stat-track {
  position: relative;
  flex: 1;
  min-width: 0;
  height: 8px;
  border-radius: var(--coc-radius-full);
  background: rgba(11, 18, 32, 0.85);
  overflow: hidden;
}

.stat--compact .stat-track {
  height: 6px;
}

.stat-fill {
  display: block;
  height: 100%;
  border-radius: var(--coc-radius-full);
  background: var(--stat-color);
  transition: width var(--coc-dur) var(--coc-ease);
}

.stat-num {
  flex-shrink: 0;
  min-width: 46px;
  text-align: right;
  font-family: var(--coc-font-mono);
  font-size: var(--coc-fs-xs);
  color: var(--coc-text);
}

.stat-max {
  color: var(--coc-text-dim);
}

/* ≤30%：填充转危险色并轻微呼吸，团里最该被看见的正是这个 */
.stat--alert .stat-fill {
  background: var(--coc-danger);
  animation: coc-glow-breathe 2.4s ease-in-out infinite;
}

.stat--alert .stat-num {
  color: #fca5a5;
  font-weight: 600;
}
</style>
