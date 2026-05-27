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
      TransactionWaitShippingFunds: 'todos.kind.waitShipping',
      MerpayRealcardWaitActivation: 'todos.kind.merpayActivation',
      ReviewedSeller: 'todos.kind.waitReview',
      IncomingMessage: 'todos.kind.waitReply',
    }

    const DEFAULT_REPLY = 'ご購入いただきありがとうございます。これから発送の準備をさせていただきます。設定した期日内に発送予定ですので今しばらくお待ちください。取引終了までよろしくお願いいたします。'
    const DEFAULT_REVIEW = 'この度はお取引ありがとうございました。また機会がありましたらよろしくお願いします。'

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

    function kindLabel(kind) {
      if (!kind) return '-'
      const key = KIND_LABEL_KEYS[kind]
      return key ? t(key) : kind
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
      currentRow.value = row
      Object.assign(detail, createEmptyDetail(), {
        item_id: row.item_id || '',
        item_name: row.item_name || '',
        photo_url: row.photo_url || '',
        buyer_name: buyerNameFromMessage(row.message) || '',
        sender_id: row.sender_id || '',
      })
      detailDialogVisible.value = true
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
      shippingConfirmLoading.value = true
      try {
        await txOverlay.run({
          title: t('todos.confirmingShipping'),
          consoleTag: '[发货确认]',
          pollFn: (jobId) => todosApi.getSyncProgress(jobId),
          actionFn: (jobId) =>
            todosApi.confirmShippingSelection(currentRow.value.id, {
              class_text: classText,
              facility: needsFacility ? shippingFacility.value : null,
              progress_job_id: jobId,
            }),
        })
        ElMessage.success(t('todos.shippingDone', { classText }))
        shippingDialogVisible.value = false
        onDetailRefresh()
      } catch (e) {
        if (!e?.response) ElMessage.error(e?.message || t('todos.submitFailed'))
      } finally {
        shippingConfirmLoading.value = false
      }
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
