<template>
  <el-dialog
    :model-value="visible"
    @update:model-value="onVisibleChange"
    :title="dialogTitle"
    width="720px"
    align-center
    destroy-on-close
    :close-on-click-modal="false"
    class="bundle-purchase-dialog"
  >
    <div v-loading="loading" element-loading-text="正在打开浏览器并捕获合并购买详情...">
      <template v-if="bundle">
        <el-descriptions :column="2" border size="small" class="bundle-meta">
          <el-descriptions-item label="买家">
            <span>{{ bundle.buyer_username || '-' }}</span>
            <span v-if="bundle.buyer_id" class="muted"> ({{ bundle.buyer_id }})</span>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            {{ bundleStateLabel(bundle.state) }}
          </el-descriptions-item>
          <el-descriptions-item label="合计金额">
            <span class="amount">¥{{ formatYen(bundle.suggested_price) }}</span>
            <span v-if="differsFromOriginal" class="muted">
              （原始: ¥{{ formatYen(bundle.original_price) }}）
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="过期时间">
            {{ displayTs(bundle.bundle_expire) }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="section-title">商品一览（{{ items.length }} 件）</div>
        <el-table :data="items" border size="small" class="bundle-items">
          <el-table-column label="图" width="80" align="center">
            <template #default="{ row }">
              <el-image
                v-if="row.thumbnail"
                :src="row.thumbnail"
                :preview-src-list="[row.thumbnail]"
                :preview-teleported="true"
                fit="cover"
                class="thumb"
                referrerpolicy="no-referrer"
              />
              <span v-else class="muted">-</span>
            </template>
          </el-table-column>
          <el-table-column label="商品" min-width="280">
            <template #default="{ row }">
              <div class="item-name">{{ row.displayName || '-' }}</div>
              <div class="item-id">
                <a
                  v-if="row.itemId"
                  :href="`https://jp.mercari.com/item/${row.itemId}`"
                  target="_blank"
                  rel="noopener"
                >
                  {{ row.itemId }}
                </a>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="价格" width="120" align="right">
            <template #default="{ row }">
              ¥{{ formatYen(row.price) }}
            </template>
          </el-table-column>
        </el-table>

        <div class="section-title">出品表单</div>
        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-width="110px"
          label-position="right"
          class="bundle-form"
        >
          <el-form-item label="配送料の負担" prop="shipping_payer" required>
            <el-select
              v-model="form.shipping_payer"
              placeholder="请选择"
              style="width: 100%"
            >
              <el-option
                v-for="o in shippingPayerOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="配送の方法" prop="shipping_method" required>
            <el-select
              v-model="form.shipping_method"
              placeholder="请选择"
              style="width: 100%"
            >
              <el-option
                v-for="o in shippingMethodOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="発送元の地域" prop="shipping_from" required>
            <el-cascader
              v-model="shippingFromPath"
              :options="shippingFromCascaderOptions"
              :props="shippingFromCascaderProps"
              :show-all-levels="false"
              filterable
              placeholder="请选择发货地（必选）"
              style="width: 100%"
              @change="handleShippingFromChange"
            />
          </el-form-item>
          <el-form-item label="発送までの日数" prop="shipping_days" required>
            <el-select
              v-model="form.shipping_days"
              placeholder="请选择"
              style="width: 100%"
            >
              <el-option
                v-for="o in shippingDaysOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
        </el-form>
      </template>
      <template v-else-if="!loading">
        <el-empty description="尚未捕获到合并购买请求数据" />
      </template>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onVisibleChange(false)" :disabled="busy">关闭</el-button>
        <el-button
          v-if="bundle"
          type="danger"
          :loading="rejecting"
          :disabled="accepting"
          @click="onReject"
        >
          取消
        </el-button>
        <el-button
          v-if="bundle"
          type="success"
          :loading="accepting"
          :disabled="rejecting"
          @click="onAccept"
        >
          依頼を承諾する
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { notificationsApi } from '@/api'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed,
} from '@/constants/mercariJapanAreas.js'

const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  bundleId: { type: String, default: '' },
  accountId: { type: [Number, String], default: null },
  notificationId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue', 'decided'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const loading = ref(false)
const accepting = ref(false)
const rejecting = ref(false)
const bundle = ref(null)
const items = ref([])
const formRef = ref(null)
const shippingFromPath = ref([])

const busy = computed(() => loading.value || accepting.value || rejecting.value)

const form = ref({
  shipping_payer: '',
  shipping_method: '',
  shipping_from: '',
  shipping_days: '',
})

const rules = {
  shipping_payer: [{ required: true, message: '请选择送料负担', trigger: 'change' }],
  shipping_method: [{ required: true, message: '请选择配送方法', trigger: 'change' }],
  shipping_from: [{ required: true, message: '请选择发货地', trigger: 'change' }],
  shipping_days: [{ required: true, message: '请选择发货天数', trigger: 'change' }],
}

// 顺序对应煤炉下拉框（第一个=包邮，第二个=到付）
const shippingPayerOptions = [
  { label: '送料込み（出品者负担）', value: 'seller' },
  { label: '着払い（购买者负担）', value: 'buyer' },
]

// 顺序与 /bundle_offer/{id} 下拉一致：未定 / らくらく / ゆうゆう / 梱包・発送たのメル便 /
// ゆうメール / レターパック / 郵便（定型・定形外・書留など） / クロネコヤマト /
// ゆうパック / クリックポスト / ゆうパケット
const shippingMethodOptions = [
  { label: '未定', value: 'undecided' },
  { label: 'らくらくメルカリ便', value: 'rakuraku' },
  { label: 'ゆうゆうメルカリ便', value: 'yuuyu' },
  { label: '梱包・発送たのメル便', value: 'takunomeru' },
  { label: 'ゆうメール', value: 'yumail' },
  { label: 'レターパック', value: 'letter_pack' },
  { label: '郵便（定型、定形外、書留など）', value: 'postal' },
  { label: 'クロネコヤマト', value: 'kuroneko' },
  { label: 'ゆうパック', value: 'yupack' },
  { label: 'クリックポスト', value: 'clickpost' },
  { label: 'ゆうパケット', value: 'yupacket' },
]

const shippingDaysOptions = [
  { label: '1~2天', value: '1_2_days' },
  { label: '2~3天', value: '2_3_days' },
  { label: '4~7天', value: '4_7_days' },
]

const shippingFromCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

const shippingFromCascaderOptions = computed(() => {
  return JP_REGION_OPTIONS.map((r) => ({
    value: `${SHIPPING_FROM_REGION_PREFIX}${r.id}`,
    label: r.label,
    children: r.areaIds
      .map((aid) => {
        const a = MERCARI_AREAS.find((x) => x.id === aid)
        return a
          ? { value: `${SHIPPING_FROM_AREA_PREFIX}${a.id}`, label: a.name }
          : null
      })
      .filter(Boolean),
  }))
})

function buildShippingFromPath(areaId) {
  if (!areaId) return []
  const regionId = getRegionIdForAreaId(areaId)
  if (!regionId) return []
  return [
    `${SHIPPING_FROM_REGION_PREFIX}${regionId}`,
    `${SHIPPING_FROM_AREA_PREFIX}${areaId}`,
  ]
}

function handleShippingFromChange(path) {
  const last = Array.isArray(path) ? path[path.length - 1] : path
  if (!last || !String(last).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
    form.value.shipping_from = ''
    return
  }
  form.value.shipping_from = String(last).slice(SHIPPING_FROM_AREA_PREFIX.length)
}

const dialogTitle = computed(() => {
  if (props.bundleId) return `合并购买请求详情 · ${props.bundleId}`
  return '合并购买请求详情'
})

const differsFromOriginal = computed(() => {
  if (!bundle.value) return false
  const a = Number(bundle.value.original_price || 0)
  const b = Number(bundle.value.suggested_price || 0)
  return a > 0 && a !== b
})

function bundleStateLabel(state) {
  const map = {
    NOTIFIED: '待处理',
    ACCEPTED: '已承诺',
    REJECTED: '已拒绝',
    EXPIRED: '已过期',
  }
  return map[state] || state || '-'
}

function formatYen(n) {
  const v = Number(n || 0)
  if (!v) return '0'
  return v.toLocaleString('ja-JP')
}

function displayTs(ms) {
  const n = Number(ms || 0)
  if (!n) return '-'
  const d = new Date(n)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function applyBundleToForm(row) {
  bundle.value = row || null
  items.value = Array.isArray(row?.items) ? row.items : []
  const seedArea = normalizeShippingFromSeed(row?.form_shipping_from)
  form.value = {
    shipping_payer: row?.form_shipping_payer || '',
    shipping_method: row?.form_shipping_method || '',
    shipping_from: seedArea,
    shipping_days: row?.form_shipping_days || '',
  }
  shippingFromPath.value = buildShippingFromPath(seedArea)
}

function resetState() {
  bundle.value = null
  items.value = []
  form.value = {
    shipping_payer: '',
    shipping_method: '',
    shipping_from: '',
    shipping_days: '',
  }
  shippingFromPath.value = []
}

async function loadDetail() {
  if (!props.bundleId) return false
  try {
    const params = props.accountId ? { account_id: props.accountId } : undefined
    const row = await notificationsApi.bundlePurchaseDetail(props.bundleId, params)
    applyBundleToForm(row)
    return true
  } catch (e) {
    if (e?.response?.status === 404) return false
    ElMessage.error(e?.message || '加载失败')
    return false
  }
}

async function runSync() {
  if (!props.bundleId) return
  loading.value = true
  try {
    await notificationsApi.bundlePurchaseSync({
      bundle_id: props.bundleId,
      account_id: props.accountId || null,
      notification_id: props.notificationId || null,
    })
    await loadDetail()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '同步失败')
  } finally {
    loading.value = false
  }
}

async function onAccept() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  accepting.value = true
  try {
    await notificationsApi.bundlePurchaseDecide(props.bundleId, {
      action: 'accept',
      account_id: props.accountId || null,
      shipping_payer: form.value.shipping_payer || null,
      shipping_method: form.value.shipping_method || null,
      shipping_from: form.value.shipping_from || null,
      shipping_days: form.value.shipping_days || null,
    })
    ElMessage.success('已点击「依頼を承諾する」')
    emit('decided', {
      bundle_id: props.bundleId,
      account_id: props.accountId || null,
      action: 'accept',
    })
    emit('update:modelValue', false)
    resetState()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '承诺失败')
  } finally {
    accepting.value = false
  }
}

async function onReject() {
  rejecting.value = true
  try {
    await notificationsApi.bundlePurchaseDecide(props.bundleId, {
      action: 'reject',
      account_id: props.accountId || null,
    })
    ElMessage.success('已点击「依頼を断る」')
    emit('decided', {
      bundle_id: props.bundleId,
      account_id: props.accountId || null,
      action: 'reject',
    })
    emit('update:modelValue', false)
    resetState()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '取消失败')
  } finally {
    rejecting.value = false
  }
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
  if (!v) {
    resetState()
  }
}

watch(
  () => [props.modelValue, props.bundleId],
  async ([open, bid]) => {
    if (!open || !bid) return
    loading.value = true
    try {
      const ok = await loadDetail()
      if (!ok) {
        // 本地无缓存 → 自动触发一次捕获
        await runSync()
      }
    } finally {
      loading.value = false
    }
  },
  { immediate: false },
)
</script>

<style scoped>
.bundle-meta {
  margin-top: 4px;
}
.section-title {
  margin: 16px 0 8px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.bundle-items :deep(.el-table__cell) {
  vertical-align: middle;
}
.thumb {
  width: 56px;
  height: 56px;
  border-radius: 6px;
  display: block;
}
.item-name {
  font-size: 13px;
  line-height: 1.4;
  color: var(--el-text-color-primary);
  word-break: break-all;
}
.item-id {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.amount {
  font-weight: 600;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 4px;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
