import http from './http'

// 仓库 → /mercariV2/src/use_web/warehouses/*
export const warehouseApi = {
  list: () => http.get('/use_web/warehouses'),
  create: (data) => http.post('/use_web/warehouses', data),
  update: (id, data) => http.put(`/use_web/warehouses/${id}`, data),
  remove: (id) => http.delete(`/use_web/warehouses/${id}`),
  /** 批量修改同一仓库展示名（其下所有货架位的 warehouse 字段） */
  renameGroup: (data) => http.put('/use_web/warehouses/rename-group', data),
  /** 同一仓库下批量修改 shelf_name 分组名称 */
  renameShelfNameGroup: (data) => http.put('/use_web/warehouses/rename-shelf-name-group', data),
  /** 将该货架位上全部库存改到目标货架位（warehouses.id） */
  migrateInventory: (fromId, data) => http.post(`/use_web/warehouses/${fromId}/migrate-inventory`, data)
}
