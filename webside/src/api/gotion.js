import http from './http'

// Gotion 表格管理 → /mercariV2/src/use_web/gotion/*
export const gotionApi = {
  // ── Tables ──────────────────────────────────────────────
  /** 顶级表列表（含 children 子表） */
  listTables: () => http.get('/use_web/gotion/tables'),
  /** 新建表（parent_id 为空表示顶级表） */
  createTable: (data) => http.post('/use_web/gotion/tables', data),
  /** 单表详情（含列定义） */
  getTable: (id) => http.get(`/use_web/gotion/tables/${id}`),
  /** 更新表（名称/图标/父级） */
  updateTable: (id, data) => http.put(`/use_web/gotion/tables/${id}`, data),
  /** 删除表（连同子表/列/行） */
  deleteTable: (id) => http.delete(`/use_web/gotion/tables/${id}`),
  /** 表排序 */
  reorderTables: (items) => http.patch('/use_web/gotion/tables/reorder', { items }),

  // ── Columns ─────────────────────────────────────────────
  listColumns: (tableId) => http.get(`/use_web/gotion/tables/${tableId}/columns`),
  createColumn: (tableId, data) => http.post(`/use_web/gotion/tables/${tableId}/columns`, data),
  updateColumn: (tableId, colId, data) => http.put(`/use_web/gotion/tables/${tableId}/columns/${colId}`, data),
  deleteColumn: (tableId, colId) => http.delete(`/use_web/gotion/tables/${tableId}/columns/${colId}`),
  reorderColumns: (tableId, items) => http.patch(`/use_web/gotion/tables/${tableId}/columns/reorder`, { items }),

  // ── Rows ────────────────────────────────────────────────
  listRows: (tableId, params) => http.get(`/use_web/gotion/tables/${tableId}/rows`, { params }),
  createRow: (tableId, data) => http.post(`/use_web/gotion/tables/${tableId}/rows`, data),
  updateRow: (tableId, rowId, data) => http.put(`/use_web/gotion/tables/${tableId}/rows/${rowId}`, data),
  deleteRow: (tableId, rowId) => http.delete(`/use_web/gotion/tables/${tableId}/rows/${rowId}`),

  // ── Import ──────────────────────────────────────────────
  /** CSV / Excel 导入（multipart） */
  importFromFile: (tableId, file, hasHeader = true) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('has_header', hasHeader)
    return http.post(`/use_web/gotion/tables/${tableId}/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
}
