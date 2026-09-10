/**
 * 模组库的「返回」语义（2026-09-10 用户反馈 #2）。
 *
 * 问题：KP 从控制台点「管理模组库」进来后是条死路——没有返回按钮，只能用浏览器
 * 后退，而且后退还会弹「离开房间」确认；重新从大厅加入又要重走一遍。
 *
 * 现在：跳转时带上 `from_room`，模组页顶栏据此显示「返回 KP 控制台」（带来源时）
 * 或「返回大厅」。模组库已并入房间工作区（见 router 的 ROOM_SCOPE_ROUTE_NAMES），
 * 因此来回跳不会拆连接；只有真正离开工作区（如回大厅）时，才在这里把还挂着的
 * 房间连接收尾，避免连接泄漏。
 */
import { computed, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ROOM_SCOPE_ROUTE_NAMES } from '@/router'
import { useRoomStore } from '@/stores/room'

export function useRoomReturn() {
  const route = useRoute()
  const router = useRouter()
  const room = useRoomStore()

  /** 来源房间号（从 KP 台跳来时带 ?from_room=xxx） */
  const fromRoom = computed(() => String(route.query.from_room ?? ''))

  /**
   * 有来源房间，且「当前会话就是它」或「本机存有该房间的身份」→ 返回控制台。
   *
   * 第二种兜底是给「在模组页刷新/新标签页直接打开」用的：Pinia store 是内存态，
   * 刷新后 roomId 为空，但 localStorage 里仍有身份；此时回控制台的 onMounted
   * 会用 peekIdentity 恢复身份，所以按钮该给「返回 KP 控制台」而不是「返回大厅」。
   */
  const canReturnToRoom = computed(
    () => !!fromRoom.value
      && (room.roomId === fromRoom.value || !!room.peekIdentity(fromRoom.value)),
  )
  const returnLabel = computed(() => (canReturnToRoom.value ? '返回 KP 控制台' : '返回大厅'))

  function goBack(): void {
    if (canReturnToRoom.value) {
      router.push({ name: 'kp-console', params: { id: fromRoom.value } })
      return
    }
    router.push({ name: 'home' })
  }

  /** 带来源房间的 query，跳详情页时透传，保证详情页也有「返回控制台」 */
  function carryQuery(): Record<string, string> {
    return fromRoom.value ? { from_room: fromRoom.value } : {}
  }

  onUnmounted(() => {
    // 回大厅等「非工作区」路由：控制台卸载时没拆（它以为模组库会接管），这里补拆
    const toName = String(router.currentRoute.value.name ?? '')
    if (room.roomId && !ROOM_SCOPE_ROUTE_NAMES.has(toName)) room.leaveRoom()
  })

  return { fromRoom, canReturnToRoom, returnLabel, goBack, carryQuery }
}
