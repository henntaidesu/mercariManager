import http from './http'

// 煤炉账号 → /mercariV2/src/use_web/meilu-accounts/*
export const meiluAccountApi = {
  list: (params) => http.get('/use_web/meilu-accounts', { params }),
  create: (data) => http.post('/use_web/meilu-accounts', data),
  update: (id, data) => http.put(`/use_web/meilu-accounts/${id}`, data),
  remove: (id) => http.delete(`/use_web/meilu-accounts/${id}`),
  /** MITM 抓取 items/get_items(trading) 请求头并写回账号（可能较久，timeout: 0） */
  fetchAuthViaMitm: (id, axiosConfig = {}) =>
    http.post(`/use_web/meilu-accounts/${id}/fetch-auth-via-mitm`, {}, { timeout: 0, ...axiosConfig }),
  /**
   * 打开出品一覧页，MITM 截获 items/get_items（on_sale,stop）并解析 seller_id。
   * account_key: meilu_prepare（新增）或 meilu_{id}（编辑）
   */
  fetchSellerIdViaMitm: (data, axiosConfig = {}) =>
    http.post('/use_web/meilu-accounts/fetch-seller-id-via-mitm', data, { timeout: 0, ...axiosConfig })
}
