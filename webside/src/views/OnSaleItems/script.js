import { defineComponent, ref, computed, onBeforeUnmount, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Loading, WarningFilled } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { onSaleItemApi, mercariAccountApi, webDriveApi } from '@/api/index.js'
import { parseMgmtIdsFromDescription, isCipherMgmtLine } from '@/utils/mgmtIdCipher.js'
import { mercariImageUrlList } from '@/utils/mercariImage.js'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncLockStore } from '@/stores/syncLock.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()
    const mercariAccountStore = useMercariAccountStore()
    const syncLockStore = useSyncLockStore()

    /** 煤炉商品 item.status → i18n label（key 对应 onSaleItems/i18n.js 的 statusXxx 字段） */
    const onSaleStatusMap = {
      on_sale: { labelKey: 'onSaleItems.statusOnSale', tag: 'success' },
      stop: { labelKey: 'onSaleItems.statusStop', tag: 'warning' },
      trading: { labelKey: 'onSaleItems.statusTrading', tag: 'primary' },
      wait_payment: { labelKey: 'onSaleItems.statusWaitPayment', tag: 'warning' },
      wait_shipping: { labelKey: 'onSaleItems.statusWaitShipping', tag: 'warning' },
      wait_review: { labelKey: 'onSaleItems.statusWaitReview', tag: 'primary' },
      sold_out: { labelKey: 'onSaleItems.statusSoldOut', tag: 'info' },
      done: { labelKey: 'onSaleItems.statusDone', tag: 'success' },
      cancelled: { labelKey: 'onSaleItems.statusCancelled', tag: 'info' },
      cancel_request: { labelKey: 'onSaleItems.statusCancelRequest', tag: 'danger' },
      deleted: { labelKey: 'onSaleItems.statusDeleted', tag: 'danger' },
      private: { labelKey: 'onSaleItems.statusPrivate', tag: 'info' },
      pending: { labelKey: 'onSaleItems.statusPending', tag: 'info' },
    }

    function onSaleStatusLabel(status) {
      if (status == null || status === '') return '-'
      const s = String(status).trim()
      const key = onSaleStatusMap[s]?.labelKey
      return key ? t(key) : s
    }

    function onSaleStatusTagType(status) {
      const s = String(status ?? '').trim()
      return onSaleStatusMap[s]?.tag ?? 'info'
    }

    const loading = ref(false)
    /** 正在请求 items/get 的商品 ID（trim 后） */
    const detailLoadingIds = ref(new Set())
    const syncLoading = ref(false)

    /** 「从煤炉同步」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */
    const syncOverlayVisible = ref(false)
    const syncOverlayTitle = ref('')
    const syncOverlayFailed = ref(false)
    const syncProgressLabel = ref('')
    let syncProgressTimer = null

    /** 查看详情弹窗 */
    const detailViewVisible = ref(false)
    const detailViewLoading = ref(false)
    const detailViewBase = ref(null)
    const detailViewOnSaleItems = ref([])
    const deleteItemLoading = ref(false)
    const resumeItemLoading = ref(false)
    const suspendItemLoading = ref(false)

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

    /** 出售类型为拍卖（存在 auction_info_json）时，详情页不允许编辑（屏蔽「修改」按钮） */
    const detailIsAuction = computed(() => {
      const base = detailViewBase.value
      return Boolean(base && String(base.auction_info_json ?? '').trim())
    })

    /** 状态为暂停出售（stop）时，详情页展示「恢复出售」按钮（出售中走「修改」） */
    const detailIsStopped = computed(() => {
      const base = detailViewBase.value
      return Boolean(base && String(base.status ?? '').trim() === 'stop')
    })

    /** 状态为出售中（on_sale）时，详情页展示「暂停出售」按钮 */
    const detailIsOnSale = computed(() => {
      const base = detailViewBase.value
      return Boolean(base && String(base.status ?? '').trim() === 'on_sale')
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
      status: '',
    })

    /** 状态筛选下拉项：出售中 / 暂停出售（值对应煤炉 item.status） */
    const statusFilterOptions = computed(() => [
      { value: 'on_sale', label: t('onSaleItems.statusOnSale') },
      { value: 'stop', label: t('onSaleItems.statusStop') },
    ])

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

    /** 标红行原因列表（已本地化），与库存管理页一致，供 tooltip 悬停展示 */
    function onSaleAlertReasons(row) {
      const reasons = []
      if (isOnSaleZeroStockAlert(row)) {
        reasons.push(t('onSaleItems.alertReasonZeroStockOnSale'))
      }
      return reasons
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
          if (!m.has(k)) m.set(k, { value: k, label: `${t('onSaleItems.seller')} ${k}` })
        }
      }
      return Array.from(m.values())
    })

    function listParams() {
      const p = { page: page.value, page_size: pageSize.value }
      if (filters.value.keyword?.trim()) p.keyword = filters.value.keyword.trim()
      if (filters.value.seller_id?.trim()) p.seller_id = filters.value.seller_id.trim()
      if (filters.value.status?.trim()) p.status = filters.value.status.trim()
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
        return mercariImageUrlList(raw.map((u) => String(u).trim()).filter(Boolean))
      }
      if (typeof raw === 'string') {
        try {
          const arr = JSON.parse(raw)
          if (Array.isArray(arr)) {
            return mercariImageUrlList(arr.map((u) => String(u).trim()).filter(Boolean))
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

    /** 本地 /imges/ 路径转缩略图接口 URL；非本地图片原样返回（与库存页一致） */
    function thumbUrl(src, size = 200) {
      if (!src || !src.startsWith('/imges/')) return src || ''
      return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(src)}&size=${size}`
    }

    /**
     * 详情弹窗：按管理 ID（= 库存 id）聚合关联商品图片，去重后每组展示其全部图片。
     * 图片路径来自后端 inventory_lines[].images（库存表 images_json / image_front 等）。
     */
    const detailLinkedImageGroups = computed(() => {
      const seen = new Set()
      const groups = []
      for (const ln of detailInventoryLines.value) {
        const mid = String(ln?.management_id || '').trim()
        if (!mid || seen.has(mid)) continue
        const imgs = Array.isArray(ln?.images)
          ? ln.images.map((s) => String(s || '').trim()).filter(Boolean)
          : []
        if (!imgs.length) continue
        seen.add(mid)
        groups.push({
          management_id: mid,
          inventory_name: String(ln?.inventory_name || '').trim(),
          images: imgs.map((p) => ({ thumb: thumbUrl(p, 160), big: thumbUrl(p, 900) })),
          previewList: imgs.map((p) => thumbUrl(p, 900)),
        })
      }
      return groups
    })

    /** 修改在售商品弹窗（标题 / 价格 / 商品说明；出品方式稍后接入，保存方法由后续提供） */
    const reviseDialogVisible = ref(false)
    const reviseSaving = ref(false)
    const reviseForm = reactive({ name: '', price: 0, listing_description: '' })
    /** 商品说明末行的「暗码」（管理番号暗号）；编辑时锁定不可改，保存时原样回拼 */
    const reviseDescCipher = ref('')

    /**
     * 拆分商品说明：仅把「最后一行」整行均为 -=~<> 暗号字符的暗码锁定，其余为可编辑正文。
     * 用 isCipherMgmtLine 判定（与解析端一致，排除「管理ID:」「バーコード:」并支持 *数量）。
     */
    function splitListingCipher(desc) {
      const text = String(desc || '')
      if (!text.trim()) return { body: text, cipher: '' }
      const lines = text.split(/\r?\n/)
      let li = -1
      for (let i = lines.length - 1; i >= 0; i--) {
        if (lines[i].trim() !== '') {
          li = i
          break
        }
      }
      if (li < 0) return { body: text, cipher: '' }
      const lastLine = lines[li].trim()
      if (!isCipherMgmtLine(lastLine)) return { body: text, cipher: '' }
      const body = lines.slice(0, li).join('\n').replace(/\s+$/, '')
      return { body, cipher: lastLine }
    }

    /** 回拼完整商品说明：可编辑正文 + 锁定暗码（保证暗码为最后一行、内容不变） */
    function composeReviseDescription() {
      const body = String(reviseForm.listing_description || '')
      const cipher = String(reviseDescCipher.value || '')
      if (!cipher) return body
      return `${body.replace(/\s+$/, '')}\n\n${cipher}`
    }

    function openReviseDialog() {
      const base = detailViewBase.value
      if (!base) return
      reviseForm.name = String(base.name || '')
      reviseForm.price = Number(base.price || 0)
      const { body, cipher } = splitListingCipher(detailListingBodyText.value || '')
      reviseForm.listing_description = body
      reviseDescCipher.value = cipher
      reviseDialogVisible.value = true
    }

    /**
     * 提交修改：打开煤炉编辑页 https://jp.mercari.com/sell/edit/{item_id} 填写并点击「変更する」。
     * 商品说明用 composeReviseDescription() 回拼，末行暗码原样保留。
     */
    async function submitReviseDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      const name = String(reviseForm.name || '').trim()
      const price = Number(reviseForm.price)
      const description = composeReviseDescription()
      if (!name) {
        ElMessage.warning(t('onSaleItems.titleRequired'))
        return
      }
      if (!Number.isFinite(price) || price < 300) {
        ElMessage.warning(t('onSaleItems.priceInvalid'))
        return
      }
      if (reviseSaving.value) return

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let pollTimer = null
      let lastConsoleStep = ''
      async function poll() {
        try {
          const pr = await onSaleItemApi.getSyncProgress(progressJobId)
          const zh = pr?.data?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[修改商品]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('onSaleItems.revisingMercariItem')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('onSaleItems.connectingServer')
      syncOverlayVisible.value = true
      reviseSaving.value = true
      await poll()
      pollTimer = setInterval(poll, 400)

      let hadError = false
      try {
        await webDriveApi.reviseMercariItem({
          account_key: resolved.accountKey,
          item_id: iid,
          name,
          price: Math.floor(price),
          description,
          use_mitm_proxy: true,
          progress_job_id: progressJobId,
        })
        ElMessage.success(t('onSaleItems.reviseSuccess'))
        reviseDialogVisible.value = false
        detailViewVisible.value = false
        await load()
      } catch (e) {
        hadError = true
        syncOverlayTitle.value = t('onSaleItems.reviseFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('onSaleItems.reviseFailed')
        syncProgressLabel.value = String(msg)
      } finally {
        if (pollTimer != null) {
          clearInterval(pollTimer)
        }
        if (hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        reviseSaving.value = false
      }
    }

    function resolveAccountKeyForRow(row) {
      const sid = String(row?.seller_id || '').trim()
      if (!sid) return null
      const matched = sellerFromAccounts.value.find((a) => String(a.seller_id || '').trim() === sid)
      if (!matched?.id) return null
      return { accountKey: `mercari_${matched.id}`, sellerId: sid }
    }

    async function deleteMercariItemFromDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.deleteConfirmMsg', { iid }),
          t('onSaleItems.deleteItem'),
          { type: 'warning', confirmButtonText: t('onSaleItems.confirmDelete'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      if (deleteItemLoading.value) return

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let pollTimer = null
      let lastConsoleStep = ''
      async function poll() {
        try {
          const pr = await onSaleItemApi.getSyncProgress(progressJobId)
          const zh = pr?.data?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[删除物品]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('onSaleItems.deletingMercariItem')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('onSaleItems.connectingServer')
      syncOverlayVisible.value = true
      deleteItemLoading.value = true
      await poll()
      pollTimer = setInterval(poll, 400)

      let hadError = false
      try {
        const res = await webDriveApi.deleteMercariItem({
          account_key: resolved.accountKey,
          item_id: iid,
          use_mitm_proxy: true,
          progress_job_id: progressJobId,
        })
        const d = res?.data || {}
        const sync = d.sync || {}
        if (d.delete_confirmed && sync && typeof sync === 'object') {
          ElMessage.success(
            t('onSaleItems.deleteSuccessFull', {
              iid,
              apiCount: sync.api_item_count ?? 0,
              updated: sync.updated ?? 0,
              marked: sync.marked_deleted ?? 0,
            })
          )
        } else if (d.delete_confirmed) {
          ElMessage.success(t('onSaleItems.deletedOnMercari', { iid }))
        } else {
          ElMessage.warning(t('onSaleItems.deleteFlowExecuted'))
        }
        detailViewVisible.value = false
        await load()
      } catch (e) {
        hadError = true
        syncOverlayTitle.value = t('onSaleItems.deleteFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('onSaleItems.deleteFailed')
        syncProgressLabel.value = String(msg)
      } finally {
        if (pollTimer != null) {
          clearInterval(pollTimer)
        }
        if (hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        deleteItemLoading.value = false
      }
    }

    async function resumeMercariItemFromDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.resumeConfirmMsg', { iid }),
          t('onSaleItems.resumeItem'),
          { type: 'info', confirmButtonText: t('onSaleItems.confirmResume'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      if (resumeItemLoading.value) return

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let pollTimer = null
      let lastConsoleStep = ''
      async function poll() {
        try {
          const pr = await onSaleItemApi.getSyncProgress(progressJobId)
          const zh = pr?.data?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[恢复出售]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('onSaleItems.resumingMercariItem')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('onSaleItems.connectingServer')
      syncOverlayVisible.value = true
      resumeItemLoading.value = true
      await poll()
      pollTimer = setInterval(poll, 400)

      let hadError = false
      try {
        await webDriveApi.resumeMercariItem({
          account_key: resolved.accountKey,
          item_id: iid,
          use_mitm_proxy: true,
          progress_job_id: progressJobId,
        })
        ElMessage.success(t('onSaleItems.resumeSuccess'))
        detailViewVisible.value = false
        await load()
      } catch (e) {
        hadError = true
        syncOverlayTitle.value = t('onSaleItems.resumeFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('onSaleItems.resumeFailed')
        syncProgressLabel.value = String(msg)
        // 绑定库存归零/不足等校验失败：用可关闭的提示明确告知，避免红色遮罩一闪而过
        ElMessage.error({ message: String(msg), duration: 6000, showClose: true })
      } finally {
        if (pollTimer != null) {
          clearInterval(pollTimer)
        }
        if (hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        resumeItemLoading.value = false
      }
    }

    async function suspendMercariItemFromDetail() {
      const base = detailViewBase.value
      if (!base?.item_id) {
        ElMessage.warning(t('onSaleItems.missingItemId'))
        return
      }
      const iid = String(base.item_id || '').trim()
      const resolved = resolveAccountKeyForRow(base)
      if (!resolved) {
        ElMessage.warning(t('onSaleItems.noActiveAccountForSeller', { sid: String(base.seller_id || '').trim() || '-' }))
        return
      }
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.suspendConfirmMsg', { iid }),
          t('onSaleItems.suspendItem'),
          { type: 'warning', confirmButtonText: t('onSaleItems.confirmSuspend'), cancelButtonText: t('common.cancel') }
        )
      } catch {
        return
      }
      if (suspendItemLoading.value) return

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let pollTimer = null
      let lastConsoleStep = ''
      async function poll() {
        try {
          const pr = await onSaleItemApi.getSyncProgress(progressJobId)
          const zh = pr?.data?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[暂停出售]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('onSaleItems.suspendingMercariItem')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('onSaleItems.connectingServer')
      syncOverlayVisible.value = true
      suspendItemLoading.value = true
      await poll()
      pollTimer = setInterval(poll, 400)

      let hadError = false
      try {
        await webDriveApi.suspendMercariItem({
          account_key: resolved.accountKey,
          item_id: iid,
          use_mitm_proxy: true,
          progress_job_id: progressJobId,
        })
        ElMessage.success(t('onSaleItems.suspendSuccess'))
        detailViewVisible.value = false
        await load()
      } catch (e) {
        hadError = true
        syncOverlayTitle.value = t('onSaleItems.suspendFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('onSaleItems.suspendFailed')
        syncProgressLabel.value = String(msg)
      } finally {
        if (pollTimer != null) {
          clearInterval(pollTimer)
        }
        if (hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        suspendItemLoading.value = false
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
        if (!silent) ElMessage.warning(t('onSaleItems.missingItemId'))
        return { ok: false }
      }
      if (detailLoadingIds.value.has(iid)) return { ok: false, skipped: true }
      const next = new Set(detailLoadingIds.value)
      next.add(iid)
      detailLoadingIds.value = next

      const showOverlay = !silent
      const progressJobId = showOverlay
        ? (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`)
        : null

      let pollTimer = null
      let lastConsoleStep = ''
      if (showOverlay) {
        syncOverlayTitle.value = t('onSaleItems.fetchingDetailFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = t('onSaleItems.connectingServer')
        syncOverlayVisible.value = true
        const poll = async () => {
          try {
            const pr = await onSaleItemApi.getSyncProgress(progressJobId)
            const zh = pr?.data?.label_zh
            if (zh) {
              syncProgressLabel.value = zh
              if (zh !== lastConsoleStep) {
                lastConsoleStep = zh
                console.log('[获取详情]', zh)
              }
            }
          } catch {
            /* 轮询失败忽略 */
          }
        }
        await poll()
        pollTimer = setInterval(poll, 400)
      }

      let hadError = false
      let result = { ok: false }
      try {
        const payload = { item_id: iid }
        if (accountId != null && accountId !== '') payload.account_id = accountId
        if (progressJobId) payload.progress_job_id = progressJobId
        const res = await onSaleItemApi.fetchDetail(payload)
        const sync = res?.data?.sync || {}
        const ok = Boolean(sync.updated)
        if (!silent) {
          if (ok) {
            ElMessage.success(
              sync.message ||
                t('onSaleItems.fetchDetailSuccess', { count: sync.inventory_ids?.length ?? 0, mid: sync.mercari_item_id })
            )
          } else {
            ElMessage.warning(sync.message || t('onSaleItems.fetchDetailNoWrite'))
          }
        }
        if (reloadAfter) await load()
        result = { ok, sync }
      } catch (e) {
        hadError = true
        if (showOverlay) {
          syncOverlayTitle.value = t('onSaleItems.fetchDetailFailed')
          syncOverlayFailed.value = true
          const msg = e?.response?.data?.detail || e?.message || t('onSaleItems.fetchFailed')
          syncProgressLabel.value = String(msg)
        }
        result = { ok: false, error: e }
      } finally {
        if (pollTimer != null) {
          clearInterval(pollTimer)
        }
        if (showOverlay && hadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        if (showOverlay) {
          syncOverlayVisible.value = false
          syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
          syncOverlayFailed.value = false
          syncProgressLabel.value = ''
        }
        const done = new Set(detailLoadingIds.value)
        done.delete(iid)
        detailLoadingIds.value = done
      }
      return result
    }

    async function fetchItemDetail(row) {
      await fetchItemDetailForItemId(row.item_id)
    }

    async function runSync() {
      if (syncLoading.value) return
      try {
        await ElMessageBox.confirm(
          t('onSaleItems.runSyncConfirmMsg'),
          t('onSaleItems.runSyncConfirmTitle'),
          { type: 'info', confirmButtonText: t('onSaleItems.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      const progressJobId =
        typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
          ? crypto.randomUUID()
          : `job_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`

      let lastConsoleStep = ''
      async function pollSyncProgress() {
        try {
          const pr = await onSaleItemApi.getSyncProgress(progressJobId)
          const d = pr?.data
          const zh = d?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[在售同步]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('onSaleItems.connectingServer')
      syncOverlayVisible.value = true
      syncLoading.value = true
      await pollSyncProgress()
      syncProgressTimer = setInterval(pollSyncProgress, 400)

      let syncHadError = false
      try {
        // 已开启账号逐个串行同步；每个账号在同一浏览器会话内对新增商品自动拉取详情并回写库存，
        // 故前端不再单独发起批量详情请求。
        const res = await onSaleItemApi.sync(
          { progress_job_id: progressJobId },
          { timeout: 0 }
        )
        const d = res.data || {}
        ElMessage.success(
          t('onSaleItems.syncSuccessFull', {
            accountCount: d.account_count ?? 0,
            failCount: d.fail_count ?? 0,
            apiCount: d.api_item_count ?? 0,
            inserted: d.inserted ?? 0,
            updated: d.updated ?? 0,
            marked: d.marked_deleted ?? 0,
          })
        )
        await load()
      } catch (exc) {
        syncHadError = true
        syncOverlayTitle.value = t('onSaleItems.syncFailed')
        syncOverlayFailed.value = true
        const msg = exc?.response?.data?.detail || exc?.message || t('onSaleItems.unknownError')
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
        syncOverlayTitle.value = t('onSaleItems.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        syncLoading.value = false
      }
    }

    async function loadSellerAccounts() {
      try {
        const res = await mercariAccountApi.list({ page: 1, page_size: 200 })
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
      mercariAccountStore.ensureLoaded()
      syncLockStore.subscribe()
      loadSellerAccounts()
      load()
    })

    onBeforeUnmount(() => {
      if (syncProgressTimer != null) {
        clearInterval(syncProgressTimer)
        syncProgressTimer = null
      }
      syncLockStore.unsubscribe()
    })

    return {
      ref,
      computed,
      onBeforeUnmount,
      onMounted,
      reactive,
      ElMessage,
      ElMessageBox,
      Download,
      Loading,
      WarningFilled,
      useI18n,
      onSaleItemApi,
      mercariAccountApi,
      webDriveApi,
      parseMgmtIdsFromDescription,
      mercariImageUrlList,
      useMercariAccountStore,
      t,
      mercariAccountStore,
      syncLockStore,
      onSaleStatusMap,
      onSaleStatusLabel,
      onSaleStatusTagType,
      loading,
      detailLoadingIds,
      syncLoading,
      syncOverlayVisible,
      syncOverlayTitle,
      syncOverlayFailed,
      syncProgressLabel,
      syncProgressTimer,
      detailViewVisible,
      detailViewLoading,
      detailViewBase,
      detailViewOnSaleItems,
      deleteItemLoading,
      resumeItemLoading,
      suspendItemLoading,
      detailInventoryLines,
      detailListingBodyText,
      detailIsAuction,
      detailIsStopped,
      detailIsOnSale,
      list,
      expandByItemId,
      total,
      page,
      pageSize,
      filters,
      statusFilterOptions,
      sellerFromAccounts,
      isOnSaleZeroStockAlert,
      onSaleAlertReasons,
      displayList,
      onSaleRowClassName,
      sellerOptions,
      listParams,
      expandKey,
      expandSlot,
      hasSecondaryData,
      hasStoredListingDescription,
      hasDetailViewable,
      inventoryLines,
      resolvedMgmtIdsForRow,
      detailMgmtIdsText,
      ensureExpandLoaded,
      onTableExpandChange,
      load,
      onFilterChange,
      pad2,
      displayTs,
      thumbPreviewList,
      firstThumb,
      formatJsonPretty,
      onDetailActionClick,
      openDetailView,
      onDetailViewClosed,
      resolveAccountKeyForRow,
      deleteMercariItemFromDetail,
      resumeMercariItemFromDetail,
      suspendMercariItemFromDetail,
      detailViewRefreshFromMercari,
      fetchItemDetailForItemId,
      fetchItemDetail,
      runSync,
      loadSellerAccounts,
      thumbUrl,
      detailLinkedImageGroups,
      reviseDialogVisible,
      reviseSaving,
      reviseForm,
      reviseDescCipher,
      openReviseDialog,
      submitReviseDetail,
    }
  },
})
