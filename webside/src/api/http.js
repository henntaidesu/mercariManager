import axios from 'axios'
import { ElMessage } from 'element-plus'

/**
 * V2 API axios 实例
 * - baseURL 指向 /mercariV2/src，各 API 模块用 '/use_web/<resource>' 或 '/operation_mercari' 拼接
 * - 例: http.get('/use_web/inventory') → /mercariV2/src/use_web/inventory
 */
const http = axios.create({
  baseURL: '/mercariV2/src',
  timeout: 15000
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.code === 'ERR_CANCELED' || err.name === 'CanceledError') {
      return Promise.reject(err)
    }
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_user')
      if (window.location.hash !== '#/login') {
        window.location.hash = '#/login'
      }
    }
    const msg = err.response?.data?.detail || err.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

export default http
