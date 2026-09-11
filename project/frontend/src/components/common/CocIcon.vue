<script setup lang="ts">
/**
 * 内联图标组件 — 阶段 6.2②。
 *
 * 项目未引入图标库，样例图里的 FontAwesome 是 CDN 依赖（比赛现场可能断网），
 * 故用内联 SVG：零依赖、随字体色变化、体积可控。路径表见 `cocIcons.ts`。
 */
import { computed } from 'vue'
import { COC_ICON_PATHS, type IconName } from './cocIcons'

const props = withDefaults(
  defineProps<{
    name: IconName
    size?: number | string
    /** 线宽，描边类图标可微调 */
    strokeWidth?: number
  }>(),
  { size: 18, strokeWidth: 1.8 },
)

const paths = computed<readonly string[]>(() => COC_ICON_PATHS[props.name] ?? [])
const px = computed(() => (typeof props.size === 'number' ? `${props.size}px` : props.size))
</script>

<template>
  <svg
    class="coc-icon-svg"
    :width="px"
    :height="px"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <path v-for="(d, i) in paths" :key="i" :d="d" />
  </svg>
</template>

<style scoped>
.coc-icon-svg {
  display: block;
  flex-shrink: 0;
}
</style>
