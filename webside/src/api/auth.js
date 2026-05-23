import http from './http'

// 认证 → /mercariV2/src/use_web/auth/*
export const authApi = {
  login: (data) => http.post('/use_web/auth/login', data),
  listUsers: () => http.get('/use_web/auth/users'),
  createUser: (data) => http.post('/use_web/auth/users', data),
  changePassword: (data) => http.post('/use_web/auth/change-password', data)
}
