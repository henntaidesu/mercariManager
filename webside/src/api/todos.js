import http from './http'

// 待办事项（本地缓存 services/todolist/v1/list）→ /mercariV2/src/use_web/todos/*
export const todosApi = {
  list: (params) => http.get('/use_web/todos', { params }),
  kinds: () => http.get('/use_web/todos/kinds'),
  /** 「発送をしてください」处理：按商品 ID 反查本地库存（图片）与关联订单号 */
  matchInventory: (itemId, axiosConfig = {}) =>
    http.get('/use_web/todos/inventory-match', { params: { item_id: itemId }, ...axiosConfig }),
  sync: (data, axiosConfig = {}) =>
    http.post('/use_web/todos/sync', data, { timeout: 0, ...axiosConfig }),
  /** 与 sync 的 progress_job_id 配合，轮询当前同步步骤 */
  getSyncProgress: (jobId, axiosConfig = {}) =>
    http.get(`/use_web/todos/sync-progress/${encodeURIComponent(jobId)}`, axiosConfig),
  /** 处理按钮：打开浏览器到 transaction 页并抓取 DOM 字段 */
  fetchTransactionDetail: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/transaction-detail`, body || {}, { timeout: 0, ...axiosConfig }),
  /** 关闭交易详情 dialog 时关掉对应账号的 __auto 浏览器（fire-and-forget） */
  closeDetailBrowser: (accountId, axiosConfig = {}) =>
    http.post(`/use_web/todos/close-detail-browser/${encodeURIComponent(accountId)}`, {}, { timeout: 0, ...axiosConfig }),
  /** 在已开浏览器内填回复并点击「取引メッセージを送る」 */
  sendTransactionMessage: (todoId, text, opts = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/send-message`, { text, ...opts }, { timeout: 60000, ...axiosConfig }),
  /** 对买家某条消息发送 emoji 反应（reaction_index = 在 is_buyer 消息中的索引） */
  sendMessageReaction: (todoId, payload, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/send-reaction`, payload, { timeout: 60000, ...axiosConfig }),
  /** 在已开浏览器（取引評価页）填评价并点击「購入者を評価して取引完了する」 */
  submitTransactionReview: (todoId, text, opts = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/submit-review`, { text, ...opts }, { timeout: 60000, ...axiosConfig }),
  /** 点「商品サイズと発送場所を選択する」→ 抓 shipping_classes → 返回可选项 */
  startShippingClass: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/start`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 提交所选 size+facility：浏览器内完成全套点击（ゆうパケットポスト系传 scan_qr=true 完了后自动打开二维码扫描页） */
  confirmShippingSelection: (todoId, data, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/confirm`, data, { timeout: 60000, ...axiosConfig }),
  /** QR 扫描页镜像：抓取有头浏览器当前标签页一帧（base64 JPEG）+ 完成状态 */
  qrScannerFrame: (todoId, axiosConfig = {}) =>
    http.get(`/use_web/todos/${encodeURIComponent(todoId)}/qr-scanner-frame`, { timeout: 20000, ...axiosConfig }),
  /** QR 读取成功后读取「発送確認符号 / 追跡番号」供二次确认 */
  postShippingInfo: (todoId, axiosConfig = {}) =>
    http.get(`/use_web/todos/${encodeURIComponent(todoId)}/post-shipping-info`, { timeout: 30000, ...axiosConfig }),
  /** 用户二次确认后：勾选シール → 发送通知 → 「発送しました」 */
  finalizePostShipping: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/finalize-post-shipping`, body || {}, { timeout: 60000, ...axiosConfig }),
  /** 点「発送方法を変更する」（仅导航，后续由用户在浏览器内手动） */
  changeShippingMethod: (todoId, body = {}, axiosConfig = {}) =>
    http.post(`/use_web/todos/${encodeURIComponent(todoId)}/shipping/change-method`, body || {}, { timeout: 60000, ...axiosConfig })
}
