<script setup lang="ts">
/**
 * 侧栏房间信息卡 — 阶段 6.2②（样例图左侧底部那块）。
 *
 * 数据全部来自 room store 已有状态（房间号/成员数/主持模式/挂载模组），零后端改动。
 * 唯一"新"数据是「本机在线」时长：`GET /rooms` 只列 waiting 房间、playing 房间没有
 * created_at 数据源，为了不为此改后端，这里展示的是**本机进房起的计时**（文案如实标注）。
 */
import { computed, onUnmounted, ref, watch } from 'vue'
import { useRoomStore } from '@/stores/room'
import { AGENT_MODE_LABELS } from '@/types/ws'
import CocIcon from '@/components/common/CocIcon.vue'

const room = useRoomStore()

/** 本机进房时长（秒）；换房/退房重置 */
const elapsed = ref(0)
let startedAt: number | null = null
let timer: number | null = null

function stopTimer(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

function startTimer(): void {
  stopTimer()
  startedAt = Date.now()
  elapsed.value = 0
  timer = window.setInterval(() => {
    if (startedAt !== null) elapsed.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)
}

watch(
  () => room.roomId,
  (id) => {
    if (id) startTimer()
    else {
      stopTimer()
      startedAt = null
      elapsed.value = 0
    }
  },
  { immediate: true },
)

onUnmounted(stopTimer)

const duration = computed(() => {
  const s = elapsed.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
})

const playerCount = computed(() => room.members.filter((m) => m.role !== 'kp').length)
const moduleName = computed(() => room.roomModule?.module_name ?? '')
</script>

<template>
  <div class="room-info">
    <!-- 模组封面占位（无素材时用渐变 + 标题，§6.2③「素材缺失不阻塞布局」） -->
    <div class="cover">
      <span class="cover-mark">
        <CocIcon name="book" :size="20" />
      </span>
      <div class="cover-text">
        <p class="cover-title">{{ moduleName || '未挂载模组' }}</p>
        <p class="cover-sub">{{ moduleName ? '当前模组' : '默认剧情骨架' }}</p>
      </div>
    </div>

    <dl class="rows">
      <div class="row">
        <dt>房间号</dt>
        <dd class="code">{{ room.roomId }}</dd>
      </div>
      <div class="row">
        <dt>玩家人数</dt>
        <dd>{{ playerCount }} 人</dd>
      </div>
      <div class="row">
        <dt>主持模式</dt>
        <dd>{{ AGENT_MODE_LABELS[room.agentMode] }}</dd>
      </div>
      <div class="row">
        <dt>本机在线</dt>
        <dd class="mono">{{ duration }}</dd>
      </div>
    </dl>
  </div>
</template>

<style scoped>
.room-info {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-3);
  padding: var(--coc-sp-3);
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: rgba(22, 32, 50, 0.7);
}

.cover {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  padding: var(--coc-sp-3);
  border-radius: var(--coc-radius-sm);
  overflow: hidden;
  background:
    radial-gradient(120% 140% at 10% 0%, rgba(34, 211, 238, 0.22), transparent 60%),
    linear-gradient(135deg, #1b2a44 0%, #101a2c 100%);
  border: 1px solid var(--coc-border-soft);
}

.cover-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: var(--coc-radius-sm);
  background: rgba(11, 18, 32, 0.55);
  color: var(--coc-accent);
}

.cover-text {
  min-width: 0;
}

.cover-title {
  margin: 0;
  font-size: var(--coc-fs-sm);
  font-weight: 600;
  color: var(--coc-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cover-sub {
  margin: 1px 0 0;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.rows {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-2);
  font-size: var(--coc-fs-xs);
}

.row dt {
  color: var(--coc-text-muted);
}

.row dd {
  margin: 0;
  color: var(--coc-text);
}

.code {
  font-family: var(--coc-font-mono);
  letter-spacing: 1.5px;
  color: var(--coc-brand);
}

.mono {
  font-family: var(--coc-font-mono);
}
</style>
