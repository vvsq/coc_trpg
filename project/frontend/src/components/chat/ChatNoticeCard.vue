<script setup lang="ts">
/**
 * 「重要信息」高亮卡 — 阶段 6.2⑤（对齐样例图的琥珀色提示卡）。
 *
 * 当前唯一使用方：状态变更行（KP/AI 改 HP·SAN，D9 必带 reason）。
 * 抽取前这行只是 12px 灰字，团里最该被看见的数值变化反而最不起眼；
 * 抽成卡片后与骰子徽章、普通气泡形成三级视觉重量：数值变更 > 骰子 > 叙事。
 *
 * 纯展示组件：title / sender / text 全由 props 传入。
 */
withDefaults(
  defineProps<{
    sender: string
    text: string
    title?: string
  }>(),
  { title: '重要信息' },
)
</script>

<template>
  <div class="notice-card">
    <p class="notice-title">
      <span class="notice-icon" aria-hidden="true">!</span>
      {{ title }}
    </p>
    <p class="notice-body">
      <span class="notice-op">{{ sender }}</span>
      {{ text }}
    </p>
  </div>
</template>

<style scoped>
.notice-card {
  max-width: min(100%, 68ch);
  margin: 0 auto;
  padding: var(--coc-sp-3) var(--coc-sp-4);
  border: 1px solid rgba(245, 158, 11, 0.32);
  border-left: 3px solid var(--coc-warning);
  border-radius: var(--coc-radius);
  background: var(--coc-warning-soft);
}

.notice-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  font-size: var(--coc-fs-sm);
  font-weight: 600;
  color: var(--coc-warning);
}

.notice-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border-radius: var(--coc-radius-full);
  background: var(--coc-warning);
  color: var(--coc-text-inverse);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
}

.notice-body {
  font-size: var(--coc-fs-sm);
  line-height: var(--coc-lh);
  color: var(--coc-text);
  word-break: break-word;
}

.notice-op {
  font-weight: 600;
  color: var(--coc-warning);
}
</style>
