<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            placeholder="搜索消息 / 商品 ID / 商品名"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.account_id"
            placeholder="账号"
            clearable
            filterable
            style="min-width: 200px"
            @change="onFilterChange"
          >
            <el-option
              v-for="a in accountOptions"
              :key="a.id"
              :label="a.label"
              :value="a.id"
            />
          </el-select>
          <el-select
            v-model="filters.kind"
            placeholder="类型"
            clearable
            filterable
            style="min-width: 200px"
            @change="onFilterChange"
          >
            <el-option
              v-for="k in kindOptions"
              :key="k"
              :label="kindLabel(k)"
              :value="k"
            />
          </el-select>
          <el-checkbox v-model="filters.only_unread" @change="onFilterChange">
            仅未读
          </el-checkbox>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-select
            v-model="globalAccountId"
            placeholder="选择煤炉账号"
            filterable
            class="sync-account-select"
            :loading="mercariAccountStore.loading"
          >
            <el-option
              v-for="acc in mercariAccountStore.activeAccounts"
              :key="acc.id"
              :label="acc.account_name"
              :value="acc.id"
            />
          </el-select>
          <el-button type="primary" :icon="Download" :loading="syncLoading" @click="runSync">
            从煤炉同步
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe row-key="id">
        <el-table-column label="图" width="80" align="center" header-align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.photo_url"
              class="ntf-thumb"
              :src="row.photo_url"
              :preview-src-list="[row.photo_url]"
              :preview-teleported="true"
              fit="cover"
              referrerpolicy="no-referrer"
              lazy
            >
              <template #error>
                <span class="thumb-fallback">-</span>
              </template>
            </el-image>
            <span v-else class="thumb-fallback">-</span>
          </template>
        </el-table-column>

        <el-table-column label="类型" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="kindTagType(row.kind)" size="small" effect="light">
              {{ kindLabel(row.kind) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="消息" min-width="360" align="left" header-align="center">
          <template #default="{ row }">
            <div :class="['cell-message', !row.is_read ? 'cell-message-unread' : '']">
              {{ row.message || '-' }}
            </div>
            <div v-if="row.item_id" class="cell-itemid">
              <span class="cell-itemid-text">{{ row.item_id }}</span>
              <span v-if="row.item_name" class="cell-itemname">{{ row.item_name }}</span>
            </div>
            <div v-if="row.price" class="cell-extra">值下げ依頼: ¥{{ formatYen(row.price) }}</div>
            <div v-if="row.bid_price" class="cell-extra">入札: ¥{{ formatYen(row.bid_price) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="发件人" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <div v-if="senderNameFromMessage(row.message)" class="cell-buyer">
              {{ senderNameFromMessage(row.message) }}
            </div>
            <div v-if="row.sender_id && row.sender_id !== '0'" class="cell-sender-id">
              ID: {{ row.sender_id }}
            </div>
            <span
              v-if="!row.sender_id && !senderNameFromMessage(row.message)"
              class="cell-muted"
            >-</span>
          </template>
        </el-table-column>

        <el-table-column label="时间" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div>{{ displayTs(row.mercari_created) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="账号" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.account_name || `#${row.account_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="120" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="actionForKind(row.kind) === 'open'"
              type="primary"
              link
              size="small"
              :disabled="!hasTargetUrl(row)"
              @click="onOpenTarget(row)"
            >
              打开
            </el-button>
            <el-button
              v-else-if="actionForKind(row.kind) === 'detail'"
              type="primary"
              link
              size="small"
              @click="onViewDetail(row)"
            >
              查看详情
            </el-button>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pagination"
        background
        layout="prev, pager, next, sizes, total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        @current-change="onPageChange"
        @size-change="onPageSizeChange"
      />
    </el-card>

    <BundlePurchaseDialog
      v-model="bundleDialogVisible"
      :bundle-id="bundleDialogBundleId"
      :account-id="bundleDialogAccountId"
      :notification-id="bundleDialogNotificationId"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { notificationsApi, meiluAccountApi } from '@/api'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import BundlePurchaseDialog from '@/components/BundlePurchaseDialog.vue'

const mercariAccountStore = useMercariAccountStore()
const globalAccountId = computed({
  get: () => mercariAccountStore.selectedId,
  set: (v) => mercariAccountStore.setSelected(v),
})

const KIND_LABELS = {
  Like: '点赞',
  Comment: '留言',
  LikedItemReceiveComment: '关注商品留言',
  DesiredPriceOfferCreated: '降价请求',
  AuctionBidCreated: '拍卖出价',
  BundleRequestCreated: '合并购买请求',
  WaitPayment: '待支付',
  PrivateMessage: '事务局消息',
  'merpay-egp-ian-promotion': '活动公告',
  'merpay-egp-ian-promotion-action-url': '活动公告',
}

const KIND_TAG_TYPES = {
  Like: 'danger',
  Comment: 'primary',
  LikedItemReceiveComment: 'primary',
  DesiredPriceOfferCreated: 'warning',
  AuctionBidCreated: 'warning',
  BundleRequestCreated: 'warning',
  WaitPayment: 'success',
  PrivateMessage: 'info',
  'merpay-egp-ian-promotion': 'info',
  'merpay-egp-ian-promotion-action-url': 'info',
}

// 操作列按 kind 区分动作类型：
// - 'none'   不显示业务按钮（仅保留 标已读/标未读）
// - 'detail' 显示「查看详情」按钮（占位，暂不对接）
// - 'open'   其他默认走「打开」（跳 target_url / action_url / item 页）
const KIND_ACTION = {
  Like: 'none',
  AuctionBidCreated: 'none',
  'merpay-egp-ian-promotion': 'none',
  'merpay-egp-ian-promotion-action-url': 'none',
  Comment: 'detail',
  BundleRequestCreated: 'detail',
}

function actionForKind(kind) {
  return KIND_ACTION[kind] || 'open'
}

const list = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)

const filters = ref({
  keyword: '',
  account_id: null,
  kind: '',
  only_unread: false,
})

const accountOptions = ref([])
const kindOptions = ref([])
const syncLoading = ref(false)

function listParams() {
  const p = { page: page.value, page_size: pageSize.value }
  const kw = filters.value.keyword?.trim()
  if (kw) p.keyword = kw
  if (filters.value.account_id) p.account_id = filters.value.account_id
  if (filters.value.kind) p.kind = filters.value.kind
  if (filters.value.only_unread) p.only_unread = true
  return p
}

async function load() {
  loading.value = true
  try {
    const res = await notificationsApi.list(listParams())
    list.value = res?.items || []
    total.value = Number(res?.total || 0)
  } catch (e) {
    ElMessage.error(e?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

async function loadAccountOptions() {
  try {
    const res = await meiluAccountApi.list({ page: 1, page_size: 200 })
    accountOptions.value = (res.items || []).map((a) => ({
      id: a.id,
      label: `${a.account_name}${a.seller_id ? ` (${a.seller_id})` : ''}`,
    }))
  } catch {
    accountOptions.value = []
  }
}

async function loadKindOptions() {
  try {
    const res = await notificationsApi.kinds()
    const arr = res?.kinds
    kindOptions.value = Array.isArray(arr) ? arr : []
  } catch {
    kindOptions.value = []
  }
}

function onFilterChange() {
  page.value = 1
  load()
}
function onPageChange(p) {
  page.value = p
  load()
}
function onPageSizeChange(s) {
  pageSize.value = s
  page.value = 1
  load()
}

async function runSync() {
  if (syncLoading.value) return
  const aid = mercariAccountStore.selectedId
  if (!aid) {
    ElMessage.warning('请先在右上角选择煤炉账号')
    return
  }
  const name = mercariAccountStore.selectedAccountName || `#${aid}`
  try {
    await ElMessageBox.confirm(
      `将使用账号「${name}」从煤炉同步お知らせ通知，是否继续？`,
      '确认同步',
      { type: 'info', confirmButtonText: '开始', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  syncLoading.value = true
  try {
    const d = (await notificationsApi.sync({ account_id: aid })) || {}
    ElMessageBox.alert(
      `账号 #${d.account_id ?? '-'} 同步完成：` +
        `新增 ${d.inserted ?? 0} 条，更新 ${d.updated ?? 0} 条，共抓取 ${d.total ?? 0} 条。`,
      '同步结果',
      { type: 'success', confirmButtonText: '确定' },
    )
    await Promise.all([load(), loadKindOptions()])
  } catch (e) {
    ElMessage.error(e?.message || '同步失败')
  } finally {
    syncLoading.value = false
  }
}

function hasTargetUrl(row) {
  return !!(row?.target_url || row?.action_url || row?.item_id)
}

function itemUrlFor(row) {
  const iid = String(row?.item_id || '').trim()
  if (iid) return `https://jp.mercari.com/item/${iid}`
  return '#'
}

const bundleDialogVisible = ref(false)
const bundleDialogBundleId = ref('')
const bundleDialogAccountId = ref(null)
const bundleDialogNotificationId = ref(null)

function extractBundleId(row) {
  const raw = String(row?.intent_json || '').trim()
  if (!raw) return ''
  try {
    const obj = JSON.parse(raw)
    const id = obj?.extra?.bundle_id
    return typeof id === 'string' ? id.trim() : ''
  } catch {
    return ''
  }
}

function onViewDetail(row) {
  if (row?.kind === 'BundleRequestCreated') {
    const bid = extractBundleId(row)
    if (!bid) {
      ElMessage.warning('该通知未携带 bundle_id，无法打开合并购买请求详情')
      return
    }
    bundleDialogBundleId.value = bid
    bundleDialogAccountId.value = row.account_id || null
    bundleDialogNotificationId.value = row.id || null
    bundleDialogVisible.value = true
    if (!row.is_read) {
      notificationsApi.markRead([row.id], true).then(() => {
        row.is_read = 1
      }).catch(() => {})
    }
    return
  }
  ElMessage.info(`查看详情功能待对接（kind=${row.kind}）`)
}

async function onOpenTarget(row) {
  let url = String(row?.target_url || row?.action_url || '').trim()
  if (!url && row?.item_id) {
    url = `https://jp.mercari.com/item/${row.item_id}`
  }
  if (!url) {
    ElMessage.warning('该通知没有可跳转的链接')
    return
  }
  window.open(url, '_blank', 'noopener')
  // 打开后自动标已读（fire-and-forget）
  if (!row.is_read) {
    try {
      await notificationsApi.markRead([row.id], true)
      row.is_read = 1
    } catch { /* 忽略 */ }
  }
}

function kindLabel(kind) {
  if (!kind) return '-'
  return KIND_LABELS[kind] || kind
}
function kindTagType(kind) {
  return KIND_TAG_TYPES[kind] || 'info'
}

function displayTs(ms) {
  const n = Number(ms || 0)
  if (!n) return '-'
  const d = new Date(n)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatYen(n) {
  const v = Number(n || 0)
  if (!v) return '0'
  return v.toLocaleString('ja-JP')
}

function senderNameFromMessage(msg) {
  const s = String(msg || '')
  const m = s.match(/^(.+?)さん[がにへ、]/)
  return m ? m[1].trim() : ''
}

onMounted(() => {
  mercariAccountStore.ensureLoaded()
  Promise.all([loadAccountOptions(), loadKindOptions()])
  load()
})
</script>

<style scoped>
.search-card {
  margin-bottom: 16px;
  border-radius: 8px;
}
.search-row {
  justify-content: space-between;
  row-gap: 10px;
}
.search-left-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.search-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.sync-account-select {
  width: 180px;
}
.table-card {
  border-radius: 8px;
}
.ntf-thumb {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  display: block;
}
.thumb-fallback {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.cell-message {
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
.cell-message-unread {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.cell-itemid {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.cell-itemname {
  color: var(--el-text-color-secondary);
}
.cell-extra {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-color-warning);
}
.cell-buyer {
  font-weight: 500;
}
.cell-sender-id {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 2px;
}
.cell-muted {
  color: var(--el-text-color-placeholder);
}
.cell-muted-sm {
  color: var(--el-text-color-placeholder);
  font-size: 11px;
  margin-top: 2px;
}
.row-tag-unread {
  margin-top: 4px;
  color: var(--el-color-danger);
  font-size: 11px;
}
.pagination {
  margin-top: 16px;
  justify-content: flex-end;
  display: flex;
}
</style>
