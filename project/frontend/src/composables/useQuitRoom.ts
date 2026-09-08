/**
 * 退出房间确认流 — 3.3 从 RoomView 抽出，KP 控制台共用。
 *
 * KP 在等待中退出会询问是否解散（解散 = 房间/成员/消息全部清除）；
 * 开团中或玩家退出只断开连接，房间保留（KP 可用原名字重进，身份不变）。
 */
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { dissolveRoom, getRoom } from '@/api/rooms'
import { useRoomStore } from '@/stores/room'

export function useQuitRoom() {
  const router = useRouter()
  const room = useRoomStore()

  async function quitRoom(): Promise<void> {
    try {
      if (room.myRole === 'kp') {
        const detail = await getRoom(room.roomId)
        const dissolving = detail.status === 'waiting'
        await ElMessageBox.confirm(
          dissolving
            ? '你是 KP：等待中的房间退出后将解散，成员与聊天记录全部清空。确定退出？'
            : '你是 KP：开团中退出后房间保留，玩家可留在房内。确定退出？',
          '退出房间',
          { confirmButtonText: '退出', cancelButtonText: '取消', type: 'warning' },
        )
        if (dissolving) await dissolveRoom(room.roomId, room.playerName)
      } else {
        await ElMessageBox.confirm('确定退出房间？', '退出房间', {
          confirmButtonText: '退出',
          cancelButtonText: '取消',
          type: 'warning',
        })
      }
    } catch {
      return // 用户点取消
    }
    room.exitRoom()
    router.push('/')
  }

  return { quitRoom }
}
