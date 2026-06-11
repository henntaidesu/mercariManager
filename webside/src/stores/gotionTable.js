import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { gotionApi } from '@/api'

const STORAGE_KEY = 'gotion.last_table_id'

function readPersisted() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw == null || raw === '') return null
    const n = Number(raw)
    return Number.isFinite(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

function writePersisted(id) {
  try {
    if (id == null || id === '') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
  } catch { /* ignore quota / disabled storage */ }
}

// 错误提示统一由 api/http.js 拦截器弹出，store 内只负责吞掉异常保持 UI 流程
export const useGotionTableStore = defineStore('gotionTable', () => {
  // 顶级表列表（含 children 数组）
  const topTables = ref([])
  // 当前打开的表 ID
  const currentTableId = ref(null)
  // 当前表的列
  const columns = ref([])
  // 当前表的行
  const rows = ref([])
  // 加载状态
  const loading = ref(false)

  // 扁平化所有表（顶级 + 子表）用于快速查找
  const allTables = computed(() => {
    const result = []
    for (const t of topTables.value) {
      result.push({ ...t, children: undefined })
      if (t.children) {
        for (const c of t.children) {
          result.push(c)
        }
      }
    }
    return result
  })

  const currentTable = computed(() => allTables.value.find(t => t.id === currentTableId.value) || null)

  // ── 加载所有表 ──────────────────────────────────────────
  async function fetchTables() {
    try {
      topTables.value = await gotionApi.listTables()
    } catch { /* http.js 已提示 */ }
  }

  // ── 恢复上次选中的表（localStorage），否则选第一张 ───────
  async function restoreSelection() {
    const persisted = readPersisted()
    const exists = persisted != null && allTables.value.some(t => t.id === persisted)
    const target = exists ? persisted : (allTables.value[0]?.id ?? null)
    if (target != null) await switchTable(target)
  }

  // ── 切换当前表 ──────────────────────────────────────────
  async function switchTable(tableId) {
    if (currentTableId.value === tableId) return
    currentTableId.value = tableId
    writePersisted(tableId)
    columns.value = []
    rows.value = []
    await loadTableData(tableId)
  }

  async function loadTableData(tableId) {
    loading.value = true
    try {
      const [cols, rws] = await Promise.all([
        gotionApi.listColumns(tableId),
        gotionApi.listRows(tableId),
      ])
      // 快速切表时旧请求可能后到，丢弃已过期的响应
      if (currentTableId.value !== tableId) return
      columns.value = cols
      rows.value = rws
    } catch { /* http.js 已提示 */ } finally {
      loading.value = false
    }
  }

  // ── 新建表 ──────────────────────────────────────────────
  async function addTable(name, icon = '', parentId = null) {
    try {
      const t = await gotionApi.createTable({ name, icon, parent_id: parentId })
      await fetchTables()
      return t
    } catch {
      return null
    }
  }

  // ── 更新表 ──────────────────────────────────────────────
  async function updateTableMeta(id, data) {
    try {
      const updated = await gotionApi.updateTable(id, data)
      await fetchTables()
      return updated
    } catch {
      return null
    }
  }

  // ── 移动表（改变父级） ──────────────────────────────────
  async function moveTable(id, newParentId) {
    try {
      await gotionApi.updateTable(id, { parent_id: newParentId })
      await fetchTables()
      return true
    } catch {
      return false
    }
  }

  // ── 删除表 ──────────────────────────────────────────────
  async function removeTable(id) {
    try {
      await gotionApi.deleteTable(id)
      await fetchTables()
      if (currentTableId.value === id) {
        currentTableId.value = allTables.value[0]?.id || null
        writePersisted(currentTableId.value)
        if (currentTableId.value) await loadTableData(currentTableId.value)
        else { columns.value = []; rows.value = [] }
      }
    } catch { /* http.js 已提示 */ }
  }

  // ── 新建列 ──────────────────────────────────────────────
  async function addColumn(tableId, colData) {
    try {
      const col = await gotionApi.createColumn(tableId, colData)
      columns.value.push(col)
      return col
    } catch {
      return null
    }
  }

  // ── 更新列 ──────────────────────────────────────────────
  async function updateCol(tableId, colId, data) {
    try {
      const updated = await gotionApi.updateColumn(tableId, colId, data)
      const idx = columns.value.findIndex(c => c.id === colId)
      if (idx !== -1) columns.value[idx] = updated
      return updated
    } catch {
      return null
    }
  }

  // ── 删除列 ──────────────────────────────────────────────
  async function removeColumn(tableId, colId) {
    try {
      await gotionApi.deleteColumn(tableId, colId)
      columns.value = columns.value.filter(c => c.id !== colId)
    } catch { /* http.js 已提示 */ }
  }

  // ── 新建行 ──────────────────────────────────────────────
  async function addRow(tableId, data = {}) {
    try {
      const row = await gotionApi.createRow(tableId, { data })
      rows.value.push(row)
      return row
    } catch {
      return null
    }
  }

  // ── 更新行 ──────────────────────────────────────────────
  async function updateRow(tableId, rowId, data) {
    try {
      const updated = await gotionApi.updateRow(tableId, rowId, { data })
      const idx = rows.value.findIndex(r => r.id === rowId)
      if (idx !== -1) rows.value[idx] = updated
      return updated
    } catch {
      return null
    }
  }

  // ── 删除行 ──────────────────────────────────────────────
  async function removeRow(tableId, rowId) {
    try {
      await gotionApi.deleteRow(tableId, rowId)
      rows.value = rows.value.filter(r => r.id !== rowId)
    } catch { /* http.js 已提示 */ }
  }

  return {
    topTables, currentTableId, columns, rows, loading,
    allTables, currentTable,
    fetchTables, restoreSelection, switchTable, loadTableData,
    addTable, updateTableMeta, removeTable, moveTable,
    addColumn, updateCol, removeColumn,
    addRow, updateRow, removeRow,
  }
})
