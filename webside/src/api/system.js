import http from './http'

// 系统（重启服务等）→ /mercariV2/src/use_web/system/*
export const systemApi = {
  restart: () => http.post('/use_web/system/restart', {}, { timeout: 30000 })
}
