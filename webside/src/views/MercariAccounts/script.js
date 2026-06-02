import { defineComponent, ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { mercariAccountApi, mercariApi, webDriveApi } from '@/api/index.js'
import { useSyncOverlay } from '@/composables/useSyncOverlay'
import SyncOverlay from '@/components/SyncOverlay.vue'
import { useSyncLockStore } from '@/stores/syncLock.js'

export default defineComponent({
  components: { SyncOverlay },
  setup() {
    const { t } = useI18n()
    const syncOverlay = useSyncOverlay()
    const syncLockStore = useSyncLockStore()

    const MERCARI_HOME = 'https://jp.mercari.com/'

    /** 新增账号前共用的 WebDrive 会话键，与后端抓包/出品等约定一致 */
    const MERCARI_PREPARE_KEY = 'mercari_prepare'

    function browserKeyFor(accountId) {
      return `mercari_${accountId}`
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
      { label: t('mercariAccounts.enabled'), value: 'active' },
      { label: t('mercariAccounts.disabled'), value: 'disabled' },
    ]

    const autoFetchSwitchOptions = [
      { label: t('mercariAccounts.autoFetchOff'), value: 0 },
      { label: t('mercariAccounts.autoFetchOn'), value: 1 },
    ]

    const fetchIntervalOptions = [
      { label: t('mercariAccounts.interval15min'), value: '15' },
      { label: t('mercariAccounts.interval30min'), value: '30' },
      { label: t('mercariAccounts.interval1h'), value: '60' },
      { label: t('mercariAccounts.interval3h'), value: '3h' },
      { label: t('mercariAccounts.interval6h'), value: '6h' },
    ]

    const legacyFetchIntervalLabels = {
      '10': t('mercariAccounts.interval10min'),
      '12h': t('mercariAccounts.interval12h'),
      '24h': t('mercariAccounts.interval24h'),
    }

    function fetchIntervalLabel(v) {
      if (v == null || v === '') return '-'
      const key = String(v)
      const cur = fetchIntervalOptions.find((o) => o.value === key)
      if (cur) return cur.label
      return legacyFetchIntervalLabels[key] || key
    }

    function pauseWindowLabel(row) {
      if (!row || row.is_open !== 1) return ''
      const s = String(row.pause_start_time || '').trim()
      const e = String(row.pause_end_time || '').trim()
      if (!s || !e || s === e) return ''
      return `${s} - ${e}`
    }

    function autoFetchTasksLabel(row) {
      if (!row || row.is_open !== 1) return ''
      const parts = []
      if (row.auto_fetch_order_list === 1) parts.push(t('mercariAccounts.taskShortOrderList'))
      if (row.auto_fetch_on_sale === 1) parts.push(t('mercariAccounts.taskShortOnSale'))
      if (row.auto_fetch_todos === 1) parts.push(t('mercariAccounts.taskShortTodos'))
      if (row.auto_fetch_notifications === 1) parts.push(t('mercariAccounts.taskShortNotifications'))
      return parts.join(t('mercariAccounts.taskJoiner'))
    }

    function onAutoFetchToggle() {
      // 关闭自动同步时**不清空**已选配置（间隔/子任务/暂停时段），
      // 以便用户重新开启后继续显示原本的数据；仅清掉校验提示。
      nextTick(() => formRef.value?.clearValidate(['fetch_interval', 'pause_window']))
    }

    function onAutoFetchTaskChange() {
      nextTick(() => formRef.value?.validateField('fetch_interval').catch(() => {}))
    }

    const createDefaultForm = () => ({
      id: null,
      account_name: '',
      seller_id: '',
      status: 'disabled',
      remark: '',
      is_open: 0,
      fetch_interval: '',
      auto_fetch_order_list: 0,
      auto_fetch_on_sale: 0,
      auto_fetch_todos: 0,
      auto_fetch_notifications: 0,
      auto_fetch_relist: 0,
      pause_start_time: null,
      pause_end_time: null,
    })

    const form = ref(createDefaultForm())

    const sellerIdRules = [
      {
        validator(_rule, val, cb) {
          const text = String(val || '').trim()
          if (!text) return cb()
          if (!/^\d+$/.test(text)) return cb(new Error(t('mercariAccounts.errSellerIdDigits')))
          cb()
        },
        trigger: 'blur',
      },
    ]

    const formRules = {
      account_name: [{ required: true, message: t('mercariAccounts.errAccountNameRequired'), trigger: 'blur' }],
      seller_id: sellerIdRules,
      status: [{ required: true, message: t('mercariAccounts.errStatusRequired'), trigger: 'change' }],
      is_open: [{ required: true, message: t('common.selectPlaceholder'), trigger: 'change' }],
      fetch_interval: [
        {
          validator(_rule, val, cb) {
            if (form.value.is_open === 1) {
              if (!val || !String(val).trim()) {
                cb(new Error(t('mercariAccounts.errIntervalRequired')))
                return
              }
              const anyTask =
                form.value.auto_fetch_order_list === 1 ||
                form.value.auto_fetch_on_sale === 1 ||
                form.value.auto_fetch_todos === 1 ||
                form.value.auto_fetch_notifications === 1
              if (!anyTask) {
                cb(new Error(t('mercariAccounts.errPickOneTask')))
                return
              }
            }
            cb()
          },
          trigger: 'change',
        },
      ],
      pause_window: [
        {
          validator(_rule, _val, cb) {
            if (form.value.is_open !== 1) return cb()
            const s = String(form.value.pause_start_time || '').trim()
            const e = String(form.value.pause_end_time || '').trim()
            if (!s && !e) return cb()
            if (!s || !e) {
              cb(new Error(t('mercariAccounts.errPauseBothRequired')))
              return
            }
            if (s === e) {
              cb(new Error(t('mercariAccounts.errPauseSameTime')))
              return
            }
            cb()
          },
          trigger: 'change',
        },
      ],
    }

    async function load() {
      loading.value = true
      const params = { page: page.value, page_size: pageSize.value }
      const res = await mercariAccountApi.list(params).finally(() => {
        loading.value = false
      })
      list.value = res.items || []
      total.value = res.total || 0
    }

    function openPrepareLoginBrowser() {
      openBrowserByKey(MERCARI_PREPARE_KEY, t('mercariAccounts.prepareLoginBrowserLabel'))
    }

    function openCreate() {
      form.value = createDefaultForm()
      dialogVisible.value = true
      nextTick(() => {
        openPrepareLoginBrowser()
      })
    }

    function onFetchUserInfoPlaceholder() {
      fetchSellerIdViaMitm()
    }

    function sellerIdCaptureAccountKey() {
      return form.value.id ? browserKeyFor(form.value.id) : MERCARI_PREPARE_KEY
    }

    async function fetchSellerIdViaMitm() {
      if (fetchSellerIdLoading.value) return
      const accountKey = sellerIdCaptureAccountKey()
      const label = form.value.id
        ? (form.value.account_name || t('mercariAccounts.accountFallbackLabel', { id: form.value.id }))
        : t('mercariAccounts.preLoginLabel')
      fetchSellerIdLoading.value = true
      try {
        ElMessage.info(t('mercariAccounts.tipOpeningEdge', { label }))
        const res = await mercariAccountApi.fetchSellerIdViaMitm({
          account_key: accountKey,
          headless: false,
          close_browser_after: false,
        })
        const sid = String(res?.data?.seller_id || '').trim()
        if (!sid) {
          ElMessage.warning(t('mercariAccounts.warnNoSellerIdParsed'))
          return
        }
        form.value.seller_id = sid
        await nextTick()
        formRef.value?.validateField('seller_id').catch(() => {})
        ElMessage.success(t('mercariAccounts.msgSellerIdFilled', { sid }))
      } catch {
        /* 错误由 axios 拦截器提示 */
      } finally {
        fetchSellerIdLoading.value = false
      }
    }

    function openEdit(row) {
      const open = row.is_open === 1 || row.is_open === true ? 1 : 0
      form.value = {
        ...createDefaultForm(),
        id: row.id,
        account_name: row.account_name || '',
        seller_id: row.seller_id != null ? String(row.seller_id) : '',
        status: row.status || 'active',
        remark: row.remark || '',
        is_open: open,
        // 即便当前关闭了自动同步，也保留并回显原本的间隔/子任务/暂停时段，便于重新开启
        fetch_interval: String(row.fetch_interval != null ? row.fetch_interval : ''),
        auto_fetch_order_list: row.auto_fetch_order_list === 1 ? 1 : 0,
        auto_fetch_on_sale: row.auto_fetch_on_sale === 1 ? 1 : 0,
        auto_fetch_todos: row.auto_fetch_todos === 1 ? 1 : 0,
        auto_fetch_notifications: row.auto_fetch_notifications === 1 ? 1 : 0,
        auto_fetch_relist: row.auto_fetch_relist === 1 ? 1 : 0,
        pause_start_time: row.pause_start_time || null,
        pause_end_time: row.pause_end_time || null,
      }
      dialogVisible.value = true
    }

    function buildPayload() {
      const name = String(form.value.account_name || '').trim()
      const open = form.value.is_open === 1 ? 1 : 0
      // 关闭自动同步时仍原样提交配置（间隔/子任务/暂停），后端会保留，便于重新开启后继续显示
      const base = {
        account_name: name,
        login_id: name,
        seller_id: String(form.value.seller_id || '').trim() || null,
        status: form.value.status,
        remark: form.value.remark || null,
        is_open: open,
        fetch_interval: String(form.value.fetch_interval || '').trim() || null,
        auto_fetch_order_list: form.value.auto_fetch_order_list === 1 ? 1 : 0,
        auto_fetch_on_sale: form.value.auto_fetch_on_sale === 1 ? 1 : 0,
        auto_fetch_todos: form.value.auto_fetch_todos === 1 ? 1 : 0,
        auto_fetch_notifications: form.value.auto_fetch_notifications === 1 ? 1 : 0,
        auto_fetch_relist: form.value.auto_fetch_relist === 1 ? 1 : 0,
        pause_start_time: String(form.value.pause_start_time || '').trim() || null,
        pause_end_time: String(form.value.pause_end_time || '').trim() || null,
      }
      if (form.value.id) {
        return base
      }
      return { ...base }
    }

    async function submit() {
      await formRef.value?.validate()
      submitting.value = true
      const payload = buildPayload()
      try {
        if (form.value.id) {
          await mercariAccountApi.update(form.value.id, payload)
          ElMessage.success(t('mercariAccounts.msgUpdateSuccess'))
          dialogVisible.value = false
          load()
        } else {
          await mercariAccountApi.create(payload)
          ElMessage.success(t('mercariAccounts.msgCreateSuccess'))
          dialogVisible.value = false
          await load()
        }
      } finally {
        submitting.value = false
      }
    }

    async function remove(id) {
      await mercariAccountApi.remove(id)
      ElMessage.success(t('mercariAccounts.msgDeleteSuccess'))
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
    const syncDataIds = ref(new Set())
    const browserLoadingKeys = ref(new Set())
    const fetchSellerIdLoading = ref(false)

    async function openBrowserByKey(accountKey, label) {
      if (browserLoadingKeys.value.has(accountKey)) return
      const next = new Set(browserLoadingKeys.value)
      next.add(accountKey)
      browserLoadingKeys.value = next
      try {
        const res = await webDriveApi.openSession({
          account_key: accountKey,
          headless: false,
          restore_tabs: true
        })
        const d = res.data || {}
        const tr = d.tab_restore || {}
        const tabHint =
          tr.restored && tr.tab_count
            ? t('mercariAccounts.tabRestoredHint', { count: tr.tab_count })
            : tr.tab_count
              ? t('mercariAccounts.tabOpenedHint', { count: tr.tab_count })
              : ''
        const tip = d.already_running
          ? t('mercariAccounts.browserAlreadyRunning', { tabHint })
          : t('mercariAccounts.browserStarted', { tabHint })
        ElMessage.success(`${label || accountKey}${t('mercariAccounts.colon')}${tip}`)
      } catch {
        /* 错误由 axios 拦截器提示 */
      } finally {
        const s = new Set(browserLoadingKeys.value)
        s.delete(accountKey)
        browserLoadingKeys.value = s
      }
    }

    function openBrowserForSavedAccount(row) {
      openBrowserByKey(browserKeyFor(row.id), row.account_name || t('mercariAccounts.accountFallbackLabel', { id: row.id }))
    }

    // 可勾选同步的页面（key 与后端 _TASK_KEYS 一致；顺序即执行顺序）
    const SYNC_TASK_DEFS = [
      { key: 'todos', labelKey: 'mercariAccounts.syncTaskTodos' },
      { key: 'notifications', labelKey: 'mercariAccounts.syncTaskNotifications' },
      { key: 'on_sale', labelKey: 'mercariAccounts.syncTaskOnSale' },
      { key: 'orders_list', labelKey: 'mercariAccounts.syncTaskOrdersList' },
      { key: 'orders_status', labelKey: 'mercariAccounts.syncTaskOrdersStatus' },
    ]

    function defaultSyncTasks() {
      return SYNC_TASK_DEFS.reduce((acc, d) => {
        acc[d.key] = true
        return acc
      }, {})
    }

    const syncDataDialogVisible = ref(false)
    const syncDataRow = ref(null)
    /** 各页面勾选状态，默认全选；用户按需取消 */
    const syncDataChecked = ref(defaultSyncTasks())

    /** 点卡片「同步数据」：打开勾选弹窗（默认全部勾选） */
    function openSyncDataDialog(row) {
      if (syncDataIds.value.has(row.id)) return
      if (row.status !== 'active') {
        ElMessage.warning(t('mercariAccounts.syncDataDisabledHint'))
        return
      }
      if (syncLockStore.locked) {
        ElMessage.warning(syncLockStore.label || t('mercariAccounts.syncBusyHint'))
        return
      }
      syncDataRow.value = row
      syncDataChecked.value = defaultSyncTasks()
      syncDataDialogVisible.value = true
    }

    /** 弹窗内确认：取勾选项执行同步 */
    async function confirmSyncData() {
      const row = syncDataRow.value
      if (!row) return
      const tasks = SYNC_TASK_DEFS.map((d) => d.key).filter((k) => syncDataChecked.value[k])
      if (!tasks.length) {
        ElMessage.warning(t('mercariAccounts.syncDataPickAtLeastOne'))
        return
      }
      syncDataDialogVisible.value = false
      await runAccountDataSync(row, tasks)
    }

    /**
     * 单账号「同步数据」：同步勾选的业务页面（待办/通知/在售/订单）的数据。
     * 全屏覆盖层实时显示「正在同步哪个页面的什么数据」（后端按页面标注进度）。
     */
    async function runAccountDataSync(row, tasks) {
      if (syncDataIds.value.has(row.id)) return
      const name = row.account_name || `#${row.id}`
      syncDataIds.value = new Set([...syncDataIds.value, row.id])
      try {
        const res = await syncOverlay.run({
          title: t('mercariAccounts.syncingAccountData', { name }),
          failedTitle: t('mercariAccounts.syncDataFailed'),
          consoleTag: '[账号同步]',
          pollFn: (jobId) => mercariApi.getSyncProgress(jobId),
          actionFn: (jobId) => mercariAccountApi.syncData(row.id, { progress_job_id: jobId, tasks }),
        })
        const d = res?.data || {}
        const msg = t('mercariAccounts.msgSyncDataResult', {
          name,
          ok: d.ok_count ?? 0,
          fail: d.fail_count ?? 0,
        })
        if ((d.fail_count ?? 0) > 0) ElMessage.warning(msg)
        else ElMessage.success(msg)
      } catch {
        /* 失败文案已由覆盖层展示 + axios 拦截器提示 */
      } finally {
        const next = new Set(syncDataIds.value)
        next.delete(row.id)
        syncDataIds.value = next
        syncLockStore.refresh()
      }
    }

    /** 编辑表单内「获取历史数据」：复用 fetchHistory，按当前编辑的账号执行 */
    function fetchHistoryFromForm() {
      if (!form.value.id) return
      return fetchHistory({
        id: form.value.id,
        seller_id: form.value.seller_id,
        account_name: form.value.account_name,
      })
    }

    async function fetchHistory(row) {
      if (syncingIds.value.has(row.id)) return
      const sid = String(row.seller_id || '').trim()
      if (!sid) {
        ElMessage.warning(t('mercariAccounts.warnConfigureSellerIdFirst'))
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
        ElMessage.warning(pre.message || t('mercariAccounts.warnHistoryAlreadyExists'))
        return
      }

      try {
        await ElMessageBox.confirm(
          t('mercariAccounts.confirmFetchHistoryBody'),
          t('mercariAccounts.fetchHistory'),
          {
            type: 'warning',
            confirmButtonText: t('mercariAccounts.confirmFetchBtn'),
            cancelButtonText: t('common.cancel'),
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
          t('mercariAccounts.msgSyncResult', {
            name: row.account_name,
            inserted: d.inserted ?? 0,
            updated: d.updated ?? 0,
            total: d.total_item_count ?? d.total ?? 0,
          })
        )
      } finally {
        const next = new Set(syncingIds.value)
        next.delete(row.id)
        syncingIds.value = next
      }
    }

    onMounted(() => {
      load()
      syncLockStore.subscribe()
    })

    onBeforeUnmount(() => {
      syncOverlay.dispose()
      syncLockStore.unsubscribe()
    })

    return {
      ref,
      onMounted,
      nextTick,
      syncOverlay,
      SyncOverlay,
      syncLockStore,
      useI18n,
      Plus,
      ElMessage,
      ElMessageBox,
      mercariAccountApi,
      mercariApi,
      webDriveApi,
      t,
      MERCARI_HOME,
      MERCARI_PREPARE_KEY,
      browserKeyFor,
      loading,
      submitting,
      list,
      total,
      page,
      pageSize,
      dialogVisible,
      formRef,
      statusOptions,
      autoFetchSwitchOptions,
      fetchIntervalOptions,
      legacyFetchIntervalLabels,
      fetchIntervalLabel,
      pauseWindowLabel,
      autoFetchTasksLabel,
      onAutoFetchToggle,
      onAutoFetchTaskChange,
      createDefaultForm,
      form,
      sellerIdRules,
      formRules,
      load,
      openPrepareLoginBrowser,
      openCreate,
      onFetchUserInfoPlaceholder,
      sellerIdCaptureAccountKey,
      fetchSellerIdViaMitm,
      openEdit,
      buildPayload,
      submit,
      remove,
      removeFromDialog,
      syncingIds,
      syncDataIds,
      browserLoadingKeys,
      fetchSellerIdLoading,
      openBrowserByKey,
      openBrowserForSavedAccount,
      fetchHistory,
      fetchHistoryFromForm,
      SYNC_TASK_DEFS,
      syncDataDialogVisible,
      syncDataRow,
      syncDataChecked,
      openSyncDataDialog,
      confirmSyncData,
    }
  },
})
