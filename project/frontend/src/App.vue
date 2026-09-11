<script setup lang="ts">
/**
 * 应用根组件 — 阶段 6.2②：只挂全局外壳（顶栏/侧栏/背景/路由过渡）。
 * 具体页面布局由各视图负责，跳转入口由 AppSideNav 统一提供。
 */
import AppLayout from '@/layouts/AppLayout.vue'
</script>

<template>
  <AppLayout />
</template>
