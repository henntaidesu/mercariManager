import http from './http'

// 分类 → /mercariV2/src/use_web/categories/*
export const categoryApi = {
  list: () => http.get('/use_web/categories'),
  create: (data) => http.post('/use_web/categories', data),
  update: (id, data) => http.put(`/use_web/categories/${id}`, data),
  remove: (id) => http.delete(`/use_web/categories/${id}`)
}
