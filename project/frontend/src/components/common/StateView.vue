<script setup lang="ts">
/**
 * 三态统一组件 — 阶段 6.2⑨。
 *
 * 加载态 / 空态 / 错误态共用一套排版（圆形图标 + 标题 + 描述 + 操作槽），
 * 替掉各页面散落的 `el-empty`、裸 spinner，以及"只有 toast、关掉后页面上什么都不剩"的错误态。
 * 用法：
 *   <StateView state="error" description="房间列表加载失败" >
 *     <el-button @click="refresh">重试</el-button>
 *   </StateView>
 */
import { computed } from 'vue'
import CocIcon from './CocIcon.vue'
import type { IconName } from './cocIcons'

const props = withDefaults(
  defineProps<{
    state?: 'loading' | 'empty' | 'error'
    title?: string
    description?: string
    icon?: IconName
    /** 紧凑模式：嵌在小面板/对话框里用（缩小图标与间距） */
    compact?: boolean
  }>(),
  { state: 'empty', title: '', description: '', compact: false },
)

const DEFAULT_TITLE: Record<'loading' | 'empty' | 'error', string> = {
  loading: '加载中…',
  empty: '暂无内容',
  error: '出错了',
}

const DEFAULT_ICON: Record<'loading' | 'empty' | 'error', IconName> = {
  loading: 'refresh',
  empty: 'info',
  error: 'close',
}

const shownTitle = computed(() => props.title || DEFAULT_TITLE[props.state])
const shownIcon = computed<IconName>(() => props.icon || DEFAULT_ICON[props.state])
</script>

<template>
  <div
    class="state-view"
    :class="[`state-view--${state}`, compact && 'state-view--compact']"
    role="status"
    aria-live="polite"
  >
    <span class="sv-icon" :class="{ 'coc-spin': state === 'loading' }">
      <CocIcon :name="shownIcon" :size="compact ? 16 : 20" />
    </span>
    <p class="sv-title">{{ shownTitle }}</p>
    <p v-if="description" class="sv-desc">{{ description }}</p>
    <div v-if="$slots.default" class="sv-actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.state-view {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--coc-sp-2);
  padding: var(--coc-sp-8) var(--coc-sp-4);
  text-align: center;
}

.state-view--compact {
  gap: var(--coc-sp-1);
  padding: var(--coc-sp-4);
}

.sv-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-full);
  background: var(--coc-card-2);
  color: var(--coc-text-dim);
}

.state-view--compact .sv-icon {
  width: 34px;
  height: 34px;
}

.state-view--loading .sv-icon {
  border-color: var(--coc-border-glow);
  color: var(--coc-accent);
}

.state-view--error .sv-icon {
  border-color: rgba(239, 68, 68, 0.5);
  background: var(--coc-danger-soft);
  color: var(--coc-danger);
}

.sv-title {
  font-size: var(--coc-fs-base);
  font-weight: 600;
  color: var(--coc-text);
}

.state-view--compact .sv-title {
  font-size: var(--coc-fs-sm);
}

.sv-desc {
  max-width: 46ch;
  font-size: var(--coc-fs-sm);
  line-height: 1.6;
  color: var(--coc-text-muted);
}

.sv-actions {
  margin-top: var(--coc-sp-2);
}
</style>
