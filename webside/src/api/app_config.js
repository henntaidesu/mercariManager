import http from './http'

// 应用配置（系统页：出品默认值等）→ /mercariV2/src/use_web/app-config/*
export const configApi = {
  getListingDefaults: () => http.get('/use_web/app-config/listing-defaults'),
  putListingDefaults: (data) => http.put('/use_web/app-config/listing-defaults', data)
}
