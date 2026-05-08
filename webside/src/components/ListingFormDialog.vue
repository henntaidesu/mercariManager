<template>
  <el-dialog
    :model-value="modelValue"
    title="组合出品"
    :width="isMobile ? '94vw' : '640px'"
    class="listing-dialog"
    destroy-on-close
    @update:model-value="onVisibleChange"
  >
    <el-form :model="form" label-width="110px">
      <el-form-item label="商品图片">
        <div class="listing-image-box">
          <el-image
            v-if="form.image"
            :src="form.image"
            fit="cover"
            class="listing-image-preview"
            :preview-src-list="[form.image]"
            :hide-on-click-modal="true"
            :preview-teleported="true"
          />
          <div v-else class="listing-image-empty">暂无图片</div>
          <div class="listing-image-actions">
            <input
              ref="fileInputRef"
              type="file"
              accept="image/*"
              style="display:none"
              @change="handleImageUpload"
            />
            <el-button type="primary" plain @click="fileInputRef?.click()">上传图片</el-button>
            <el-button @click="form.image = ''">清空</el-button>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="商品名">
        <el-input v-model="form.name" placeholder="请输入商品名" clearable />
      </el-form-item>
      <el-form-item label="商品类型">
        <el-cascader
          v-model="form.category_mapping_path"
          :options="categoryTypeCascaderOptions"
          :props="categoryTypeCascaderProps"
          :show-all-levels="false"
          clearable
          filterable
          placeholder="请选择商品类型（1/2/3级）"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleCategoryTypeChange"
        />
      </el-form-item>
      <el-form-item label="商品状态">
        <el-select v-model="form.status" placeholder="请选择商品状态" style="width: 100%">
          <el-option v-for="s in listingStatusOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="商品说明">
        <el-input v-model="form.description" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="请输入商品说明" />
      </el-form-item>
      <el-form-item label="快递费负担">
        <el-select v-model="form.shipping_payer" placeholder="请选择快递费负担" style="width: 100%">
          <el-option v-for="s in shippingPayerOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="配送方法">
        <el-select v-model="form.shipping_method" placeholder="请选择配送方法" style="width: 100%">
          <el-option v-for="s in shippingMethodOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="发货地址">
        <el-cascader
          v-model="form.shipping_from_path"
          :options="shippingFromCascaderOptions"
          :props="shippingFromCascaderProps"
          :show-all-levels="false"
          clearable
          filterable
          placeholder="请选择发货地（地区 / 都道府県）"
          style="width: 100%"
          popper-class="product-type-cascader-popper"
          @change="handleShippingFromChange"
        />
      </el-form-item>
      <el-form-item label="最大发货天数">
        <el-select v-model="form.shipping_days" placeholder="请选择最大发货天数" style="width: 100%">
          <el-option v-for="s in shippingDaysOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="出售类型">
        <el-select v-model="form.sale_type" placeholder="请选择出售类型" style="width: 100%">
          <el-option v-for="s in saleTypeOptions" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
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
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
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
  isMobile: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'saved'])

const fileInputRef = ref()
const form = ref(getDefaultForm())

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
  { label: '价格可谈', value: 'negotiable' }
]

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    const seed = props.initialData || {}
    const seedMappingId = seed.category_mapping_id != null ? String(seed.category_mapping_id) : null
    const seedPath = seedMappingId
      ? (categoryTypeTreeMeta.value.idToPath.get(seedMappingId) || [])
      : []
    const areaId = normalizeShippingFromSeed(seed.shipping_from)
    form.value = {
      ...getDefaultForm(),
      image: seed.image || '',
      name: seed.name || '',
      category_mapping_id: seedMappingId,
      category_mapping_path: seedPath,
      description: seed.description || '',
      shipping_from: areaId,
      shipping_from_path: buildShippingFromPath(areaId)
    }
  }
)

function getDefaultForm() {
  return {
    image: '',
    name: '',
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
    sale_type: 'instant_buy'
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

function handleImageUpload(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('图片不能超过5MB')
    return
  }
  const reader = new FileReader()
  reader.onload = (ev) => {
    form.value.image = ev.target?.result || ''
  }
  reader.readAsDataURL(file)
  e.target.value = ''
}

function submitStub() {
  emit('saved', { ...form.value })
  ElMessage.success('出品表单已保存（暂未对接接口）')
  onVisibleChange(false)
}
</script>

<style scoped>
.listing-image-box {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: 100%;
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
.listing-image-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
