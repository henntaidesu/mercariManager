import { defineComponent, ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { inventoryApi, transactionApi, orderApi } from '@/api/index.js'
import { rollingLocalDayRangeTs, localTodayRangeTs } from '@/utils/orderStatsTime.js'
import { formatUnixSecLocal } from '@/utils/timeDisplay.js'

export default defineComponent({
  setup() {
    const { t } = useI18n()
    const summary = ref({})
    const recentTx = ref([])
    const orderStatsLoading = ref(false)
    const orderStats = ref({
      total_count: 0,
      sum_amount: 0,
      sum_service_fee: 0,
      sum_shipping_fee: 0,
      sum_net_income: 0,
      sum_packaging: 0,
      today_total_count: 0,
      today_sum_amount: 0,
      today_sum_service_fee: 0,
      today_sum_shipping_fee: 0,
      today_sum_net_income: 0,
      today_sum_packaging: 0,
    })

    const statCards = [
      { key: 'total_inventory', labelKey: 'dashboard.totalInventory', icon: 'Goods', color: '#409EFF' },
      { key: 'total_quantity', labelKey: 'dashboard.totalQuantity', icon: 'Box', color: '#E6A23C' },
      { key: 'today_in', labelKey: 'dashboard.todayIn', icon: 'Top', color: '#67C23A' },
      { key: 'today_out', labelKey: 'dashboard.todayOut', icon: 'Bottom', color: '#F56C6C' }
    ]

    function txTypeLabel(type) {
      const map = {
        in: t('dashboard.txIn'),
        out: t('dashboard.txOut'),
        transfer: t('dashboard.txTransfer'),
      }
      return map[type] || type
    }

    const orderStatCards = computed(() => {
      const o = orderStats.value
      return [
        {
          label: t('dashboard.orderCount'),
          display: o.total_count ?? 0,
          todayDisplay: o.today_total_count ?? 0,
          icon: 'Document',
          color: '#409EFF',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.totalAmount'),
          display: Math.round(Number(o.sum_amount || 0)),
          todayDisplay: Math.round(Number(o.today_sum_amount || 0)),
          icon: 'Money',
          color: '#E6A23C',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.serviceFee'),
          display: Math.round(Number(o.sum_service_fee || 0)),
          todayDisplay: Math.round(Number(o.today_sum_service_fee || 0)),
          icon: 'Histogram',
          color: '#F56C6C',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.shippingFee'),
          display: Math.round(Number(o.sum_shipping_fee || 0)),
          todayDisplay: Math.round(Number(o.today_sum_shipping_fee || 0)),
          icon: 'Box',
          color: '#F56C6C',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.packaging'),
          display: Math.round(Number(o.sum_packaging || 0)),
          todayDisplay: Math.round(Number(o.today_sum_packaging || 0)),
          icon: 'ShoppingCart',
          color: '#909399',
          cardClass: '',
          valueClass: '',
        },
        {
          label: t('dashboard.netIncome'),
          display: Math.round(Number(o.sum_net_income || 0)),
          todayDisplay: Math.round(Number(o.today_sum_net_income || 0)),
          icon: 'TrendCharts',
          color: '#67C23A',
          cardClass: '',
          valueClass: '',
        },
      ]
    })

    async function loadOrderStats() {
      orderStatsLoading.value = true
      try {
        const range = rollingLocalDayRangeTs(30)
        const today = localTodayRangeTs()
        const res = await orderApi.stats({
          ...range,
          ...today,
        })
        orderStats.value = {
          total_count: res.total_count ?? 0,
          sum_amount: res.sum_amount ?? 0,
          sum_service_fee: res.sum_service_fee ?? 0,
          sum_shipping_fee: res.sum_shipping_fee ?? 0,
          sum_net_income: res.sum_net_income ?? 0,
          sum_packaging: res.sum_packaging ?? 0,
          today_total_count: res.today_total_count ?? 0,
          today_sum_amount: res.today_sum_amount ?? 0,
          today_sum_service_fee: res.today_sum_service_fee ?? 0,
          today_sum_shipping_fee: res.today_sum_shipping_fee ?? 0,
          today_sum_net_income: res.today_sum_net_income ?? 0,
          today_sum_packaging: res.today_sum_packaging ?? 0,
        }
      } finally {
        orderStatsLoading.value = false
      }
    }

    async function load() {
      const [invSummary, tx] = await Promise.all([
        inventoryApi.summary(),
        transactionApi.list({ page_size: 10 }),
      ])
      await loadOrderStats()
      summary.value = {
        total_inventory: invSummary.total_inventory ?? 0,
        total_quantity: invSummary.total_quantity ?? 0,
        today_in: tx.today_in ?? '-',
        today_out: tx.today_out ?? '-'
      }
      recentTx.value = tx.items
    }

    onMounted(load)

    return {
      ref,
      computed,
      onMounted,
      useI18n,
      inventoryApi,
      transactionApi,
      orderApi,
      rollingLocalDayRangeTs,
      localTodayRangeTs,
      formatUnixSecLocal,
      t,
      summary,
      recentTx,
      orderStatsLoading,
      orderStats,
      statCards,
      txTypeLabel,
      orderStatCards,
      loadOrderStats,
      load,
    }
  },
})
