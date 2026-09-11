<script setup lang="ts">
/**
 * 外观设置面板 — 阶段 6.2④（② 先落背景预设，③④ 补上传与氛围项）。
 *
 * 纯本机偏好：改完立即生效（写 documentElement 的 CSS 变量/class），不产生后端请求，
 * 也不影响同房间其他人。数据源见 stores/settings.ts。
 */
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSettingsStore, type BgPresetId } from '@/stores/settings'
import { useBackgroundImage, MAX_BG_BYTES } from '@/composables/useBackgroundImage'
import CocIcon from '@/components/common/CocIcon.vue'

const { settings, patch, reset } = useSettingsStore()
const { url: customUrl, save: saveCustom, clear: clearCustom } = useBackgroundImage()

const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

/** 预设卡片：只用 CSS 变量拼代表色，避免为每个预设再写一套渐变规则 */
const PRESETS: { id: BgPresetId; name: string; desc: string; swatch: string }[] = [
  {
    id: 'abyss',
    name: '深渊',
    desc: '青蓝底色 · 默认',
    swatch: 'radial-gradient(circle at 30% 25%, #1c4a63, #0b1220 70%)',
  },
  {
    id: 'fog',
    name: '雾镇',
    desc: '冷灰雾气',
    swatch: 'radial-gradient(circle at 50% 20%, #33455c, #0d1420 72%)',
  },
  {
    id: 'deepsea',
    name: '深海',
    desc: '幽绿暗流',
    swatch: 'radial-gradient(circle at 70% 20%, #0e5f70, #061420 72%)',
  },
  {
    id: 'mansion',
    name: '宅邸',
    desc: '暖褐烛光',
    swatch: 'radial-gradient(circle at 25% 20%, #5a4526, #14100b 72%)',
  },
  {
    id: 'none',
    name: '纯色',
    desc: '最低干扰',
    swatch: 'linear-gradient(180deg, #0b1220, #070d18)',
  },
]

const customActive = computed(() => settings.bgPreset === 'custom')

function pickPreset(id: BgPresetId): void {
  patch({ bgPreset: id })
}

// el-switch / el-radio-group 的值是 boolean | string | number，这里收口成强类型，
// 避免把非法值写进偏好（设置项都是有限枚举）
function setAmbience(v: string | number | boolean): void {
  patch({ ambience: Boolean(v) })
}

function setMotion(v: string | number | boolean): void {
  patch({ motion: Boolean(v) })
}

function setGlow(v: string | number | boolean): void {
  if (v === 0 || v === 1 || v === 2) patch({ glowStrength: v })
}

function setFont(v: string | number | boolean): void {
  if (v === 0.9 || v === 1 || v === 1.15) patch({ fontScale: v })
}

function triggerUpload(): void {
  fileInput.value?.click()
}

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 允许连续选同一张图
  if (!file) return
  uploading.value = true
  try {
    await saveCustom(file)
    patch({ bgPreset: 'custom' })
    ElMessage.success('背景图已更新（仅本机可见）')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '背景图保存失败')
  } finally {
    uploading.value = false
  }
}

async function onClearCustom(): Promise<void> {
  try {
    await ElMessageBox.confirm('将删除本机保存的自定义背景图，确定？', '清除自选背景', {
      confirmButtonText: '清除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await clearCustom()
  patch({ bgPreset: 'abyss' })
  ElMessage.success('已恢复默认背景')
}

async function onReset(): Promise<void> {
  try {
    await ElMessageBox.confirm('恢复默认外观（背景/氛围/发光/字号/动效/音效）？', '恢复默认', {
      confirmButtonText: '恢复',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  reset()
  ElMessage.success('已恢复默认外观')
}
</script>

<template>
  <div class="settings-panel">
    <!-- ---------- 背景 ---------- -->
    <section class="block">
      <header class="block-head">
        <h3 class="block-title">
          <CocIcon name="image" :size="16" />
          背景图
        </h3>
        <span class="coc-chip">仅本机生效</span>
      </header>

      <div class="preset-grid">
        <button
          v-for="p in PRESETS"
          :key="p.id"
          type="button"
          class="preset"
          :class="{ 'preset--active': settings.bgPreset === p.id }"
          @click="pickPreset(p.id)"
        >
          <span class="preset-swatch" :style="{ background: p.swatch }">
            <CocIcon v-if="settings.bgPreset === p.id" name="check" :size="15" />
          </span>
          <span class="preset-name">{{ p.name }}</span>
          <span class="preset-desc">{{ p.desc }}</span>
        </button>

        <!-- 自选图：存 IndexedDB，不上传服务器 -->
        <button
          type="button"
          class="preset preset--custom"
          :class="{ 'preset--active': customActive }"
          :disabled="uploading"
          @click="triggerUpload"
        >
          <span
            class="preset-swatch preset-swatch--image"
            :style="customUrl ? { backgroundImage: `url('${customUrl}')` } : undefined"
          >
            <CocIcon v-if="!customUrl" name="upload" :size="15" />
            <CocIcon v-else-if="customActive" name="check" :size="15" />
          </span>
          <span class="preset-name">{{ uploading ? '处理中…' : '自选图片' }}</span>
          <span class="preset-desc">{{ customUrl ? '点击更换' : `≤ ${(MAX_BG_BYTES / 1024 / 1024).toFixed(0)}MB` }}</span>
        </button>
      </div>

      <div class="row-actions">
        <button v-if="customUrl" type="button" class="ghost-btn" :disabled="uploading" @click="onClearCustom">
          <CocIcon name="trash" :size="14" />
          清除自选图
        </button>
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          accept="image/*"
          @change="onFileChange"
        />
      </div>
      <p class="coc-hint">
        自选图片保存在本机浏览器（IndexedDB），不会上传服务器，同房间其他人看不到。
      </p>
    </section>

    <!-- ---------- 氛围与可读性 ---------- -->
    <section class="block">
      <header class="block-head">
        <h3 class="block-title">
          <CocIcon name="palette" :size="16" />
          氛围与可读性
        </h3>
      </header>

      <div class="opt-row">
        <div class="opt-text">
          <p class="opt-name">背景氛围动效</p>
          <p class="opt-desc">两团缓慢漂浮的渐变光斑；演示机位配置较低时可关闭</p>
        </div>
        <el-switch :model-value="settings.ambience" @update:model-value="setAmbience" />
      </div>

      <div class="opt-row">
        <div class="opt-text">
          <p class="opt-name">界面动效</p>
          <p class="opt-desc">页面切换、消息入场、面板发光；关闭等于全局减少动效</p>
        </div>
        <el-switch :model-value="settings.motion" @update:model-value="setMotion" />
      </div>

      <div class="opt-row">
        <div class="opt-text">
          <p class="opt-name">面板发光强度</p>
          <p class="opt-desc">描边与悬停辉光的强弱</p>
        </div>
        <el-radio-group
          :model-value="settings.glowStrength"
          size="small"
          @update:model-value="setGlow"
        >
          <el-radio-button :value="0">关</el-radio-button>
          <el-radio-button :value="1">标准</el-radio-button>
          <el-radio-button :value="2">张扬</el-radio-button>
        </el-radio-group>
      </div>

      <div class="opt-row">
        <div class="opt-text">
          <p class="opt-name">字体大小</p>
          <p class="opt-desc">整站字号缩放，长文本跑团建议标准档</p>
        </div>
        <el-radio-group
          :model-value="settings.fontScale"
          size="small"
          @update:model-value="setFont"
        >
          <el-radio-button :value="0.9">小</el-radio-button>
          <el-radio-button :value="1">标准</el-radio-button>
          <el-radio-button :value="1.15">大</el-radio-button>
        </el-radio-group>
      </div>
    </section>

    <div class="footer-actions">
      <button type="button" class="ghost-btn" @click="onReset">
        <CocIcon name="refresh" :size="14" />
        恢复默认外观
      </button>
    </div>
  </div>
</template>

<style scoped>
.settings-panel {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-5);
}

.block {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-3);
  padding: var(--coc-sp-4);
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-lg);
  background: rgba(22, 32, 50, 0.62);
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-2);
}

.block-title {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin: 0;
  font-size: var(--coc-fs-base);
  color: var(--coc-text-strong);
}

.block-title .coc-icon-svg {
  color: var(--coc-accent);
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(104px, 1fr));
  gap: var(--coc-sp-3);
}

.preset {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: var(--coc-sp-2);
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: rgba(11, 18, 32, 0.5);
  color: var(--coc-text);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--coc-dur-fast) var(--coc-ease), box-shadow var(--coc-dur-fast) var(--coc-ease),
    transform var(--coc-dur-fast) var(--coc-ease);
}

.preset:hover:not(:disabled) {
  border-color: var(--coc-border-glow);
  box-shadow: var(--coc-glow);
  transform: translateY(-2px);
}

.preset--active {
  border-color: var(--coc-border-glow);
  box-shadow: inset 0 0 0 1px var(--coc-border-glow), var(--coc-glow);
}

.preset:disabled {
  cursor: progress;
  opacity: 0.7;
}

.preset-swatch {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 52px;
  border-radius: var(--coc-radius-sm);
  border: 1px solid var(--coc-border-soft);
  color: var(--coc-accent);
  background-size: cover;
  background-position: center;
}

.preset-swatch--image {
  background-color: rgba(11, 18, 32, 0.6);
}

.preset-name {
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-strong);
}

.preset-desc {
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.row-actions {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
}

.file-input {
  display: none;
}

.opt-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-4);
  padding: var(--coc-sp-2) 0;
  border-bottom: 1px dashed var(--coc-border-soft);
}

.opt-row:last-child {
  border-bottom: none;
}

.opt-text {
  min-width: 0;
}

.opt-name {
  margin: 0;
  font-size: var(--coc-fs-base);
  color: var(--coc-text);
}

.opt-desc {
  margin: 2px 0 0;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease), border-color var(--coc-dur-fast) var(--coc-ease);
}

.ghost-btn:hover {
  color: var(--coc-accent);
  border-color: var(--coc-border-glow);
}

.footer-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
