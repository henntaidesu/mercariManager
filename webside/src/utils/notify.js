/**
 * 统一提示入口（替代 element-plus 的 ElMessage 居中提示）
 *
 * - 改为右侧卡片拉出提示（ElNotification，position: top-right）。
 * - 每条提示同时上报后端「操作日志」(category='operation')，由后端从登录令牌识别用户。
 *
 * 用法与 ElMessage 完全一致，调用点无需改动：
 *   import { ElMessage } from '@/utils/notify'
 *   ElMessage.success('xxx'); ElMessage.error('xxx'); ElMessage({ message, type })
 */
import { ElNotification } from 'element-plus'
import i18n from '@/i18n'

// ElMessage 类型 → ElNotification 类型（一致）；info 归一到 'info'
const TITLE_KEYS = {
  success: 'common.success',
  warning: 'common.warning',
  error: 'common.error',
  info: 'common.tip'
}

function levelTitle(type) {
  try {
    return i18n.global.t(TITLE_KEYS[type] || 'common.tip')
  } catch {
    return ''
  }
}

function extractText(arg) {
  if (arg == null) return ''
  if (typeof arg === 'string') return arg
  if (typeof arg === 'object') return arg.message != null ? String(arg.message) : ''
  return String(arg)
}

// 上报操作日志：fetch 直连，绕开 axios 拦截器，避免「提示 → 失败 → 再提示」递归
function logOperation(level, message) {
  const msg = (message || '').toString().trim()
  if (!msg) return
  let token = null
  try {
    token = localStorage.getItem('auth_token')
  } catch {
    token = null
  }
  if (!token) return // 未登录不记录
  try {
    fetch('/mercariV2/src/use_web/system/operation-logs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ level, message: msg }),
      keepalive: true
    }).catch(() => {})
  } catch {
    // 记日志失败不影响页面
  }
}

// 上报结构化日志（带 detail / category / account_id）：fetch 直连绕开 axios 拦截器，
// best-effort，记日志失败绝不打扰用户。供「出品成功后记录提交信息」等场景使用。
function reportLog({ level = 'info', message = '', detail = null, category = 'operation', account_id = null } = {}) {
  let token = null
  try {
    token = localStorage.getItem('auth_token')
  } catch {
    token = null
  }
  if (!token) return // 未登录不记录
  try {
    fetch('/mercariV2/src/use_web/system/operation-logs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`
      },
      body: JSON.stringify({ level, message, detail, category, account_id }),
      keepalive: true
    }).catch(() => {})
  } catch {
    // 记日志失败不影响页面
  }
}

// 同一条提示（type + message）在展示期间去重：并发请求失败时只弹一次。
const activeNotifyKeys = new Set()

function show(defaultType, arg) {
  const isObj = arg && typeof arg === 'object'
  const type = (isObj && arg.type) || defaultType
  const message = extractText(arg)
  const duration = isObj && arg.duration != null ? arg.duration : 3000
  const key = `${type}|${message}`
  // 屏幕上已有同一条提示时，忽略重复（含重复的操作日志上报）
  if (activeNotifyKeys.has(key)) return
  activeNotifyKeys.add(key)
  ElNotification({
    type,
    title: (isObj && arg.title) || levelTitle(type),
    message,
    position: 'top-right',
    duration,
    onClose: () => activeNotifyKeys.delete(key)
  })
  logOperation(type, message)
}

function ElMessage(arg) {
  show('info', arg)
}
ElMessage.success = (arg) => show('success', arg)
ElMessage.warning = (arg) => show('warning', arg)
ElMessage.error = (arg) => show('error', arg)
ElMessage.info = (arg) => show('info', arg)

export { ElMessage, reportLog }
export default ElMessage
