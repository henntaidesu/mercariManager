import http from './http'

// 库存 → /mercariV2/src/use_web/inventory/*
export const inventoryApi = {
  list: (params) => http.get('/use_web/inventory', { params }),
  get: (id) => http.get(`/use_web/inventory/${id}`),
  pendingOutboundLines: (id) => http.get(`/use_web/inventory/${id}/pending-outbound-lines`),
  findByBarcode: (barcode) => http.get(`/use_web/inventory/barcode/${encodeURIComponent(barcode)}`),
  findByImage: (file) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'query.jpg')
    return http.post('/use_web/inventory/find-by-image', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 15000
    })
  },
  uploadImage: (file, onUploadProgress, signal) => {
    const fd = new FormData()
    fd.append('file', file, file?.name || 'inventory.jpg')
    return http.post('/use_web/inventory/upload-image', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
      onUploadProgress,
      signal
    })
  },
  create: (data) => http.post('/use_web/inventory', data),
  combine: (data) => http.post('/use_web/inventory/combine', data),
  update: (id, data) => http.put(`/use_web/inventory/${id}`, data),
  remove: (id) => http.delete(`/use_web/inventory/${id}`),
  stockIn: (id, data) => http.post(`/use_web/inventory/${id}/stock-in`, data),
  stockOut: (id, data) => http.post(`/use_web/inventory/${id}/stock-out`, data)
}
