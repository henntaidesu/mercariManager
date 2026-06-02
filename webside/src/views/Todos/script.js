import { defineComponent, computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Loading } from '@element-plus/icons-vue'
import { todosApi, costRecordApi, costExpenseApi, orderApi } from '@/api'
import { useMercariAccountStore } from '@/stores/mercariAccount.js'
import { useSyncLockStore } from '@/stores/syncLock.js'
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
    const syncLockStore = useSyncLockStore()

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

    // ゆうゆうメルカリ便 各尺寸共用的发送方法（发货地）：郵便局 / ローソン。
    // code 与煤炉 /shipping_facilities 页 radio 的 value 属性完全一致（大写）。
    const YUYU_FACILITIES = [
      { code: 'POST_OFFICE', label: '郵便局', img: 'japan-post' },
      { code: 'LAWSON', label: 'ローソン', img: 'lawson' },
    ]

    // らくらくメルカリ便 各尺寸（ネコポス / 宅急便コンパクト / 宅急便60-160 / 宅急便180-200）共用的
    // 发送方法（发货地）：到店出示二维码发货的门店类。code 与煤炉 /shipping_facilities
    // radio 的 value 属性完全一致（大写）。选择后浏览器内点「選択して完了する」→ 返回交易页
    // 点「発送用◯◯コードを発行」生成二维码 → 后端保存到本地。
    const RAKURAKU_FACILITIES = [
      { code: 'SEVEN_ELEVEN', label: 'セブン-イレブン', img: '7-eleven' },
      { code: 'FAMILY_MART', label: 'ファミリーマート', img: 'family-mart' },
      { code: 'YAMATO_OFFICE', label: 'ヤマト運輸 営業所', img: 'yamato' },
      { code: 'PUDO', label: '宅配便ロッカーPUDO', img: 'pudo' },
    ]

    // 宅急便60-160（taQBin 60-160）专用发送方法：与煤炉 /shipping_facilities 页
    // 该尺寸可用 radio 完全一致（code = value 属性）。比小尺寸多出 集荷 / スマリボックス /
    // マンション・戸建てSmari。选择后同样：返回交易页点「発送用◯◯コードを発行」生成并保存二维码。
    const RAKURAKU_TAQ160_FACILITIES = [
      { code: 'SEVEN_ELEVEN', label: 'セブン-イレブン', img: '7-eleven' },
      { code: 'FAMILY_MART', label: 'ファミリーマート', img: 'family-mart' },
      { code: 'YAMATO_OFFICE', label: 'ヤマト運輸 営業所', img: 'yamato' },
      { code: 'PICKUP', label: 'ヤマト運輸による集荷', img: 'pick-up' },
      { code: 'PUDO', label: '宅配便ロッカーPUDO', img: 'pudo' },
      { code: 'SMARI', label: 'スマリボックス', img: 'smari-box' },
      { code: 'SMARI_HOME_LOCKER', label: 'マンション・戸建てSmari', img: 'smari-box' },
    ]

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
          facilities: YUYU_FACILITIES,
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
          facilities: YUYU_FACILITIES,
        },
        {
          name: 'ゆうパック60 - 100',
          rows: [
            ['サイズ', '3辺合計100cm以内'],
            ['送料', '¥750 - ¥1,070'],
            ['重さ', '25kg以内'],
          ],
          facilities: YUYU_FACILITIES,
        },
        {
          name: 'ゆうパック120 - 170',
          rows: [
            ['サイズ', '3辺合計170cm以内'],
            ['送料', '¥1,200 - ¥1,900'],
            ['重さ', '25kg以内'],
          ],
          facilities: YUYU_FACILITIES,
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
          // 发货地（与煤炉 /shipping_facilities radio 的 value 属性一致）。img 为 public/static/post_hukuro 下文件名（无扩展名）
          facilities: RAKURAKU_FACILITIES,
        },
        {
          name: '宅急便コンパクト',
          rows: [
            ['サイズ', '専用BOX (20cm×25cm×5cm) / 薄型専用BOX (24.8cm×34cm)'],
            ['送料', '¥450'],
          ],
          facilities: RAKURAKU_FACILITIES,
        },
        {
          name: '宅急便60 - 160',
          rows: [
            ['サイズ', '3辺合計160cm以内'],
            ['送料', '¥750'],
          ],
          facilities: RAKURAKU_TAQ160_FACILITIES,
        },
        {
          name: '宅急便180 - 200',
          rows: [
            ['サイズ', '3辺合計200cm以内'],
          ],
          facilities: RAKURAKU_FACILITIES,
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
      kind: '',
      include_deleted: false,
    })

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

    // ===== 待发货：包材选择 + 关联订单出库（发货成功后同步到 /#/orders） =====
    const PACKAGING_ITEM_NONE = '__PACKAGING_NONE__'
    const packagingItemsOptions = ref([])
    // 用户选定的包材列表（可多个、可同种重复；每行数量固定 1）。末尾始终保留一个空行供继续添加
    const shipPackagingRows = ref([{ item_name: '' }])
    // 关联订单的出库明细（发货成功后逐条出库）
    const shipOutbound = reactive({ loading: false, lines: [] })

    function selectedPackagingMeta(itemName) {
      return (packagingItemsOptions.value || []).find((it) => it.item_name === itemName) || null
    }
    /** 归一化包材行：去掉中间空行、末尾补一个空行；选「不选择包材」时独占一行 */
    function normalizePackagingRows() {
      const rows = (shipPackagingRows.value || []).map((r) => ({ item_name: String(r?.item_name || '') }))
      if (rows.some((r) => r.item_name === PACKAGING_ITEM_NONE)) {
        shipPackagingRows.value = [{ item_name: PACKAGING_ITEM_NONE }]
        return
      }
      const filled = rows.filter((r) => r.item_name.trim())
      shipPackagingRows.value = [...filled, { item_name: '' }]
    }
    function onShipPackagingChange() {
      normalizePackagingRows()
    }
    async function loadPackagingItemOptions() {
      try {
        const res = await costRecordApi.listPackagingItems()
        packagingItemsOptions.value = Array.isArray(res?.items) ? res.items : []
      } catch (e) {
        console.error('[包材选项]', e?.message || e)
        packagingItemsOptions.value = []
      }
    }
    function resetShipCommit() {
      shipPackagingRows.value = [{ item_name: '' }]
      shipOutbound.loading = false
      shipOutbound.lines = []
    }
    function shipLineCanStockOut(line) {
      if (Number(line?.is_stocked_out || 0) === 1) return false
      if (line?.inventory_id == null) return false
      return Math.max(1, Number(line?.quantity || 1)) > 0
    }
    const shipPendingOutboundCount = computed(
      () => (shipOutbound.lines || []).filter((l) => shipLineCanStockOut(l)).length,
    )
    async function loadShipOutboundLines(orderNos) {
      const list = Array.isArray(orderNos) ? orderNos : [orderNos]
      const nos = [...new Set(list.map((x) => String(x || '').trim()).filter(Boolean))]
      if (!nos.length) {
        shipOutbound.lines = []
        return
      }
      shipOutbound.loading = true
      try {
        const all = []
        for (const ono of nos) {
          const res = await orderApi.outboundLines({ order_no: ono })
          const rows = Array.isArray(res?.items) ? res.items : []
          for (const r of rows) all.push({ ...r, __order_no: ono })
        }
        shipOutbound.lines = all
      } catch (e) {
        console.error('[出库明细]', e?.message || e)
        shipOutbound.lines = []
      } finally {
        shipOutbound.loading = false
      }
    }

    /** 发货成功后：把所选包材写入关联订单，并把关联订单的待出库明细逐条出库 */
    async function commitShipPackagingAndOutbound() {
      const nos = [...new Set((invMatch.order_nos || []).map((x) => String(x || '').trim()).filter(Boolean))]
      const itemId = String(currentRow.value?.item_id || '').trim()
      if (!nos.length && itemId) nos.push(itemId)
      if (!nos.length) return
      // 1) 同步包材到订单（与 /#/orders 二级列表一致）。同种包材按选择次数合并为数量
      const counts = new Map()
      let hasNone = false
      for (const r of shipPackagingRows.value || []) {
        const name = String(r?.item_name || '').trim()
        if (!name) continue
        if (name === PACKAGING_ITEM_NONE) {
          hasNone = true
          continue
        }
        counts.set(name, (counts.get(name) || 0) + 1)
      }
      try {
        if (counts.size) {
          for (const ono of nos) {
            for (const [name, qty] of counts) {
              const meta = selectedPackagingMeta(name)
              const unitPrice = Math.max(0, Number(meta?.amount || 0))
              await costExpenseApi.create({ order_no: ono, item_name: name, quantity: qty, unit_price: unitPrice })
            }
          }
        } else if (hasNone) {
          for (const ono of nos) await orderApi.waivePackaging({ order_no: ono })
        }
      } catch (e) {
        console.error('[包材同步]', e?.message || e)
        ElMessage.warning(t('todos.packagingSyncFailed'))
      }
      // 2) 出库：关联订单下所有待出库明细
      let okCount = 0
      let failCount = 0
      for (const line of shipOutbound.lines || []) {
        if (!shipLineCanStockOut(line)) continue
        try {
          await orderApi.stockOutOutboundLine(Number(line.id), {})
          okCount += 1
        } catch (e) {
          failCount += 1
          console.error('[出库]', line?.id, e?.message || e)
        }
      }
      if (okCount) ElMessage.success(t('todos.outboundDone', { count: okCount }))
      if (failCount) ElMessage.warning(t('todos.outboundPartialFail', { count: failCount }))
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
      resetShipCommit()
      invMatch.loading = true
      try {
        const res = await todosApi.matchInventory(iid)
        invMatch.inventory = Array.isArray(res?.inventory) ? res.inventory : []
        invMatch.order_nos = Array.isArray(res?.order_nos) ? res.order_nos : []
        // 预载包材选项 + 关联订单出库明细，供发货成功后同步到 /#/orders
        loadPackagingItemOptions()
        loadShipOutboundLines(invMatch.order_nos.length ? invMatch.order_nos : [iid])
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
        // 发行后保存到本地的发货二维码图片（/imges/...）
        qr_image_url: '',
        // 上次从煤炉抓取的时间戳（缓存命中时显示）
        detail_synced_at: null,
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
    // 当前选中尺寸对应的发货地卡片列表（按尺寸不同；未定义则回落到旧式 邮局/罗森 radio）
    const shippingFacilities = computed(() => {
      if (shippingPickedIdx.value == null) return []
      const opt = shippingOptions.value[shippingPickedIdx.value]
      return Array.isArray(opt?.facilities) ? opt.facilities : []
    })
    // 选择尺寸：切换后重置已选发货地（不同尺寸可选发货地不同）
    function onPickShipping(idx) {
      shippingPickedIdx.value = idx
      shippingFacility.value = null
    }
    // 发货地图标：public/static/post_hukuro/<img>.png
    function facilityImageUrl(img) {
      const s = String(img || '').trim()
      if (!s) return ''
      return `/static/post_hukuro/${encodeURIComponent(s)}.png?v=1`
    }

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
      try {
        await ElMessageBox.confirm(
          t('todos.syncConfirmMessage'),
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
        const d = (await todosApi.sync({ progress_job_id: progressJobId })) || {}
        ElMessageBox.alert(
          t('todos.syncResultMessage', {
            accountCount: d.account_count ?? 0,
            failCount: d.fail_count ?? 0,
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
      // 优先读本地缓存（不开浏览器）；用户点「刷新抓取」才打开浏览器更新
      loadDetailCache()
    }

    /** 读取交易详情本地缓存（不开浏览器）。无缓存时保持本地预填字段。 */
    async function loadDetailCache() {
      if (!currentRow.value?.id) return
      try {
        const d = await todosApi.transactionDetailCache(currentRow.value.id)
        if (d && typeof d === 'object') {
          const merged = { ...d }
          // null 字段不覆盖本地预填（buyer_name 等）
          if (merged.buyer_name == null) delete merged.buyer_name
          Object.assign(detail, merged)
        }
      } catch { /* 无缓存：静默，保留本地预填 */ }
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
      // ゆうパケットポスト系（auto_finish_no_facility）は完了後そのまま二维码扫描ページへ（用摄像头）。
      // それ以外（需选发货地的方法）は完了後、返回交易ページ发行 发送用 QR/条形码（无需摄像头）。
      const wantScanQr = !!opt.auto_finish_no_facility
      const wantGenerateCode = needsFacility
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
              generate_code: wantGenerateCode,
              progress_job_id: jobId,
            }),
        })
        ElMessage.success(t('todos.shippingDone', { classText }))
        shippingDialogVisible.value = false
        if (wantScanQr && result?.qr_scanner_open) {
          // 后端已自动打开 /qr_code_scanner → 开镜像弹窗轮询视频帧
          startQrScanMirror(currentRow.value.id)
        } else if (wantGenerateCode) {
          // 发行后已保存发货二维码：直接显示，并刷新本地缓存（不再开浏览器）
          if (result?.qr_image_url) detail.qr_image_url = result.qr_image_url
          loadDetailCache()
        } else {
          loadDetailCache()
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shippingConfirmLoading.value = false
      }
    }

    // ─── 远程摄像头：服务器无摄像头 → 把「本机（客户端）摄像头」推流给有头浏览器当虚拟摄像头 ───
    // 弹窗里显示本机摄像头画面，并以 ~15fps 把每帧上传后端 → 注入到 /qr_code_scanner 的虚拟摄像头 canvas。
    // 同一次上传的响应带 done 状态：读取成功（回到 /transaction/）即停止推流并进入二次确认。
    const qrScanVisible = ref(false)
    const qrScanDone = ref(false)
    const qrCamError = ref('')
    const qrVideoEl = ref(null)
    const QR_CAM_FPS = 15
    const QR_CAM_MAX_W = 960 // 上传帧最大宽度（限制体积，同时保留足够分辨率供二维码识别）
    let qrCamStream = null
    let qrCamCanvas = null
    let qrScanTimer = null
    let qrPushInFlight = false // 防止上一帧未返回就堆积请求

    function stopQrScanMirror() {
      if (qrScanTimer != null) {
        clearInterval(qrScanTimer)
        qrScanTimer = null
      }
      qrPushInFlight = false
      if (qrCamStream) {
        try {
          qrCamStream.getTracks().forEach((tr) => tr.stop())
        } catch { /* noop */ }
        qrCamStream = null
      }
      if (qrVideoEl.value) {
        try {
          qrVideoEl.value.srcObject = null
        } catch { /* noop */ }
      }
    }

    /** 抓取本机摄像头一帧 → JPEG dataURL → 上传后端注入虚拟摄像头；响应里读 done */
    async function captureAndPushFrame() {
      const id = currentRow.value?.id
      if (!id) return
      if (qrPushInFlight) return
      qrPushInFlight = true
      try {
        let frame = ''
        let w = 0
        let h = 0
        const video = qrVideoEl.value
        if (video && video.readyState >= 2 && video.videoWidth > 0) {
          const sw = video.videoWidth
          const sh = video.videoHeight
          const scale = sw > QR_CAM_MAX_W ? QR_CAM_MAX_W / sw : 1
          w = Math.round(sw * scale)
          h = Math.round(sh * scale)
          if (!qrCamCanvas) qrCamCanvas = document.createElement('canvas')
          qrCamCanvas.width = w
          qrCamCanvas.height = h
          const ctx = qrCamCanvas.getContext('2d')
          ctx.drawImage(video, 0, 0, w, h)
          frame = qrCamCanvas.toDataURL('image/jpeg', 0.6)
        }
        const res = await todosApi.cameraFrame(id, { frame, width: w, height: h })
        if (res?.done) {
          qrScanDone.value = true
          stopQrScanMirror()
          // 读取成功 → 自动关闭扫码弹窗 → 读取确认信息并弹二次确认框
          qrScanVisible.value = false
          openShipConfirmDialog()
        }
      } catch (e) {
        console.error('[QR摄像头]', e?.message || e)
      } finally {
        qrPushInFlight = false
      }
    }

    async function startQrScanMirror(/* todoId */) {
      stopQrScanMirror()
      qrScanDone.value = false
      qrCamError.value = ''
      qrScanVisible.value = true
      // 等弹窗渲染出 <video> 后再绑定摄像头流
      await nextTick()
      try {
        qrCamStream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        })
        if (qrVideoEl.value) {
          qrVideoEl.value.srcObject = qrCamStream
          try {
            await qrVideoEl.value.play()
          } catch { /* 自动播放可能被拦截，muted + playsinline 一般可行 */ }
        }
      } catch (e) {
        qrCamError.value = e?.message || String(e)
        ElMessage.error(t('todos.cameraOpenFailed'))
      }
      // 即使本机相机打开失败，也继续轮询后端状态（done 检测）；相机正常则同时推帧
      qrPushInFlight = false
      captureAndPushFrame()
      qrScanTimer = setInterval(captureAndPushFrame, Math.round(1000 / QR_CAM_FPS))
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
        const result = await txOverlay.run({
          title: t('todos.finalizingShipping'),
          consoleTag: '[发货通知]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) => todosApi.finalizePostShipping(id, { progress_job_id: jobId }),
        })
        // 仅当后端检测到「購入者の受取をお待ちください」才算发送成功
        if (result?.shipped_ok) {
          ElMessage.success(t('todos.shipNotified'))
          // 发货成功 → 把所选包材同步到关联订单，并把关联物品出库
          await commitShipPackagingAndOutbound()
        } else {
          ElMessage.warning(t('todos.shipNotifyUnconfirmed'))
        }
        // 完成后关闭本流程所有弹窗/表单：二次确认 → 扫码镜像 → 尺寸选择 → 交易详情
        // （关交易详情会触发 closeDetailBrowser 关闭有头浏览器会话）
        stopQrScanMirror()
        shipConfirmVisible.value = false
        qrScanVisible.value = false
        shippingDialogVisible.value = false
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

    // ─── 已发行二维码后修改发货方式：点「商品サイズや発送方法を修正する」+ 二次确认「変更する」→ 清除二维码 ───
    async function onReviseShippingAfterQr() {
      if (!currentRow.value?.id) return
      try {
        const result = await txOverlay.run({
          title: t('todos.clickingChangeMethod'),
          consoleTag: '[修正发货]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.reviseShippingAfterQr(currentRow.value.id, { progress_job_id: jobId }),
        })
        if (result?.success !== false) {
          // 清除二维码，恢复原本发货方式选择（UI 自动切回选尺寸/改方式布局）
          detail.qr_image_url = ''
          loadDetailCache()
          ElMessage.success(t('todos.reviseQrDone'))
        }
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.clickFailed'))
      }
    }

    // ─── 修改发货方式（点「発送方法を変更する」→ /shipping_method → 下拉选择 → 「変更する」）───
    const changeMethodVisible = ref(false)
    const changeMethodOptions = ref([])
    const changeMethodPicked = ref('')
    const changeMethodLoading = ref(false)

    async function onClickShippingChangeMethod() {
      if (!currentRow.value?.id) return
      try {
        const result = await txOverlay.run({
          title: t('todos.clickingChangeMethod'),
          consoleTag: '[修改发送方式]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.changeShippingMethod(currentRow.value.id, { progress_job_id: jobId }),
        })
        const opts = Array.isArray(result?.options) ? result.options : []
        if (!opts.length) {
          ElMessage.warning(t('todos.noShippingMethodOptions'))
          return
        }
        changeMethodOptions.value = opts
        const checked = opts.find((o) => o.checked)
        changeMethodPicked.value = String((checked || opts[0]).value || '')
        changeMethodVisible.value = true
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.clickFailed'))
      }
    }

    async function onConfirmChangeShippingMethod() {
      const id = currentRow.value?.id
      if (!id) return
      const val = String(changeMethodPicked.value || '')
      if (!val) {
        ElMessage.warning(t('todos.pleasePickShippingMethod'))
        return
      }
      const opt = (changeMethodOptions.value || []).find((o) => String(o.value) === val)
      changeMethodLoading.value = true
      try {
        await txOverlay.run({
          title: t('todos.changingShippingMethod'),
          consoleTag: '[修改发送方式]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.confirmChangeShippingMethod(id, {
              method_value: val,
              method_label: opt?.label || '',
              progress_job_id: jobId,
            }),
        })
        ElMessage.success(t('todos.shippingMethodChanged'))
        changeMethodVisible.value = false
        // 配送方式变更后刷新交易详情（重新抓取页面状态）
        onDetailRefresh()
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        changeMethodLoading.value = false
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
      syncLockStore.subscribe()
      loadKindOptions()
      load()
    })

    onBeforeUnmount(() => {
      if (syncProgressTimer != null) {
        clearInterval(syncProgressTimer)
        syncProgressTimer = null
      }
      syncLockStore.unsubscribe()
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
      useMercariAccountStore,
      useSyncOverlay,
      SyncOverlay,
      mercariImageUrl,
      t,
      txOverlay,
      mercariAccountStore,
      syncLockStore,
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
      PACKAGING_ITEM_NONE,
      packagingItemsOptions,
      shipPackagingRows,
      shipOutbound,
      onShipPackagingChange,
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
      shippingFacilities,
      onPickShipping,
      facilityImageUrl,
      shippingImageUrl,
      onShippingImgError,
      listParams,
      load,
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
      qrScanDone,
      qrCamError,
      qrVideoEl,
      startQrScanMirror,
      stopQrScanMirror,
      onQrScanDialogClose,
      shipConfirmVisible,
      shipConfirmLoading,
      shipConfirmInfo,
      onShipConfirmSubmit,
      onShipConfirmCancel,
      onClickShippingChangeMethod,
      onReviseShippingAfterQr,
      changeMethodVisible,
      changeMethodOptions,
      changeMethodPicked,
      changeMethodLoading,
      onConfirmChangeShippingMethod,
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
