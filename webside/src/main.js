import './resumeGuard.js'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import i18n, { elementLocales, currentLocale } from './i18n'
import { configApi } from './api/index.js'
import { setCipherMode } from './utils/mgmtIdCipher.js'

document.documentElement.classList.add('dark')

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(i18n)
app.use(ElementPlus, { locale: elementLocales[currentLocale.value] || elementLocales['zh-CN'] })
app.mount('#app')

// 启动时拉取管理番号暗号编码模式（需登录态；隐藏页 /x9 可切换）。默认 base5，失败静默。
if (localStorage.getItem('auth_token')) {
  configApi
    .getMgmtCipherMode()
    .then((res) => {
      if (res?.mode) setCipherMode(res.mode)
    })
    .catch(() => {})
}
