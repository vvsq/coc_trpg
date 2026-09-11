import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

/**
 * 样式引入顺序不可调换（阶段 6.2①）：
 * EP 基础样式 → EP 官方暗色变量 → 设计令牌 → 全局映射（覆盖 EP 变量） → 动效库
 */
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './assets/styles/tokens.css'
import './assets/styles/global.css'
import './assets/styles/animations.css'

import App from './App.vue'
import router from './router'

// EP 的暗色变量挂在 `html.dark` 上，必须显式加类（index.html 不写死，便于将来做亮色切换）
document.documentElement.classList.add('dark')

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
