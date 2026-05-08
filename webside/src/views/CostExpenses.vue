<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="12" align="middle">
        <el-col :xs="24" :md="16" class="search-left-group">
          <el-select v-model="filters.type" placeholder="使用类型" clearable @change="onFilterChange">
            <el-option v-for="item in typeOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-input
            v-model="filters.order_no"
            clearable
            placeholder="订单号"
            @change="onFilterChange"
          />
          <el-select v-model="filters.owner" placeholder="归属人" clearable @change="onFilterChange">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.username" />
          </el-select>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="x"
            @change="onFilterChange"
          />
        </el-col>
        <el-col :xs="24" :md="8" class="search-actions">
          <el-button type="primary" @click="openCreate">新增包材使用记录</el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column label="类型" prop="type" min-width="120" />
        <el-table-column label="订单号" prop="order_no" min-width="150">
          <template #default="{ row }">{{ row.order_no || '-' }}</template>
        </el-table-column>
        <el-table-column label="物品名称" prop="item_name" min-width="160" />
        <el-table-column label="数量" prop="quantity" width="100" align="center" />
        <el-table-column label="单价" width="120" align="right">
          <template #default="{ row }">
            ¥{{ Number(row.unit_price || 0) }}
          </template>
        </el-table-column>
        <el-table-column label="总价" width="120" align="right">
          <template #default="{ row }">
            ¥{{ Number(row.quantity || 0) * Number(row.unit_price || 0) }}
          </template>
        </el-table-column>
        <el-table-column label="归属人" prop="owner" width="120">
          <template #default="{ row }">{{ row.owner || '-' }}</template>
        </el-table-column>
        <el-table-column label="记录时间" width="190">
          <template #default="{ row }">{{ formatTs(row.record_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-popconfirm title="确认删除该记录？" @confirm="remove(row.id)">
              <template #reference>
                <el-button size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

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

    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑包材使用记录' : '新增包材使用记录'" width="520px" destroy-on-close>
      <el-form :model="form" :rules="rules" ref="formRef" label-width="88px">
        <el-form-item label="订单号">
          <el-input v-model="form.order_no" clearable placeholder="可选：填写后会关联订单" />
        </el-form-item>
        <el-form-item label="物品名称" prop="item_name">
          <el-select
            v-model="form.item_name"
            placeholder="请选择物品名称"
            filterable
            clearable
            @change="onItemNameChange"
            style="width: 100%"
          >
            <el-option
              v-for="item in costRecordItemOptions"
              :key="item.item_name"
              :label="item.item_name"
              :value="item.item_name"
            />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="数量" prop="quantity">
              <el-input-number v-model="form.quantity" :min="1" :precision="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="单价" prop="unit_price">
              <el-input-number v-model="form.unit_price" :min="1" :precision="0" :controls="false" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="归属人">
          <el-select v-model="form.owner" clearable placeholder="请选择归属人（可选）" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="u.display_name || u.username" :value="u.username" />
          </el-select>
        </el-form-item>
        <el-form-item label="记录时间" prop="record_time">
          <el-date-picker
            v-model="form.record_time"
            type="datetime"
            value-format="x"
            placeholder="请选择记录时间"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { authApi, costExpenseApi, costRecordApi } from '@/api/index.js'

const loading = ref(false)
const submitting = ref(false)
const list = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const dialogVisible = ref(false)
const formRef = ref()
const dateRange = ref([])
const users = ref([])
const costRecordItemOptions = ref([])
const typeOptions = ['快递费', '包装材料']

const filters = ref({
  type: '',
  owner: '',
  order_no: '',
})

const createDefaultForm = () => ({
  id: null,
  type: '',
  item_name: '',
  quantity: 1,
  unit_price: null,
  owner: '',
  order_no: '',
  record_time: Date.now(),
})

const form = ref(createDefaultForm())

const rules = {
  item_name: [{ required: true, message: '请输入物品名称', trigger: 'blur' }],
  quantity: [{ required: true, message: '请输入数量', trigger: 'blur' }],
  unit_price: [{ required: true, message: '请输入单价', trigger: 'blur' }],
  record_time: [{ required: true, message: '请选择记录时间', trigger: 'change' }],
}

function formatTs(ts) {
  if (!ts) return '-'
  return new Date(Number(ts) * 1000).toLocaleString()
}

async function load() {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
    }
    if (filters.value.type) params.type = filters.value.type
    if (filters.value.owner) params.owner = filters.value.owner
    if (String(filters.value.order_no || '').trim()) {
      params.order_no = String(filters.value.order_no || '').trim()
    }
    if (dateRange.value?.length === 2) {
      params.start_time = Math.floor(Number(dateRange.value[0]) / 1000)
      params.end_time = Math.floor(Number(dateRange.value[1]) / 1000)
    }
    const res = await costExpenseApi.list(params)
    list.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

async function loadUsers() {
  users.value = await authApi.listUsers()
}

async function loadCostRecordItemOptions() {
  const res = await costRecordApi.listPackagingItems()
  costRecordItemOptions.value = Array.isArray(res?.items) ? res.items : []
}

function getSelectedItemMeta(itemName) {
  return costRecordItemOptions.value.find((item) => item.item_name === itemName) || null
}

function onItemNameChange(itemName) {
  const meta = getSelectedItemMeta(itemName)
  if (!meta) return
  form.value.type = meta.expense_type || ''
  form.value.unit_price = Number(meta.amount || 0)
}

function onFilterChange() {
  page.value = 1
  load()
}

function openCreate() {
  form.value = createDefaultForm()
  dialogVisible.value = true
}

function openEdit(row) {
  form.value = {
    id: row.id,
    type: row.type || '',
    item_name: row.item_name || '',
    quantity: Number(row.quantity || 1),
    unit_price: Number(row.unit_price || 0),
    owner: row.owner || '',
    order_no: row.order_no || '',
    record_time: Number(row.record_time || 0) * 1000,
  }
  dialogVisible.value = true
}

async function submit() {
  await formRef.value?.validate()
  submitting.value = true
  try {
    const payload = {
      item_name: String(form.value.item_name || '').trim(),
      quantity: Number(form.value.quantity || 0),
      unit_price: Number(form.value.unit_price || 0),
      owner: String(form.value.owner || '').trim() || null,
      order_no: String(form.value.order_no || '').trim() || null,
      record_time: Math.floor(Number(form.value.record_time || Date.now()) / 1000),
    }
    if (form.value.id) {
      await costExpenseApi.update(form.value.id, payload)
      ElMessage.success('更新成功')
    } else {
      await costExpenseApi.create(payload)
      ElMessage.success('新增成功')
    }
    dialogVisible.value = false
    load()
  } finally {
    submitting.value = false
  }
}

async function remove(id) {
  await costExpenseApi.remove(id)
  ElMessage.success('删除成功')
  if (list.value.length === 1 && page.value > 1) page.value -= 1
  load()
}

onMounted(async () => {
  await Promise.all([loadUsers(), loadCostRecordItemOptions()])
  await load()
})
</script>

<style scoped>
.search-card { margin-bottom: 16px; border-radius: 8px; }
.search-left-group { display: flex; gap: 12px; }
.search-actions { display: flex; justify-content: flex-end; }
.table-card { border-radius: 8px; }
.pagination { margin-top: 16px; display: flex; justify-content: flex-end; }
</style>
