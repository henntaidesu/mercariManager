import http from './http'

/** Edge 持久化会话：按 account_key 隔离 Cookie → /mercariV2/src/use_web/web-drive/* */
export const webDriveApi = {
  openSession: (data, axiosConfig = {}) =>
    http.post('/use_web/web-drive/sessions/open', data, { timeout: 0, ...axiosConfig }),
  closeSession: (data) => http.post('/use_web/web-drive/sessions/close', data),
  listSessions: () => http.get('/use_web/web-drive/sessions'),
  profilesRoot: () => http.get('/use_web/web-drive/profiles-root'),
  /** WebDrive 打开编辑页并删除煤炉在售商品 */
  deleteMercariItem: (data, axiosConfig = {}) =>
    http.post('/use_web/web-drive/on-sale/delete-item', data, { timeout: 0, ...axiosConfig })
}

/**
 * 出品自动化：打开 Edge（SSL 中间人）→ 填写 Mercari 出品页 → /mercariV2/src/use_web/web-drive/listing/*
 *   account_key  webdrive 账号标识（通常 meilu_{id}）
 *   name         商品名称
 *   description  商品说明（含管理番号）
 *   image_urls   图片路径数组，如 ['/imges/xxx.jpg']
 *   use_mitm_proxy 是否启用 MITM 代理（默认 true）
 */
export const listingApi = {
  postToMarket: (data, axiosConfig = {}) =>
    http.post('/use_web/web-drive/listing/post-to-market', data, { timeout: 0, ...axiosConfig }),
  /** 与 postToMarket 的 progress_job_id 配合，轮询当前自动化步骤 */
  getPostProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_web/web-drive/listing/post-progress/${encodeURIComponent(jobId)}`, axiosConfig)
}
