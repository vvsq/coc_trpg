/**
 * 本机 UI 偏好 store — 阶段 6.2（② 落地，④ 补设置界面）。
 *
 * 边界（用户 2026-09-11 决策）：这里**只存"本机个性化"**，不碰业务状态、不进后端。
 * 自选背景图的图片二进制存 IndexedDB（见 composables/useBackgroundImage.ts），
 * 其余小项存 localStorage（键 `coc_ui_settings`）。
 *
 * 生效方式：把偏好写进 `documentElement` 的 CSS 变量与 class，全站样式自动跟随，
 * 不做组件级重渲染（tokens.css 里的 --coc-font-scale / --coc-glow-strength 即为此设计）。
 */
import { defineStore } from 'pinia'
import { reactive, watch } from 'vue'

/** 背景预设：abyss 深渊 / fog 雾镇 / deepsea 深海 / mansion 宅邸 / custom 自选图 / none 纯黑 */
export type BgPresetId = 'abyss' | 'fog' | 'deepsea' | 'mansion' | 'custom' | 'none'
/** 面板发光强度：0 关闭 / 1 标准 / 2 张扬 */
export type GlowStrength = 0 | 1 | 2
/** 字体档：小 / 标准 / 大 */
export type FontScale = 0.9 | 1 | 1.15

export interface UiSettings {
  bgPreset: BgPresetId
  /** 背景氛围层（缓慢漂浮的渐变光斑）；默认关闭，避免演示掉帧 */
  ambience: boolean
  glowStrength: GlowStrength
  fontScale: FontScale
  /** 动效总开关（关掉等于全局 reduced-motion） */
  motion: boolean
  /** 音效总开关（骰子/消息提示音，WebAudio 合成，默认关闭） */
  sound: boolean
}

const STORAGE_KEY = 'coc_ui_settings'

const DEFAULTS: UiSettings = {
  bgPreset: 'abyss',
  ambience: false,
  glowStrength: 1,
  fontScale: 1,
  motion: true,
  sound: false,
}

const BG_PRESETS: BgPresetId[] = ['abyss', 'fog', 'deepsea', 'mansion', 'custom', 'none']

/** 读取并逐字段归一（本地存储可能被手改/来自旧版本） */
function load(): UiSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULTS }
    const saved = JSON.parse(raw) as Partial<UiSettings>
    const preset = BG_PRESETS.includes(saved.bgPreset as BgPresetId)
      ? (saved.bgPreset as BgPresetId)
      : DEFAULTS.bgPreset
    const glow = [0, 1, 2].includes(saved.glowStrength as number)
      ? (saved.glowStrength as GlowStrength)
      : DEFAULTS.glowStrength
    const font = [0.9, 1, 1.15].includes(saved.fontScale as number)
      ? (saved.fontScale as FontScale)
      : DEFAULTS.fontScale
    return {
      bgPreset: preset,
      ambience: typeof saved.ambience === 'boolean' ? saved.ambience : DEFAULTS.ambience,
      glowStrength: glow,
      fontScale: font,
      motion: typeof saved.motion === 'boolean' ? saved.motion : DEFAULTS.motion,
      sound: typeof saved.sound === 'boolean' ? saved.sound : DEFAULTS.sound,
    }
  } catch {
    return { ...DEFAULTS }
  }
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = reactive<UiSettings>(load())

  /** 把偏好同步到 DOM（CSS 变量 + 动效 class），老浏览器无 classList 时静默跳过 */
  function applyDom(): void {
    const el = document.documentElement
    el.style.setProperty('--coc-font-scale', String(settings.fontScale))
    el.style.setProperty('--coc-glow-strength', String(settings.glowStrength))
    el.classList.toggle('coc-reduce-motion', !settings.motion)
  }

  function persist(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    } catch {
      // 隐私模式/配额不足：偏好落不了盘不影响本次会话使用
    }
  }

  /** 局部更新（设置页各控件统一入口） */
  function patch(partial: Partial<UiSettings>): void {
    Object.assign(settings, partial)
  }

  /** 恢复默认（设置页「恢复默认外观」） */
  function reset(): void {
    Object.assign(settings, DEFAULTS)
  }

  applyDom()
  watch(settings, () => {
    applyDom()
    persist()
  }, { deep: true })

  return { settings, patch, reset, applyDom }
})
