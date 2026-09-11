<script setup lang="ts">
/**
 * 全局应用外壳 — 阶段 6.2②；6.2⑩ 接入移动端底部导航。
 *
 * 结构：背景层（fixed）→ 顶栏（品牌/模式/设置）→ 左导航 + 主内容区 → 底部 Tab 导航。
 * 移动端（≤768px）：左导航隐藏（AppSideNav 自带媒体查询），底部 Tab 出现
 * （AppBottomNav 自带媒体查询），三者互不遮挡（同属 flex 纵向流）。
 * 主内容区用路由过渡（coc-route）承载 RouterView，视图本身不需要再关心
 * 顶栏高度或全局底色（历史遗留的 `calc(100vh - 55px)` 已随之清理）。
 *
 * 边界：外壳只读 store（room / settings），不写业务状态、不发业务请求。
 */
import { watch } from 'vue'
import { RouterView } from 'vue-router'
import AppBackground from '@/components/AppBackground.vue'
import { useSettingsStore } from '@/stores/settings'
import { setSfxEnabled } from '@/utils/sfx'
import AppTopBar from './AppTopBar.vue'
import AppSideNav from './AppSideNav.vue'
import AppBottomNav from './AppBottomNav.vue'

// 音效总开关的唯一绑定点：设置页只改 store，实际生效在这里（外壳常驻，刷新也立刻生效）
const { settings } = useSettingsStore()
watch(() => settings.sound, setSfxEnabled, { immediate: true })
</script>

<template>
  <div class="app-shell">
    <AppBackground />

    <div class="app-foreground">
      <AppTopBar />

      <div class="app-body">
        <AppSideNav />

        <main class="app-main">
          <RouterView v-slot="{ Component }">
            <Transition name="coc-route" mode="out-in">
              <component :is="Component" />
            </Transition>
          </RouterView>
        </main>
      </div>

      <AppBottomNav />
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  height: 100vh;
  /* 移动端地址栏收放时 100vh 会溢出：优先动态视口高度（不支持时回落 100vh） */
  height: 100dvh;
  overflow: hidden;
}

/* 内容层压在背景层之上；背景层是 fixed 且 pointer-events: none */
.app-foreground {
  position: relative;
  z-index: var(--coc-z-content);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.app-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

.app-main {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  /* 内容页超长时由这里滚动；全高页面（房间/KP 台）用 height:100% 填满即可 */
  overflow-y: auto;
  overflow-x: hidden;
}

@media (max-width: 1100px) {
  .app-body {
    /* 窄屏时主区仍可横向放下，侧栏自身已收窄 */
    min-width: 0;
  }
}
</style>
