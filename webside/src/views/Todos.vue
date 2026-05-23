<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            placeholder="搜索标题 / 消息 / 商品 ID / 商品名"
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
          <el-checkbox v-model="filters.include_deleted" @change="onFilterChange">
            含已完成
          </el-checkbox>
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-button type="primary" :icon="Download" :loading="syncLoading" @click="openSyncDialog">
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
              class="todo-thumb"
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

        <el-table-column label="类型" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="kindTagType(row.kind)" size="small" effect="light">
              {{ kindLabel(row.kind) }}
            </el-tag>
            <div v-if="row.is_delete" class="row-tag-done">已完成</div>
          </template>
        </el-table-column>

        <el-table-column label="标题 / 消息" min-width="320" align="left" header-align="center">
          <template #default="{ row }">
            <div v-if="row.title" class="cell-title">{{ row.title }}</div>
            <div class="cell-message">{{ row.message || '-' }}</div>
            <div v-if="row.item_id" class="cell-itemid">
              <el-link :href="mercariItemUrl(row.item_id)" target="_blank" type="primary" :underline="false">
                {{ row.item_id }}
              </el-link>
              <span v-if="row.item_name" class="cell-itemname">{{ row.item_name }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="买家" width="160" align="center" header-align="center">
          <template #default="{ row }">
            <div v-if="buyerNameFromMessage(row.message)" class="cell-buyer">{{ buyerNameFromMessage(row.message) }}</div>
            <div v-if="row.sender_id" class="cell-sender-id">ID: {{ row.sender_id }}</div>
            <span v-if="!row.sender_id && !buyerNameFromMessage(row.message)" class="cell-muted">-</span>
          </template>
        </el-table-column>

        <el-table-column label="时间" width="170" align="center" header-align="center">
          <template #default="{ row }">
            <div>{{ displayTs(row.mercari_updated || row.mercari_created) }}</div>
            <div v-if="row.synced_at" class="cell-muted-sm">同步: {{ displayTs(row.synced_at) }}</div>
          </template>
        </el-table-column>

        <el-table-column label="账号" width="140" align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.account_name || `#${row.account_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="90" align="center" header-align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="onProcess(row)">处理</el-button>
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

    <el-dialog v-model="syncDialogVisible" title="从煤炉同步代办事项" width="420">
      <el-form label-width="80px">
        <el-form-item label="账号">
          <el-select v-model="syncDialog.account_id" placeholder="选择账号" clearable filterable style="width: 100%">
            <el-option
              v-for="a in accountOptions"
              :key="a.id"
              :label="a.label"
              :value="a.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <div class="dialog-hint">
            未选择则按系统中第一个「启用 + active」的账号同步。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="syncDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="syncLoading" @click="confirmSync">开始同步</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { todosApi, meiluAccountApi } from '@/api'

const KIND_LABELS = {
  WaitShippingCard: '待发货',
  WaitShippingPoint: '待发货',
  TransactionWaitShippingFunds: '待发货',
  MerpayRealcardWaitActivation: 'Merpay 卡激活',
}

const KIND_TAG_TYPES = {
  WaitShippingCard: 'warning',
  WaitShippingPoint: 'warning',
  TransactionWaitShippingFunds: 'warning',
  MerpayRealcardWaitActivation: 'info',
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
  include_deleted: false,
})

const accountOptions = ref([])
const kindOptions = ref([])

const syncDialogVisible = ref(false)
const syncDialog = reactive({ account_id: null })
const syncLoading = ref(false)

function listParams() {
  const p = { page: page.value, page_size: pageSize.value }
  const kw = filters.value.keyword?.trim()
  if (kw) p.keyword = kw
  if (filters.value.account_id) p.account_id = filters.value.account_id
  if (filters.value.kind) p.kind = filters.value.kind
  if (filters.value.include_deleted) p.include_deleted = true
  return p
}

async function load() {
  loading.value = true
  try {
    const res = await todosApi.list(listParams())
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
    const res = await todosApi.kinds()
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

function openSyncDialog() {
  syncDialog.account_id = filters.value.account_id || null
  syncDialogVisible.value = true
}

async function confirmSync() {
  syncLoading.value = true
  try {
    const d = await todosApi.sync({ account_id: syncDialog.account_id || null }) || {}
    ElMessageBox.alert(
      `账号 #${d.account_id ?? '-'} 同步完成：` +
        `新增 ${d.inserted ?? 0} 条，更新 ${d.updated ?? 0} 条，` +
        `标记完成 ${d.marked_deleted ?? 0} 条，共抓取 ${d.total ?? 0} 条。`,
      '同步结果',
      { type: 'success', confirmButtonText: '确定' },
    )
    syncDialogVisible.value = false
    await Promise.all([load(), loadKindOptions()])
  } catch (e) {
    ElMessage.error(e?.message || '同步失败')
  } finally {
    syncLoading.value = false
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

function mercariItemUrl(itemId) {
  const s = String(itemId || '').trim()
  if (!s) return '#'
  return `https://jp.mercari.com/item/${s}`
}

function onProcess(row) {
  // TODO: 处理按钮的具体行为待定（本地标完成 / 打开煤炉商品页 / 二者皆有）
  ElMessage.info(`处理 todo #${row.id}（功能待实现）`)
}

function buyerNameFromMessage(msg) {
  const s = String(msg || '')
  // 「<买家名>さんが...」 / 「<买家名>さんに...」
  const m = s.match(/^(.+?)さん[がにへ]/)
  return m ? m[1].trim() : ''
}

onMounted(() => {
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
  gap: 8px;
}
.table-card {
  border-radius: 8px;
}
.todo-thumb {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  display: block;
}
.thumb-fallback {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.cell-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.cell-message {
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
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
.row-tag-done {
  margin-top: 4px;
  color: var(--el-color-success);
  font-size: 11px;
}
.pagination {
  margin-top: 16px;
  justify-content: flex-end;
  display: flex;
}
.dialog-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
</style>
