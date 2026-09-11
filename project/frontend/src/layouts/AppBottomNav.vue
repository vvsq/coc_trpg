<script setup lang="ts">
/**
 * 底部 Tab 导航 — 阶段 6.2⑩ 移动端重构（对应 移动端样例demo.html 底部导航）。
 *
 * 手机（≤768px）下替代左侧 AppSideNav：侧栏完全隐藏（不再收成图标条），
 * 导航职能下沉到底部 5 个 tab（大厅 / 房间 / 角色 / 模组 / 设置）。
 * 默认（>768px）整条隐藏，桌面布局零影响。
 *
 * 与 AppSideNav 同源：导航项映射现有路由、不新增业务；「房间」按身份落点
 * （KP → 控制台，玩家 → 房间页），不在房间时禁用；模组/设置携带 from_room
 * query（沿用 ROOM_SCOPE_ROUTE_NAMES 的房间工作区约定）。
 */
import { computed } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import { useRoomStore } from '@/stores/room'
import CocIcon from '@/components/common/CocIcon.vue'
import type { IconName } from '@/components/common/cocIcons'

const route = useRoute()
const router = useRouter()
const room = useRoomStore()

interface NavItem {
  key: string
  label: string
  icon: IconName
  match: string[]
  to: () => RouteLocationRaw
  disabled?: boolean
  hint?: string
}

const inRoom = computed(() => !!room.roomId)

const NAV_ITEMS = computed<NavItem[]>(() => [
  {
    key: 'home',
    label: '大厅',
    icon: 'home',
    match: ['home'],
    to: () => ({ name: 'home' }),
  },
  {
    key: 'room',
    label: '房间',
    icon: 'dice',
    match: ['room', 'kp-console'],
    to: () =>
      room.myRole === 'kp'
        ? { name: 'kp-console', params: { id: room.roomId } }
        : { name: 'room', params: { id: room.roomId } },
    disabled: !inRoom.value,
    hint: inRoom.value ? '' : '尚未进入任何房间',
  },
  {
    key: 'cards',
    label: '角色',
    icon: 'card',
    match: ['card-list', 'card-detail', 'card-create'],
    to: () => ({ name: 'card-list' }),
  },
  {
    key: 'modules',
    label: '模组',
    icon: 'book',
    match: ['module-list', 'module-detail'],
    to: () => ({ name: 'module-list', query: inRoom.value ? { from_room: room.roomId } : {} }),
  },
  {
    key: 'settings',
    label: '设置',
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
  <nav class="bottom-nav" aria-label="主导航（移动端）">
    <button
      v-for="item in NAV_ITEMS"
      :key="item.key"
      type="button"
      class="nav-btn"
      :class="{ 'nav-btn--active': isActive(item) }"
      :disabled="item.disabled"
      :title="item.hint || item.label"
      @click="go(item)"
    >
      <CocIcon :name="item.icon" :size="20" />
      <span>{{ item.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
/* 桌面不出现；移动端（≤768px）由 AppLayout 放在外壳底部 */
.bottom-nav {
  display: none;
}

@media (max-width: 768px) {
  .bottom-nav {
    display: flex;
    align-items: stretch;
    flex-shrink: 0;
    min-height: var(--coc-bottomnav-h);
    padding-bottom: env(safe-area-inset-bottom, 0px);
    background: rgba(11, 18, 32, 0.92);
    border-top: 1px solid var(--coc-border);
    backdrop-filter: blur(12px);
    z-index: var(--coc-z-topbar);
  }

  .nav-btn {
    display: flex;
    flex: 1;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    padding: 6px 0;
    border: none;
    background: transparent;
    color: var(--coc-text-muted);
    font-family: inherit;
    font-size: 10px;
    cursor: pointer;
    transition: color var(--coc-dur-fast) var(--coc-ease);
    -webkit-tap-highlight-color: transparent;
  }

  .nav-btn--active {
    color: var(--coc-accent);
  }

  .nav-btn:disabled {
    opacity: 0.38;
    cursor: not-allowed;
  }
}
</style>
