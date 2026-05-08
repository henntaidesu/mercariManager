import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: () => import('@/components/Layout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '控制台', icon: 'Odometer' } },
      { path: 'inventory', name: 'Inventory', component: () => import('@/views/Products.vue'), meta: { title: '库存管理', icon: 'Goods' } },
      { path: 'orders', name: 'Orders', component: () => import('@/views/Orders.vue'), meta: { title: '订单管理', icon: 'Tickets' } },
      { path: 'on-sale-items', name: 'OnSaleItems', component: () => import('@/views/OnSaleItems.vue'), meta: { title: '在售商品', icon: 'ShoppingBag' } },
      { path: 'transactions', name: 'Transactions', component: () => import('@/views/Transactions.vue'), meta: { title: '库存记录', icon: 'List' } },
      { path: 'cost-records', name: 'CostRecords', component: () => import('@/views/CostRecords.vue'), meta: { title: '库存包材', icon: 'Money' } },
      { path: 'cost-expenses', name: 'CostExpenses', component: () => import('@/views/CostExpenses.vue'), meta: { title: '包材使用记录', icon: 'Wallet' } },
      { path: 'meilu-accounts', name: 'MeiluAccounts', component: () => import('@/views/MeiluAccounts.vue'), meta: { title: '煤炉账号', icon: 'User' } },
      { path: 'warehouses', name: 'Warehouses', component: () => import('@/views/Warehouses.vue'), meta: { title: '仓库管理', icon: 'OfficeBuilding' } },
      { path: 'categories', name: 'Categories', component: () => import('@/views/Categories.vue'), meta: { title: '游戏分类', icon: 'Collection' } },
      { path: 'product-type-category-mappings', name: 'ProductTypeCategoryMappings', component: () => import('@/views/ProductTypeCategoryMappings.vue'), meta: { title: '商品类型映射', icon: 'Connection' } },
      { path: 'system', name: 'System', component: () => import('@/views/System.vue'), meta: { title: '系统管理', icon: 'Setting' } }
    ]
  }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const isPublic = Boolean(to.meta?.public)
  const token = localStorage.getItem('auth_token')

  if (!isPublic && !token) {
    next('/login')
    return
  }

  if (to.path === '/login' && token) {
    next('/dashboard')
    return
  }

  next()
})

export default router
