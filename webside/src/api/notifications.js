import http from './http'

// お知らせ通知（本地缓存 services/notification/v1/list）→ /mercariV2/src/use_web/notifications/*
export const notificationsApi = {
  list: (params) => http.get('/use_web/notifications', { params }),
  kinds: () => http.get('/use_web/notifications/kinds'),
  sync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/sync', data, { timeout: 0, ...axiosConfig }),
  markRead: (ids, is_read = true) =>
    http.post('/use_web/notifications/mark-read', { ids, is_read }),
  markAllRead: (account_id) =>
    http.post(
      '/use_web/notifications/mark-all-read',
      null,
      account_id ? { params: { account_id } } : undefined,
    ),
  // 合并购买请求（BundleRequestCreated）详情
  bundlePurchaseSync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/bundle-purchase/sync', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  bundlePurchaseDetail: (bundleId, params) =>
    http.get(`/use_web/notifications/bundle-purchase/${encodeURIComponent(bundleId)}`, {
      params,
    }),
  bundlePurchaseDecide: (bundleId, data, axiosConfig = {}) =>
    http.post(
      `/use_web/notifications/bundle-purchase/${encodeURIComponent(bundleId)}/decide`,
      data,
      { timeout: 0, ...axiosConfig },
    ),
  // 留言 (Comment) — 商品コメント
  itemCommentSync: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/sync', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  itemCommentPost: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/post', data, {
      timeout: 0,
      ...axiosConfig,
    }),
  itemCommentClose: (data, axiosConfig = {}) =>
    http.post('/use_web/notifications/item-comment/close', data, {
      timeout: 0,
      ...axiosConfig,
    }),
}
