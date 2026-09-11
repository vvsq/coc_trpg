<script setup lang="ts">
/**
 * 聊天流头像 — 阶段 6.2⑤（对应样例图消息行的圆形头像）。
 *
 * 三类身份三种外观，与昵称配色一致，扫一眼就能分清谁在说话：
 *   KP（人类）→ 橙底盾牌；AI 主持 → 青底星芒；玩家 → 灰底昵称首字。
 * 纯展示组件：不读 store、不发请求。
 */
import { computed } from 'vue'
import CocIcon from '@/components/common/CocIcon.vue'
import type { IconName } from '@/components/common/cocIcons'

const props = withDefaults(
  defineProps<{
    name: string
    /** 发送者身份（system 行不渲染头像，由调用方控制） */
    role?: 'kp' | 'player'
    /** AI 主持（4.2）：与人类 KP 用不同图标与配色区分 */
    ai?: boolean
    /** 仅 KP 专享行（keeper 笔记/暗骰） */
    keeper?: boolean
    /** 显式指定图标（如骰子行用 dice），优先于身份推导 */
    icon?: IconName
    size?: number
  }>(),
  { role: 'player', ai: false, keeper: false, size: 30 },
)

const initial = computed(() => (props.name || '?').trim().slice(0, 1).toUpperCase())

/** 配色档：keeper 优先于 ai 优先于角色 */
const tone = computed(() => (props.keeper ? 'keeper' : props.ai ? 'ai' : props.role))

const iconName = computed<IconName | null>(() => {
  if (props.icon) return props.icon
  if (props.ai || props.keeper) return 'sparkles'
  if (props.role === 'kp') return 'shield'
  return null
})
</script>

<template>
  <span class="avatar" :class="`avatar--${tone}`" :style="{ width: `${size}px`, height: `${size}px` }">
    <CocIcon v-if="iconName" :name="iconName" :size="size * 0.54" :stroke-width="1.7" />
    <template v-else>{{ initial }}</template>
  </span>
</template>

<style scoped>
.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border-radius: var(--coc-radius-full);
  border: 1px solid var(--coc-border);
  font-size: var(--coc-fs-sm);
  font-weight: 600;
  line-height: 1;
  user-select: none;
}

.avatar--kp {
  border-color: rgba(230, 162, 60, 0.5);
  background: var(--coc-brand-soft);
  color: var(--coc-brand);
}

.avatar--ai {
  border-color: var(--coc-border-glow);
  background: var(--coc-primary-soft);
  color: var(--coc-accent);
  box-shadow: var(--coc-glow);
}

.avatar--player {
  background: var(--coc-card-3);
  color: var(--coc-text);
}

.avatar--keeper {
  border-color: rgba(122, 92, 214, 0.55);
  background: var(--coc-keeper-soft);
  color: #b9a4f5;
}
</style>
