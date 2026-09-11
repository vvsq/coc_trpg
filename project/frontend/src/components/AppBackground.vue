<script setup lang="ts">
/**
 * 全局背景层 — 阶段 6.2③（② 先行接入外壳）。
 *
 * 三种来源，优先级：自选图 > 预设渐变 > 纯色兜底。
 * 素材策略（用户 2026-09-11 决策）：先用 CSS 渐变兜底，不引入位图，缺素材不阻塞布局。
 *
 * 性能约束：单例、fixed、pointer-events: none，只画不交互；不使用大面积 backdrop-filter。
 */
import { computed } from 'vue'
import { useSettingsStore, type BgPresetId } from '@/stores/settings'
import { useBackgroundImage } from '@/composables/useBackgroundImage'

const { settings } = useSettingsStore()
const { url } = useBackgroundImage()

/** 预设渐变（纯 CSS，无图片依赖）；custom 不在这里，由用户自选图接管 */
const PRESET_BG = {
  abyss: [
    'radial-gradient(1100px 700px at 14% -12%, rgba(14, 165, 233, 0.20), transparent 62%)',
    'radial-gradient(900px 620px at 102% 108%, rgba(122, 92, 214, 0.18), transparent 60%)',
    'radial-gradient(760px 520px at 62% 42%, rgba(34, 211, 238, 0.06), transparent 72%)',
    'linear-gradient(180deg, #0b1220 0%, #070d18 100%)',
  ].join(','),
  fog: [
    'radial-gradient(1000px 720px at 48% -18%, rgba(148, 163, 184, 0.20), transparent 66%)',
    'radial-gradient(820px 620px at 6% 104%, rgba(34, 211, 238, 0.10), transparent 62%)',
    'linear-gradient(180deg, #0d1420 0%, #070c14 100%)',
  ].join(','),
  deepsea: [
    'radial-gradient(920px 620px at 82% -6%, rgba(6, 182, 212, 0.22), transparent 62%)',
    'radial-gradient(920px 700px at -4% 92%, rgba(2, 132, 199, 0.22), transparent 62%)',
    'linear-gradient(180deg, #061420 0%, #040b14 100%)',
  ].join(','),
  mansion: [
    'radial-gradient(920px 620px at 20% -8%, rgba(230, 162, 60, 0.16), transparent 62%)',
    'radial-gradient(820px 620px at 96% 104%, rgba(122, 92, 214, 0.16), transparent 62%)',
    'linear-gradient(180deg, #14100b 0%, #0a0908 100%)',
  ].join(','),
  none: '#0b1220',
} as const

/** 取预设底色；custom 与非预设值一律回落深渊 */
function presetBackground(id: BgPresetId): string {
  if (id === 'custom') return PRESET_BG.abyss
  return PRESET_BG[id]
}

const isCustom = computed(() => settings.bgPreset === 'custom' && !!url.value)

const bgStyle = computed<Record<string, string>>(() => {
  const style: Record<string, string> = {}
  if (isCustom.value && url.value) {
    // 覆盖一层半透明底色，保证暗色文字在任意自选图上都可读
    style.backgroundImage = `linear-gradient(rgba(11, 18, 32, 0.86), rgba(7, 13, 24, 0.94)), url("${url.value}")`
    style.backgroundSize = 'cover'
    style.backgroundPosition = 'center'
    style.backgroundRepeat = 'no-repeat'
  } else {
    style.background = presetBackground(settings.bgPreset)
  }
  return style
})
</script>

<template>
  <div class="app-bg" aria-hidden="true">
    <div class="app-bg__layer" :style="bgStyle" />
    <!-- 氛围层（默认关闭）：两团缓慢漂浮的光斑，纯 CSS 动画，关掉即零开销 -->
    <div v-if="settings.ambience" class="app-bg__ambience">
      <span class="orb orb--cyan coc-ambient-drift" />
      <span class="orb orb--violet coc-ambient-drift" />
    </div>
    <div class="app-bg__vignette" />
  </div>
</template>

<style scoped>
.app-bg {
  position: fixed;
  inset: 0;
  z-index: var(--coc-z-bg);
  pointer-events: none;
  overflow: hidden;
}

.app-bg__layer {
  position: absolute;
  inset: 0;
  transition: background var(--coc-dur-slow) var(--coc-ease);
}

.app-bg__ambience {
  position: absolute;
  inset: 0;
}

.orb {
  position: absolute;
  display: block;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.6;
}

.orb--cyan {
  width: 42vw;
  height: 42vw;
  top: -12vw;
  left: -8vw;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.35), transparent 68%);
}

.orb--violet {
  width: 38vw;
  height: 38vw;
  right: -10vw;
  bottom: -14vw;
  background: radial-gradient(circle, rgba(122, 92, 214, 0.32), transparent 68%);
  animation-delay: -9s;
}

/* 四周暗角：把注意力收进内容区，也让亮色背景图不至于"糊"住文字 */
.app-bg__vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(120% 100% at 50% 0%, transparent 40%, rgba(4, 8, 16, 0.55) 100%);
}
</style>
