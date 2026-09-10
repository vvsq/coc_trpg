import { createRouter, createWebHistory } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import HomeView from '../views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/about',
      name: 'about',
      // 路由级代码分割：访问 /about 时才加载此块
      component: () => import('../views/AboutView.vue'),
    },
    {
      path: '/cards',
      name: 'card-list',
      component: () => import('../views/CardListView.vue'),
    },
    {
      path: '/cards/new',
      name: 'card-create',
      component: () => import('../views/CardCreateView.vue'),
    },
    {
      // 房间页（玩家双栏）
      path: '/room/:id',
      name: 'room',
      component: () => import('../views/RoomView.vue'),
    },
    {
      // KP 三栏控制台（3.3）：仅 KP 可入，非 KP 在视图内被弹回 /room/:id
      path: '/room/:id/kp',
      name: 'kp-console',
      component: () => import('../views/KPConsoleView.vue'),
    },
    {
      // 放最后：静态段 /cards/new 优先级更高，避免 :id 抢占；顺序上仍建议静态在前
      path: '/cards/:id',
      name: 'card-detail',
      component: () => import('../views/CardDetailView.vue'),
    },
    {
      // 阶段 5：模组库（上传 / 解析 / 校对），KP 台挂载房间的模组在这里管理
      path: '/modules',
      name: 'module-list',
      component: () => import('../views/ModuleListView.vue'),
    },
    {
      path: '/modules/:id',
      name: 'module-detail',
      component: () => import('../views/ModuleDetailView.vue'),
    }
  ],
})

// 房间会话保护：从房间系路由离开到其他页面（顶部导航/后退）时弹确认，
// 防止误触导航静默断开 WS 错过剧情。房间系路由之间互跳（控制台⇄房间页
// 的守卫弹回）不拦截；退出房间走 quitRoom → exitRoom() 先清空会话，
// roomId 已空时守卫天然放行，不会出现二次确认。
const ROOM_ROUTE_NAMES = new Set(['room', 'kp-console'])

router.beforeEach(async (to, from) => {
  if (!ROOM_ROUTE_NAMES.has(from.name as string)) return true
  if (ROOM_ROUTE_NAMES.has(to.name as string)) return true
  const { useRoomStore } = await import('@/stores/room')
  const room = useRoomStore()
  if (!room.roomId) return true
  try {
    await ElMessageBox.confirm(
      '离开房间将断开连接，正在进行的团仍在继续，可凭房间号重新加入。确定离开？',
      '离开房间',
      { confirmButtonText: '离开', cancelButtonText: '留在房间', type: 'warning' },
    )
    return true
  } catch {
    return false // 用户留在房间
  }
})

export default router
