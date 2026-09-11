<script setup lang="ts">
/**
 * 顶部品牌栏 — 阶段 6.2②（对应样例图 header）。
 *
 * 内容映射到现有功能：品牌区（项目名/副标题）、局域网联机标识（部署形态即局域网）、
 * 主持模式开关（ModeSwitch，仅房间内有意义）、设置入口（/settings）、全屏按钮、当前身份。
 * 明确不做：导航（已下沉到左侧 AppSideNav）。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useRoomStore } from '@/stores/room'
import CocIcon from '@/components/common/CocIcon.vue'
import ModeSwitch from './ModeSwitch.vue'

const router = useRouter()
const room = useRoomStore()

const inRoom = computed(() => !!room.roomId)
const roleLabel = computed(() => (room.myRole === 'kp' ? '守秘人' : '调查员'))

// ---------- 全屏（样例图的 expand 按钮；浏览器不允许时给人话提示） ----------
const isFullscreen = ref(false)

function syncFullscreen(): void {
  isFullscreen.value = !!document.fullscreenElement
}

async function toggleFullscreen(): Promise<void> {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await document.documentElement.requestFullscreen()
  } catch {
    ElMessage.warning('当前浏览器不允许全屏，可用 F11 代替')
  }
}

onMounted(() => document.addEventListener('fullscreenchange', syncFullscreen))
onUnmounted(() => document.removeEventListener('fullscreenchange', syncFullscreen))

function openSettings(): void {
  // 从房间进设置属于「房间工作区」内跳转，不会断连接（见 router ROOM_SCOPE_ROUTE_NAMES）
  router.push({ name: 'settings', query: inRoom.value ? { from_room: room.roomId } : {} })
}
</script>

<template>
  <header class="top-bar">
    <div class="brand">
      <span class="brand-logo">
        <CocIcon name="skull" :size="22" :stroke-width="1.6" />
      </span>
      <div class="brand-text">
        <h1 class="brand-title">COC 跑团助手</h1>
        <p class="brand-sub">让每个人都能轻松开启一场克苏鲁之旅</p>
      </div>
    </div>

    <div class="bar-right">
      <span class="lan-chip">
        <i class="lan-dot" />
        局域网联机
      </span>

      <ModeSwitch />

      <span v-if="inRoom" class="me-chip coc-chip">
        <CocIcon :name="room.myRole === 'kp' ? 'shield' : 'card'" :size="13" />
        {{ room.playerName }} · {{ roleLabel }}
        <i class="conn-dot" :class="{ 'conn-dot--on': room.connected }" :title="room.connected ? '已连接' : '重连中…'" />
      </span>

      <button class="icon-btn" type="button" title="系统设置" @click="openSettings">
        <CocIcon name="gear" :size="17" />
      </button>
      <button
        class="icon-btn fullscreen-btn"
        type="button"
        :title="isFullscreen ? '退出全屏' : '全屏'"
        @click="toggleFullscreen"
      >
        <CocIcon name="expand" :size="17" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-4);
  height: var(--coc-topbar-h);
  padding: 0 var(--coc-sp-5);
  flex-shrink: 0;
  background: rgba(11, 18, 32, 0.72);
  border-bottom: 1px solid var(--coc-border);
  backdrop-filter: blur(12px);
  z-index: var(--coc-z-topbar);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  min-width: 0;
}

.brand-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: var(--coc-radius);
  color: var(--coc-accent);
  background: linear-gradient(160deg, rgba(34, 211, 238, 0.18), rgba(122, 92, 214, 0.16));
  border: 1px solid var(--coc-border-glow);
  box-shadow: var(--coc-glow);
}

.brand-text {
  min-width: 0;
}

.brand-title {
  margin: 0;
  font-size: var(--coc-fs-md);
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--coc-text-strong);
  white-space: nowrap;
}

.brand-sub {
  margin: 1px 0 0;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
  white-space: nowrap;
}

.bar-right {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  min-width: 0;
}

.lan-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-muted);
  white-space: nowrap;
}

.lan-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--coc-success);
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.8);
}

.me-chip {
  gap: 6px;
  color: var(--coc-text);
}

.conn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--coc-danger);
}

.conn-dot--on {
  background: var(--coc-success);
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.8);
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid transparent;
  border-radius: var(--coc-radius);
  background: transparent;
  color: var(--coc-text-muted);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease), background var(--coc-dur-fast) var(--coc-ease),
    border-color var(--coc-dur-fast) var(--coc-ease);
}

.icon-btn:hover {
  color: var(--coc-accent);
  background: var(--coc-card-2);
  border-color: var(--coc-border);
}

@media (max-width: 900px) {
  .brand-sub,
  .lan-chip {
    display: none;
  }

  .top-bar {
    padding: 0 var(--coc-sp-3);
  }
}

/* 阶段 6.2⑩：手机宽度下品牌文案与身份 chip 让位，只留 logo + 模式开关 + 图标按钮 */
@media (max-width: 768px) {
  .brand-text,
  .me-chip {
    display: none;
  }

  .bar-right {
    gap: var(--coc-sp-2);
  }

  /* 玩家端模式只读 chip 也藏起来（模式本身由 KP 控制，房间信息卡里已有回显） */
  .bar-right :deep(.mode-readonly) {
    display: none;
  }

  /* 手机浏览器全屏收益小且占位：让位给底部 Tab 导航（6.2⑩） */
  .fullscreen-btn {
    display: none;
  }

  /* 顶栏整体降高，把纵向空间让给内容 */
  .top-bar {
    height: 54px;
  }

  .brand-logo {
    width: 32px;
    height: 32px;
  }
}
</style>
