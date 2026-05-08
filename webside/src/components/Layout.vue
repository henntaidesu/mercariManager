<template>
  <el-container class="layout-container" direction="horizontal" :class="{ 'layout--mobile': isMobile }">
    <!-- 手机：遮罩 / 菜单按钮挂到 body，避免父级 transform 导致 fixed 失效、被内容盖住 -->
    <Teleport to="body">
      <div
        v-if="isMobile && mobileDrawerOpen"
        class="layout-mobile-mask"
        @click="mobileDrawerOpen = false"
      />
    </Teleport>
    <Teleport to="body">
      <button
        v-if="isMobile && !mobileDrawerOpen"
        type="button"
        class="layout-mobile-fab"
        aria-label="打开菜单"
        aria-expanded="false"
        @click="mobileDrawerOpen = true"
      >
        <el-icon :size="22"><Menu /></el-icon>
      </button>
    </Teleport>

    <!-- 手机端挂到 body：避免任意祖先 transform 导致侧栏 fixed 错位，保证从左缘滑入 -->
    <Teleport to="body" :disabled="!isMobile">
      <el-aside
        width="220px"
        class="sidebar"
        :class="{
          'sidebar--mobile': isMobile,
          'sidebar--drawer-open': isMobile && mobileDrawerOpen,
        }"
      >
      <div class="sidebar-inner">
        <div class="logo-area">
          <img
            class="logo-image"
            src="/static/mercari.png"
            alt="mercari 订单管理"
          />
          <span class="logo-text">mercari 订单管理</span>
          <el-button
            v-if="isMobile"
            text
            class="sidebar-close-btn"
            @click="mobileDrawerOpen = false"
          >
            <el-icon :size="18"><Close /></el-icon>
          </el-button>
        </div>
        <div class="sidebar-menu-wrap">
          <el-menu
            :default-active="$route.path"
            :collapse="false"
            router
            background-color="#001529"
            text-color="#a6adb4"
            active-text-color="#ffffff"
            @select="onMenuSelect"
          >
            <el-menu-item v-for="item in menuItems" :key="item.path" :index="item.path">
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </el-menu>
        </div>
        <div class="sidebar-footer">
          <div class="sidebar-footer-row">
            <div class="sidebar-footer-user" :title="userName">{{ userName }}</div>
            <el-button class="sidebar-logout-btn" type="danger" plain size="small" @click="handleLogout">
              退出
            </el-button>
          </div>
        </div>
      </div>
    </el-aside>
    </Teleport>

    <el-main class="main-content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Menu, Close } from '@element-plus/icons-vue'

const router = useRouter()
const isMobile = ref(false)
/** 仅手机端：抽屉侧栏是否打开；电脑端忽略 */
const mobileDrawerOpen = ref(false)

/** 与库存页等一致：(max-width: 768px)，避免 768px 宽度下 Layout/页面判断不一致 */
let mqMobile = null

function syncMobileFromMedia() {
  if (typeof window === 'undefined' || !mqMobile) return
  const next = mqMobile.matches
  isMobile.value = next
  if (!next) {
    mobileDrawerOpen.value = false
  }
}

function onMenuSelect() {
  if (isMobile.value) {
    mobileDrawerOpen.value = false
  }
}

onMounted(() => {
  mqMobile = window.matchMedia('(max-width: 768px)')
  syncMobileFromMedia()
  mqMobile.addEventListener('change', syncMobileFromMedia)
})
onUnmounted(() => {
  mqMobile?.removeEventListener('change', syncMobileFromMedia)
})

const userName = computed(() => {
  try {
    const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
    return u.display_name || u.username || '用户'
  } catch {
    return '用户'
  }
})

const menuItems = [
  { path: '/dashboard', title: '控制台', icon: 'Odometer' },
  { path: '/inventory', title: '库存管理', icon: 'Goods' },
  { path: '/orders', title: '订单管理', icon: 'Tickets' },
  { path: '/on-sale-items', title: '在售商品', icon: 'ShoppingBag' },
  { path: '/transactions', title: '库存记录', icon: 'List' },
  { path: '/cost-records', title: '库存包材', icon: 'Money' },
  { path: '/cost-expenses', title: '包材使用记录', icon: 'Wallet' },
  { path: '/meilu-accounts', title: '煤炉账号', icon: 'User' },
  { path: '/warehouses', title: '仓库管理', icon: 'OfficeBuilding' },
  { path: '/categories', title: '游戏分类', icon: 'Collection' },
  { path: '/product-type-category-mappings', title: '商品类型映射', icon: 'Connection' },
  { path: '/system', title: '系统管理', icon: 'Setting' },
]

const handleLogout = async () => {
  await ElMessageBox.confirm('确认退出当前账号？', '提示', {
    type: 'warning',
    confirmButtonText: '退出',
    cancelButtonText: '取消',
  })
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
  router.replace('/login')
}
</script>

<style scoped>
.layout-container {
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  background: #0f1728;
  overflow: hidden;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* 手机：抽屉侧栏从左侧滑入（挂到 body，相对视口固定） */
.sidebar--mobile {
  position: fixed !important;
  left: 0;
  top: 0;
  bottom: 0;
  width: min(220px, 85vw) !important;
  max-width: 220px;
  z-index: 5010;
  transform: translate3d(-100%, 0, 0);
  transition: transform 0.3s cubic-bezier(0.32, 0.72, 0, 1);
  box-shadow: none;
  will-change: transform;
}

.sidebar--mobile.sidebar--drawer-open {
  transform: translate3d(0, 0, 0);
  box-shadow: 4px 0 24px rgba(0, 0, 0, 0.45);
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.sidebar-menu-wrap {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.sidebar-footer {
  flex-shrink: 0;
  padding: 12px 14px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.sidebar-footer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
}

.sidebar-footer-user {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  color: #9ba8bf;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar-logout-btn {
  flex-shrink: 0;
  margin: 0 !important;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  white-space: nowrap;
  overflow: hidden;
}

.logo-image {
  width: 40px;
  height: 40px;
  object-fit: contain;
  flex-shrink: 0;
}

.logo-text {
  flex: 1;
  min-width: 0;
  color: #b8c4d0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-close-btn {
  flex-shrink: 0;
  color: #a6adb4 !important;
  padding: 4px !important;
  margin-left: auto;
}

:deep(.el-menu) {
  border-right: none;
}

:deep(.el-menu-item.is-active) {
  background-color: #1890ff !important;
  border-radius: 6px;
  margin: 2px 8px;
  width: calc(100% - 16px);
}

:deep(.el-menu-item) {
  border-radius: 6px;
  margin: 2px 8px;
  width: calc(100% - 16px);
}

.main-content {
  flex: 1;
  overflow-y: auto;
  background: #0b1220;
  padding: 20px;
  min-width: 0;
}

@media (max-width: 767px) {
  .main-content {
    padding: 12px;
    padding-top: 56px;
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

<!-- Teleport 到 body，不能用 scoped，单独挂类名 -->
<style>
.layout-mobile-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 5000;
}
.layout-mobile-fab {
  position: fixed;
  left: max(12px, env(safe-area-inset-left, 0px));
  top: max(12px, env(safe-area-inset-top, 0px));
  z-index: 5020;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: #121b2e;
  border: 1px solid #253149;
  color: #ecf2ff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.45);
  padding: 0;
}
.layout-mobile-fab:active {
  opacity: 0.92;
}
</style>
