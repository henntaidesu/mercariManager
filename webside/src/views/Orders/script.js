import { defineComponent, ref, computed, onMounted, watch, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessageBox } from 'element-plus'
import { ElMessage } from '@/utils/notify'
import { RefreshRight, Refresh, Plus, Minus, Loading } from '@element-plus/icons-vue'
import {
  orderApi,
  mercariApi,
  inventoryApi,
  costExpenseApi,
  costRecordApi,
  authApi,
} from '@/api/index.js'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncLockStore } from '@/stores/syncLock.js'
import {
  useInventoryListApiFilters,
  warehouseCascaderProps,
  productTypeCascaderProps,
} from '@/composables/useInventoryListApiFilters.js'
import {
  localYmdToDayStartTs,
  localYmdToDayEndTs,
} from '@/utils/orderStatsTime.js'
import { decodeMgmtIdCipher, parseMgmtIdsFromDescription } from '@/utils/mgmtIdCipher.js'
import { mercariImageUrlList } from '@/utils/mercariImage.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()
    const mercariAccountStore = useMercariAccountStore()
    const syncLockStore = useSyncLockStore()

    const orderTableRef = ref(null)
    /** 当前已展开的主表行（用于筛选变更时折叠，避免展开区与缓存不一致） */
    const lastExpandedRows = ref([])
    const ownerUsers = ref([])

    /** 当前登录用户是否为 admin（仅 admin 可使用「归属转化」） */
    const isAdminUser = computed(() => {
      try {
        const u = JSON.parse(localStorage.getItem('auth_user') || '{}')
        return String(u?.username || '').trim() === 'admin'
      } catch {
        return false
      }
    })

    const loading = ref(false)
    const statsLoading = ref(false)
    /** 与 Layout / 库存页一致：(max-width: 768px) */
    const isMobile = ref(false)
    const submitting = ref(false)
    /** 正在 Mercari 拉取详情的行 id */
    const refreshingId = ref(null)
    /** 二级列表：正在执行出库的明细键 order_no:line_id */
    const lineStockingKey = ref('')
    const manualOutboundDialogVisible = ref(false)
    const manualOutboundSaving = ref(false)
    const manualInventoryLoading = ref(false)
    const manualInventoryOptions = ref([])
    const bindOutboundDialogVisible = ref(false)
    const bindOutboundSaving = ref(false)
    const bindInventoryLoading = ref(false)
    const bindInventoryOptions = ref([])
    const bindOutboundContext = ref({
      order_no: '',
      line_id: 0,
      is_stocked_out: false,
      original_inventory_id: null,
    })
    const bindOutboundForm = ref({ inventory_id: null, quantity: 1 })
    const convertOwnerDialogVisible = ref(false)
    const convertOwnerSubmitting = ref(false)
    const convertOwnerContext = ref({
      order_no: '',
      line_id: 0,
      inventory_id: null,
      inventory_label: '',
      current_owner_user_id: null,
      current_owner_name: '',
      quantity: 1,
      is_stocked_out: false,
    })
    const convertOwnerForm = ref({ owner_user_id: null })
    const convertOwnerCanSubmit = computed(() => {
      const oid = convertOwnerForm.value.owner_user_id
      if (oid == null) return false
      if (Number(oid) <= 0) return false
      if (Number(oid) === Number(convertOwnerContext.value.current_owner_user_id)) return false
      return Number(convertOwnerContext.value.line_id || 0) > 0
    })
    const packagingItemsOptions = ref([])
    // 每个订单的「添加包材」下拉是否展开（点击按钮后才显示下拉框）
    const packagingAddingOpen = ref({})
    let _manualObRowKeySeq = 0
    function newManualOutboundRowKey() {
      _manualObRowKeySeq += 1
      return `mob-${_manualObRowKeySeq}`
    }

    const manualOutboundForm = ref({
      order_no: '',
      /** 出库明细行：同一 inventory_id 仅允许一行（与后端 batch 校验一致） */
      rows: [],
    })

    function scheduleManualInvReload() {
      void reloadManualInventoryList()
    }
    const manualInvFilters = useInventoryListApiFilters(scheduleManualInvReload)
    const manualInvWarehouseCascaderProps = warehouseCascaderProps
    const manualInvProductTypeCascaderProps = productTypeCascaderProps

    function scheduleBindInvReload() {
      void reloadBindInventoryList()
    }
    const bindInvFilters = useInventoryListApiFilters(scheduleBindInvReload)
    const bindInvWarehouseCascaderProps = warehouseCascaderProps
    const bindInvProductTypeCascaderProps = productTypeCascaderProps

    async function reloadManualInventoryList() {
      if (!manualOutboundDialogVisible.value) return
      manualInventoryLoading.value = true
      try {
        const res = await inventoryApi.list(
          manualInvFilters.buildInventoryListParams({ in_stock_only: true })
        )
        let next = Array.isArray(res) ? res : []
        const inList = new Set(next.map((x) => Number(x.id)))
        const selectedIds = [
          ...new Set(
            (manualOutboundForm.value.rows || [])
              .map((r) => Number(r?.inventory_id || 0))
              .filter((id) => Number.isFinite(id) && id > 0)
          ),
        ]
        const missing = selectedIds.filter((id) => !inList.has(id))
        if (missing.length) {
          const fetched = await Promise.all(
            missing.map((id) => inventoryApi.get(id).catch(() => null))
          )
          for (const one of fetched) {
            if (one && one.id != null) {
              next.push(one)
              inList.add(Number(one.id))
            }
          }
        }
        manualInventoryOptions.value = next
        const allowed = inList
        for (const row of manualOutboundForm.value.rows || []) {
          const iid = Number(row?.inventory_id || 0)
          if (Number.isFinite(iid) && iid > 0 && !allowed.has(iid)) {
            row.inventory_id = null
            row.quantity = 1
          }
        }
      } finally {
        manualInventoryLoading.value = false
      }
    }
    async function reloadBindInventoryList() {
      if (!bindOutboundDialogVisible.value) return
      bindInventoryLoading.value = true
      try {
        const res = await inventoryApi.list(
          bindInvFilters.buildInventoryListParams({ in_stock_only: true })
        )
        let next = Array.isArray(res) ? res : []
        const inList = new Set(next.map((x) => Number(x.id)))
        const selectedId = Number(bindOutboundForm.value.inventory_id || 0)
        if (Number.isFinite(selectedId) && selectedId > 0 && !inList.has(selectedId)) {
          const one = await inventoryApi.get(selectedId).catch(() => null)
          if (one && one.id != null) {
            next.push(one)
            inList.add(Number(one.id))
          }
        }
        bindInventoryOptions.value = next
        if (Number.isFinite(selectedId) && selectedId > 0 && !inList.has(selectedId)) {
          bindOutboundForm.value.inventory_id = null
        }
      } finally {
        bindInventoryLoading.value = false
      }
    }

    const stats = ref({
      total_count: 0,
      sum_amount: 0,
      sum_service_fee: 0,
      sum_shipping_fee: 0,
      sum_net_income: 0,
      sum_packaging: 0,
    })

    const packagingState = ref({})
    /** 包材下拉：与真实库存包材名称隔离，避免重名冲突 */
    const PACKAGING_ITEM_NONE = '__PACKAGING_NONE__'

    /** 与列表相同条件：keyword、状态、最后时间区间（order_updated_at 优先）；今日副指标为本地当日且仍满足相同 keyword/状态（同上时间口径）。汇总不含 status=cancelled（后端 stats 排除已取消）。 */
    const orderStatCards = computed(() => {
      const o = stats.value
      return [
        {
          label: t('dashboard.orderCount'),
          display: o.total_count ?? 0,
          icon: 'Document',
          color: '#409EFF',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.totalAmount'),
          display: Math.round(Number(o.sum_amount || 0)),
          icon: 'Money',
          color: '#E6A23C',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.serviceFee'),
          display: Math.round(Number(o.sum_service_fee || 0)),
          icon: 'Histogram',
          color: '#F56C6C',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.shippingFee'),
          display: Math.round(Number(o.sum_shipping_fee || 0)),
          icon: 'Box',
          color: '#F56C6C',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.packaging'),
          display: Math.round(Number(o.sum_packaging || 0)),
          icon: 'ShoppingCart',
          color: '#909399',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.netIncome'),
          display: Math.round(Number(o.sum_net_income || 0)),
          icon: 'TrendCharts',
          color: '#67C23A',
          cardClass: '',
          valueClass: '',
        },
      ]
    })

    /** 订单行展开：按 order_no 缓存出库明细 */
    const expandState = ref({})

    const list = ref([])
    const total = ref(0)
    const page = ref(1)
    const pageSize = ref(20)
    const dateRange = ref([])
    const dialogVisible = ref(false)
    const formRef = ref()

    const filters = ref({ keyword: '', status: '', owner_user_id: null })

    /** 与后端 routes.orders ORDER_STATUSES 一致（煤炉） */
    const ORDER_STATUS_KEYS = [
      'pending',
      'trading',
      'wait_payment',
      'wait_shipping',
      'wait_review',
      'done',
      'sold_out',
      'cancelled',
      'cancel_request',
    ]

    /** 展示用标签：value 与数据库/API 一致 */
    const statusMap = computed(() => ({
      pending:        { label: t('orders.statusPendingHandle'), tag: 'info' },
      trading:        { label: t('orders.statusTrading'), tag: 'warning' },
      wait_payment:   { label: t('orders.statusWaitPayment'), tag: 'warning' },
      wait_shipping:  { label: t('orders.statusPending'), tag: 'warning' },
      wait_review:    { label: t('orders.statusWaitReview'), tag: 'primary' },
      done:           { label: t('orders.statusCompleted'), tag: 'success' },
      sold_out:       { label: t('orders.statusSoldOut'), tag: 'info' },
      cancelled:      { label: t('orders.statusCancelled'), tag: 'info' },
      cancel_request: { label: t('orders.statusCancelRequest'), tag: 'danger' },
    }))

    /** 列表/统计筛选项：仅四种（与 load 条件一致） */
    const LIST_FILTER_STATUS_KEYS = ['wait_shipping', 'wait_review', 'done', 'cancelled']

    const orderListStatusFilterOptions = computed(() =>
      LIST_FILTER_STATUS_KEYS.filter((k) => statusMap.value[k]).map((value) => ({
        value,
        label: statusMap.value[value].label,
      }))
    )

    const orderStatusOptions = computed(() =>
      ORDER_STATUS_KEYS.filter((k) => statusMap.value[k]).map((value) => ({
        value,
        label: statusMap.value[value].label,
      }))
    )

    /** 编辑弹窗：若库里为旧版手工状态等未在 statusMap 中的值，补一项便于查看与改选 */
    const formOrderStatusOptions = computed(() => {
      const base = orderStatusOptions.value
      const cur = form.value?.status
      if (cur && !statusMap.value[cur]) {
        return [...base, { value: cur, label: t('orders.legacyStatusLabel', { status: cur }) }]
      }
      return base
    })

    // ---- 同步订单（更新列表 / 更新状态 共用，账号选择见工具栏全局下拉）----
    const syncLoading = ref(false)
    /** newData：增量入库出售中；statusRefresh：库内未完成订单批量刷新（与单行「刷新」相同接口） */
    const syncMode = ref('newData')

    /** 「更新列表 / 更新状态」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */
    const syncOverlayVisible = ref(false)
    const syncOverlayTitle = ref('')
    const syncOverlayFailed = ref(false)
    const syncProgressLabel = ref('')
    let syncProgressTimer = null

    async function runSync(mode = 'newData') {
      if (syncLoading.value) return
      const actionLabel = mode === 'statusRefresh' ? t('orders.actionBatchUpdateStatus') : t('orders.actionUpdateSellingList')
      try {
        await ElMessageBox.confirm(
          t('orders.confirmSyncMessage', { action: actionLabel }),
          t('orders.confirmSyncTitle'),
          { type: 'info', confirmButtonText: t('orders.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let lastConsoleStep = ''
      const consoleTag = mode === 'statusRefresh' ? '[更新状态]' : '[更新列表]'
      async function pollSyncProgress() {
        try {
          const pr = await mercariApi.getSyncProgress(progressJobId)
          const d = pr?.data
          const zh = d?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log(consoleTag, zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncMode.value = mode
      syncOverlayTitle.value = mode === 'statusRefresh' ? t('orders.updatingStatus') : t('orders.updatingList')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('orders.connectingServer')
      syncOverlayVisible.value = true
      syncLoading.value = true
      await pollSyncProgress()
      syncProgressTimer = setInterval(pollSyncProgress, 1000)

      let syncHadError = false
      try {
        const payload = { progress_job_id: progressJobId }
        if (mode === 'statusRefresh') {
          const res = await mercariApi.batchRefreshInfo(payload)
          const d = res.data || {}
          const failed = d.failed?.length ?? 0
          const msg = t('orders.statusRefreshDoneMsg', {
            total: d.total ?? 0,
            ok: d.ok ?? 0,
            skipped: d.skipped_no_account ?? 0,
            failed,
          })
          if (failed > 0) ElMessage.warning(msg)
          else ElMessage.success(msg)
        } else {
          const res = await mercariApi.syncNewData(payload)
          const d = res.data || {}
          ElMessage.success(
            t('orders.updateDoneMsg', {
              accountCount: d.account_count ?? 0,
              failCount: d.fail_count ?? 0,
              api: d.api_item_count ?? 0,
              pending: d.pending_new ?? 0,
              inserted: d.inserted ?? 0,
              enriched: d.info_enriched ?? 0,
            })
          )
        }
        load()
        loadStats()
      } catch (e) {
        syncHadError = true
        syncOverlayTitle.value = mode === 'statusRefresh' ? t('orders.updateStatusFailed') : t('orders.updateListFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('orders.syncFailed')
        syncProgressLabel.value = String(msg)
      } finally {
        if (syncProgressTimer != null) {
          clearInterval(syncProgressTimer)
          syncProgressTimer = null
        }
        if (syncHadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = ''
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        syncLoading.value = false
      }
    }

    function formatLocalDatetime(d = new Date()) {
      const pad = (n) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    }

    /** 旧数据仅 YYYY-MM-DD 时补全为当天 00:00:00（按 UTC 日界） */
    function normalizeDatetimeStr(v) {
      if (!v) return ''
      const s = String(v).trim()
      if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return `${s} 00:00:00`
      return s
    }

    const pad2 = (n) => String(n).padStart(2, '0')

    /**
     * 将服务端存库的 UTC 时间字符串解析为 Date（本地显示用）
     * 格式 YYYY-MM-DD 或 YYYY-MM-DD HH:mm:ss，均按 UTC 理解
     */
    function parseUtcDbToDate(v) {
      if (v == null || v === '') return null
      const s = normalizeDatetimeStr(String(v).trim())
      const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?$/)
      if (!m) return null
      const y = +m[1]
      const mo = +m[2] - 1
      const d = +m[3]
      const h = m[4] != null ? +m[4] : 0
      const mi = m[5] != null ? +m[5] : 0
      const sec = m[6] != null ? +m[6] : 0
      return new Date(Date.UTC(y, mo, d, h, mi, sec))
    }

    function formatLocalWallToStr(dt) {
      if (!dt || Number.isNaN(dt.getTime())) return ''
      return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())} ${pad2(dt.getHours())}:${pad2(dt.getMinutes())}:${pad2(dt.getSeconds())}`
    }

    /**
     * 存库值：优先 Unix 秒/毫秒时间戳；否则按旧版 UTC 字符串解析（兼容旧数据）
     */
    function tsOrLegacyToDate(v) {
      if (v == null || v === '') return null
      if (typeof v === 'number' && Number.isFinite(v)) {
        if (v > 1e11) return new Date(v)
        if (v > 1e8) return new Date(v * 1000)
        return null
      }
      const s = String(v).trim()
      if (/^\d+\.?\d*$/.test(s)) {
        const n = Number(s)
        if (Number.isFinite(n)) {
          if (n > 1e11) return new Date(n)
          if (n > 1e8) return new Date(n * 1000)
        }
      }
      return parseUtcDbToDate(v)
    }

    /** 表格：Unix 秒或旧串 -> 本地展示 */
    function displayTsLocal(v) {
      if (v == null || v === '') return '-'
      const dt = tsOrLegacyToDate(v)
      if (!dt || Number.isNaN(dt.getTime())) return String(v)
      return formatLocalWallToStr(dt)
    }

    /** 编辑弹窗：存库值 -> 选择器 value-format 串 */
    function tsOrLegacyToLocalForm(v) {
      if (v == null || v === '') return ''
      const dt = tsOrLegacyToDate(v)
      if (!dt || Number.isNaN(dt.getTime())) return normalizeDatetimeStr(String(v))
      return formatLocalWallToStr(dt)
    }

    /** 保存：本地 datetime 串 -> Unix 秒（null 表示清空可选字段） */
    function localFormStringToUnixSec(v) {
      if (!v || !String(v).trim()) return null
      const s = String(v).trim()
      const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}):(\d{2}))?$/)
      if (!m) return null
      const y = +m[1]
      const mo = +m[2] - 1
      const d = +m[3]
      const h = m[4] != null ? +m[4] : 0
      const mi = m[5] != null ? +m[5] : 0
      const sec = m[6] != null ? +m[6] : 0
      const local = new Date(y, mo, d, h, mi, sec)
      if (Number.isNaN(local.getTime())) return null
      return Math.floor(local.getTime() / 1000)
    }

    function optionalNumFromRow(v) {
      if (v == null || v === '') return undefined
      const n = Number(v)
      return Number.isNaN(n) ? undefined : n
    }

    function numOrNull(v) {
      if (v === null || v === undefined || v === '') return null
      const n = Number(v)
      return Number.isNaN(n) ? null : n
    }

    function optionalIntFromRow(v) {
      if (v == null || v === '') return undefined
      const n = Number.parseInt(String(v), 10)
      return Number.isNaN(n) ? undefined : n
    }

    function intOrNull(v) {
      if (v === null || v === undefined || v === '') return null
      const n = Number.parseInt(String(v), 10)
      return Number.isNaN(n) ? null : n
    }

    function thumbnailsToFormText(row) {
      const t = row.thumbnails
      if (t == null || t === '') return ''
      if (Array.isArray(t)) return JSON.stringify(t, null, 2)
      if (typeof t === 'string') {
        try {
          const o = JSON.parse(t)
          if (Array.isArray(o)) return JSON.stringify(o, null, 2)
        } catch {
          /* 原样展示 */
        }
        return t
      }
      return String(t)
    }

    /** 解析为 API 所需的 string[]；空串返回 null 表示清空或未传 */
    function parseThumbnailsPayload(text) {
      const raw = String(text ?? '').trim()
      if (!raw) return null
      try {
        const p = JSON.parse(raw)
        if (Array.isArray(p)) {
          const urls = p.map((s) => String(s).trim()).filter(Boolean)
          return urls.length ? urls : null
        }
      } catch {
        /* 按行/逗号拆分 */
      }
      const urls = raw.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
      return urls.length ? urls : null
    }

    /** 手续费 / 快递费 / 净收益列：null 表示无数据，单元格显示「-」；展示为整数（四舍五入） */
    function orderMoneyField(v) {
      if (v == null || v === '') return null
      const n = Number(v)
      if (Number.isNaN(n)) return null
      return String(Math.round(n))
    }

    /** 「手续/快递」合并列：手续费/快递费，缺失一侧显示 - */
    function formatFeeShippingCell(row) {
      const tax = orderMoneyField(row.service_fee)
      const ship = orderMoneyField(row.shipping_fee)
      const left = tax != null ? tax : '-'
      const right = ship != null ? ship : '-'
      if (left === '-' && right === '-') return '-'
      return `${left}/${right}`
    }

    /** thumbnails 为 JSON 字符串或数组时解析为 URL 列表（用于预览）；煤炉 CDN URL 经后端代理返回 */
    function thumbnailPreviewList(row) {
      const raw = row.thumbnails
      if (raw == null || raw === '') return []
      if (Array.isArray(raw)) {
        return mercariImageUrlList(
          raw.map((u) => (u != null && u !== '' ? String(u) : '')).filter(Boolean)
        )
      }
      if (typeof raw === 'string') {
        try {
          const arr = JSON.parse(raw)
          if (Array.isArray(arr)) {
            return mercariImageUrlList(
              arr.map((u) => (u != null && u !== '' ? String(u) : '')).filter(Boolean)
            )
          }
        } catch {
          return []
        }
      }
      return []
    }

    /** thumbnails 为 JSON 字符串或数组时取首张图 URL */
    function firstThumbUrl(row) {
      const list = thumbnailPreviewList(row)
      return list.length ? list[0] : ''
    }

    const createDefaultForm = () => ({
      id: null,
      order_no: '',
      order_date: formatLocalDatetime(),
      order_updated_at: '',
      purchase_time: '',
      data_user: '',
      customer_name: '',
      status: 'pending',
      amount: null,
      service_fee: undefined,
      net_income: undefined,
      carrier_display_name: '',
      request_class_display_name: '',
      shipping_fee: undefined,
      tracking_no: '',
      ship_confirm_code: '',
      transaction_evidence_id: undefined,
      remark: '',
      description: '',
      thumbnails_text: '',
    })

    const form = ref(createDefaultForm())

    /** 编辑订单弹窗：当前订单的包材合计金额（日元） */
    const formPackagingTotal = computed(() => {
      const ono = String(form.value.order_no || '').trim()
      return Math.round(Number(packagingState.value?.[ono]?.total_amount || 0))
    })

    const rules = computed(() => ({
      order_no: [{ required: true, message: t('orders.orderNumberPlaceholder'), trigger: 'blur' }],
      order_date: [{ required: true, message: t('orders.pleaseSelectOrderTime'), trigger: 'change' }],
      status: [{ required: true, message: t('orders.pleaseSelectOrderStatus'), trigger: 'change' }],
      amount: [{ required: true, message: t('orders.pleaseInputOrderAmount'), trigger: 'blur' }],
    }))

    const LIST_FILTER_STATUS_SET = new Set(LIST_FILTER_STATUS_KEYS)

    function listFilterParams() {
      const params = {}
      if (filters.value.keyword) params.keyword = filters.value.keyword
      const st = (filters.value.status || '').trim()
      if (st && LIST_FILTER_STATUS_SET.has(st)) params.status = st
      const ouid = filters.value.owner_user_id
      if (ouid != null && ouid !== '') {
        const n = Number(ouid)
        if (Number.isFinite(n) && n > 0) params.owner_user_id = n
      }
      if (dateRange.value?.length === 2) {
        const start = localYmdToDayStartTs(dateRange.value[0])
        const end = localYmdToDayEndTs(dateRange.value[1])
        if (start != null) params.start_ts = start
        if (end != null) params.end_ts = end
      }
      return params
    }

    /** 与列表「商品归属」筛选一致：展开区只请求该归属下的出库行（一单多归属时各显示各的） */
    function buildOutboundLinesParams(orderNo) {
      const ono = String(orderNo || '').trim()
      const params = { order_no: ono }
      const p = listFilterParams()
      if (p.owner_user_id != null) params.owner_user_id = p.owner_user_id
      return params
    }

    async function resetExpandAndCollapseRows() {
      const rows = [...(lastExpandedRows.value || [])]
      expandState.value = {}
      await nextTick()
      const tbl = orderTableRef.value
      if (tbl && typeof tbl.toggleRowExpansion === 'function') {
        rows.forEach((r) => {
          try {
            tbl.toggleRowExpansion(r, false)
          } catch (_) {
            /* ignore */
          }
        })
      }
      lastExpandedRows.value = []
    }

    function updateViewportState() {
      isMobile.value = window.matchMedia('(max-width: 768px)').matches
    }

    async function loadStats() {
      if (isMobile.value) return
      statsLoading.value = true
      try {
        const res = await orderApi.stats({
          ...listFilterParams(),
        })
        stats.value = {
          total_count: res.total_count ?? 0,
          sum_amount: res.sum_amount ?? 0,
          sum_service_fee: res.sum_service_fee ?? 0,
          sum_shipping_fee: res.sum_shipping_fee ?? 0,
          sum_net_income: res.sum_net_income ?? 0,
          sum_packaging: res.sum_packaging ?? 0,
        }
      } finally {
        statsLoading.value = false
      }
    }

    async function load() {
      loading.value = true
      const params = { page: page.value, page_size: pageSize.value, ...listFilterParams() }
      const res = await orderApi.list(params).finally(() => {
        loading.value = false
      })
      list.value = res.items || []
      total.value = res.total || 0
    }

    async function onFilterChange() {
      page.value = 1
      await resetExpandAndCollapseRows()
      load()
      loadStats()
    }

    async function resetFilters() {
      filters.value = { keyword: '', status: '', owner_user_id: null }
      dateRange.value = []
      page.value = 1
      await resetExpandAndCollapseRows()
      load()
      loadStats()
    }

    function clearOutboundExpandCache(orderNo) {
      const ono = String(orderNo || '').trim()
      if (!ono) return
      const next = { ...expandState.value }
      delete next[ono]
      expandState.value = next
    }

    const orderDescriptionMgmtHint = computed(() => {
      const ids = parseMgmtIdsFromDescription(form.value.description)
      if (!ids.length) return ''
      return t('orders.mgmtIdsParsedHint', { ids: ids.join('、') })
    })

    /** 出库明细「标识」列：mgmt_id 行展示数字；暗号 token 尝试解码 */
    function formatOutboundManagementId(line) {
      const raw = String(line?.management_id ?? '').trim()
      if (!raw) return '-'
      const k = String(line?.line_kind || '').trim()
      if (k === 'mgmt_id' || k === 'manual') {
        const n = Number(raw)
        if (Number.isFinite(n) && n > 0) return String(Math.floor(n))
      }
      const decoded = decodeMgmtIdCipher(raw)
      if (decoded != null) return String(decoded)
      return raw
    }

    /** 出库明细行：后端 line_kind 含 mgmt_id | barcode | bundle_title | manual */
    function outboundLineKindLabel(line) {
      const k = line?.line_kind
      if (k === 'bundle_title') return t('orders.kindBundleTitle')
      if (k === 'manual') return t('orders.kindManual')
      if (k === 'barcode') return t('orders.kindBarcode')
      return t('orders.kindMgmtId')
    }

    /** 后端已写入 goods_ratio / ratio_price 时展示（组合标题或按库存价分摊的手动/管理 ID/条码行） */
    function outboundLineShowsRatioPricing(line) {
      return line?.goods_ratio != null || line?.ratio_price != null
    }

    function outboundLineKey(orderNo, lineId) {
      return `${String(orderNo || '').trim()}:${Number(lineId || 0)}`
    }

    function expenseAmount(line) {
      return Math.max(0, Number(line?.quantity || 0)) * Math.max(0, Number(line?.unit_price || 0))
    }

    function formatExpenseTs(ts) {
      if (!ts) return '-'
      const dt = new Date(Number(ts) * 1000)
      if (Number.isNaN(dt.getTime())) return '-'
      return formatLocalWallToStr(dt)
    }

    function outboundPendingQty(line) {
      return Number(line?.is_stocked_out || 0) === 1 ? 0 : Math.max(0, Number(line?.quantity || 0))
    }

    function formatGoodsRatio(v) {
      const n = Number(v)
      if (v == null || v === '' || Number.isNaN(n)) return '-'
      return `${(n * 100).toFixed(2)}%`
    }

    function canStockOutLine(line) {
      if (Number(line?.is_stocked_out || 0) === 1) return false
      if (line?.inventory_id == null) return false
      const qty = Math.max(1, Number(line?.quantity || 1))
      // 出库按钮按“是否仍有待出库”判断，不以前端当前库存拦截。
      // 库存/并发等最终校验交由后端接口处理。
      return qty > 0
    }

    /** 二级明细是否已关联有效库存 ID（有则禁用「修改」） */
    function outboundLineHasBoundInventory(line) {
      const id = line?.inventory_id
      if (id == null || id === '') return false
      const n = Number(id)
      return Number.isFinite(n) && n > 0
    }

    /** 与在售商品页标红口径一致：未关联库存或库存无商品归属 */
    function isOutboundLineOwnerUnmatched(line) {
      if (!line || typeof line !== 'object') return false
      if (!outboundLineHasBoundInventory(line)) return true
      const ouid = line.inventory_owner_user_id
      if (ouid == null || ouid === '') return true
      const n = Number(ouid)
      return !Number.isFinite(n) || n <= 0
    }

    function sortOutboundLinesDisplay(rows) {
      const arr = Array.isArray(rows) ? [...rows] : []
      arr.sort((a, b) => {
        const aa = isOutboundLineOwnerUnmatched(a) ? 0 : 1
        const ba = isOutboundLineOwnerUnmatched(b) ? 0 : 1
        if (aa !== ba) return aa - ba
        const sa = Number(a?.sort_index) || 0
        const sb = Number(b?.sort_index) || 0
        if (sa !== sb) return sa - sb
        return (Number(a?.id) || 0) - (Number(b?.id) || 0)
      })
      return arr
    }

    function outboundLinesForExpand(orderNo) {
      const ono = String(orderNo || '').trim()
      if (!ono) return []
      const rows = expandState.value[ono]?.rows
      return sortOutboundLinesDisplay(rows)
    }

    function outboundLineRowClassName({ row }) {
      return isOutboundLineOwnerUnmatched(row) ? 'on-sale-stock-alert-row' : ''
    }

    /** 主表行标红：与后端 order_needs_alert 一致（出库/包材/待评价待出库等） */
    function isOrderAlertRow(row) {
      if (!row || typeof row !== 'object') return false
      if (Number(row.order_needs_alert ?? 0) === 1) return true
      if (Number(row.has_owner_unmatched_outbound || 0) === 1) return true
      if (Number(row.has_no_bound_outbound || 0) === 1) return true
      if (Number(row.has_packaging_pending || 0) === 1) return true
      if (String(row.status || '').trim() === 'wait_review') {
        return Number(row.pending_outbound_qty || 0) > 0
      }
      return false
    }

    const displayList = computed(() => {
      const arr = Array.isArray(list.value) ? [...list.value] : []
      arr.sort((a, b) => {
        const aa = isOrderAlertRow(a) ? 0 : 1
        const ba = isOrderAlertRow(b) ? 0 : 1
        if (aa !== ba) return aa - ba
        const ta = Number(a.purchase_time || a.order_updated_at || a.order_date || 0)
        const tb = Number(b.purchase_time || b.order_updated_at || b.order_date || 0)
        if (tb !== ta) return tb - ta
        return (Number(b.id) || 0) - (Number(a.id) || 0)
      })
      return arr
    })

    function orderRowClassName({ row }) {
      return isOrderAlertRow(row) ? 'on-sale-stock-alert-row' : ''
    }

    async function reloadOutboundLinesExpand(orderNo) {
      const ono = String(orderNo || '').trim()
      if (!ono) return
      const cur = expandState.value[ono]
      if (!cur?.loaded) return
      expandState.value = { ...expandState.value, [ono]: { ...cur, loading: true } }
      try {
        const res = await orderApi.outboundLines(buildOutboundLinesParams(ono))
        const rows = Array.isArray(res?.items) ? res.items : []
        expandState.value = {
          ...expandState.value,
          [ono]: { loading: false, loaded: true, rows },
        }
      } catch {
        expandState.value = {
          ...expandState.value,
          [ono]: { loading: false, loaded: true, rows: cur.rows || [] },
        }
      }
    }

    function maxStockForBindRow(inventoryId) {
      const id = Number(inventoryId || 0)
      if (!Number.isFinite(id) || id <= 0) return undefined
      const row = (bindInventoryOptions.value || []).find((x) => Number(x.id) === id)
      if (!row) return undefined
      const q = Number(row.quantity ?? 0)
      return Number.isFinite(q) && q >= 1 ? q : 1
    }

    function onBindOutboundInventoryChange() {
      const max = maxStockForBindRow(bindOutboundForm.value?.inventory_id)
      const n = Math.max(1, Number(bindOutboundForm.value.quantity || 1))
      if (max != null) {
        bindOutboundForm.value.quantity = Math.min(n, max)
      } else {
        bindOutboundForm.value.quantity = n
      }
    }

    async function openBindOutboundInventoryDialog(orderRow, line) {
      const orderNo = String(orderRow?.order_no || '').trim()
      const lineId = Number(line?.id || 0)
      if (!orderNo || !lineId) return
      bindOutboundContext.value = {
        order_no: orderNo,
        line_id: lineId,
        is_stocked_out: Number(line?.is_stocked_out || 0) === 1,
        original_inventory_id:
          line?.inventory_id != null && Number.isFinite(Number(line.inventory_id))
            ? Number(line.inventory_id)
            : null,
      }
      const currentInvId =
        line?.inventory_id != null && Number.isFinite(Number(line.inventory_id))
          ? Number(line.inventory_id)
          : null
      bindOutboundForm.value = {
        inventory_id: currentInvId,
        quantity: Math.max(1, Number(line?.quantity || 1)),
      }
      bindInvFilters.resetFilters()
      bindOutboundDialogVisible.value = true
      bindInventoryLoading.value = true
      try {
        await bindInvFilters.loadFilterMetadata()
        await reloadBindInventoryList()
      } catch {
        bindInventoryOptions.value = []
      } finally {
        bindInventoryLoading.value = false
      }
    }

    function openConvertOwnerDialog(orderRow, line) {
      const orderNo = String(orderRow?.order_no || '').trim()
      const lineId = Number(line?.id || 0)
      if (!orderNo || !lineId) return
      if (!outboundLineHasBoundInventory(line)) {
        ElMessage.warning(t('orders.convertOwnerNeedBound'))
        return
      }
      const invId = Number(line?.inventory_id || 0)
      const invName = String(line?.inventory_name || '').trim() || '-'
      convertOwnerContext.value = {
        order_no: orderNo,
        line_id: lineId,
        inventory_id: invId,
        inventory_label: `${invId} · ${invName}`,
        current_owner_user_id:
          line?.inventory_owner_user_id != null
            ? Number(line.inventory_owner_user_id)
            : null,
        current_owner_name: String(line?.inventory_owner_name || '').trim(),
        quantity: Math.max(1, Number(line?.quantity || 1)),
        is_stocked_out: Number(line?.is_stocked_out || 0) === 1,
      }
      convertOwnerForm.value = { owner_user_id: null }
      convertOwnerDialogVisible.value = true
    }

    async function submitConvertOwner() {
      const orderNo = String(convertOwnerContext.value.order_no || '').trim()
      const lineId = Number(convertOwnerContext.value.line_id || 0)
      const ownerId = Number(convertOwnerForm.value.owner_user_id || 0)
      if (!orderNo || !lineId || ownerId <= 0) return
      convertOwnerSubmitting.value = true
      try {
        const res = await orderApi.convertOutboundLineOwner(lineId, { owner_user_id: ownerId })
        const newInvId = res?.new_inventory_id ?? ''
        ElMessage.success(t('orders.convertOwnerSuccess', { id: newInvId }))
        convertOwnerDialogVisible.value = false
        await reloadOutboundLinesExpand(orderNo)
        await load()
      } finally {
        convertOwnerSubmitting.value = false
      }
    }

    async function submitBindOutboundInventory() {
      const orderNo = String(bindOutboundContext.value.order_no || '').trim()
      const lineId = Number(bindOutboundContext.value.line_id || 0)
      const invId = Number(bindOutboundForm.value.inventory_id || 0)
      if (!orderNo || !lineId) return
      if (!Number.isFinite(invId) || invId <= 0) {
        ElMessage.warning(t('orders.pleaseSelectInventory'))
        return
      }
      const max = maxStockForBindRow(invId)
      const qty = Math.max(1, Number(bindOutboundForm.value.quantity || 1))
      if (max != null && qty > max) {
        ElMessage.warning(t('orders.outboundQtyExceedStock', { max }))
        return
      }
      bindOutboundSaving.value = true
      try {
        await orderApi.bindOutboundLineInventory(lineId, { inventory_id: invId, quantity: qty })
        ElMessage.success(t('orders.boundInventory'))
        bindOutboundDialogVisible.value = false
        await reloadOutboundLinesExpand(orderNo)
        await load()
      } finally {
        bindOutboundSaving.value = false
      }
    }

    async function onOrderExpandChange(row, expandedRows) {
      const exp = Array.isArray(expandedRows) ? expandedRows : []
      lastExpandedRows.value = [...exp]
      const ono = String(row?.order_no || '').trim()
      if (!ono) return
      const opened = exp.some((r) => String(r?.order_no || '').trim() === ono)
      if (!opened) return
      if (expandState.value[ono]?.loaded) return
      expandState.value = {
        ...expandState.value,
        [ono]: { loading: true, loaded: false, rows: [] },
      }
      try {
        const res = await orderApi.outboundLines(buildOutboundLinesParams(ono))
        const rows = Array.isArray(res?.items) ? res.items : []
        expandState.value = {
          ...expandState.value,
          [ono]: { loading: false, loaded: true, rows },
        }
      } catch {
        expandState.value = {
          ...expandState.value,
          [ono]: { loading: false, loaded: true, rows: [] },
        }
      }
      await loadPackagingExpenses(ono)
    }

    async function loadPackagingItemOptions() {
      const res = await costRecordApi.listPackagingItems()
      packagingItemsOptions.value = Array.isArray(res?.items) ? res.items : []
    }

    function selectedPackagingMeta(itemName) {
      return (packagingItemsOptions.value || []).find((it) => it.item_name === itemName) || null
    }

    function packagingDisplayRows(orderNo) {
      const rows = packagingState.value?.[String(orderNo || '').trim()]?.rows || []
      // 无包材：仅一行占位行（操作列显示「添加包材」）
      if (!rows.length) return [{ __placeholder: true }]
      // 有包材：不额外生成空行，把「添加包材」放在最后一行的操作列
      return rows.map((r, i) => (i === rows.length - 1 ? { ...r, __canAdd: true } : r))
    }

    async function loadPackagingExpenses(orderNo) {
      const ono = String(orderNo || '').trim()
      if (!ono) return
      packagingState.value = {
        ...packagingState.value,
        [ono]: {
          loading: true,
          loaded: false,
          rows: [],
          total_amount: 0,
        },
      }
      try {
        const res = await costExpenseApi.list({
          order_no: ono,
          type: '包装材料',
          page: 1,
          page_size: 200,
        })
        const rows = Array.isArray(res?.items) ? res.items : []
        const totalAmount = rows.reduce((sum, it) => sum + expenseAmount(it), 0)
        packagingState.value = {
          ...packagingState.value,
          [ono]: {
            loading: false,
            loaded: true,
            rows,
            total_amount: totalAmount,
          },
        }
      } catch {
        packagingState.value = {
          ...packagingState.value,
          [ono]: {
            loading: false,
            loaded: true,
            rows: [],
            total_amount: 0,
          },
        }
      }
    }

    function setPackagingSubmitting(orderNo, val) {
      const ono = String(orderNo || '').trim()
      const cur = packagingState.value?.[ono] || {
        loading: false,
        loaded: false,
        rows: [],
        total_amount: 0,
      }
      packagingState.value = {
        ...packagingState.value,
        [ono]: { ...cur, submitting: val },
      }
    }

    function openPackagingSelect(orderNo) {
      const ono = String(orderNo || '').trim()
      if (!ono) return
      packagingAddingOpen.value = { ...packagingAddingOpen.value, [ono]: true }
    }

    function closePackagingSelect(orderNo) {
      const ono = String(orderNo || '').trim()
      if (!ono) return
      const next = { ...packagingAddingOpen.value }
      delete next[ono]
      packagingAddingOpen.value = next
    }

    async function submitInlinePackaging(orderNo, itemName) {
      const ono = String(orderNo || '').trim()
      const name = String(itemName || '').trim()
      if (!ono || !name) return
      if (packagingState.value?.[ono]?.submitting) return
      setPackagingSubmitting(ono, true)
      try {
        if (name === PACKAGING_ITEM_NONE) {
          await orderApi.waivePackaging({ order_no: ono })
          ElMessage.success(t('orders.confirmedNoPackaging'))
          await loadPackagingExpenses(ono)
          await load()
          return
        }
        const meta = selectedPackagingMeta(name)
        const unitPrice = Math.max(1, Number(meta?.amount || 0))
        if (unitPrice <= 0) {
          ElMessage.warning(t('orders.pleaseInputUnitPrice'))
          return
        }
        await costExpenseApi.create({
          order_no: ono,
          item_name: name,
          quantity: 1,
          unit_price: unitPrice,
        })
        ElMessage.success(t('orders.packagingAddedDeducted'))
        await loadPackagingExpenses(ono)
        await load()
        await loadStats()
      } finally {
        setPackagingSubmitting(ono, false)
        closePackagingSelect(ono)
      }
    }

    function addManualOutboundRow() {
      manualOutboundForm.value.rows.push({
        key: newManualOutboundRowKey(),
        inventory_id: null,
        quantity: 1,
      })
    }

    function removeManualOutboundRow(rowKey) {
      const rows = (manualOutboundForm.value.rows || []).filter((r) => r.key !== rowKey)
      manualOutboundForm.value.rows = rows
    }

    function rowInventoryOptions(rowKey) {
      const rows = manualOutboundForm.value.rows || []
      const otherIds = new Set(
        rows
          .filter((r) => r.key !== rowKey && r.inventory_id != null && r.inventory_id !== '')
          .map((r) => Number(r.inventory_id))
          .filter((id) => Number.isFinite(id) && id > 0)
      )
      return (manualInventoryOptions.value || []).filter((it) => {
        const id = Number(it.id)
        if (!Number.isFinite(id)) return false
        if (otherIds.has(id)) return false
        return true
      })
    }

    function maxStockForManualRow(inventoryId) {
      const id = Number(inventoryId || 0)
      if (!Number.isFinite(id) || id <= 0) return undefined
      const row = (manualInventoryOptions.value || []).find((x) => Number(x.id) === id)
      if (!row) return undefined
      const q = Number(row.quantity ?? 0)
      return Number.isFinite(q) && q >= 1 ? q : 1
    }

    function onManualOutboundRowInventoryChange(row) {
      const max = maxStockForManualRow(row?.inventory_id)
      if (max != null) {
        const n = Math.max(1, Number(row.quantity || 1))
        row.quantity = Math.min(n, max)
      } else {
        row.quantity = Math.max(1, Number(row.quantity || 1))
      }
    }

    async function openManualOutboundDialog(orderRow) {
      const orderNo = String(orderRow?.order_no || '').trim()
      if (!orderNo) return
      manualOutboundForm.value = {
        order_no: orderNo,
        rows: [{ key: newManualOutboundRowKey(), inventory_id: null, quantity: 1 }],
      }
      manualInvFilters.resetFilters()
      manualOutboundDialogVisible.value = true
      manualInventoryLoading.value = true
      try {
        await manualInvFilters.loadFilterMetadata()
        await reloadManualInventoryList()
      } catch {
        manualInventoryOptions.value = []
      } finally {
        manualInventoryLoading.value = false
      }
    }

    async function submitManualOutbound() {
      const orderNo = String(manualOutboundForm.value.order_no || '').trim()
      if (!orderNo) return
      const rows = manualOutboundForm.value.rows || []
      const lines = []
      const seen = new Set()
      for (const row of rows) {
        const iid = Number(row?.inventory_id || 0)
        if (!Number.isFinite(iid) || iid <= 0) continue
        if (seen.has(iid)) {
          ElMessage.warning(t('orders.duplicateInventorySelected'))
          return
        }
        seen.add(iid)
        const max = maxStockForManualRow(iid)
        const qty = Math.max(1, Number(row.quantity || 1))
        if (max != null && qty > max) {
          ElMessage.warning(t('orders.outboundQtyExceedStockNamed', { name: inventoryLabelById(iid), max }))
          return
        }
        lines.push({ inventory_id: iid, quantity: qty })
      }
      if (!lines.length) {
        ElMessage.warning(t('orders.pleaseAddAtLeastOneRow'))
        return
      }
      manualOutboundSaving.value = true
      try {
        await orderApi.addManualOutboundLinesBatch({
          order_no: orderNo,
          lines,
        })
        ElMessage.success(t('orders.manualOutboundAdded', { count: lines.length }))
        manualOutboundDialogVisible.value = false
        clearOutboundExpandCache(orderNo)
        await load()
      } finally {
        manualOutboundSaving.value = false
      }
    }

    function inventoryLabelById(iid) {
      const row = (manualInventoryOptions.value || []).find((x) => Number(x.id) === Number(iid))
      if (!row) return t('orders.inventoryNumberFallback', { id: iid })
      return `${row.name || '-'}（${t('orders.stockLabel')}:${Number(row.quantity || 0)}）`
    }

    function inventoryThumbUrl(row) {
      const f = String(row?.image_front || '').trim()
      if (f) return f
      const i = String(row?.image || '').trim()
      return i || ''
    }

    /** 下拉项内点击图片预览：正 / 背（与列表缩略图同源，去重） */
    function inventoryPreviewSrcList(row) {
      const front = String(row?.image_front || '').trim()
      const back = String(row?.image_back || '').trim()
      const legacy = String(row?.image || '').trim()
      const primary = front || legacy
      const out = []
      if (primary) out.push(primary)
      if (back && !out.includes(back)) out.push(back)
      return out
    }

    async function stockOutLine(orderRow, line) {
      const orderNo = String(orderRow?.order_no || '').trim()
      const lineId = Number(line?.id || 0)
      if (!orderNo || !lineId) return
      if (!canStockOutLine(line)) return
      const k = outboundLineKey(orderNo, lineId)
      lineStockingKey.value = k
      try {
        await orderApi.stockOutOutboundLine(lineId, {})
        ElMessage.success(t('inventory.outboundSuccess'))
        const cur = expandState.value[orderNo]
        if (cur?.loaded) {
          const nextRows = (cur.rows || []).map((r) => {
            if (Number(r.id) !== lineId) return r
            const deducted = Number(r.stock_deducted || 0) === 1
            const newStock = deducted
              ? Number(r.stock_quantity || 0)
              : Math.max(0, Number(r.stock_quantity || 0) - Math.max(1, Number(r.quantity || 1)))
            return {
              ...r,
              is_stocked_out: 1,
              stock_quantity: newStock,
            }
          })
          expandState.value = {
            ...expandState.value,
            [orderNo]: { ...cur, rows: nextRows },
          }
        }
        load()
      } finally {
        lineStockingKey.value = ''
      }
    }

    function openEdit(row) {
      const dbMoney = row._owner_split_money_db
      form.value = {
        id: row.id,
        order_no: row.order_no || '',
        order_date: tsOrLegacyToLocalForm(row.order_date),
        order_updated_at: tsOrLegacyToLocalForm(row.order_updated_at),
        purchase_time: tsOrLegacyToLocalForm(row.purchase_time),
        data_user: row.data_user != null && row.data_user !== '' ? String(row.data_user) : '',
        customer_name: row.customer_name || '',
        status: row.status || 'pending',
        amount: Number((dbMoney ? dbMoney.amount : row.amount) ?? 0),
        service_fee: optionalNumFromRow(dbMoney ? dbMoney.service_fee : row.service_fee),
        net_income: optionalNumFromRow(dbMoney ? dbMoney.net_income : row.net_income),
        carrier_display_name: row.carrier_display_name || '',
        request_class_display_name: row.request_class_display_name || '',
        shipping_fee: optionalNumFromRow(dbMoney ? dbMoney.shipping_fee : row.shipping_fee),
        tracking_no: row.tracking_no || '',
        ship_confirm_code: row.ship_confirm_code || '',
        transaction_evidence_id: optionalIntFromRow(row.transaction_evidence_id),
        remark: row.remark || '',
        description: row.description || '',
        thumbnails_text: thumbnailsToFormText(row),
      }
      // 加载该订单的包材合计金额用于展示
      loadPackagingExpenses(row.order_no)
      dialogVisible.value = true
    }

    /** 单行拉取 transaction_evidences/get，更新状态、金额、说明、费用等 */
    async function refreshOrder(row) {
      if (!row?.id) return
      const orderNo = String(row.order_no || '').trim()
      if (!orderNo) {
        ElMessage.warning(t('orders.missingOrderNo'))
        return
      }
      const dataUser = row.data_user != null && row.data_user !== '' ? String(row.data_user).trim() : ''
      if (!dataUser) {
        ElMessage.warning(t('orders.missingSellerId'))
        return
      }

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let lastConsoleStep = ''
      async function pollSyncProgress() {
        try {
          const pr = await orderApi.getRefreshProgress(progressJobId)
          const d = pr?.data
          const zh = d?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[订单刷新]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('orders.refreshingOrder')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('orders.connectingServer')
      syncOverlayVisible.value = true
      refreshingId.value = row.id
      await pollSyncProgress()
      syncProgressTimer = setInterval(pollSyncProgress, 1000)

      let hadError = false
      try {
        await orderApi.refreshInfo({
          order_no: orderNo,
          data_user: dataUser,
          progress_job_id: progressJobId,
        })
        ElMessage.success(t('orders.refreshedFromMercari'))
        clearOutboundExpandCache(orderNo)
        load()
        loadStats()
      } catch (e) {
        hadError = true
        syncOverlayTitle.value = t('orders.refreshFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('orders.refreshFailed')
        syncProgressLabel.value = String(msg)
      } finally {
        if (syncProgressTimer != null) {
          clearInterval(syncProgressTimer)
          syncProgressTimer = null
        }
        if (hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = ''
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        refreshingId.value = null
      }
    }

    async function submit() {
      await formRef.value?.validate()
      if (!form.value.id) {
        ElMessage.warning(t('orders.noOrderSelected'))
        return
      }
      const orderDateSec = localFormStringToUnixSec(form.value.order_date)
      if (orderDateSec == null) {
        ElMessage.warning(t('orders.orderDateInvalid'))
        return
      }
      submitting.value = true
      const payload = {
        order_no: String(form.value.order_no || '').trim(),
        order_date: orderDateSec,
        order_updated_at: localFormStringToUnixSec(form.value.order_updated_at),
        purchase_time: localFormStringToUnixSec(form.value.purchase_time),
        data_user: String(form.value.data_user || '').trim() || null,
        customer_name: String(form.value.customer_name || '').trim() || null,
        status: form.value.status,
        amount: Number(form.value.amount || 0),
        service_fee: numOrNull(form.value.service_fee),
        net_income: numOrNull(form.value.net_income),
        carrier_display_name: String(form.value.carrier_display_name || '').trim() || null,
        request_class_display_name: String(form.value.request_class_display_name || '').trim() || null,
        shipping_fee: numOrNull(form.value.shipping_fee),
        tracking_no: String(form.value.tracking_no || '').trim() || null,
        ship_confirm_code: String(form.value.ship_confirm_code || '').trim() || null,
        transaction_evidence_id: intOrNull(form.value.transaction_evidence_id),
        remark: String(form.value.remark || '').trim() || null,
        description: String(form.value.description || '').trim() || null,
        thumbnails: parseThumbnailsPayload(form.value.thumbnails_text),
      }
      try {
        await orderApi.update(form.value.id, payload)
        ElMessage.success(t('orders.updateSuccess'))
        clearOutboundExpandCache(payload.order_no)
        dialogVisible.value = false
        load()
        loadStats()
      } finally {
        submitting.value = false
      }
    }

    async function remove(id) {
      await orderApi.remove(id)
      ElMessage.success(t('inventory.deleteSuccess'))
      expandState.value = {}
      if (list.value.length === 1 && page.value > 1) page.value -= 1
      load()
      loadStats()
    }

    async function removeFromDialog() {
      const id = form.value.id
      if (!id) return
      await remove(id)
      dialogVisible.value = false
    }

    watch(isMobile, (mobile) => {
      if (!mobile) loadStats()
    })

    onMounted(async () => {
      updateViewportState()
      window.addEventListener('resize', updateViewportState)
      mercariAccountStore.ensureLoaded()
      syncLockStore.subscribe()
      try {
        const users = await authApi.listUsers()
        ownerUsers.value = Array.isArray(users) ? users : []
      } catch {
        ownerUsers.value = []
      }
      load()
      loadStats()
      loadPackagingItemOptions()
    })

    onBeforeUnmount(() => {
      window.removeEventListener('resize', updateViewportState)
      if (syncProgressTimer != null) {
        clearInterval(syncProgressTimer)
        syncProgressTimer = null
      }
      syncLockStore.unsubscribe()
    })

    return {
      ref,
      computed,
      onMounted,
      watch,
      onBeforeUnmount,
      nextTick,
      useI18n,
      ElMessage,
      ElMessageBox,
      RefreshRight,
      Refresh,
      Plus,
      Minus,
      Loading,
      orderApi,
      mercariApi,
      inventoryApi,
      costExpenseApi,
      costRecordApi,
      authApi,
      useMercariAccountStore,
      useInventoryListApiFilters,
      warehouseCascaderProps,
      productTypeCascaderProps,
      localYmdToDayStartTs,
      localYmdToDayEndTs,
      decodeMgmtIdCipher,
      parseMgmtIdsFromDescription,
      mercariImageUrlList,
      t,
      mercariAccountStore,
      syncLockStore,
      orderTableRef,
      lastExpandedRows,
      ownerUsers,
      isAdminUser,
      loading,
      statsLoading,
      isMobile,
      submitting,
      refreshingId,
      lineStockingKey,
      manualOutboundDialogVisible,
      manualOutboundSaving,
      manualInventoryLoading,
      manualInventoryOptions,
      bindOutboundDialogVisible,
      bindOutboundSaving,
      bindInventoryLoading,
      bindInventoryOptions,
      bindOutboundContext,
      bindOutboundForm,
      convertOwnerDialogVisible,
      convertOwnerSubmitting,
      convertOwnerContext,
      convertOwnerForm,
      convertOwnerCanSubmit,
      packagingItemsOptions,
      newManualOutboundRowKey,
      manualOutboundForm,
      scheduleManualInvReload,
      manualInvFilters,
      manualInvWarehouseCascaderProps,
      manualInvProductTypeCascaderProps,
      scheduleBindInvReload,
      bindInvFilters,
      bindInvWarehouseCascaderProps,
      bindInvProductTypeCascaderProps,
      reloadManualInventoryList,
      reloadBindInventoryList,
      stats,
      packagingState,
      PACKAGING_ITEM_NONE,
      orderStatCards,
      expandState,
      list,
      total,
      page,
      pageSize,
      dateRange,
      dialogVisible,
      formRef,
      filters,
      ORDER_STATUS_KEYS,
      statusMap,
      LIST_FILTER_STATUS_KEYS,
      orderListStatusFilterOptions,
      orderStatusOptions,
      formOrderStatusOptions,
      syncLoading,
      syncMode,
      syncOverlayVisible,
      syncOverlayTitle,
      syncOverlayFailed,
      syncProgressLabel,
      syncProgressTimer,
      runSync,
      formatLocalDatetime,
      normalizeDatetimeStr,
      pad2,
      parseUtcDbToDate,
      formatLocalWallToStr,
      tsOrLegacyToDate,
      displayTsLocal,
      tsOrLegacyToLocalForm,
      localFormStringToUnixSec,
      optionalNumFromRow,
      numOrNull,
      optionalIntFromRow,
      intOrNull,
      thumbnailsToFormText,
      parseThumbnailsPayload,
      orderMoneyField,
      formatFeeShippingCell,
      thumbnailPreviewList,
      firstThumbUrl,
      createDefaultForm,
      form,
      rules,
      LIST_FILTER_STATUS_SET,
      listFilterParams,
      buildOutboundLinesParams,
      resetExpandAndCollapseRows,
      updateViewportState,
      loadStats,
      load,
      onFilterChange,
      resetFilters,
      clearOutboundExpandCache,
      orderDescriptionMgmtHint,
      formatOutboundManagementId,
      outboundLineKindLabel,
      outboundLineShowsRatioPricing,
      outboundLineKey,
      expenseAmount,
      formatExpenseTs,
      outboundPendingQty,
      formatGoodsRatio,
      canStockOutLine,
      outboundLineHasBoundInventory,
      isOutboundLineOwnerUnmatched,
      sortOutboundLinesDisplay,
      outboundLinesForExpand,
      outboundLineRowClassName,
      isOrderAlertRow,
      displayList,
      orderRowClassName,
      reloadOutboundLinesExpand,
      maxStockForBindRow,
      onBindOutboundInventoryChange,
      openBindOutboundInventoryDialog,
      openConvertOwnerDialog,
      submitConvertOwner,
      submitBindOutboundInventory,
      onOrderExpandChange,
      loadPackagingItemOptions,
      selectedPackagingMeta,
      packagingDisplayRows,
      loadPackagingExpenses,
      packagingAddingOpen,
      openPackagingSelect,
      closePackagingSelect,
      submitInlinePackaging,
      addManualOutboundRow,
      removeManualOutboundRow,
      rowInventoryOptions,
      maxStockForManualRow,
      onManualOutboundRowInventoryChange,
      openManualOutboundDialog,
      submitManualOutbound,
      formPackagingTotal,
      inventoryLabelById,
      inventoryThumbUrl,
      inventoryPreviewSrcList,
      stockOutLine,
      openEdit,
      refreshOrder,
      submit,
      remove,
      removeFromDialog,
    }
  },
})
