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
    http.post('/use_web/web-drive/on-sale/delete-item', data, { timeout: 0, ...axiosConfig }),
  /** WebDrive 打开编辑页并提交修改（标题 / 价格 / 商品说明） */
  reviseMercariItem: (data, axiosConfig = {}) =>
    http.post('/use_web/web-drive/on-sale/revise-item', data, { timeout: 0, ...axiosConfig }),
  /** WebDrive 打开编辑页并点击「出品を再開する」恢复出售（仅暂停出售状态适用） */
  resumeMercariItem: (data, axiosConfig = {}) =>
    http.post('/use_web/web-drive/on-sale/resume-item', data, { timeout: 0, ...axiosConfig }),
  /** WebDrive 打开编辑页并点击「出品を一時停止する」暂停出售（仅出售中状态适用） */
  suspendMercariItem: (data, axiosConfig = {}) =>
    http.post('/use_web/web-drive/on-sale/suspend-item', data, { timeout: 0, ...axiosConfig })
}

/**
 * 出品自动化：打开 Edge（SSL 中间人）→ 填写 Mercari 出品页 → /mercariV2/src/use_web/web-drive/listing/*
 *   account_key  webdrive 账号标识（通常 mercari_{id}）
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
