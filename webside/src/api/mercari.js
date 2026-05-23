import http from './http'

// Mercari 操作 → /mercariV2/src/operation_mercari/*（注意：不在 use_web 下）
export const mercariApi = {
  /** 「获取历史数据」前置校验：orders 是否已有该卖家 data_user 数据 */
  historySyncPrecheck: (params) =>
    http.get('/operation_mercari/history-sync-precheck', { params }),
  /** 同步订单：默认不设置超时（一直等到服务端返回）。axiosConfig 可覆盖，例如 { timeout: 60000 } */
  syncOrders: (data, axiosConfig = {}) =>
    http.post('/operation_mercari/sync-orders', data, { timeout: 0, ...axiosConfig }),
  /** 订单页增量更新：仅入库列表中尚未存在的出售中单 */
  syncNewData: (data, axiosConfig = {}) =>
    http.post('/operation_mercari/sync-new-data', data, { timeout: 0, ...axiosConfig }),
  /** 批量 items/get：库内未完成订单 + data_user，与列表「刷新」相同逻辑 */
  batchRefreshInfo: (data, axiosConfig = {}) =>
    http.post('/operation_mercari/batch-refresh-info', data, { timeout: 0, ...axiosConfig })
}
