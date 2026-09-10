<script setup lang="ts">
/**
 * KP 台 · 模组选择面板 — 阶段 5.4。
 *
 * 一个房间同时只挂 1 个模组（用户决策 2026-09-10）：选中 → 挂载/解绑。
 * 只列「已就绪」的模组——未解析完的挂上去等于给 AI 一个空骨架。
 *
 * 状态来源：进面板时用 GET /rooms/{id} 的 module 字段做初次回显（服务端值），
 * 之后一切变更由 module_changed 全员广播驱动，**不在本地乐观更新**
 * （与 KpStylePanel 同款范式）。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listModules } from '@/api/modules'
import { getRoom, setRoomModule } from '@/api/rooms'
import { useRoomStore } from '@/stores/room'
import type { ModuleMeta } from '@/types/module'

const room = useRoomStore()
const router = useRouter()

const modules = ref<ModuleMeta[]>([])
const selected = ref<number | null>(null)
const loading = ref(false)
const switching = ref(false)

const readyModules = computed(() => modules.value.filter((m) => m.parse_status === 'ready'))
const current = computed(() => room.roomModule)
const pendingCount = computed(() => modules.value.length - readyModules.value.length)

/**
 * 首次回显必须等 roomId 就绪：父视图 KPConsoleView.onMounted 是异步的
 * （要先 await getRoom 做 KP 守卫校验），而子组件的 onMounted 早于它执行——
 * 那时 roomId 还是空串，立即请求会 404，面板永久停在"未挂载"（实测踩过）。
 * 因此用 watch immediate 等待 roomId 出现，换房时也会自动重载。
 */
watch(
  () => room.roomId,
  async (roomId: string) => {
    if (!roomId) return
    loading.value = true
    try {
      const [list, detail] = await Promise.all([listModules(), getRoom(roomId)])
      modules.value = list
      room.syncRoomModule(detail.module)
      selected.value = detail.module?.module_id ?? null
    } catch {
      // 错误提示由 axios 拦截器统一弹出
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

async function apply(): Promise<void> {
  switching.value = true
  try {
    await setRoomModule(room.roomId, room.playerName, selected.value)
    ElMessage.success(
      selected.value ? '已挂载模组，下一轮主持起生效' : '已解绑模组，回退默认骨架',
    )
  } catch {
    // 失败保持原选择，回显仍以服务端广播为准
  } finally {
    switching.value = false
  }
}
</script>

<template>
  <div v-loading="loading" class="module-panel">
    <el-select
      v-model="selected"
      size="small"
      class="sel"
      clearable
      placeholder="未挂载（使用默认骨架）"
    >
      <el-option v-for="m in readyModules" :key="m.id" :label="m.name" :value="m.id" />
    </el-select>

    <p class="cur">
      当前：
      <span v-if="current" class="cur-on">{{ current.module_name }}（已就绪）</span>
      <span v-else class="cur-off">未挂载 · 使用默认骨架</span>
    </p>

    <div class="acts">
      <el-button size="small" type="primary" :loading="switching" @click="apply">
        挂载 / 解绑
      </el-button>
      <!-- 带来源房间，模组库据此显示「返回 KP 控制台」；同属房间工作区，来回不拆连接 -->
      <el-button
        size="small"
        text
        type="primary"
        @click="router.push({ name: 'module-list', query: { from_room: room.roomId } })"
      >
        管理模组库
      </el-button>
    </div>

    <p class="hint">
      仅「已就绪」的模组可挂载
      <template v-if="pendingCount > 0">（还有 {{ pendingCount }} 个待解析）</template>
      ；挂载后 AI 会按模组的 NPC / 线索 / 时钟主持剧情。
    </p>
  </div>
</template>

<style scoped>
.module-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 60px;
}

.sel {
  width: 100%;
}

.cur {
  margin: 0;
  font-size: 12px;
  color: #909399;
}

.cur-on {
  color: #e6a23c;
}

.cur-off {
  color: #909399;
}

.acts {
  display: flex;
  align-items: center;
  gap: 8px;
}

.hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}
</style>
