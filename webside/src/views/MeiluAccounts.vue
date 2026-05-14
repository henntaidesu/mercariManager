<template>
  <div>
    <el-card shadow="never" class="list-card" v-loading="loading">
      <el-row :gutter="16">
        <el-col :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
          <div class="add-card">
            <div class="add-card-main" @click="openCreate">
              <el-icon class="add-card-icon"><Plus /></el-icon>
              <span>新增账号</span>
            </div>
          </div>
        </el-col>
        <el-col v-for="row in list" :key="row.id" :xs="24" :sm="12" :md="8" :lg="6" class="card-col">
          <el-card shadow="hover" class="account-card">
            <div class="card-header">
              <div class="card-title">{{ row.account_name || '-' }}</div>
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </div>
            <div class="card-item"><span>平台：</span>{{ row.value?.x_platform || '-' }}</div>
            <div class="card-item"><span>卖家ID：</span>{{ row.seller_id || '-' }}</div>
            <div class="card-item">
              <span>自动数据获取：</span>
              <template v-if="row.is_open === 1">开启 · {{ fetchIntervalLabel(row.fetch_interval) }}</template>
              <template v-else>关闭</template>
            </div>
            <div class="card-item"><span>备注：</span>{{ row.remark || '-' }}</div>
            <div class="card-actions">
              <el-button
                size="small"
                type="primary"
                plain
                :loading="browserLoadingKeys.has(browserKeyFor(row.id))"
                @click="openBrowserForSavedAccount(row)"
              >打开浏览器</el-button>
              <el-button
                size="small"
                type="success"
                :loading="syncingIds.has(row.id)"
                @click="fetchHistory(row)"
              >获取历史数据</el-button>
              <el-button size="small" @click="openEdit(row)">编辑</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          @change="load"
          background
          small
        />
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="form.id ? '编辑煤炉账号' : '新增煤炉账号'"
      width="560px"
      top="6vh"
      destroy-on-close
      class="meilu-dialog"
    >
      <p v-if="!form.id" class="form-intro-tip">保存后将自动打开该账号专用浏览器，请在窗口中登录 jp.mercari.com。</p>
      <el-form :model="form" :rules="formRules" ref="formRef" label-width="120px" class="meilu-form">
        <el-divider content-position="left">基础信息</el-divider>
        <el-form-item label="账号名称" prop="account_name">
          <el-input v-model="form.account_name" maxlength="60" clearable />
        </el-form-item>
        <el-form-item label="卖家ID" prop="seller_id">
          <el-input v-model="form.seller_id" maxlength="30" clearable placeholder="纯数字，可留空" />
        </el-form-item>
        <el-form-item label="账号状态" prop="status">
          <el-select v-model="form.status" style="width: 100%">
            <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" maxlength="200" show-word-limit />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="meilu-dialog-footer">
          <el-popconfirm v-if="form.id" title="确认删除该账号？" @confirm="removeFromDialog">
            <template #reference>
              <el-button type="danger" plain>删除</el-button>
            </template>
          </el-popconfirm>
          <div class="meilu-dialog-footer__actions">
            <el-button @click="dialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
          </div>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { meiluAccountApi, mercariApi, webDriveApi } from '@/api/index.js'

const MERCARI_HOME = 'https://jp.mercari.com/'

function browserKeyFor(accountId) {
  return `meilu_${accountId}`
}

const loading = ref(false)
const submitting = ref(false)
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dialogVisible = ref(false)
const formRef = ref()

const statusOptions = [
  { label: '启用', value: 'active' },
  { label: '停用', value: 'disabled' },
]

const fetchIntervalOptions = [
  { label: '10 分钟', value: '10' },
  { label: '30 分钟', value: '30' },
  { label: '60 分钟', value: '60' },
  { label: '3 小时', value: '3h' },
  { label: '6 小时', value: '6h' },
  { label: '12 小时', value: '12h' },
  { label: '24 小时', value: '24h' },
]

const fetchIntervalLabelMap = Object.fromEntries(fetchIntervalOptions.map((o) => [o.value, o.label]))

function fetchIntervalLabel(v) {
  if (v == null || v === '') return '-'
  return fetchIntervalLabelMap[v] || v
}

const createDefaultForm = () => ({
  id: null,
  account_name: '',
  seller_id: '',
  status: 'active',
  remark: '',
})

const form = ref(createDefaultForm())

const sellerIdRules = [
  {
    validator(_rule, val, cb) {
      const text = String(val || '').trim()
      if (!text) return cb()
      if (!/^\d+$/.test(text)) return cb(new Error('卖家ID必须为纯数字'))
      cb()
    },
    trigger: 'blur',
  },
]

const formRules = {
  account_name: [{ required: true, message: '请输入账号名称', trigger: 'blur' }],
  seller_id: sellerIdRules,
  status: [{ required: true, message: '请选择账号状态', trigger: 'change' }],
}

async function load() {
  loading.value = true
  const params = { page: page.value, page_size: pageSize.value }
  const res = await meiluAccountApi.list(params).finally(() => {
    loading.value = false
  })
  list.value = res.items || []
  total.value = res.total || 0
}

function openCreate() {
  form.value = createDefaultForm()
  dialogVisible.value = true
}

function openEdit(row) {
  form.value = {
    ...createDefaultForm(),
    id: row.id,
    account_name: row.account_name || '',
    seller_id: row.seller_id != null ? String(row.seller_id) : '',
    status: row.status || 'active',
    remark: row.remark || '',
  }
  dialogVisible.value = true
}

function buildPayload() {
  const name = String(form.value.account_name || '').trim()
  const base = {
    account_name: name,
    login_id: name,
    seller_id: String(form.value.seller_id || '').trim() || null,
    status: form.value.status,
    remark: form.value.remark || null,
  }
  if (form.value.id) {
    return base
  }
  return {
    ...base,
    is_open: 0,
    fetch_interval: null,
  }
}

async function submit() {
  await formRef.value?.validate()
  submitting.value = true
  const payload = buildPayload()
  try {
    if (form.value.id) {
      await meiluAccountApi.update(form.value.id, payload)
      ElMessage.success('更新成功')
      dialogVisible.value = false
      load()
    } else {
      const created = await meiluAccountApi.create(payload)
      ElMessage.success('新增成功')
      dialogVisible.value = false
      await load()
      const newId = created?.id
      if (newId != null) {
        await openBrowserByKey(
          browserKeyFor(newId),
          created.account_name || payload.account_name || `账号 #${newId}`,
        )
      }
    }
  } finally {
    submitting.value = false
  }
}

async function remove(id) {
  await meiluAccountApi.remove(id)
  ElMessage.success('删除成功')
  if (list.value.length === 1 && page.value > 1) page.value -= 1
  load()
}

async function removeFromDialog() {
  if (!form.value.id) return
  const id = form.value.id
  await remove(id)
  dialogVisible.value = false
}

const syncingIds = ref(new Set())
const browserLoadingKeys = ref(new Set())

async function openBrowserByKey(accountKey, label) {
  if (browserLoadingKeys.value.has(accountKey)) return
  const next = new Set(browserLoadingKeys.value)
  next.add(accountKey)
  browserLoadingKeys.value = next
  try {
    const res = await webDriveApi.openSession({
      account_key: accountKey,
      headless: false,
      start_url: MERCARI_HOME,
    })
    const d = res.data || {}
    const tip = d.already_running ? '（已在运行，已跳转首页）' : '已启动 Edge'
    ElMessage.success(`${label || accountKey}：${tip}`)
  } catch {
    /* 错误由 axios 拦截器提示 */
  } finally {
    const s = new Set(browserLoadingKeys.value)
    s.delete(accountKey)
    browserLoadingKeys.value = s
  }
}

function openBrowserForSavedAccount(row) {
  openBrowserByKey(browserKeyFor(row.id), row.account_name || `账号 #${row.id}`)
}

async function fetchHistory(row) {
  if (syncingIds.value.has(row.id)) return
  const sid = String(row.seller_id || '').trim()
  if (!sid) {
    ElMessage.warning('请先为该账号配置卖家 ID')
    return
  }

  let preRes
  try {
    preRes = await mercariApi.historySyncPrecheck({ account_id: row.id })
  } catch {
    return
  }
  const pre = preRes?.data || {}
  if (!pre.allowed) {
    ElMessage.warning(pre.message || '该卖家在订单表中已有数据，无法重复获取历史数据')
    return
  }

  try {
    await ElMessageBox.confirm(
      '本地订单库中尚无该卖家的记录。确认从煤炉全量拉取出售中与历史订单？耗时可能较长，请勿关闭页面。',
      '获取历史数据',
      {
        type: 'warning',
        confirmButtonText: '确认拉取',
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      }
    )
  } catch {
    return
  }

  syncingIds.value = new Set([...syncingIds.value, row.id])
  try {
    const res = await mercariApi.syncOrders({ account_id: row.id })
    const d = res.data || {}
    ElMessage.success(
      `「${row.account_name}」同步完成：新增 ${d.inserted ?? 0} 条，更新 ${d.updated ?? 0} 条，共 ${d.total_item_count ?? d.total ?? 0} 条`
    )
  } finally {
    const next = new Set(syncingIds.value)
    next.delete(row.id)
    syncingIds.value = next
  }
}

onMounted(() => {
  load()
})
</script>

<style scoped>
.list-card {
  border-radius: 8px;
}
.card-col {
  margin-bottom: 16px;
}
.add-card {
  height: 100%;
  min-height: 220px;
  border: 1px dashed #3a4a65;
  border-radius: 8px;
  background: rgba(19, 28, 47, 0.85);
  color: #a8b4c8;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px;
  transition: all 0.2s ease;
}
.add-card:hover {
  border-color: #409eff;
  background: #1b2942;
}
.add-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  width: 100%;
  min-height: 120px;
  color: #a8b4c8;
  transition: color 0.2s ease;
}
.add-card:hover .add-card-main {
  color: #69b1ff;
}
.add-card-icon {
  font-size: 24px;
}
.account-card {
  border-radius: 8px;
  height: 100%;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: #e6edf7;
}
.card-item {
  margin-bottom: 8px;
  color: #a8b4c8;
  word-break: break-all;
  font-size: 13px;
}
.card-item span {
  color: #7d8da6;
}
.card-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.meilu-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}
.meilu-dialog-footer__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-left: auto;
}
.form-intro-tip {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.55;
  color: #7d8da6;
}
.meilu-form {
  max-height: 70vh;
  overflow-y: auto;
  padding-right: 8px;
}
</style>

<style>
.meilu-dialog .el-dialog__body {
  padding-top: 8px;
}
</style>
