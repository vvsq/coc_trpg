<script setup lang="ts">
/**
 * 左侧导航侧栏 — 阶段 6.2②（对应样例图 aside）。
 *
 * 导航项映射现有路由，不新增业务：游戏大厅 / 当前房间 / 角色管理 / 模组库 / 系统设置，
 * 底部收纳房间信息卡与「结束游戏」（房间内才出现），以及关于页入口。
 *
 * 「当前房间」的落点按身份决定：KP → 控制台，玩家 → 房间页；不在房间时该项禁用
 * （避免把用户骗进一个空房间）。
 */
import { computed } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import { useRoomStore } from '@/stores/room'
import { useQuitRoom } from '@/composables/useQuitRoom'
import CocIcon from '@/components/common/CocIcon.vue'
import RoomInfoCard from './RoomInfoCard.vue'
import type { IconName } from '@/components/common/cocIcons'

const route = useRoute()
const router = useRouter()
const room = useRoomStore()
const { quitRoom } = useQuitRoom()

interface NavItem {
  key: string
  label: string
  icon: IconName
  /** 命中这些路由名时高亮 */
  match: string[]
  to: () => RouteLocationRaw
  disabled?: boolean
  hint?: string
}

const inRoom = computed(() => !!room.roomId)

const NAV_ITEMS = computed<NavItem[]>(() => [
  {
    key: 'home',
    label: '游戏大厅',
    icon: 'home',
    match: ['home'],
    to: () => ({ name: 'home' }),
  },
  {
    key: 'room',
    label: '当前房间',
    icon: 'dice',
    match: ['room', 'kp-console', 'settings'],
    to: () =>
      room.myRole === 'kp'
        ? { name: 'kp-console', params: { id: room.roomId } }
        : { name: 'room', params: { id: room.roomId } },
    disabled: !inRoom.value,
    hint: inRoom.value ? '' : '尚未进入任何房间',
  },
  {
    key: 'cards',
    label: '角色管理',
    icon: 'card',
    match: ['card-list', 'card-detail', 'card-create'],
    to: () => ({ name: 'card-list' }),
  },
  {
    key: 'modules',
    label: '模组库',
    icon: 'book',
    match: ['module-list', 'module-detail'],
    to: () => ({ name: 'module-list', query: inRoom.value ? { from_room: room.roomId } : {} }),
  },
  {
    key: 'settings',
    label: '系统设置',
    icon: 'gear',
    match: ['settings'],
    to: () => ({ name: 'settings', query: inRoom.value ? { from_room: room.roomId } : {} }),
  },
])

const currentName = computed(() => String(route.name ?? ''))

function isActive(item: NavItem): boolean {
  return item.match.includes(currentName.value)
}

function go(item: NavItem): void {
  if (item.disabled) return
  router.push(item.to())
}
</script>

<template>
  <aside class="side-nav">
    <nav class="nav-list">
      <button
        v-for="item in NAV_ITEMS"
        :key="item.key"
        type="button"
        class="nav-item"
        :class="{ 'nav-item--active': isActive(item), 'nav-item--disabled': item.disabled }"
        :disabled="item.disabled"
        :title="item.hint || item.label"
        @click="go(item)"
      >
        <span class="nav-bar" />
        <CocIcon :name="item.icon" :size="17" />
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>

    <div class="nav-bottom">
      <div v-if="inRoom" class="nav-info">
        <RoomInfoCard />
      </div>
      <button v-if="inRoom" type="button" class="quit-btn" @click="quitRoom">
        <CocIcon name="close" :size="15" />
        结束游戏
      </button>
      <button type="button" class="about-btn" @click="router.push({ name: 'about' })">
        <CocIcon name="info" :size="14" />
        关于本项目
      </button>
    </div>
  </aside>
</template>

<style scoped>
.side-nav {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: var(--coc-sidenav-w);
  flex-shrink: 0;
  padding: var(--coc-sp-4) var(--coc-sp-3) var(--coc-sp-3);
  background: rgba(11, 18, 32, 0.6);
  border-right: 1px solid var(--coc-border);
  backdrop-filter: blur(10px);
  overflow-y: auto;
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  width: 100%;
  padding: 10px var(--coc-sp-3);
  border: none;
  border-radius: var(--coc-radius);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-base);
  text-align: left;
  cursor: pointer;
  transition: background var(--coc-dur-fast) var(--coc-ease), color var(--coc-dur-fast) var(--coc-ease);
}

.nav-item:hover:not(.nav-item--disabled) {
  background: var(--coc-card-2);
  color: var(--coc-text);
}

.nav-bar {
  position: absolute;
  left: 0;
  top: 50%;
  width: 2px;
  height: 0;
  border-radius: 2px;
  transform: translateY(-50%);
  background: var(--coc-accent);
  transition: height var(--coc-dur) var(--coc-ease), box-shadow var(--coc-dur) var(--coc-ease);
}

.nav-item--active {
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.16), rgba(14, 165, 233, 0.04));
  color: var(--coc-accent);
}

.nav-item--active .nav-bar {
  height: 62%;
  box-shadow: 0 0 10px var(--coc-border-glow);
}

.nav-item--disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.nav-label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-bottom {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-3);
  margin-top: var(--coc-sp-5);
}

.quit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 9px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: rgba(30, 43, 66, 0.6);
  color: var(--coc-text);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  cursor: pointer;
  transition: border-color var(--coc-dur-fast) var(--coc-ease), color var(--coc-dur-fast) var(--coc-ease),
    background var(--coc-dur-fast) var(--coc-ease);
}

.quit-btn:hover {
  border-color: rgba(239, 68, 68, 0.55);
  background: var(--coc-danger-soft);
  color: #fca5a5;
}

.about-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 4px;
  border: none;
  background: transparent;
  color: var(--coc-text-dim);
  font-family: inherit;
  font-size: var(--coc-fs-xs);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease);
}

.about-btn:hover {
  color: var(--coc-text-muted);
}

/* 窄屏：导航收成图标条（阶段 6.2⑩ 再做抽屉化，这里保证不撑破布局） */
@media (max-width: 1100px) {
  .side-nav {
    width: 68px;
    padding: var(--coc-sp-3) var(--coc-sp-2);
  }

  .nav-label {
    display: none;
  }

  .nav-item {
    justify-content: center;
    padding: 12px 0;
  }

  .nav-bottom {
    align-items: center;
  }

  /* 6.2⑩：图标条模式下房间信息卡放不下（房间号/人数会挤成一列字），隐藏之 */
  .nav-info {
    display: none;
  }

  .quit-btn,
  .about-btn {
    width: 100%;
    font-size: 0;
    gap: 0;
    padding: 10px 0;
  }
}

/* 阶段 6.2⑩ 移动端：侧栏整体退场（导航职能交给 AppBottomNav 底部 Tab），
   不再以"图标条"形态占住手机屏幕左侧——这是"PC 缩放版"观感的主要来源。 */
@media (max-width: 768px) {
  .side-nav {
    display: none;
  }
}
</style>
