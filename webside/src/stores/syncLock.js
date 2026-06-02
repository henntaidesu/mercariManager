import { defineStore } from 'pinia'
import { ref } from 'vue'
import { mercariApi } from '@/api'

/**
 * 全局同步锁状态（后端进程内共享）。任意页面订阅后会轮询后端：
 * 当有「自动同步」或用户发起的「全量同步」在进行时，locked=true，
 * 各页同步按钮据此禁用、转圈并提示 label（如「正在自动同步 / 正在全量同步」）。
 *
 * 跨刷新 / 跨用户一致：状态来自后端，刷新页面或其他用户登录都会读到同一状态。
 */
export const useSyncLockStore = defineStore('syncLock', () => {
  const locked = ref(false)
  const kind = ref(null)
  const label = ref('')

  let subscribers = 0
  let timer = null
  const POLL_MS = 2000

  async function refresh() {
    try {
      const res = await mercariApi.getSyncLock()
      const d = res?.data || {}
      locked.value = !!d.locked
      kind.value = d.kind || null
      label.value = d.label_zh || ''
    } catch {
      /* 轮询失败忽略，保持上一次状态 */
    }
  }

  function subscribe() {
    subscribers += 1
    if (timer == null) {
      refresh()
      timer = setInterval(refresh, POLL_MS)
    }
  }

  function unsubscribe() {
    subscribers = Math.max(0, subscribers - 1)
    if (subscribers === 0 && timer != null) {
      clearInterval(timer)
      timer = null
    }
  }

  return { locked, kind, label, refresh, subscribe, unsubscribe }
})
