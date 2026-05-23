import http from './http'

// 成本支出 → /mercariV2/src/use_web/cost-expenses/*
export const costExpenseApi = {
  list: (params) => http.get('/use_web/cost-expenses', { params }),
  create: (data) => http.post('/use_web/cost-expenses', data),
  update: (id, data) => http.put(`/use_web/cost-expenses/${id}`, data),
  remove: (id) => http.delete(`/use_web/cost-expenses/${id}`)
}
