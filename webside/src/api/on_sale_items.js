import http from './http'

// 在售商品（本地缓存 items/get_items）→ /mercariV2/src/use_web/on-sale-items/*
export const onSaleItemApi = {
  list: (params) => http.get('/use_web/on-sale-items', { params }),
  /** 按煤炉商品 ID 查本地 on_sale_items（二级表） */
  listByItemId: (params) => http.get('/use_web/on-sale-items/by-item-id', { params }),
  /** 按多个煤炉商品 ID 批量查本地 on_sale_items（逗号分隔） */
  listByItemIds: (params) => http.get('/use_web/on-sale-items/by-item-ids', { params }),
  sync: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/sync', data, { timeout: 0, ...axiosConfig }),
  /** items/get 详情并同步库存 mercari_item_id / on_sale_quantity；须配置 dpop_item_get_info */
  fetchDetail: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/fetch-detail', data, { timeout: 120000, ...axiosConfig }),
  /** 同一账号队列内串行批量 items/get（单 HTTP，服务端 run_meilu_serial 一次） */
  fetchDetailsBatch: (data, axiosConfig = {}) =>
    http.post('/use_web/on-sale-items/fetch-details-batch', data, { timeout: 0, ...axiosConfig })
}
