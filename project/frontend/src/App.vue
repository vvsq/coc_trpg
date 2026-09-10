<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <header class="app-header">
    <h1>跑团辅助应用</h1>
    <nav>
      <RouterLink to="/">首页</RouterLink>
      <RouterLink to="/cards">角色卡</RouterLink>
      <RouterLink to="/cards/new">建卡</RouterLink>
      <RouterLink to="/modules">模组</RouterLink>
      <RouterLink to="/about">关于</RouterLink>
    </nav>
  </header>

  <main>
    <RouterView />
  </main>
</template>

<style scoped>
/* 全局导航：克苏鲁暗夜蓝，与大厅/房间页同一主题 */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 54px;
  padding: 0 24px;
  background: #151c26;
  border-bottom: 1px solid #2c3e50;
  box-sizing: border-box;
}

.app-header h1 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  color: #e8eaed;
  letter-spacing: 1px;
}

nav a {
  margin: 0 12px;
  padding: 4px 2px;
  font-size: 14px;
  color: #909399;
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}

nav a:hover {
  color: #e8eaed;
}

nav a.router-link-active {
  color: #e6a23c;
  border-color: #e6a23c;
}
</style>

<style>
/* 非 scoped：旧页面（卡片系列）大多假设白底黑字，统一兜底全局底色 */
body {
  margin: 0;
  background: #1b2431;
}
</style>
