import http from './http'

// 成本记录 → /mercariV2/src/use_web/cost-records/*
export const costRecordApi = {
  list: (params) => http.get('/use_web/cost-records', { params }),
  listPackagingItems: () => http.get('/use_web/cost-records/packaging-items'),
  create: (data) => http.post('/use_web/cost-records', data),
  update: (id, data) => http.put(`/use_web/cost-records/${id}`, data),
  remove: (id) => http.delete(`/use_web/cost-records/${id}`),
  uploadImage: (file) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'cost.jpg')
    return http.post('/use_web/cost-records/upload-image', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 15000
    })
  }
}
