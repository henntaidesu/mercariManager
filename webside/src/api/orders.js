import http from './http'

// 订单管理 → /mercariV2/src/use_web/orders/*
export const orderApi = {
  list: (params) => http.get('/use_web/orders', { params }),
  stats: (params) => http.get('/use_web/orders/stats', { params }),
  /** 订单展开：从说明解析的待出库明细（管理 ID、仓库等） */
  outboundLines: (params) => http.get('/use_web/orders/outbound-lines', { params }),
  /** 订单二级列表：未匹配库存的明细行手动关联 inventory_id */
  bindOutboundLineInventory: (lineId, data) =>
    http.patch(`/use_web/orders/outbound-lines/${lineId}/bind-inventory`, data),
  /** 订单二级列表：单行手动出库（已出库不可重复） */
  stockOutOutboundLine: (lineId, data = {}) =>
    http.post(`/use_web/orders/outbound-lines/${lineId}/stock-out`, data),
  /** 订单二级列表：手动新增出库明细（预扣库存并进入待出库） */
  addManualOutboundLine: (data) => http.post('/use_web/orders/outbound-lines/manual', data),
  /** 订单二级列表：手动批量新增出库明细（多选商品） */
  addManualOutboundLinesBatch: (data) => http.post('/use_web/orders/outbound-lines/manual/batch', data),
  create: (data) => http.post('/use_web/orders', data),
  update: (id, data) => http.put(`/use_web/orders/${id}`, data),
  remove: (id) => http.delete(`/use_web/orders/${id}`),
  /** 单行 items/get 刷新：传 order_no + data_user（卖家ID），与煤炉账号 seller_id 对应 */
  refreshInfo: (data, axiosConfig = {}) =>
    http.post('/use_web/orders/refresh-info', data, { timeout: 60000, ...axiosConfig }),
  /** 待评价/已完成：确认本单不使用包材 */
  waivePackaging: (data) => http.post('/use_web/orders/packaging-waive', data)
}
