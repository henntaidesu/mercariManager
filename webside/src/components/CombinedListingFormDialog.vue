<template>
  <el-dialog
    :model-value="modelValue"
    title="组合出品"
    :width="isMobile ? '94vw' : '680px'"
    class="listing-dialog"
    destroy-on-close
    @update:model-value="onVisibleChange"
  >
    <el-form
      ref="listingFormRef"
      :model="form"
      :rules="listingFormRules"
      label-width="112px"
      label-position="right"
      class="listing-dialog-form"
      scroll-to-error
    >
      <el-form-item label="关联库存" prop="inventory_ids" required>
        <span v-if="form.inventory_ids?.length" class="listing-inv-count"
          >已选 {{ form.inventory_ids.length }} 条库存条目（组合出品）</span
        >
        <span v-else class="listing-inv-count listing-inv-count--warn">未关联库存条目</span>
      </el-form-item>
      <el-form-item label="商品图片" prop="combined_listing_images" class="listing-form-item--images" required>
        <div class="listing-field-full listing-combined-images-wrap">
          <div v-if="!combinedPreviewImages.length" class="listing-combined-empty">暂无商品图片数据</div>
          <div v-else class="listing-combined-gallery">
            <div
              v-for="(block, idx) in combinedPreviewImages"
              :key="`${block.inventory_id ?? idx}-${idx}`"
              class="listing-combined-card"
            >
              <div class="listing-combined-card-title">商品 {{ idx + 1 }} · 管理 {{ block.inventory_id ?? '—' }}</div>
              <div class="listing-images-thumbs listing-images-thumbs--combined">
                <div class="listing-thumb-block">
                  <span class="listing-thumb-label">正面</span>
                  <el-image
                    v-if="block.front"
                    :src="block.front"
                    fit="cover"
                    class="listing-image-preview listing-image-preview--combined"
                    :preview-src-list="pairPreviewList(block)"
                    :hide-on-click-modal="true"
                    :preview-teleported="true"
                    :initial-index="0"
                  />
                  <div v-else class="listing-image-empty listing-image-empty--combined">无</div>
                </div>
                <div v-if="block.back" class="listing-thumb-block">
                  <span class="listing-thumb-label">背面</span>
                  <el-image
                    :src="block.back"
                    fit="cover"
                    class="listing-image-preview listing-image-preview--combined"
                    :preview-src-list="pairPreviewList(block)"
                    :hide-on-click-modal="true"
                    :preview-teleported="true"
                    :initial-index="pairPreviewList(block).length > 1 ? 1 : 0"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="出品标题" prop="listing_title" class="listing-form-item--name" required>
        <div class="listing-field-full">
          <el-input
            v-model="form.listing_title"
            class="listing-name-input"
            placeholder="请输入出品标题（必填）"
            clearable
          />
        </div>
      </el-form-item>
      <el-form-item label="商品说明" prop="description" class="listing-form-item--desc" required>
        <div class="listing-field-full listing-desc-with-footer">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="4"
            :maxlength="
              managementNumberLine
                ? descriptionBodyMaxLength > 0
                  ? descriptionBodyMaxLength
                  : undefined
                : 1000
            "
            show-word-limit
            placeholder="请输入商品说明（必填）"
          />
          <div
            v-if="managementNumberLine"
            class="listing-mgmt-footer"
            title="由所选库存自动生成的末行暗号（-=~<>），不可在此删除"
          >
            {{ managementNumberLine }}
          </div>
        </div>
      </el-form-item>
      <el-form-item label="商品类型" prop="category_mapping_id" required>
        <el-cascader
          v-model="form.category_mapping_path"
          :options="categoryTypeCascaderOptions"
          :props="categoryTypeCascaderProps"
          :show-all-levels="false"
          filterable
          placeholder="请选择商品类型（必选）"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleCategoryTypeChange"
        />
      </el-form-item>
      <el-form-item label="商品状态" prop="status" required>
        <el-select v-model="form.status" placeholder="请选择商品状态" style="width: 100%">
          <el-option v-for="s in listingStatusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="出品账号" prop="meilu_account_id" required>
        <el-select
          v-model="form.meilu_account_id"
          placeholder="请选择煤炉账号"
          style="width: 100%"
          filterable
          :loading="meiluAccountsLoading"
        >
          <el-option
            v-for="a in meiluAccountOptions"
            :key="a.id"
            :label="meiluAccountOptionLabel(a)"
            :value="a.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="快递费负担" prop="shipping_payer" required>
        <el-select v-model="form.shipping_payer" placeholder="请选择快递费负担" style="width: 100%">
          <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="配送方法" prop="shipping_method" required>
        <el-select v-model="form.shipping_method" placeholder="请选择配送方法" style="width: 100%">
          <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="发货地址" prop="shipping_from" required>
        <el-cascader
          v-model="form.shipping_from_path"
          :options="shippingFromCascaderOptions"
          :props="shippingFromCascaderProps"
          :show-all-levels="false"
          filterable
          placeholder="请选择发货地（必选）"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleShippingFromChange"
        />
      </el-form-item>
      <el-form-item label="最大发货天数" prop="shipping_days" required>
        <el-select v-model="form.shipping_days" placeholder="请选择最大发货天数" style="width: 100%">
          <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="出售方法" prop="sale_type" required>
        <div class="listing-compact-row">
          <el-select
            v-model="form.sale_type"
            placeholder="请选择出售方法"
            class="listing-compact-control"
            @change="onSaleTypeChange"
          >
            <el-option v-for="s in saleTypeOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item
        v-if="form.sale_type === 'auction'"
        label="拍卖时长"
        prop="auction_duration"
        required
      >
        <el-select v-model="form.auction_duration" placeholder="请选择拍卖时长" style="width: 100%">
          <el-option label="通常" value="normal" />
          <el-option label="三小时" value="3hours" />
        </el-select>
      </el-form-item>
      <el-form-item label="商品单价" prop="price" class="listing-form-item--price" required>
        <div class="listing-compact-row">
          <el-input
            v-model="listingPriceEdit"
            placeholder="必填，日元整数且大于 0（同步到所选库存）"
            class="listing-price-input listing-compact-control"
            inputmode="numeric"
            @blur="applyListingPriceToForm"
          />
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <div class="dialog-footer">
        <el-button @click="onVisibleChange(false)">取消</el-button>
        <el-button type="primary" @click="submitStub">保存</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch, computed, nextTick } from 'vue'
import { meiluAccountApi } from '@/api/index.js'
import { encodeMgmtIds, stripTrailingMgmtBlock } from '@/utils/mgmtIdCipher.js'
import {
  MERCARI_AREAS,
  JP_REGION_OPTIONS,
  getRegionIdForAreaId,
  normalizeShippingFromSeed
} from '@/constants/mercariJapanAreas.js'

const SHIPPING_FROM_AREA_PREFIX = 'AREA:'
const SHIPPING_FROM_REGION_PREFIX = 'REGION:'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  categoryMappings: { type: Array, default: () => [] },
  initialData: { type: Object, default: null },
  listingDefaults: { type: Object, default: null },
  isMobile: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'saved'])

const listingFormRef = ref()
const form = ref(getDefaultForm())
/** 组合出品：各库存条目的正/背面图（仅展示，不参与提交） */
const combinedPreviewImages = ref([])
/** 商品单价：纯文本整数，blur / 提交前写回 form.price */
const listingPriceEdit = ref('0')

const listingFormRules = {
  inventory_ids: [
    {
      type: 'array',
      required: true,
      min: 1,
      message: '请至少关联一条库存',
      trigger: 'change'
    }
  ],
  combined_listing_images: [
    {
      validator: (_, __, cb) => {
        const imgs = combinedPreviewImages.value
        if (!imgs.length) {
          cb(new Error('所选库存无商品图片数据'))
          return
        }
        if (imgs.some((b) => !String(b?.front || '').trim())) {
          cb(new Error('每条库存须有正面商品图'))
          return
        }
        cb()
      },
      trigger: 'change'
    }
  ],
  listing_title: [
    {
      validator: (_, val, cb) => {
        if (!String(val ?? '').trim()) cb(new Error('请输入出品标题'))
        else cb()
      },
      trigger: 'blur'
    }
  ],
  price: [
    {
      validator: (_, val, cb) => {
        const n = Number(val)
        if (!Number.isFinite(n) || n <= 0 || !Number.isInteger(n)) {
          cb(new Error('请输入商品单价（须为大于 0 的整数）'))
          return
        }
        cb()
      },
      trigger: ['blur', 'change']
    }
  ],
  auction_duration: [
    {
      validator: (_, val, cb) => {
        if (form.value.sale_type !== 'auction') {
          cb()
          return
        }
        if (val !== 'normal' && val !== '3hours') {
          cb(new Error('请选择拍卖时长'))
          return
        }
        cb()
      },
      trigger: 'change'
    }
  ],
  description: [
    {
      validator: (_, val, cb) => {
        if (!String(val ?? '').trim()) cb(new Error('请输入商品说明'))
        else cb()
      },
      trigger: 'blur'
    }
  ],
  category_mapping_id: [
    {
      validator: (_, val, cb) => {
        if (val == null || String(val).trim() === '') cb(new Error('请选择商品类型'))
        else cb()
      },
      trigger: 'change'
    }
  ],
  status: [{ required: true, message: '请选择商品状态', trigger: 'change' }],
  meilu_account_id: [
    {
      required: true,
      message: '请选择出品账号',
      trigger: 'change'
    }
  ],
  shipping_payer: [{ required: true, message: '请选择快递费负担', trigger: 'change' }],
  shipping_method: [{ required: true, message: '请选择配送方法', trigger: 'change' }],
  shipping_from: [
    {
      validator: (_, val, cb) => {
        if (val == null || String(val).trim() === '') cb(new Error('请选择发货地址'))
        else cb()
      },
      trigger: 'change'
    }
  ],
  shipping_days: [{ required: true, message: '请选择最大发货天数', trigger: 'change' }],
  sale_type: [{ required: true, message: '请选择出售方法', trigger: 'change' }]
}

function onSaleTypeChange() {
  if (form.value.sale_type !== 'auction') {
    form.value.auction_duration = 'normal'
    nextTick(() => {
      listingFormRef.value?.clearValidate?.(['auction_duration'])
    })
  }
}

function syncListingPriceFromForm() {
  listingPriceEdit.value = String(Math.round(Number(form.value.price ?? 0)))
}

function applyListingPriceToForm() {
  const raw = String(listingPriceEdit.value ?? '').trim()
  const n = parseInt(raw, 10)
  const v = Number.isNaN(n) ? 0 : Math.max(0, Math.min(999999999, n))
  form.value.price = v
  listingPriceEdit.value = String(v)
}

function pairPreviewList(block) {
  return [block?.front, block?.back].filter((u) => u && String(u).trim())
}

/** 所选库存 id 的末行暗号（-=~<> 五进制），保存时拼在说明最底部 */
const managementNumberLine = computed(() => {
  const ids = (form.value.inventory_ids || [])
    .map((id) => Number(id))
    .filter((x) => Number.isFinite(x) && x > 0)
  if (!ids.length) return ''
  return encodeMgmtIds(ids)
})

/** 可编辑说明字数上限：总长 1000，为底部固定行预留字符 */
const descriptionBodyMaxLength = computed(() => {
  const foot = managementNumberLine.value
  if (!foot) return 1000
  const reserved = foot.length + 2
  return Math.max(0, 1000 - reserved)
})
const meiluAccountOptions = ref([])
const meiluAccountsLoading = ref(false)

const categoryTypeCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

const shippingFromCascaderProps = {
  value: 'value',
  label: 'label',
  children: 'children',
  emitPath: true,
  checkStrictly: false,
}

/** 发货地两级级联：一级=日本地域，二级=都道府県（叶子值=AREA:<id>） */
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
      .filter(Boolean)
  }))
})

function buildShippingFromPath(areaId) {
  if (!areaId) return []
  const regionId = getRegionIdForAreaId(areaId)
  if (!regionId) return []
  return [
    `${SHIPPING_FROM_REGION_PREFIX}${regionId}`,
    `${SHIPPING_FROM_AREA_PREFIX}${areaId}`
  ]
}

function ensureNode(children, value, label) {
  let node = children.find((item) => item.value === value)
  if (!node) {
    node = { value, label, children: [] }
    children.push(node)
  }
  return node
}

const categoryTypeTreeMeta = computed(() => {
  const roots = []
  const idToPath = new Map()
  for (const m of (props.categoryMappings || [])) {
    const mappingId = String(m?.mapping_id ?? '').trim()
    const typeName = String(m?.product_type ?? '').trim()
    if (!mappingId || !typeName) continue
    const l1 = String(m?.category_level1 ?? '').trim() || '未分类'
    const l2 = String(m?.category_level2 ?? '').trim()
    const l3 = String(m?.category_level3 ?? '').trim()
    const l1Val = `L1:${l1}`
    const l1Node = ensureNode(roots, l1Val, l1)
    const l1Path = [l1Val]

    if (!l2) {
      l1Node.children.push({ value: `PT:${mappingId}`, label: typeName, children: [] })
      idToPath.set(mappingId, [...l1Path, `PT:${mappingId}`])
      continue
    }
    const l2Val = `L2:${l1}__${l2}`
    const l2Node = ensureNode(l1Node.children, l2Val, l2)
    const l2Path = [...l1Path, l2Val]
    if (!l3) {
      l2Node.children.push({ value: `PT:${mappingId}`, label: typeName, children: [] })
      idToPath.set(mappingId, [...l2Path, `PT:${mappingId}`])
      continue
    }
    const l3Val = `L3:${l1}__${l2}__${l3}`
    const l3Node = ensureNode(l2Node.children, l3Val, l3)
    const l3Path = [...l2Path, l3Val]
    l3Node.children.push({ value: `PT:${mappingId}`, label: typeName, children: [] })
    idToPath.set(mappingId, [...l3Path, `PT:${mappingId}`])
  }
  return { roots, idToPath }
})

const categoryTypeCascaderOptions = computed(() => categoryTypeTreeMeta.value.roots)

const listingStatusOptions = [
  { label: '新品、未使用', value: 'new_unused' },
  { label: '未使用に近い', value: 'almost_unused' },
  { label: '目立った傷や汚れなし', value: 'good' },
  { label: 'やや傷や汚れあり', value: 'fair' },
  { label: '傷や汚れあり', value: 'used' }
]
const shippingPayerOptions = [
  { label: '送料込み(出品者负担)', value: 'seller' },
  { label: '着払い(购买者负担)', value: 'buyer' }
]
const shippingMethodOptions = [
  { label: '未定', value: 'undecided' },
  { label: 'らくらくメルカリ便', value: 'rakuraku' },
  { label: 'ゆうゆうメルカリ便', value: 'yuuyu' },
  { label: '普通邮便(定形、定形外)', value: 'regular_mail' }
]
const shippingDaysOptions = [
  { label: '1~2天', value: '1_2_days' },
  { label: '2~3天', value: '2_3_days' },
  { label: '4~7天', value: '4_7_days' }
]
const saleTypeOptions = [
  { label: '即购', value: 'instant_buy' },
  { label: '拍卖', value: 'auction' }
]

function meiluAccountOptionLabel(a) {
  const name = (a?.account_name || '').trim() || `ID ${a?.id}`
  const sid = String(a?.seller_id || '').trim()
  const tail = sid ? ` · 卖家 ${sid}` : ''
  const inactive = a?.status === 'disabled' ? '（停用）' : ''
  return `${name}${tail}${inactive}`
}

async function fetchMeiluAccounts() {
  meiluAccountsLoading.value = true
  try {
    const res = await meiluAccountApi.list({ page: 1, page_size: 500 })
    meiluAccountOptions.value = Array.isArray(res?.items) ? res.items : []
  } catch {
    meiluAccountOptions.value = []
  } finally {
    meiluAccountsLoading.value = false
  }
}

function pickListingStr(seedVal, cfgVal, fallback) {
  const a = seedVal != null && String(seedVal).trim() ? String(seedVal).trim() : ''
  if (a) return a
  const b = cfgVal != null && String(cfgVal).trim() ? String(cfgVal).trim() : ''
  if (b) return b
  return fallback
}

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    fetchMeiluAccounts()
    const seed = props.initialData || {}
    const cfg = props.listingDefaults || {}
    const seedMappingId = seed.category_mapping_id != null ? String(seed.category_mapping_id) : null
    const seedPath = seedMappingId
      ? (categoryTypeTreeMeta.value.idToPath.get(seedMappingId) || [])
      : []
    const areaFromSeed = normalizeShippingFromSeed(seed.shipping_from)
    const areaFromCfg = normalizeShippingFromSeed(cfg.shipping_from_area_id)
    const areaId = areaFromSeed || areaFromCfg || ''
    const accId = seed.meilu_account_id != null ? Number(seed.meilu_account_id) : null
    const cfgMid = cfg.meilu_account_id != null ? Number(cfg.meilu_account_id) : null
    const seedPrice = seed.price != null ? Math.round(Number(seed.price)) : 0
    const priceVal = Number.isFinite(seedPrice) && seedPrice >= 0 ? seedPrice : 0
    combinedPreviewImages.value = Array.isArray(seed.combined_images) ? seed.combined_images : []
    form.value = {
      ...getDefaultForm(),
      image: '',
      image_back: '',
      listing_title: seed.listing_title || seed.name || '',
      category_mapping_id: seedMappingId,
      category_mapping_path: seedPath,
      description: '',
      price: priceVal,
      shipping_from: areaId,
      shipping_from_path: buildShippingFromPath(areaId),
      inventory_ids: Array.isArray(seed.inventory_ids)
        ? seed.inventory_ids.map((x) => Number(x)).filter((x) => Number.isFinite(x))
        : [],
      meilu_account_id:
        Number.isFinite(accId) && accId > 0
          ? accId
          : Number.isFinite(cfgMid) && cfgMid > 0
            ? cfgMid
            : null,
      shipping_payer: pickListingStr(seed.shipping_payer, cfg.shipping_payer, 'seller'),
      shipping_method: pickListingStr(seed.shipping_method, cfg.shipping_method, 'undecided'),
      shipping_days: pickListingStr(seed.shipping_days, cfg.shipping_days, '2_3_days')
    }
    syncListingPriceFromForm()
  }
)

function getDefaultForm() {
  return {
    /** meilu_accounts.id，用于指定以哪一账号出品 */
    meilu_account_id: null,
    image: '',
    image_back: '',
    listing_title: '',
    category_mapping_id: null,
    category_mapping_path: [],
    status: 'new_unused',
    description: '',
    shipping_payer: 'seller',
    shipping_method: 'undecided',
    /** Mercari areas[].id，与煤炉 API 发货地一致 */
    shipping_from: '',
    /** el-cascader 的路径值：[REGION:xxx, AREA:xxx] */
    shipping_from_path: [],
    shipping_days: '2_3_days',
    sale_type: 'instant_buy',
    auction_duration: 'normal',
    inventory_ids: [],
    price: 0,
    /** 仅占位，供「商品图片」表单项校验（实际读 combinedPreviewImages） */
    combined_listing_images: ''
  }
}

function handleCategoryTypeChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith('PT:')) {
    form.value.category_mapping_id = null
    return
  }
  form.value.category_mapping_id = String(picked).slice(3)
}

function handleShippingFromChange(path) {
  const picked = Array.isArray(path) ? path[path.length - 1] : null
  if (!picked || !String(picked).startsWith(SHIPPING_FROM_AREA_PREFIX)) {
    form.value.shipping_from = ''
    return
  }
  form.value.shipping_from = String(picked).slice(SHIPPING_FROM_AREA_PREFIX.length)
}

function onVisibleChange(v) {
  emit('update:modelValue', v)
}

async function submitStub() {
  applyListingPriceToForm()
  const elForm = listingFormRef.value
  if (!elForm) return
  try {
    await elForm.validate()
  } catch {
    return
  }
  const foot = managementNumberLine.value
  let body = String(form.value.description || '').trimEnd()
  if (foot) {
    const maxBody = Math.max(0, 1000 - foot.length - 2)
    if (body.length > maxBody) body = body.slice(0, maxBody)
  }
  const fullDescription = foot ? (body ? `${body}\n\n${foot}` : foot) : body
  emit('saved', { ...form.value, description: fullDescription })
  onVisibleChange(false)
}
</script>

<style scoped>
.listing-dialog-form :deep(.el-form-item) {
  margin-bottom: 18px;
}
.listing-form-item--images :deep(.el-form-item__content) {
  line-height: normal;
}
/** 商品名 / 商品说明 / 单价 */
.listing-form-item--name :deep(.el-form-item__content),
.listing-form-item--desc :deep(.el-form-item__content),
.listing-form-item--price :deep(.el-form-item__content) {
  flex: 1 1 auto;
  min-width: 0;
  max-width: none;
}
.listing-field-full {
  display: block;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.listing-field-full :deep(.el-input) {
  width: 100% !important;
  max-width: none !important;
}
.listing-field-full :deep(.el-input__wrapper) {
  width: 100% !important;
  max-width: none !important;
  box-sizing: border-box;
}
.listing-field-full :deep(.el-textarea) {
  width: 100% !important;
  max-width: none !important;
}
.listing-field-full :deep(.el-textarea__inner) {
  width: 100% !important;
  max-width: none !important;
  box-sizing: border-box;
}
.listing-desc-with-footer :deep(.el-textarea__inner) {
  border-radius: 4px 4px 0 0;
}
.listing-mgmt-footer {
  margin-top: -1px;
  padding: 8px 11px;
  font-size: 13px;
  color: #a8b4ce;
  background: rgba(26, 35, 54, 0.95);
  border: 1px solid var(--el-border-color);
  border-top: none;
  border-radius: 0 0 4px 4px;
  line-height: 1.5;
}
.listing-image-box {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  width: 100%;
}
.listing-images-thumbs {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  gap: 14px;
  flex-shrink: 0;
}
.listing-thumb-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}
.listing-thumb-label {
  font-size: 12px;
  color: #909399;
  line-height: 1;
}
.listing-image-preview {
  width: 96px;
  height: 96px;
  border-radius: 6px;
}
.listing-image-empty {
  width: 96px;
  height: 96px;
  border: 1px dashed #5a6b88;
  border-radius: 6px;
  color: #8ea0bf;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
}
.listing-combined-images-wrap {
  width: 100%;
}
.listing-combined-gallery {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  max-height: 280px;
  overflow-y: auto;
  padding: 2px 0;
}
.listing-combined-card {
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 10px;
  background: rgba(0, 0, 0, 0.12);
}
.listing-combined-card-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}
.listing-images-thumbs--combined {
  flex-wrap: nowrap;
}
.listing-image-preview--combined,
.listing-image-empty--combined {
  width: 80px;
  height: 80px;
  border-radius: 6px;
}
.listing-image-empty--combined {
  font-size: 11px;
}
.listing-combined-empty {
  font-size: 13px;
  color: #8ea0bf;
  padding: 12px 0;
}
.listing-compact-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 220px;
  max-width: 100%;
}
.listing-compact-control {
  width: 100%;
}
.listing-auction-duration-control {
  width: 110px;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.listing-inv-count {
  font-size: 13px;
  color: #606266;
}
.listing-inv-count--warn {
  color: var(--el-color-danger);
}
/** 商品名单行输入不展示字数统计（避免与 maxlength 等组合时出现计数） */
.listing-field-full .listing-name-input :deep(.el-input__count) {
  display: none;
}
.listing-field-full .listing-price-input :deep(.el-input__count) {
  display: none;
}
</style>
