import http from './http'

// Mercari 操作 → /mercariV2/src/use_mercari/*（注意：不在 use_web 下）
export const mercariApi = {
  /** 「获取历史数据」前置校验：orders 是否已有该卖家 data_user 数据 */
  historySyncPrecheck: (params) =>
    http.get('/use_mercari/history-sync-precheck', { params }),
  /** 同步订单：默认不设置超时（一直等到服务端返回）。axiosConfig 可覆盖，例如 { timeout: 60000 } */
  syncOrders: (data, axiosConfig = {}) =>
    http.post('/use_mercari/sync-orders', data, { timeout: 0, ...axiosConfig }),
  /** 订单页增量更新：仅入库列表中尚未存在的出售中单 */
  syncNewData: (data, axiosConfig = {}) =>
    http.post('/use_mercari/sync-new-data', data, { timeout: 0, ...axiosConfig }),
  /** 批量 items/get：库内未完成订单 + data_user，与列表「刷新」相同逻辑 */
  batchRefreshInfo: (data, axiosConfig = {}) =>
    http.post('/use_mercari/batch-refresh-info', data, { timeout: 0, ...axiosConfig }),
  /** 与 syncNewData / batchRefreshInfo 的 progress_job_id 配合，轮询当前同步步骤 */
  getSyncProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_mercari/sync-progress/${encodeURIComponent(jobId)}`, axiosConfig),
  /** 全局同步锁状态：是否有同步（自动/全量）在进行，供各页禁用同步按钮 */
  getSyncLock: (axiosConfig = {}) =>
    http.get('/use_mercari/sync-lock', axiosConfig)
}
