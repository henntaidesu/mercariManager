import { defineComponent, computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Loading } from '@element-plus/icons-vue'
import { todosApi, mercariAccountApi } from '@/api'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncOverlay } from '@/composables/useSyncOverlay'
import SyncOverlay from '@/components/SyncOverlay.vue'
import { mercariImageUrl } from '@/utils/mercariImage.js'

export default defineComponent({
  components: {
    SyncOverlay,
    Loading,
  },
  setup() {
    const { t } = useI18n()

    // 交易详情类「浏览器自动化」操作的等待覆盖（与 syncOverlay*（从煤炉同步）独立）
    const txOverlay = useSyncOverlay()

    const mercariAccountStore = useMercariAccountStore()
    const globalAccountId = computed({
      get: () => mercariAccountStore.selectedId,
      set: (v) => mercariAccountStore.setSelected(v),
    })

    const KIND_LABEL_KEYS = {
      WaitShippingCard: 'todos.kind.waitShipping',
      WaitShippingPoint: 'todos.kind.waitShipping',
      WaitShippingCarrier: 'todos.kind.waitShipping',
      TransactionWaitShippingFunds: 'todos.kind.waitShipping',
      MerpayRealcardWaitActivation: 'todos.kind.merpayActivation',
      ReviewedSeller: 'todos.kind.waitReview',
      IncomingMessage: 'todos.kind.waitReply',
    }

    const DEFAULT_REPLY = 'ご購入いただきありがとうございます。これから発送の準備をさせていただきます。設定した期日内に発送予定ですので今しばらくお待ちください。取引終了までよろしくお願いいたします。'
    const DEFAULT_REVIEW = 'この度はお取引ありがとうございました。また機会がありましたらよろしくお願いします。'

    // 「発送をしてください」（待发货）待办：处理时按商品 ID 反查本地库存图片与关联订单号
    const WAIT_SHIPPING_TITLE = '発送をしてください'

    // 发货尺寸硬编码列表，按 shipping_method_name 区分。
    // name 字段必须与煤炉 /shipping_class 页 radio 卡片标题文本完全一致（用于 Playwright 文本匹配点击）
    const SHIPPING_OPTIONS = {
      'ゆうゆうメルカリ便': [
        {
          name: 'ゆうパケット',
          rows: [
            ['サイズ', '3辺合計60cm以内'],
            ['送料', '¥230'],
            ['厚さ', '3cm以内'],
            ['重さ', '1kg以内'],
          ],
        },
        {
          name: 'ゆうパケットポストmini',
          rows: [
            ['サイズ', '専用封筒 (21cm×17cm)'],
            ['送料', '¥160'],
            ['重さ', '2kg以内'],
            ['発送', '郵便ポストから発送'],
          ],
          caveats: ['※専用封筒(¥20)の購入が必要です'],
          auto_finish_no_facility: true,
        },
        {
          name: 'ゆうパケットポスト',
          rows: [
            ['サイズ', '郵便ポストに投函可能なもの'],
            ['送料', '¥215'],
            ['重さ', '2kg以内'],
            ['発送', '郵便ポストから発送'],
          ],
          caveats: ['※専用箱(¥65)、または発送用シール(20枚入り¥100)の購入が必要です。'],
          auto_finish_no_facility: true,
        },
        {
          name: 'ゆうパケットプラス',
          rows: [
            ['サイズ', '専用箱 (17cm×24cm×7cm)'],
            ['送料', '¥455'],
            ['重さ', '2kg以内'],
          ],
          caveats: ['※専用箱(¥65)の購入が必要です'],
        },
        {
          name: 'ゆうパック60 - 100',
          rows: [
            ['サイズ', '3辺合計100cm以内'],
            ['送料', '¥750 - ¥1,070'],
            ['重さ', '25kg以内'],
          ],
        },
        {
          name: 'ゆうパック120 - 170',
          rows: [
            ['サイズ', '3辺合計170cm以内'],
            ['送料', '¥1,200 - ¥1,900'],
            ['重さ', '25kg以内'],
          ],
        },
      ],
      'らくらくメルカリ便': [
        {
          name: 'ネコポス',
          rows: [
            ['サイズ', '3辺合計60cm以内'],
            ['長辺', '34cm以内'],
            ['最小', '23cm × 11.5cm'],
          ],
        },
        {
          name: '宅急便コンパクト',
          rows: [
            ['サイズ', '専用BOX (20cm×25cm×5cm) / 薄型専用BOX (24.8cm×34cm)'],
            ['送料', '¥450'],
          ],
        },
        {
          name: '宅急便60 - 160',
          rows: [
            ['サイズ', '3辺合計160cm以内'],
            ['送料', '¥750'],
          ],
        },
        {
          name: '宅急便180 - 200',
          rows: [
            ['サイズ', '3辺合計200cm以内'],
          ],
        },
      ],
    }

    const KIND_TAG_TYPES = {
      WaitShippingCard: 'warning',
      WaitShippingPoint: 'warning',
      WaitShippingCarrier: 'warning',
      TransactionWaitShippingFunds: 'warning',
      MerpayRealcardWaitActivation: 'info',
      ReviewedSeller: 'success',
      IncomingMessage: 'primary',
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

    const syncLoading = ref(false)
    const bulkReviewLoading = ref(false)

    /** 「从煤炉同步」全屏等待与步骤文案（与后端 progress_job_id 轮询同步） */
    const syncOverlayVisible = ref(false)
    const syncOverlayTitle = ref(t('todos.syncingFromMercari'))
    const syncOverlayFailed = ref(false)
    const syncProgressLabel = ref('')
    let syncProgressTimer = null

    // ─── 交易详情面板 ───
    // 后端抓取接口未接入；先用本地 row 已有字段填充，其他字段留 null 显示占位
    const dash = '—'
    const detailDialogVisible = ref(false)
    const detailLoading = ref(false)
    const currentRow = ref(null)
    const detail = reactive(createEmptyDetail())

    // 「発送をしてください」反查到的本地库存（图片）与关联订单号
    const invMatch = reactive({ loading: false, inventory: [], order_nos: [] })

    function resetInvMatch() {
      invMatch.loading = false
      invMatch.inventory = []
      invMatch.order_nos = []
    }

    /** 本地库存图（/imges/...）走缩略图端点；非本地路径原样返回 */
    function inventoryThumbUrl(src, size = 200) {
      const s = String(src || '')
      if (!s.startsWith('/imges/')) return s
      return `/mercariV2/src/use_web/inventory/image-thumb?path=${encodeURIComponent(s)}&size=${size}`
    }

    // 当前待办是否「発送をしてください」（待发货）
    const isWaitShipping = computed(
      () => String(currentRow.value?.title || '').trim() === WAIT_SHIPPING_TITLE,
    )
    // 反查到的库存里是否有至少一张本地图片
    const hasLocalInventoryImages = computed(() =>
      (invMatch.inventory || []).some((inv) => Array.isArray(inv?.images) && inv.images.length > 0),
    )
    // 关联库存的「商品类型」（去重后合并展示；无匹配时为空）
    const inventoryProductType = computed(() => {
      const types = (invMatch.inventory || [])
        .map((inv) => String(inv?.product_type_name || '').trim())
        .filter(Boolean)
      return [...new Set(types)].join(' / ')
    })
    // 是否展示煤炉缩略图：仅在「非待发货」或「待发货但没关联到本地图片」时回落到煤炉图
    const showMercariPhoto = computed(() => {
      if (!detail.photo_url) return false
      if (!isWaitShipping.value) return true
      return !invMatch.loading && !hasLocalInventoryImages.value
    })

    async function loadInventoryMatch(itemId) {
      const iid = String(itemId || '').trim()
      if (!iid) return
      resetInvMatch()
      invMatch.loading = true
      try {
        const res = await todosApi.matchInventory(iid)
        invMatch.inventory = Array.isArray(res?.inventory) ? res.inventory : []
        invMatch.order_nos = Array.isArray(res?.order_nos) ? res.order_nos : []
      } catch (e) {
        // 反查失败不打断处理流程，仅记录
        console.error('[库存反查]', e?.message || e)
      } finally {
        invMatch.loading = false
      }
    }

    function createEmptyDetail() {
      return {
        // 本地 todo_items 即可得
        item_id: '',
        item_name: '',
        photo_url: '',
        buyer_name: '',
        sender_id: '',
        // 抓取 MITM 才有
        product_name: '',
        shipping_method_name: null,
        sender_address: null,
        current_shipping_status: null,
        shipment_status: null,
        has_size_location_btn: false,
        has_change_method_btn: false,
        messages: [], // [{ from, text, at, is_buyer, user_id }]
        captured: { shipping_info: false, transaction_messages: false },
        // 回复草稿（默认为空，点「默认回复」按钮可一键填入模板）
        reply_draft: '',
        // 评价草稿（仅 ReviewedSeller 用，预填默认评价）
        review_draft: DEFAULT_REVIEW,
      }
    }

    const replyLoading = ref(false)
    const reviewLoading = ref(false)
    const reactionLoading = ref(false)

    // 反应表情列表（与后端 SUPPORTED_REACTIONS / Mercari picker 顺序一一对应）
    // Mercari 的 picker 实际只有 5 个 emoji，按 button[1]..button[5] 顺序排列
    const REACTION_OPTIONS = [
      { key: 'heart', emoji: '❤️', label: '好き' },
      { key: 'smile', emoji: '😊', label: '笑顔' },
      { key: 'laugh', emoji: '😆', label: '笑い' },
      { key: 'pray', emoji: '🙏', label: 'ありがとう' },
      { key: 'party', emoji: '🎉', label: 'お祝い' },
    ]
    const REACTION_EMOJI_BY_KEY = Object.fromEntries(REACTION_OPTIONS.map((o) => [o.key, o.emoji]))
    const reactionOptions = REACTION_OPTIONS
    function emojiFor(key) {
      if (!key) return ''
      // 后端有可能直接返回 emoji 字符；这里两边都兼容
      return REACTION_EMOJI_BY_KEY[key] || key
    }

    // 当前待办是否是「评价买家」类型 → 切换为取引評価表单
    // 条件：kind === 'ReviewedSeller' 且 title === '評価をしてください'
    const isReviewedSeller = computed(() => {
      const kind = (currentRow.value?.kind || '').trim()
      const title = (currentRow.value?.title || '').trim()
      return kind === 'ReviewedSeller' && title === '評価をしてください'
    })

    // 仅在「待回复」(IncomingMessage) 类型下，允许给买家消息加 emoji 反应
    const canReactToMessages = computed(() => {
      return (currentRow.value?.kind || '').trim() === 'IncomingMessage'
    })

    // 选择尺寸 dialog（不再走 MITM 抓取，纯前端硬编码列表）
    const shippingDialogVisible = ref(false)
    const shippingConfirmLoading = ref(false)
    const shippingPickedIdx = ref(null)
    const shippingFacility = ref(null) // 'post_office' | 'lawson' | null
    const shippingOptions = computed(() => {
      const method = (detail.shipping_method_name || '').trim()
      if (SHIPPING_OPTIONS[method]) return SHIPPING_OPTIONS[method]
      // 未识别配送方式时把两套都列出来，让用户自行判断
      return [...(SHIPPING_OPTIONS['ゆうゆうメルカリ便'] || []), ...(SHIPPING_OPTIONS['らくらくメルカリ便'] || [])]
    })
    const shippingNeedsFacility = computed(() => {
      if (shippingPickedIdx.value == null) return false
      const opt = shippingOptions.value[shippingPickedIdx.value]
      return !!opt && !opt.auto_finish_no_facility
    })

    // 配送尺寸卡片插图：public/static/post_hukuro/<尺寸名>.png（文件名与 opt.name 完全一致）
    // 带版本号 query 防止旧的 404 负缓存命中（文件后补放进 public 时浏览器可能缓存过 404）
    function shippingImageUrl(name) {
      const s = String(name || '').trim()
      if (!s) return ''
      return `/static/post_hukuro/${encodeURIComponent(s)}.png?v=1`
    }

    // 图片缺失时隐藏 <img>，避免显示破图占位
    function onShippingImgError(e) {
      const el = e?.target
      if (el && el.style) el.style.visibility = 'hidden'
    }

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
        ElMessage.error(e?.message || t('todos.loadFailed'))
      } finally {
        loading.value = false
      }
    }

    async function loadAccountOptions() {
      try {
        const res = await mercariAccountApi.list({ page: 1, page_size: 200 })
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

    async function runSync() {
      if (syncLoading.value) return
      const aid = mercariAccountStore.selectedId
      if (!aid) {
        ElMessage.warning(t('todos.pleasePickAccountFirst'))
        return
      }
      const name = mercariAccountStore.selectedAccountName || `#${aid}`
      try {
        await ElMessageBox.confirm(
          t('todos.syncConfirmMessage', { name }),
          t('todos.syncConfirmTitle'),
          { type: 'info', confirmButtonText: t('todos.start'), cancelButtonText: t('common.cancel') },
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
          const pr = await todosApi.getSyncProgress(progressJobId)
          const d = pr?.data
          const zh = d?.label_zh
          if (zh) {
            syncProgressLabel.value = zh
            if (zh !== lastConsoleStep) {
              lastConsoleStep = zh
              console.log('[待办同步]', zh)
            }
          }
        } catch {
          /* 轮询失败忽略 */
        }
      }

      syncOverlayTitle.value = t('todos.syncingFromMercari')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('todos.connectingServer')
      syncOverlayVisible.value = true
      syncLoading.value = true
      await pollSyncProgress()
      syncProgressTimer = setInterval(pollSyncProgress, 400)

      let syncHadError = false
      try {
        const d = (await todosApi.sync({ account_id: aid, progress_job_id: progressJobId })) || {}
        ElMessageBox.alert(
          t('todos.syncResultMessage', {
            accountId: d.account_id ?? '-',
            inserted: d.inserted ?? 0,
            updated: d.updated ?? 0,
            markedDone: d.marked_deleted ?? 0,
            total: d.total ?? 0,
          }),
          t('todos.syncResultTitle'),
          { type: 'success', confirmButtonText: t('dialog.confirmBtn') },
        )
        await Promise.all([load(), loadKindOptions()])
      } catch (e) {
        syncHadError = true
        syncOverlayTitle.value = t('todos.syncFailed')
        syncOverlayFailed.value = true
        const msg = e?.response?.data?.detail || e?.message || t('todos.syncFailed')
        syncProgressLabel.value = String(msg)
        ElMessage.error(msg)
      } finally {
        if (syncProgressTimer != null) {
          clearInterval(syncProgressTimer)
          syncProgressTimer = null
        }
        if (syncHadError) {
          await new Promise((r) => setTimeout(r, 1200))
        }
        syncOverlayVisible.value = false
        syncOverlayTitle.value = t('todos.syncingFromMercari')
        syncOverlayFailed.value = false
        syncProgressLabel.value = ''
        syncLoading.value = false
      }
    }

    async function runBulkReview() {
      if (bulkReviewLoading.value || syncLoading.value) return

      let candidates = []
      try {
        const res = await todosApi.list({ page: 1, page_size: 500, kind: 'ReviewedSeller' })
        candidates = (res?.items || []).filter(
          (r) => !r.is_delete && String(r.title || '').trim() === '評価をしてください',
        )
      } catch (e) {
        ElMessage.error(e?.message || t('todos.loadFailed'))
        return
      }

      if (!candidates.length) {
        ElMessage.info(t('todos.bulkReviewNoCandidates'))
        return
      }

      try {
        await ElMessageBox.confirm(
          t('todos.bulkReviewConfirmMessage', { count: candidates.length }),
          t('todos.bulkReviewConfirmTitle'),
          { type: 'info', confirmButtonText: t('todos.start'), cancelButtonText: t('common.cancel') },
        )
      } catch {
        return
      }

      bulkReviewLoading.value = true
      syncOverlayTitle.value = t('todos.bulkReviewRunning')
      syncOverlayFailed.value = false
      syncProgressLabel.value = t('todos.connectingServer')
      syncOverlayVisible.value = true

      let okCount = 0
      let failCount = 0
      const failures = []

      for (let i = 0; i < candidates.length; i++) {
        const row = candidates[i]
        syncProgressLabel.value = t('todos.bulkReviewProgress', {
          current: i + 1,
          total: candidates.length,
          itemId: row.item_id || `#${row.id}`,
        })
        try {
          await todosApi.fetchTransactionDetail(row.id, {})
          const result = await todosApi.submitTransactionReview(row.id, DEFAULT_REVIEW, {})
          if (result?.completed) {
            okCount += 1
          } else {
            failCount += 1
            failures.push(`#${row.id} ${row.item_id || ''}`.trim())
          }
        } catch (e) {
          failCount += 1
          const msg = e?.response?.data?.detail || e?.message || 'error'
          failures.push(`#${row.id} ${row.item_id || ''}: ${msg}`.trim())
          console.error('[一键好评]', row.id, msg)
        } finally {
          // 每条结束后幂等关一次浏览器，避免下一条被卡
          const aid = row.account_id
          if (aid) {
            try { await todosApi.closeDetailBrowser(aid) } catch { /* 忽略 */ }
          }
        }
      }

      syncOverlayVisible.value = false
      syncOverlayTitle.value = t('todos.syncingFromMercari')
      syncProgressLabel.value = ''
      bulkReviewLoading.value = false

      const summary = t('todos.bulkReviewResult', {
        ok: okCount,
        fail: failCount,
        total: candidates.length,
      })
      ElMessageBox.alert(
        failures.length ? `${summary}\n${failures.slice(0, 10).join('\n')}` : summary,
        t('todos.bulkReviewConfirmTitle'),
        { type: failCount ? 'warning' : 'success', confirmButtonText: t('dialog.confirmBtn') },
      )

      await load()
    }

    // 入参可为 kind 字符串（下拉筛选）或整行（表格）；标题为「発送をしてください」时一律按待发货
    function kindLabel(kindOrRow) {
      const isRow = kindOrRow && typeof kindOrRow === 'object'
      const kind = String((isRow ? kindOrRow.kind : kindOrRow) || '').trim()
      const title = isRow ? String(kindOrRow.title || '').trim() : ''
      if (title === WAIT_SHIPPING_TITLE) return t('todos.kind.waitShipping')
      if (!kind) return '-'
      const key = KIND_LABEL_KEYS[kind]
      return key ? t(key) : kind
    }

    function kindTagType(kindOrRow) {
      const isRow = kindOrRow && typeof kindOrRow === 'object'
      const kind = String((isRow ? kindOrRow.kind : kindOrRow) || '').trim()
      const title = isRow ? String(kindOrRow.title || '').trim() : ''
      if (title === WAIT_SHIPPING_TITLE) return 'warning'
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
      currentRow.value = row
      Object.assign(detail, createEmptyDetail(), {
        item_id: row.item_id || '',
        item_name: row.item_name || '',
        photo_url: row.photo_url || '',
        buyer_name: buyerNameFromMessage(row.message) || '',
        sender_id: row.sender_id || '',
      })
      resetInvMatch()
      detailDialogVisible.value = true
      // 「発送をしてください」：按商品 ID 反查本地库存图片与关联订单号
      if (String(row.title || '').trim() === WAIT_SHIPPING_TITLE) {
        loadInventoryMatch(row.item_id)
      }
      // 自动启动浏览器抓取真实数据
      onDetailRefresh()
    }

    async function onDetailRefresh() {
      if (!currentRow.value?.id) return
      if (!currentRow.value?.item_id) {
        ElMessage.warning(t('todos.noItemIdInTodo'))
        return
      }
      detailLoading.value = true
      try {
        const d = await txOverlay.run({
          title: t('todos.fetchingDetail'),
          consoleTag: '[交易详情]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.fetchTransactionDetail(currentRow.value.id, { progress_job_id: jobId }),
        })
        if (!d || typeof d !== 'object') {
          ElMessage.warning(t('todos.noDetailData'))
          return
        }
        // 合并抓取结果；本地预填的字段（item_id/photo_url 等）保留
        const merged = { ...d }
        // 部分字段可能为 null，避免覆盖本地预填值
        if (merged.buyer_name == null) delete merged.buyer_name
        Object.assign(detail, merged)
        ElMessage.success(t('todos.detailFetched'))
      } catch (e) {
        // axios 拦截器已弹错误；此处保留兜底
        if (!e?.response) ElMessage.error(e?.message || t('todos.fetchFailed'))
      } finally {
        detailLoading.value = false
      }
    }

    function onOpenMercariPage() {
      const iid = String(detail.item_id || '').trim()
      if (!iid) {
        ElMessage.warning(t('todos.noItemIdCannotOpen'))
        return
      }
      window.open(`https://jp.mercari.com/transaction/${iid}`, '_blank', 'noopener')
    }

    async function onClickShippingSizeLocation() {
      if (!currentRow.value?.id) return
      // 先点开页面上的「商品サイズと発送場所を選択する」让浏览器跳到尺寸选择页
      try {
        await txOverlay.run({
          title: t('todos.openingSizeSelection'),
          consoleTag: '[尺寸选择]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.startShippingClass(currentRow.value.id, { progress_job_id: jobId }),
        })
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.openSizePageFailed'))
        return
      }
      shippingPickedIdx.value = null
      shippingFacility.value = null
      shippingDialogVisible.value = true
    }

    async function onConfirmShippingSelection() {
      if (!currentRow.value?.id) return
      const idx = shippingPickedIdx.value
      if (idx == null) return
      const opt = shippingOptions.value[idx]
      if (!opt) return
      const classText = opt.name
      const needsFacility = !opt.auto_finish_no_facility
      if (needsFacility && !shippingFacility.value) {
        ElMessage.warning(t('todos.pickFacility'))
        return
      }
      // ゆうパケットポスト系（auto_finish_no_facility）は完了後そのまま二维码扫描ページへ
      const wantScanQr = !!opt.auto_finish_no_facility
      shippingConfirmLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.confirmingShipping'),
          consoleTag: '[发货确认]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.confirmShippingSelection(currentRow.value.id, {
              class_text: classText,
              facility: needsFacility ? shippingFacility.value : null,
              scan_qr: wantScanQr,
              progress_job_id: jobId,
            }),
        })
        ElMessage.success(t('todos.shippingDone', { classText }))
        shippingDialogVisible.value = false
        // 后端已自动打开 /qr_code_scanner → 开镜像弹窗轮询视频帧
        if (wantScanQr && result?.qr_scanner_open) {
          startQrScanMirror(currentRow.value.id)
        } else {
          onDetailRefresh()
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shippingConfirmLoading.value = false
      }
    }

    // ─── QR 扫描镜像（把有头浏览器的 /qr_code_scanner 摄像头画面镜像到弹窗） ───
    const qrScanVisible = ref(false)
    const qrScanFrame = ref('')
    const qrScanDone = ref(false)
    const QR_SCAN_FPS = 24
    let qrScanTimer = null
    let qrScanInFlight = false // 防止上一帧未返回就发下一帧请求堆积

    function stopQrScanMirror() {
      if (qrScanTimer != null) {
        clearInterval(qrScanTimer)
        qrScanTimer = null
      }
      qrScanInFlight = false
    }

    async function pollQrScanFrame() {
      const id = currentRow.value?.id
      if (!id) return
      if (qrScanInFlight) return
      qrScanInFlight = true
      try {
        const res = await todosApi.qrScannerFrame(id)
        if (res?.frame) qrScanFrame.value = res.frame
        if (res?.done) {
          qrScanDone.value = true
          stopQrScanMirror()
          // 扫描成功 → 自动关闭扫码弹窗 → 读取确认信息并弹二次确认框
          qrScanVisible.value = false
          openShipConfirmDialog()
        }
      } catch (e) {
        console.error('[QR镜像]', e?.message || e)
      } finally {
        qrScanInFlight = false
      }
    }

    function startQrScanMirror(/* todoId */) {
      stopQrScanMirror()
      qrScanFrame.value = ''
      qrScanDone.value = false
      qrScanVisible.value = true
      pollQrScanFrame()
      qrScanTimer = setInterval(pollQrScanFrame, Math.round(1000 / QR_SCAN_FPS))
    }

    function onQrScanDialogClose() {
      stopQrScanMirror()
      qrScanVisible.value = false
    }

    // ─── 发货二次确认（読み取り成功後の発送確認符号 / 追跡番号 → 用户确认 → 発送通知） ───
    const shipConfirmVisible = ref(false)
    const shipConfirmLoading = ref(false)
    const shipConfirmInfo = reactive({ ok: false, confirm_code: '', tracking_no: '' })

    async function openShipConfirmDialog() {
      const id = currentRow.value?.id
      if (!id) return
      shipConfirmInfo.ok = false
      shipConfirmInfo.confirm_code = ''
      shipConfirmInfo.tracking_no = ''
      shipConfirmVisible.value = true
      shipConfirmLoading.value = true
      try {
        const res = await todosApi.postShippingInfo(id)
        shipConfirmInfo.ok = !!res?.ok
        shipConfirmInfo.confirm_code = res?.confirm_code || ''
        shipConfirmInfo.tracking_no = res?.tracking_no || ''
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.fetchFailed'))
      } finally {
        shipConfirmLoading.value = false
      }
    }

    async function onShipConfirmSubmit() {
      const id = currentRow.value?.id
      if (!id) return
      shipConfirmLoading.value = true
      try {
        await txOverlay.run({
          title: t('todos.finalizingShipping'),
          consoleTag: '[发货通知]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) => todosApi.finalizePostShipping(id, { progress_job_id: jobId }),
        })
        ElMessage.success(t('todos.shipNotified'))
        shipConfirmVisible.value = false
        detailDialogVisible.value = false
        load()
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shipConfirmLoading.value = false
      }
    }

    function onShipConfirmCancel() {
      shipConfirmVisible.value = false
    }

    async function onClickShippingChangeMethod() {
      if (!currentRow.value?.id) return
      try {
        await txOverlay.run({
          title: t('todos.clickingChangeMethod'),
          consoleTag: '[修改发送方式]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.changeShippingMethod(currentRow.value.id, { progress_job_id: jobId }),
        })
        ElMessage.success(t('todos.changeMethodClicked'))
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.clickFailed'))
      }
    }


    function onDetailSubmit() {
      // TODO: 完成处理 → 本地标完成 + 关闭面板（具体动作待定）
      ElMessage.info(t('todos.finishActionPending'))
    }

    function onResetReplyDefault() {
      detail.reply_draft = DEFAULT_REPLY
    }

    async function onSendReply() {
      if (!currentRow.value?.id) return
      const text = (detail.reply_draft || '').trim()
      if (!text) {
        ElMessage.warning(t('todos.replyEmpty'))
        return
      }
      replyLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.sendingMessage'),
          consoleTag: '[发送回复]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.sendTransactionMessage(currentRow.value.id, text, { progress_job_id: jobId }),
        })
        if (result?.completed) {
          // 待回复（IncomingMessage）：后端已软删 + 关浏览器，前端关 dialog + 刷列表
          ElMessage.success(t('todos.repliedDone'))
          detailDialogVisible.value = false
          load()
        } else {
          ElMessage.success(t('todos.sendButtonClicked'))
          // 普通发送：刷新一次抓取让消息流更新
          onDetailRefresh()
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.sendFailed'))
      } finally {
        replyLoading.value = false
      }
    }

    function onResetReviewDefault() {
      detail.review_draft = DEFAULT_REVIEW
    }

    async function onSubmitReview() {
      if (!currentRow.value?.id) return
      const text = (detail.review_draft || '').trim()
      if (!text) {
        ElMessage.warning(t('todos.reviewEmpty'))
        return
      }
      reviewLoading.value = true
      try {
        const result = await txOverlay.run({
          title: t('todos.submittingReview'),
          consoleTag: '[提交评价]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.submitTransactionReview(currentRow.value.id, text, { progress_job_id: jobId }),
        })
        if (result?.completed) {
          const note = result.order_refresh_error
            ? t('todos.orderRefreshErrorNote', { error: result.order_refresh_error })
            : ''
          ElMessage.success(`${t('todos.transactionCompletedDetected')}${note}`)
          // 浏览器已由后端关闭；这里关 dialog（onDetailDialogClose 里的 closeBrowser 是幂等的）
          detailDialogVisible.value = false
          load() // 刷新待办列表（todo 已软删，列表中应消失）
        } else {
          ElMessage.warning(t('todos.submittedNoComplete'))
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        reviewLoading.value = false
      }
    }

    async function onSendReaction(message, reactionKey) {
      if (!currentRow.value?.id) return
      if (!message || !message.is_buyer) return
      if (reactionLoading.value) return
      // 在「买家消息序列」里查 reaction_index（后端按这个在 DOM 上定位第 N 个 + 反应按钮）
      const buyerMessages = (detail.messages || []).filter((m) => m && m.is_buyer)
      const reactionIndex = buyerMessages.findIndex((m) => {
        if (message.id && m.id) return String(m.id) === String(message.id)
        return m === message
      })
      if (reactionIndex < 0) {
        ElMessage.error(t('todos.locateMsgFailed'))
        return
      }
      reactionLoading.value = true
      try {
        await txOverlay.run({
          title: t('todos.sendingReaction'),
          consoleTag: '[发送反应]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.sendMessageReaction(currentRow.value.id, {
              message_id: message.id || null,
              reaction_index: reactionIndex,
              reaction: reactionKey,
              progress_job_id: jobId,
            }),
        })
        // 本地立即把反应贴到对应消息上,避免再抓一次煤炉
        message.reaction = reactionKey
        ElMessage.success(t('todos.reactionSent', { emoji: REACTION_EMOJI_BY_KEY[reactionKey] || reactionKey }))
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.reactionFailed'))
      } finally {
        reactionLoading.value = false
      }
    }

    function onDetailDialogClose() {
      // 关 dialog 时同步关掉对应账号的 __auto 浏览器（fire-and-forget）
      const aid = currentRow.value?.account_id
      if (aid) {
        todosApi.closeDetailBrowser(aid).catch(() => { /* 忽略关浏览器失败 */ })
      }
      currentRow.value = null
      replyLoading.value = false
      resetInvMatch()
    }


    function buyerNameFromMessage(msg) {
      const s = String(msg || '')
      // 「<买家名>さんが...」 / 「<买家名>さんに...」
      const m = s.match(/^(.+?)さん[がにへ]/)
      return m ? m[1].trim() : ''
    }

    onMounted(() => {
      mercariAccountStore.ensureLoaded()
      Promise.all([loadAccountOptions(), loadKindOptions()])
      load()
    })

    onBeforeUnmount(() => {
      if (syncProgressTimer != null) {
        clearInterval(syncProgressTimer)
        syncProgressTimer = null
      }
      stopQrScanMirror()
      txOverlay.dispose()
    })

    return {
      computed,
      onBeforeUnmount,
      onMounted,
      reactive,
      ref,
      useI18n,
      ElMessage,
      ElMessageBox,
      Download,
      Loading,
      todosApi,
      mercariAccountApi,
      useMercariAccountStore,
      useSyncOverlay,
      SyncOverlay,
      mercariImageUrl,
      t,
      txOverlay,
      mercariAccountStore,
      globalAccountId,
      KIND_LABEL_KEYS,
      DEFAULT_REPLY,
      DEFAULT_REVIEW,
      SHIPPING_OPTIONS,
      KIND_TAG_TYPES,
      list,
      total,
      loading,
      page,
      pageSize,
      filters,
      accountOptions,
      kindOptions,
      syncLoading,
      bulkReviewLoading,
      syncOverlayVisible,
      syncOverlayTitle,
      syncOverlayFailed,
      syncProgressLabel,
      syncProgressTimer,
      dash,
      detailDialogVisible,
      detailLoading,
      currentRow,
      detail,
      createEmptyDetail,
      WAIT_SHIPPING_TITLE,
      invMatch,
      inventoryThumbUrl,
      loadInventoryMatch,
      isWaitShipping,
      hasLocalInventoryImages,
      showMercariPhoto,
      inventoryProductType,
      replyLoading,
      reviewLoading,
      reactionLoading,
      REACTION_OPTIONS,
      REACTION_EMOJI_BY_KEY,
      reactionOptions,
      emojiFor,
      isReviewedSeller,
      canReactToMessages,
      shippingDialogVisible,
      shippingConfirmLoading,
      shippingPickedIdx,
      shippingFacility,
      shippingOptions,
      shippingNeedsFacility,
      shippingImageUrl,
      onShippingImgError,
      listParams,
      load,
      loadAccountOptions,
      loadKindOptions,
      onFilterChange,
      onPageChange,
      onPageSizeChange,
      runSync,
      runBulkReview,
      kindLabel,
      kindTagType,
      displayTs,
      mercariItemUrl,
      onProcess,
      onDetailRefresh,
      onOpenMercariPage,
      onClickShippingSizeLocation,
      onConfirmShippingSelection,
      qrScanVisible,
      qrScanFrame,
      qrScanDone,
      startQrScanMirror,
      stopQrScanMirror,
      onQrScanDialogClose,
      shipConfirmVisible,
      shipConfirmLoading,
      shipConfirmInfo,
      onShipConfirmSubmit,
      onShipConfirmCancel,
      onClickShippingChangeMethod,
      onDetailSubmit,
      onResetReplyDefault,
      onSendReply,
      onResetReviewDefault,
      onSubmitReview,
      onSendReaction,
      onDetailDialogClose,
      buyerNameFromMessage,
    }
  },
})
