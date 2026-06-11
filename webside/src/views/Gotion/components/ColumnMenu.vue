<template>
  <!-- 列头菜单弹窗 -->
  <el-dialog
    v-model="visible"
    :title="t('gotion.colMenu.title', { name: form.name })"
    width="420px"
    @close="onClose"
    destroy-on-close
  >
    <el-form class="gtn-form" :model="form" label-width="80px" size="default">
      <el-form-item :label="t('gotion.colMenu.columnNameLabel')">
        <el-input v-model="form.name" />
      </el-form-item>

      <el-form-item :label="t('gotion.colMenu.typeLabel')">
        <el-select v-model="form.type" @change="onTypeChange">
          <el-option v-for="ct in colTypes" :key="ct.value" :value="ct.value" :label="ct.label">
            <span>{{ ct.label }}</span>
          </el-option>
        </el-select>
        <div v-if="typeChanged" class="gtn-type-warning">
          <el-icon><Warning /></el-icon>
          {{ t('gotion.colMenu.typeChangeWarning') }}
        </div>
      </el-form-item>

      <el-form-item :label="t('gotion.colMenu.widthLabel')">
        <el-input-number v-model="form.width" :min="20" :max="800" :step="10" />
      </el-form-item>

      <!-- select / tags 选项管理 -->
      <template v-if="form.type === 'select' || form.type === 'tags'">
        <el-form-item :label="t('gotion.colMenu.optionsLabel')">
          <div class="gtn-opts-container">
            <div v-for="(opt, idx) in form.config.options" :key="idx" class="gtn-opt-row">
              <el-input v-model="opt.label" :placeholder="t('gotion.colMenu.optionNamePlaceholder')" size="small" class="gtn-opt-input" />
              <el-color-picker v-model="opt.color" size="small" />
              <el-button type="danger" :icon="Delete" circle size="small" @click="removeOpt(idx)" />
            </div>
            <el-button size="small" @click="addOpt">{{ t('gotion.colMenu.addOption') }}</el-button>
          </div>
        </el-form-item>
      </template>

      <!-- table_ref 目标表 -->
      <template v-if="form.type === 'table_ref'">
        <el-form-item :label="t('gotion.colMenu.targetTableLabel')">
          <el-select v-model="form.config.target_table_id">
            <el-option
              v-for="tb in allTables"
              :key="tb.id"
              :value="tb.id"
              :label="`${tb.icon ? tb.icon + ' ' : ''}${tb.name}`"
            />
          </el-select>
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="onClose">{{ t('common.cancel') }}</el-button>
      <el-button type="danger" @click="onDelete">{{ t('gotion.colMenu.deleteColumn') }}</el-button>
      <el-button type="primary" @click="onSave">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { Delete, Warning } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useGotionTableStore } from '@/stores/gotionTable.js'

const props = defineProps({
  modelValue: Boolean,
  column: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'saved', 'deleted'])

const store = useGotionTableStore()
const { t } = useI18n()
const allTables = computed(() => store.allTables)
const visible = ref(false)

const colTypes = computed(() => [
  { value: 'text',      label: t('gotion.types.text') },
  { value: 'number',    label: t('gotion.types.number') },
  { value: 'select',    label: t('gotion.types.select') },
  { value: 'tags',      label: t('gotion.types.tags') },
  { value: 'url',       label: t('gotion.types.url') },
  { value: 'table_ref', label: t('gotion.types.tableRef') },
])

const form = ref({ name: '', type: 'text', width: 200, config: { options: [] } })
const originalType = ref('text')
const typeChanged = ref(false)

watch(() => props.modelValue, v => { visible.value = v })
watch(visible, v => { if (!v) emit('update:modelValue', false) })

watch(() => props.column, col => {
  if (!col) return
  form.value = {
    name: col.name,
    type: col.type,
    width: col.width || 200,
    config: col.config
      ? JSON.parse(JSON.stringify(col.config))
      : { options: [] },
  }
  originalType.value = col.type
  typeChanged.value = false
  if (!form.value.config.options) form.value.config.options = []
}, { immediate: true })

function onTypeChange(newType) {
  if (newType !== originalType.value) {
    typeChanged.value = true
    // 重置 config
    if (newType === 'select' || newType === 'tags') {
      form.value.config = { options: [] }
    } else if (newType === 'table_ref') {
      form.value.config = { target_table_id: null }
    } else {
      form.value.config = {}
    }
  } else {
    typeChanged.value = false
  }
}

function addOpt() {
  const colors = ['#409eff','#67c23a','#e6a23c','#f56c6c','#909399','#b37feb']
  form.value.config.options.push({
    label: '',
    color: colors[form.value.config.options.length % colors.length],
  })
}
function removeOpt(idx) { form.value.config.options.splice(idx, 1) }

function onClose() { visible.value = false }

async function onSave() {
  // 如果类型改变了，需要先清空该列的所有数据
  if (typeChanged.value && props.column) {
    await clearColumnData()
  }

  const data = {
    name: form.value.name,
    type: form.value.type,
    width: form.value.width,
    config: form.value.config,
  }
  await store.updateCol(props.column.table_id, props.column.id, data)
  emit('saved')
  visible.value = false
}

async function clearColumnData() {
  // 清空所有行中该列的数据
  const colKey = props.column.key
  const rows = store.rows
  for (const row of rows) {
    if (row.data && row.data[colKey] !== undefined) {
      const newData = { ...row.data }
      delete newData[colKey]
      await store.updateRow(props.column.table_id, row.id, newData)
    }
  }
}

async function onDelete() {
  try {
    await ElMessageBox.confirm(t('gotion.colMenu.deleteColumnConfirm', { name: props.column.name }), t('gotion.sidebar.deleteConfirmTitle'), { type: 'warning' })
  } catch {
    return // 用户取消
  }
  await store.removeColumn(props.column.table_id, props.column.id)
  emit('deleted')
  visible.value = false
}
</script>

<style scoped>
.gtn-opts-container { display:flex; flex-direction:column; gap:6px; width:100%; }
.gtn-opt-row { display:flex; align-items:center; gap:6px; }
.gtn-type-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
  font-size: 12px;
  color: #e6a23c;
}

/* 对冲全局 .el-input { width:180px !important }：表单输入框占满整行，选项行输入框自适应 */
.gtn-form :deep(.el-input),
.gtn-form :deep(.el-select) {
  width: 100% !important;
}
.gtn-opt-row .gtn-opt-input {
  flex: 1;
}
.gtn-opt-row :deep(.el-input) {
  width: 100% !important;
}
</style>
