import http from './http'

// 游戏类型 → /mercariV2/src/use_web/product-types/*
export const productTypeApi = {
  list: () => http.get('/use_web/product-types'),
  create: (data) => http.post('/use_web/product-types', data),
  update: (id, data) => http.put(`/use_web/product-types/${id}`, data),
  remove: (id) => http.delete(`/use_web/product-types/${id}`)
}

// 游戏类型与类别字段映射 → /mercariV2/src/use_web/product-type-category-mappings/*
export const productTypeCategoryMappingApi = {
  list: () => http.get('/use_web/product-type-category-mappings'),
  create: (data) => http.post('/use_web/product-type-category-mappings', data),
  update: (id, data) => http.put(`/use_web/product-type-category-mappings/${id}`, data),
  remove: (id) => http.delete(`/use_web/product-type-category-mappings/${id}`)
}
