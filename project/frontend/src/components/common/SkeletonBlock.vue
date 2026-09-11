<script setup lang="ts">
/**
 * 加载骨架屏 — 阶段 6.2⑨（配 StateView 的加载态）。
 *
 * 用 css 渐变流光（animations.css 的 `.coc-shimmer`）占位，让"内容即将出现在哪里"一眼可见；
 * 比全屏转圈更适合列表/卡片/消息流这类形状可预期的内容。
 *
 * variant：
 *   row  —— 列表行（左标题右说明，如大厅房间列表）
 *   card —— 卡片网格（带方形缩略块，如模组库）
 *   chat —— 消息流（圆形头像 + 两行文本）
 *   text —— 纯文本行（如角色卡详情）
 */
withDefaults(
  defineProps<{
    variant?: 'row' | 'card' | 'chat' | 'text'
    /** 占位条目数 */
    count?: number
    /** 每条的行数（card/chat 有头像块时行数从第 2 行起算宽度） */
    rows?: number
  }>(),
  { variant: 'row', count: 3, rows: 2 },
)
</script>

<template>
  <div class="skeleton" :class="`skeleton--${variant}`" aria-busy="true" aria-live="polite">
    <div v-for="i in count" :key="i" class="sk-item">
      <span v-if="variant === 'card'" class="sk-thumb coc-shimmer" />
      <span v-if="variant === 'chat'" class="sk-avatar coc-shimmer" />
      <div class="sk-lines">
        <span
          v-for="r in rows"
          :key="r"
          class="sk-line coc-shimmer"
          :style="{ width: `${100 - (r - 1) * 22}%` }"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-3);
  width: 100%;
}

.skeleton--card {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.sk-item {
  display: flex;
  align-items: flex-start;
  gap: var(--coc-sp-3);
  padding: var(--coc-sp-3) var(--coc-sp-4);
  border: 1px solid var(--coc-border-soft);
  border-radius: var(--coc-radius);
  background: var(--coc-card-2);
}

.skeleton--text .sk-item {
  padding: var(--coc-sp-2) 0;
  border: none;
  background: transparent;
}

.skeleton--chat .sk-item {
  border: none;
  background: transparent;
  padding: 0;
}

.sk-thumb {
  flex-shrink: 0;
  width: 64px;
  height: 64px;
  border-radius: var(--coc-radius-sm);
}

.sk-avatar {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: var(--coc-radius-full);
}

.sk-lines {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--coc-sp-2);
  padding-top: 2px;
}

.sk-line {
  display: block;
  height: 10px;
  border-radius: var(--coc-radius-full);
}
</style>
