<template>
  <div>
    <el-card shadow="never" class="search-card">
      <el-row :gutter="0" align="middle" class="search-row">
        <el-col :xs="24" :md="14" class="search-left-group">
          <el-input
            v-model="filters.keyword"
            placeholder="搜索商品 ID、标题、商品说明"
            clearable
            @change="onFilterChange"
          />
          <el-select
            v-model="filters.seller_id"
            placeholder="卖家（煤炉ID）"
            clearable
            filterable
            style="min-width: 200px; width: 100%"
            @change="onFilterChange"
          >
            <el-option
              v-for="s in sellerOptions"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-col>
        <el-col :xs="24" :md="10" class="search-actions">
          <el-button type="primary" :icon="Download" :loading="syncLoading" @click="openSyncDialog">
            从煤炉同步
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        :data="displayList"
        v-loading="loading"
        stripe
        row-key="item_id"
        :row-class-name="onSaleRowClassName"
        @expand-change="onTableExpandChange"
      >
        <el-table-column type="expand" width="44">
          <template #default="props">
            <div v-loading="expandSlot(props.row.item_id)?.loading" class="os-expand-wrap">
              <el-table
                :data="expandSlot(props.row.item_id)?.rows || []"
                border
                size="small"
                class="os-expand-table"
                empty-text="暂无数据，展开后自动加载"
              >
                <el-table-column label="管理ID" width="120" align="center">
                  <template #default="{ row: r }">
                    <div v-if="resolvedMgmtIdsForRow(r).length" class="multi-line-cell">
                      <div v-for="(mid, idx) in resolvedMgmtIdsForRow(r)" :key="`mgmt-${idx}`">{{ mid }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="条码" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`bc-${idx}`">{{ ln.barcode || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="商品名称" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`name-${idx}`">{{ ln.inventory_name || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="存储位置" min-width="180" show-overflow-tooltip>
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`loc-${idx}`">{{ ln.location || '-' }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="在售数" width="90" align="center">
                  <template #default="{ row: r }">
                    <div v-if="inventoryLines(r).length" class="multi-line-cell">
                      <div v-for="(ln, idx) in inventoryLines(r)" :key="`qty-${idx}`">{{ ln.on_sale_quantity ?? 0 }}</div>
                    </div>
                    <span v-else class="cell-muted">-</span>
                  </template>
                </el-table-column>
                <el-table-column label="更新" width="140" align="center">
                  <template #default="{ row: r }">{{ displayTs(r.updated) }}</template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="图" width="72" align="center" header-align="center" fixed>
          <template #default="{ row }">
            <el-image
              v-if="firstThumb(row)"
              class="os-thumb"
              :src="firstThumb(row)"
              :preview-src-list="thumbPreviewList(row)"
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
        <el-table-column label="商品ID" prop="item_id" width="128" show-overflow-tooltip align="center" header-align="center" />
        <el-table-column label="卖家" prop="seller_name" width="120" show-overflow-tooltip align="center" header-align="center">
          <template #default="{ row }">
            <span>{{ row.seller_name || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="标题" prop="name" min-width="200" show-overflow-tooltip align="left" header-align="center" />
        <el-table-column label="价格¥" width="88" align="center" header-align="center">
          <template #default="{ row }">{{ Number(row.price || 0) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="112" align="center" header-align="center">
          <template #default="{ row }">
            <el-tag :type="onSaleStatusTagType(row.status)" size="small" effect="light">
              {{ onSaleStatusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="赞/评" width="76" align="center" header-align="center">
          <template #default="{ row }">{{ row.num_likes ?? 0 }}/{{ row.num_comments ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="PV/近7日" width="100" align="center" header-align="center">
          <template #default="{ row }">{{ row.item_pv ?? 0 }}/{{ row.recent_item_pv ?? 0 }}</template>
        </el-table-column>
        <el-table-column label="搜索曝光" width="108" align="center" header-align="center">
          <template #default="{ row }">
            <span v-if="row.search_impression != null">{{ row.search_impression }}/{{ row.recent_search_impression ?? '-' }}</span>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="拍卖" width="72" align="center" header-align="center">
          <template #default="{ row }">
            <el-popover v-if="row.auction_info_json" placement="left" :width="280" trigger="click">
              <template #reference>
                <el-button link type="primary" size="small">查看</el-button>
              </template>
              <pre class="auction-pre">{{ formatJsonPretty(row.auction_info_json) }}</pre>
            </el-popover>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="创建" width="160" align="center" header-align="center">
          <template #default="{ row }">{{ displayTs(row.created) }}</template>
        </el-table-column>
        <el-table-column label="更新" width="160" align="center" header-align="center">
          <template #default="{ row }">{{ displayTs(row.updated) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right" align="center" header-align="center">
          <template #default="{ row }">
            <el-button
              :type="hasDetailViewable(row) ? 'success' : 'warning'"
              link
              size="small"
              :loading="detailLoadingIds.has(String(row.item_id || '').trim())"
              @click="onDetailActionClick(row)"
            >
              {{ hasDetailViewable(row) ? '查看详情' : '获取详情' }}
            </el-button>
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

    <el-dialog
      v-model="detailViewVisible"
      title="在售商品详情"
      width="760px"
      class="on-sale-detail-dialog"
      destroy-on-close
      @closed="onDetailViewClosed"
    >
      <div v-loading="detailViewLoading" class="detail-view-body">
        <template v-if="detailViewBase">
          <div class="detail-section-title">煤炉侧信息</div>
          <el-descriptions :column="2" border size="small" class="detail-desc">
            <el-descriptions-item label="商品 ID" :span="1">{{ detailViewBase.item_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="状态" :span="1">
              <el-tag :type="onSaleStatusTagType(detailViewBase.status)" size="small" effect="light">
                {{ onSaleStatusLabel(detailViewBase.status) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="标题" :span="2">{{ detailViewBase.name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="价格（日元）" :span="1">{{ Number(detailViewBase.price || 0) }}</el-descriptions-item>
            <el-descriptions-item label="卖家" :span="1">
              {{ detailViewBase.seller_name || '-' }}
              <span v-if="detailViewBase.seller_id" class="cell-muted">（{{ detailViewBase.seller_id }}）</span>
            </el-descriptions-item>
            <el-descriptions-item label="煤炉更新" :span="1">{{ displayTs(detailViewBase.updated) }}</el-descriptions-item>
            <el-descriptions-item label="本地同步" :span="1">{{ displayTs(detailViewBase.synced_at) }}</el-descriptions-item>
          </el-descriptions>

          <div class="detail-section-title">商品说明（煤炉）</div>
          <div v-if="detailListingBodyText" class="detail-listing-body-wrap">
            <el-input
              type="textarea"
              :model-value="detailListingBodyText"
              readonly
              :autosize="{ minRows: 10, maxRows: 22 }"
            />
          </div>
          <el-empty v-else description="暂无已保存的商品说明，请使用「获取详情」或下方「重新从煤炉获取」" :image-size="48" />

          <div class="detail-section-title">库存关联摘要</div>
          <el-descriptions :column="1" border size="small" class="detail-desc">
            <el-descriptions-item label="匹配条数">{{ Number(detailViewBase.inventory_match_count || 0) }}</el-descriptions-item>
            <el-descriptions-item label="管理 ID（汇总）">
              <span v-if="detailMgmtIdsText">{{ detailMgmtIdsText }}</span>
              <span v-else class="cell-muted">-</span>
            </el-descriptions-item>
            <el-descriptions-item label="条码（汇总）">
              <span v-if="(detailViewBase.inventory_barcodes_text || '').trim()">{{ detailViewBase.inventory_barcodes_text }}</span>
              <span v-else class="cell-muted">-</span>
            </el-descriptions-item>
            <el-descriptions-item v-if="(detailViewBase.inventory_locations_text || '').trim()" label="位置（汇总）">
              {{ detailViewBase.inventory_locations_text }}
            </el-descriptions-item>
          </el-descriptions>

          <div class="detail-section-title">关联库存明细</div>
          <el-table
            v-if="detailInventoryLines.length"
            :data="detailInventoryLines"
            border
            stripe
            size="small"
            max-height="320"
            class="detail-inv-table"
          >
            <el-table-column prop="management_id" label="管理 ID" width="100" align="center" />
            <el-table-column prop="barcode" label="条码" min-width="140" show-overflow-tooltip />
            <el-table-column prop="inventory_name" label="库存名称" min-width="160" show-overflow-tooltip />
            <el-table-column prop="location" label="存储位置" min-width="140" show-overflow-tooltip />
            <el-table-column prop="on_sale_quantity" label="在售数" width="88" align="center" />
          </el-table>
          <el-empty v-else description="暂无解析出的库存行（可尝试重新从煤炉获取）" :image-size="56" />
        </template>
      </div>
      <template #footer>
        <el-button @click="detailViewVisible = false">关闭</el-button>
        <el-button
          v-if="detailViewBase"
          type="danger"
          plain
          :loading="deleteItemLoading"
          @click="deleteMercariItemFromDetail"
        >
          删除物品
        </el-button>
        <el-button
          v-if="detailViewBase"
          type="primary"
          plain
          :loading="detailLoadingIds.has(String(detailViewBase.item_id || '').trim())"
          @click="detailViewRefreshFromMercari"
        >
          重新从煤炉获取
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="syncVisible" title="从煤炉同步在售列表" width="420px" destroy-on-close>
      <el-form label-width="88px">
        <el-form-item label="煤炉账号">
          <el-select
            v-model="syncAccountId"
            style="width: 100%"
            :loading="accountsLoading"
          >
            <el-option
              v-for="acc in accountOptions"
              :key="acc.id"
              :label="acc.account_name"
              :value="acc.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="syncVisible = false">取消</el-button>
        <el-button type="primary" :loading="syncLoading" @click="runSync">开始同步</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download } from '@element-plus/icons-vue'
import { onSaleItemApi, meiluAccountApi, webDriveApi } from '@/api/index.js'
import { parseMgmtIdsFromDescription } from '@/utils/mgmtIdCipher.js'

/** 煤炉商品 item.status → 中文（与 API 原始值对应） */
const onSaleStatusMap = {
  on_sale: { label: '出售中', tag: 'success' },
  stop: { label: '暂停出售', tag: 'warning' },
  trading: { label: '交易中', tag: 'primary' },
  wait_payment: { label: '待支付', tag: 'warning' },
  wait_shipping: { label: '待发货', tag: 'warning' },
  wait_review: { label: '待评价', tag: 'primary' },
  sold_out: { label: '已售完', tag: 'info' },
  done: { label: '已完成', tag: 'success' },
  cancelled: { label: '已取消', tag: 'info' },
  cancel_request: { label: '取消申请中', tag: 'danger' },
  deleted: { label: '已删除', tag: 'danger' },
  private: { label: '非公开', tag: 'info' },
  pending: { label: '待处理', tag: 'info' },
}

function onSaleStatusLabel(status) {
  if (status == null || status === '') return '-'
  const s = String(status).trim()
  return onSaleStatusMap[s]?.label ?? s
}

function onSaleStatusTagType(status) {
  const s = String(status ?? '').trim()
  return onSaleStatusMap[s]?.tag ?? 'info'
}

const loading = ref(false)
/** 正在请求 items/get 的商品 ID（trim 后） */
const detailLoadingIds = ref(new Set())
const syncLoading = ref(false)
const syncVisible = ref(false)
const syncAccountId = ref(null)
const accountOptions = ref([])
const accountsLoading = ref(false)

/** 查看详情弹窗 */
const detailViewVisible = ref(false)
const detailViewLoading = ref(false)
const detailViewBase = ref(null)
const detailViewOnSaleItems = ref([])
const deleteItemLoading = ref(false)

const detailInventoryLines = computed(() => {
  const items = detailViewOnSaleItems.value
  if (Array.isArray(items) && items.length > 0) {
    const acc = []
    for (const it of items) {
      for (const ln of inventoryLines(it)) {
        acc.push(ln)
      }
    }
    if (acc.length) return acc
  }
  const base = detailViewBase.value
  return base ? inventoryLines(base) : []
})

/** 弹窗内展示：优先列表行上的 listing_description，否则明细接口返回的行 */
const detailListingBodyText = computed(() => {
  const base = detailViewBase.value
  if (base && String(base.listing_description ?? '').trim()) {
    return String(base.listing_description)
  }
  const items = detailViewOnSaleItems.value
  if (Array.isArray(items) && items.length) {
    for (const it of items) {
      const t = String(it?.listing_description ?? '').trim()
      if (t) return String(it.listing_description)
    }
  }
  return ''
})

const list = ref([])
/** 展开区：key 为 trim 后的 item_id */
const expandByItemId = reactive({})
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = ref({
  keyword: '',
  seller_id: '',
})

const sellerFromAccounts = ref([])

function isOnSaleZeroStockAlert(row) {
  if (!row || typeof row !== 'object') return false
  const status = String(row.status ?? '').trim()
  if (status !== 'on_sale') return false
  const q = Number(row.inventory_quantity)
  if (!Number.isFinite(q)) return false
  return q <= 0
}

const displayList = computed(() => {
  return Array.isArray(list.value) ? list.value : []
})

function onSaleRowClassName({ row }) {
  return isOnSaleZeroStockAlert(row) ? 'on-sale-stock-alert-row' : ''
}

const sellerOptions = computed(() => {
  const m = new Map()
  for (const s of sellerFromAccounts.value) {
    if (s?.value) m.set(String(s.value), s)
  }
  for (const row of list.value) {
    const sid = row.seller_id
    if (sid != null && String(sid).trim()) {
      const k = String(sid).trim()
      if (!m.has(k)) m.set(k, { value: k, label: `卖家 ${k}` })
    }
  }
  return Array.from(m.values())
})

function listParams() {
  const p = { page: page.value, page_size: pageSize.value }
  if (filters.value.keyword?.trim()) p.keyword = filters.value.keyword.trim()
  if (filters.value.seller_id?.trim()) p.seller_id = filters.value.seller_id.trim()
  return p
}

function expandKey(itemId) {
  return String(itemId ?? '').trim()
}

function expandSlot(itemId) {
  const k = expandKey(itemId)
  return k ? expandByItemId[k] : null
}

function hasSecondaryData(row) {
  if (!row || typeof row !== 'object') return false
  const mgmt = String(row.inventory_mgmt_ids_text || '').trim()
  const barcodes = String(row.inventory_barcodes_text || '').trim()
  const descMgmt = String(row.description_mgmt_ids_text || '').trim()
  const matched = Number(row.inventory_match_count || 0)
  return Boolean(mgmt || barcodes || descMgmt || matched > 0)
}

function hasStoredListingDescription(row) {
  if (!row || typeof row !== 'object') return false
  return Boolean(String(row.listing_description ?? '').trim())
}

/** 已有关联库存或已拉取并保存过商品说明时，可打开「查看详情」 */
function hasDetailViewable(row) {
  return hasSecondaryData(row) || hasStoredListingDescription(row)
}

function inventoryLines(row) {
  if (!row || !Array.isArray(row.inventory_lines)) return []
  return row.inventory_lines
}

/** 管理 ID：优先库存关联行，否则从说明暗号/明文解析 */
function resolvedMgmtIdsForRow(row) {
  const lines = inventoryLines(row)
  if (lines.length) {
    return lines.map((ln) => String(ln.management_id || '').trim()).filter(Boolean)
  }
  const linked = String(row?.inventory_mgmt_ids_text || '').trim()
  if (linked) {
    return linked.split(/[、,，\s]+/).map((s) => s.trim()).filter(Boolean)
  }
  const fromDesc = String(row?.description_mgmt_ids_text || '').trim()
  if (fromDesc) {
    return fromDesc.split(/[、,，\s]+/).map((s) => s.trim()).filter(Boolean)
  }
  const desc = String(row?.listing_description || '').trim()
  if (desc) {
    return parseMgmtIdsFromDescription(desc).map(String)
  }
  return []
}

const detailMgmtIdsText = computed(() => {
  const base = detailViewBase.value
  if (!base) return ''
  const linked = String(base.inventory_mgmt_ids_text || '').trim()
  if (linked) return linked
  const hint = String(base.description_mgmt_ids_text || '').trim()
  if (hint) return hint
  const fromBody = parseMgmtIdsFromDescription(detailListingBodyText.value)
  if (fromBody.length) return fromBody.join('、')
  return ''
})

async function ensureExpandLoaded(row) {
  const k = expandKey(row.item_id)
  if (!k) return
  if (!expandByItemId[k]) {
    expandByItemId[k] = { loading: false, loaded: false, rows: [], total: 0 }
  }
  const slot = expandByItemId[k]
  if (slot.loaded || slot.loading) return
  slot.loading = true
  try {
    const res = await onSaleItemApi.listByItemId({ item_id: k })
    slot.rows = res.items || []
    slot.total = res.total != null ? res.total : slot.rows.length
    slot.loaded = true
  } catch {
    slot.rows = []
    slot.total = 0
    slot.loaded = true
  } finally {
    slot.loading = false
  }
}

/** 展开行时按商品 ID 拉取在售表明细（二级表格） */
function onTableExpandChange(row, expandedRows) {
  const k = expandKey(row.item_id)
  if (!k) return
  const opened = expandedRows.some((r) => expandKey(r.item_id) === k)
  if (opened) ensureExpandLoaded(row)
}

async function load() {
  loading.value = true
  try {
    const res = await onSaleItemApi.list(listParams())
    list.value = res.items || []
    total.value = res.total || 0
    for (const k of Object.keys(expandByItemId)) {
      delete expandByItemId[k]
    }
  } finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  load()
}

const pad2 = (n) => String(n).padStart(2, '0')

function displayTs(sec) {
  if (sec == null || sec === '') return '-'
  const n = Number(sec)
  if (!Number.isFinite(n)) return String(sec)
  const ms = n > 1e12 ? n : n * 1000
  const d = new Date(ms)
  if (Number.isNaN(d.getTime())) return String(sec)
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

function thumbPreviewList(row) {
  const raw = row.thumbnails
  if (!raw) return []
  if (Array.isArray(raw)) {
    return raw.map((u) => String(u).trim()).filter(Boolean)
  }
  if (typeof raw === 'string') {
    try {
      const arr = JSON.parse(raw)
      if (Array.isArray(arr)) {
        return arr.map((u) => String(u).trim()).filter(Boolean)
      }
    } catch {
      /* ignore */
    }
  }
  return []
}

function firstThumb(row) {
  const urls = thumbPreviewList(row)
  return urls.length ? urls[0] : ''
}

function formatJsonPretty(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return String(raw || '')
  }
}

function onDetailActionClick(row) {
  if (hasDetailViewable(row)) {
    openDetailView(row)
  } else {
    fetchItemDetail(row)
  }
}

async function openDetailView(row) {
  if (!row) return
  detailViewBase.value = { ...row }
  detailViewVisible.value = true
  const k = expandKey(row.item_id)
  if (!k) return
  detailViewLoading.value = true
  detailViewOnSaleItems.value = []
  try {
    const res = await onSaleItemApi.listByItemId({ item_id: k })
    detailViewOnSaleItems.value = res.items || []
  } catch {
    detailViewOnSaleItems.value = []
  } finally {
    detailViewLoading.value = false
  }
}

function onDetailViewClosed() {
  detailViewBase.value = null
  detailViewOnSaleItems.value = []
}

function resolveAccountKeyForRow(row) {
  const sid = String(row?.seller_id || '').trim()
  if (!sid) return null
  const matched = sellerFromAccounts.value.find((a) => String(a.seller_id || '').trim() === sid)
  if (!matched?.id) return null
  return { accountKey: `meilu_${matched.id}`, sellerId: sid }
}

async function deleteMercariItemFromDetail() {
  const base = detailViewBase.value
  if (!base?.item_id) {
    ElMessage.warning('缺少商品 ID')
    return
  }
  const iid = String(base.item_id || '').trim()
  const resolved = resolveAccountKeyForRow(base)
  if (!resolved) {
    ElMessage.warning(`未找到卖家 ${String(base.seller_id || '').trim() || '-'} 对应的 active 账号`)
    return
  }
  try {
    await ElMessageBox.confirm(
      `将使用无头浏览器在煤炉删除商品 ${iid} 并自动同步列表，此操作不可撤销。请确保该账号 Cookie 有效。`,
      '删除物品',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  if (deleteItemLoading.value) return
  deleteItemLoading.value = true
  try {
    const res = await webDriveApi.deleteMercariItem({
      account_key: resolved.accountKey,
      item_id: iid,
      use_mitm_proxy: true
    })
    const d = res?.data || {}
    const sync = d.sync || {}
    if (d.delete_confirmed && sync && typeof sync === 'object') {
      ElMessage.success(
        `已删除商品 ${iid}，列表已同步：煤炉 ${sync.api_item_count ?? 0} 条，更新 ${sync.updated ?? 0}，标记删除 ${sync.marked_deleted ?? 0}`
      )
    } else if (d.delete_confirmed) {
      ElMessage.success(`已在煤炉删除商品 ${iid}`)
    } else {
      ElMessage.warning('删除流程已执行，请检查浏览器中的煤炉页面')
    }
    detailViewVisible.value = false
    await load()
  } catch {
    /* 错误由 axios 拦截器提示 */
  } finally {
    deleteItemLoading.value = false
  }
}

async function detailViewRefreshFromMercari() {
  const base = detailViewBase.value
  if (!base?.item_id) return
  await fetchItemDetailForItemId(base.item_id, { reloadAfter: true })
  const k = expandKey(base.item_id)
  const found = list.value.find((r) => expandKey(r.item_id) === k)
  if (found) {
    detailViewBase.value = { ...found }
  }
  detailViewLoading.value = true
  try {
    const res = await onSaleItemApi.listByItemId({ item_id: k })
    detailViewOnSaleItems.value = res.items || []
  } catch {
    detailViewOnSaleItems.value = []
  } finally {
    detailViewLoading.value = false
  }
}

async function fetchItemDetailForItemId(itemId, options = {}) {
  const { accountId = null, silent = false, reloadAfter = true } = options
  const iid = String(itemId || '').trim()
  if (!iid) {
    if (!silent) ElMessage.warning('缺少商品 ID')
    return { ok: false }
  }
  if (detailLoadingIds.value.has(iid)) return { ok: false, skipped: true }
  const next = new Set(detailLoadingIds.value)
  next.add(iid)
  detailLoadingIds.value = next
  try {
    const payload = { item_id: iid }
    if (accountId != null && accountId !== '') payload.account_id = accountId
    const res = await onSaleItemApi.fetchDetail(payload)
    const sync = res?.data?.sync || {}
    const ok = Boolean(sync.updated)
    if (!silent) {
      if (ok) {
        ElMessage.success(
          sync.message ||
            `已关联 ${sync.inventory_ids?.length ?? 0} 条库存，煤炉 ID ${sync.mercari_item_id}`
        )
      } else {
        ElMessage.warning(sync.message || '未写入库存（请检查说明中的管理番号/条码与账号 DPoP_ItemGet-Info）')
      }
    }
    if (reloadAfter) await load()
    return { ok, sync }
  } finally {
    const done = new Set(detailLoadingIds.value)
    done.delete(iid)
    detailLoadingIds.value = done
  }
}

async function fetchItemDetail(row) {
  await fetchItemDetailForItemId(row.item_id)
}

async function openSyncDialog() {
  syncVisible.value = true
  syncAccountId.value = null
  accountsLoading.value = true
  try {
    const res = await meiluAccountApi.list({ page: 1, page_size: 100 })
    accountOptions.value = (res.items || []).filter((a) => a.status === 'active')
    syncAccountId.value = accountOptions.value[0]?.id ?? null
  } catch {
    accountOptions.value = []
    syncAccountId.value = null
  } finally {
    accountsLoading.value = false
  }
}

async function runSync() {
  syncLoading.value = true
  try {
    const payload = {}
    if (syncAccountId.value) payload.account_id = syncAccountId.value
    const res = await onSaleItemApi.sync(payload, { timeout: 0 })
    const d = res.data || {}
    ElMessage.success(
      `同步完成：煤炉 ${d.api_item_count ?? 0} 条，新增 ${d.inserted ?? 0}，更新 ${d.updated ?? 0}，标记删除 ${d.marked_deleted ?? 0}`
    )
    syncVisible.value = false
    await load()

    const rawNewIds = Array.isArray(d.inserted_item_ids) ? d.inserted_item_ids : []
    const newIds = rawNewIds.map((x) => String(x ?? '').trim()).filter(Boolean)
    if (newIds.length > 0) {
      const aid = syncAccountId.value
      const batchRes = await onSaleItemApi.fetchDetailsBatch(
        { account_id: aid, item_ids: newIds },
        { timeout: 0 }
      )
      const bd = batchRes.data || {}
      const okN = Number(bd.ok_synced ?? 0) || 0
      const failN = Number(bd.not_ok ?? 0) || 0
      await load()
      ElMessage.info(
        `新增商品已自动获取详情：成功关联库存 ${okN} 条，未写入 ${failN} 条（请核对商品说明与 DPoP_ItemGet-Info）`
      )
    }
  } finally {
    syncLoading.value = false
  }
}

async function loadSellerAccounts() {
  try {
    const res = await meiluAccountApi.list({ page: 1, page_size: 200 })
    sellerFromAccounts.value = (res.items || [])
      .filter((a) => a.status === 'active' && (a.seller_id || '').toString().trim())
      .map((a) => ({
        id: a.id,
        seller_id: String(a.seller_id).trim(),
        value: String(a.seller_id).trim(),
        label: `${a.account_name} (${a.seller_id})`,
      }))
  } catch {
    sellerFromAccounts.value = []
  }
}

onMounted(() => {
  loadSellerAccounts()
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
}
.search-left-group {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.search-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}
.table-card {
  border-radius: 8px;
}
.os-thumb {
  width: 48px;
  height: 48px;
  border-radius: 4px;
  display: block;
  cursor: zoom-in;
}
.thumb-fallback {
  color: #909399;
  font-size: 12px;
}
.cell-muted {
  color: #909399;
}
.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.auction-pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
}
.os-expand-wrap {
  padding: 8px 12px 12px 36px;
  max-width: 100%;
}
.os-expand-table {
  width: 100%;
}
.multi-line-cell {
  display: flex;
  flex-direction: column;
}
.multi-line-cell > div {
  min-height: 38px;
  line-height: 38px;
  box-sizing: border-box;
}
:deep(.on-sale-stock-alert-row) {
  --el-table-tr-bg-color: #3a1517;
}
:deep(.on-sale-stock-alert-row td) {
  background-color: #3a1517 !important;
}
:deep(.on-sale-stock-alert-row:hover > td) {
  background-color: #4a1a1d !important;
}
:deep(.on-sale-stock-alert-row td .cell) {
  color: #ffd6d9;
  font-weight: 600;
}

.detail-section-title {
  font-size: 14px;
  font-weight: 600;
  margin: 16px 0 10px;
  color: var(--el-text-color-primary);
}
.detail-section-title:first-of-type {
  margin-top: 0;
}
.detail-view-body {
  min-height: 80px;
}
.detail-desc {
  width: 100%;
}
.detail-inv-table {
  width: 100%;
}
.detail-listing-body-wrap :deep(.el-textarea__inner) {
  font-family: inherit;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
