import http from './http'

// 出入库 → /mercariV2/src/use_web/transactions/*
export const transactionApi = {
  list: (params) => http.get('/use_web/transactions', { params }),
  create: (data) => http.post('/use_web/transactions', data)
}
