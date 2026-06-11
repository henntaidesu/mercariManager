<template>
  <div class="gtn-grid-wrap" v-loading="store.loading">
    <template v-if="store.currentTable">
      <!-- 表头 -->
      <div class="gtn-grid-header">
        <div class="gtn-title-bar">
          <span class="gtn-icon-big">{{ store.currentTable.icon }}</span>
          <h2 class="gtn-title">{{ store.currentTable.name }}</h2>
          <span class="gtn-row-count">{{ t('gotion.grid.rowCount', { count: rows.length }) }}</span>
          <el-button size="small" @click="showAddCol = true" :icon="Plus" plain>{{ t('gotion.grid.addColumn') }}</el-button>
          <el-button size="small" @click="showImportDialog = true" :icon="Upload" plain>{{ t('gotion.grid.importBtn') }}</el-button>
          <el-button size="small" @click="doExport" :icon="Download" plain :disabled="!columns.length">{{ t('gotion.grid.exportBtn') }}</el-button>
        </div>
        <p v-if="store.currentTable.description" class="gtn-desc">{{ store.currentTable.description }}</p>
      </div>

      <!-- 滚动容器 -->
      <div class="gtn-grid-scroll">
        <table class="gtn-grid-table" :style="{ width: tableWidth + 'px', tableLayout: 'fixed' }">
          <colgroup>
            <col style="width:40px" /> <!-- 行号列 -->
            <col
              v-for="col in columns"
              :key="col.id"
              :style="{ width: col.width + 'px' }"
            />
            <col style="width:40px" /> <!-- 添加列按钮 -->
          </colgroup>

          <!-- 列头行 -->
          <thead>
            <tr>
              <th class="gtn-th-row-num"></th>
              <th
                v-for="col in columns"
                :key="col.id"
                class="gtn-th-col"
                :class="{ dragging: dragCol?.id === col.id }"
                draggable="true"
                @dblclick="openColMenu(col)"
                @dragstart="onColDragStart($event, col)"
                @dragover.prevent="onColDragOver($event, col)"
                @dragleave="onColDragLeave($event, col)"
                @drop="onColDrop($event, col)"
                @dragend="onColDragEnd"
              >
                <div class="gtn-th-inner">
                  <span class="gtn-col-name">{{ col.name }}</span>
                  <el-icon class="gtn-col-menu-btn" :title="t('gotion.grid.columnSettings')" @click.stop="openColMenu(col)"><MoreFilled /></el-icon>

                  <!-- 拖拽调整列宽 -->
                  <div class="gtn-col-resize-handle" @mousedown.stop="startResize($event, col)" />
                </div>
              </th>
              <th class="gtn-th-add-col" @click="showAddCol = true">
                <el-icon><Plus /></el-icon>
              </th>
            </tr>
          </thead>

          <!-- 数据行 -->
          <tbody>
            <tr v-for="(row, ri) in rows" :key="row.id" class="gtn-data-row">
              <td class="gtn-td-row-num">
                <span class="gtn-row-num-text">{{ ri + 1 }}</span>
                <el-icon
                  class="gtn-row-delete-btn"
                  :title="t('gotion.grid.deleteThisRow')"
                  @click="confirmDeleteRow(row)"
                ><Delete /></el-icon>
              </td>

              <td v-for="col in columns" :key="col.id" class="gtn-td-cell">
                <component
                  :is="cellComponent(col.type)"
                  :model-value="row.data[col.key]"
                  :column="col"
                  @change="val => onCellChange(row, col, val)"
                />
              </td>

              <td class="gtn-td-empty"></td>
            </tr>

            <!-- 内联添加行：任一列有了数据立即建行 -->
            <tr class="gtn-add-row-tr" v-if="columns.length">
              <td class="gtn-td-row-num gtn-add-row-num"
                  :title="t('gotion.grid.addRowHint')"
                  @click="commitNewRow">
                <el-icon v-if="hasNewRowData" class="gtn-commit-icon"><Check /></el-icon>
                <el-icon v-else><Plus /></el-icon>
              </td>
              <td v-for="col in columns" :key="'new-'+col.id" class="gtn-td-cell gtn-add-row-cell"
                  @keydown.enter="commitNewRow">
                <component
                  :is="cellComponent(col.type)"
                  :model-value="newRowData[col.key]"
                  :column="col"
                  @change="val => onNewCellChange(col, val)"
                />
              </td>
              <td class="gtn-td-empty"></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- 无表时的空状态 -->
    <template v-else>
      <div class="gtn-empty-state">
        <div class="gtn-empty-icon">🗂️</div>
        <div class="gtn-empty-text">{{ t('gotion.grid.emptyText') }}</div>
        <el-button type="primary" @click="$emit('create-table')">{{ t('gotion.grid.createFirstTable') }}</el-button>
      </div>
    </template>

    <!-- 添加列弹窗 -->
    <el-dialog v-model="showAddCol" :title="t('gotion.grid.addNewColumn')" width="380px">
      <el-form class="gtn-form" label-width="80px">
        <el-form-item :label="t('gotion.grid.columnNameLabel')">
          <el-input v-model="addColForm.name" :placeholder="t('gotion.grid.columnNamePlaceholder')" @keydown.enter="doAddCol" />
        </el-form-item>
        <el-form-item :label="t('gotion.grid.typeLabel')">
          <el-select v-model="addColForm.type">
            <el-option v-for="ct in colTypes" :key="ct.value" :value="ct.value" :label="`${ct.icon} ${ct.label}`">
              <span>{{ ct.icon }} {{ ct.label }}</span>
            </el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddCol = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="doAddCol">{{ t('common.add') }}</el-button>
      </template>
    </el-dialog>

    <!-- 列设置弹窗 -->
    <ColumnMenu
      v-model="showColMenu"
      :column="selectedCol"
      @saved="showColMenu = false"
      @deleted="showColMenu = false"
    />

    <!-- 导入文件对话框 -->
    <el-dialog v-model="showImportDialog" :title="t('gotion.grid.importTitle')" width="420px">
      <div class="gtn-import-content">
        <p class="gtn-import-hint">{{ t('gotion.grid.importHint') }}</p>
        <el-upload
          ref="uploadRef"
          drag
          :auto-upload="false"
          :limit="1"
          accept=".csv,.xlsx,.xls"
          :on-change="handleImportFileChange"
          :on-exceed="handleImportExceed"
        >
          <el-icon class="el-icon--upload"><Upload /></el-icon>
          <div class="el-upload__text">{{ t('gotion.grid.dropHere') }} <em>{{ t('gotion.grid.clickToPick') }}</em></div>
          <template #tip>
            <div class="el-upload__tip">{{ t('gotion.grid.importTip') }}</div>
          </template>
        </el-upload>
        <div style="margin-top: 12px;">
          <el-checkbox v-model="importHasHeader">{{ t('gotion.grid.firstRowHeader') }}</el-checkbox>
        </div>
      </div>
      <template #footer>
        <el-button @click="cancelImport">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="importing" :disabled="!importFile" @click="doImport">{{ t('gotion.grid.importBtn') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Plus, Delete, Check, Upload, Download, MoreFilled } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useGotionTableStore } from '@/stores/gotionTable.js'
import { gotionApi } from '@/api'
import ColumnMenu from './ColumnMenu.vue'
import CellText from './cell-types/CellText.vue'
import CellNumber from './cell-types/CellNumber.vue'
import CellSelect from './cell-types/CellSelect.vue'
import CellTags from './cell-types/CellTags.vue'
import CellUrl from './cell-types/CellUrl.vue'
import CellTableRef from './cell-types/CellTableRef.vue'

const emit = defineEmits(['create-table'])

const store = useGotionTableStore()
const { t } = useI18n()
const columns = computed(() => store.columns)
const rows = computed(() => store.rows)

// ── 列类型 ──────────────────────────────────────────────
const colTypes = computed(() => [
  { value: 'text',      label: t('gotion.types.text'),     icon: '📝' },
  { value: 'number',    label: t('gotion.types.number'),   icon: '🔢' },
  { value: 'select',    label: t('gotion.types.select'),   icon: '🔵' },
  { value: 'tags',      label: t('gotion.types.tags'),     icon: '🏷️' },
  { value: 'url',       label: t('gotion.types.url'),      icon: '🔗' },
  { value: 'table_ref', label: t('gotion.types.tableRef'), icon: '📋' },
])

const cellCompMap = {
  text: CellText,
  number: CellNumber,
  select: CellSelect,
  tags: CellTags,
  url: CellUrl,
  table_ref: CellTableRef,
}
function cellComponent(type) { return cellCompMap[type] || CellText }

// 表格总宽 = 行号列 40 + 各列宽 + 添加列按钮 40，避免表格被拉伸到全屏宽
const tableWidth = computed(() =>
  80 + columns.value.reduce((sum, c) => sum + (c.width || 200), 0)
)

// ── 单元格保存 ───────────────────────────────────────────
async function onCellChange(row, col, val) {
  const newData = { ...row.data, [col.key]: val }
  await store.updateRow(store.currentTableId, row.id, newData)
}

// ── 内联添加行 ──────────────────────────────────────────────
const newRowData = ref({})

const hasNewRowData = computed(() => {
  return Object.values(newRowData.value).some(v =>
    v !== null && v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0)
  )
})

function onNewCellChange(col, val) {
  newRowData.value = { ...newRowData.value, [col.key]: val }
  // 任一列有了数据就立即建行（选标签、文本失焦等都会触发 change）
  if (hasNewRowData.value) {
    commitNewRow()
  }
}

async function commitNewRow() {
  if (!hasNewRowData.value) return
  const data = { ...newRowData.value }
  newRowData.value = {}
  await store.addRow(store.currentTableId, data)
}

// ── 删除行 ───────────────────────────────────────────────
async function confirmDeleteRow(row) {
  const firstCol = columns.value[0]
  const label = firstCol ? (row.data[firstCol.key] || `#${row.id}`) : `#${row.id}`
  try {
    await ElMessageBox.confirm(t('gotion.grid.deleteRowConfirm', { label }), t('gotion.sidebar.deleteConfirmTitle'), { type: 'warning' })
  } catch {
    return // 用户取消
  }
  await store.removeRow(store.currentTableId, row.id)
}

// ── 列头菜单 ─────────────────────────────────────────────
const showColMenu = ref(false)
const selectedCol = ref(null)

function openColMenu(col) {
  selectedCol.value = col
  showColMenu.value = true
}

// ── 添加列 ───────────────────────────────────────────────
const showAddCol = ref(false)
const addColForm = ref({ name: '', type: 'text' })

async function doAddCol() {
  if (!addColForm.value.name.trim()) return
  await store.addColumn(store.currentTableId, {
    name: addColForm.value.name.trim(),
    type: addColForm.value.type,
  })
  addColForm.value = { name: '', type: 'text' }
  showAddCol.value = false
}

// ── 列宽拖拽 ─────────────────────────────────────────────
let resizeCol = null, resizeStartX = 0, resizeStartW = 0
let isResizing = false

function startResize(e, col) {
  isResizing = true
  resizeCol = col
  resizeStartX = e.clientX
  resizeStartW = col.width || 200
  e.preventDefault()
  window.addEventListener('mousemove', onResizeMove)
  window.addEventListener('mouseup', stopResize)
}
function onResizeMove(e) {
  if (!resizeCol) return
  const newW = Math.max(20, resizeStartW + e.clientX - resizeStartX)
  resizeCol.width = newW
}
async function stopResize() {
  if (resizeCol) {
    await store.updateCol(store.currentTableId, resizeCol.id, { width: resizeCol.width })
    resizeCol = null
  }
  isResizing = false
  window.removeEventListener('mousemove', onResizeMove)
  window.removeEventListener('mouseup', stopResize)
}

// ── 列拖拽排序 ─────────────────────────────────────────────
const dragCol = ref(null)
const dragOverCol = ref(null)

function onColDragStart(e, col) {
  if (isResizing) {
    e.preventDefault()
    return
  }
  dragCol.value = col
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', col.id.toString())
}

function onColDragOver(e, col) {
  if (dragCol.value && dragCol.value.id !== col.id) {
    dragOverCol.value = col
    col._dragOver = true
  }
}

function onColDragLeave(e, col) {
  col._dragOver = false
}

async function onColDrop(e, targetCol) {
  e.preventDefault()
  if (!dragCol.value || dragCol.value.id === targetCol.id) return

  // 计算新顺序
  const cols = [...columns.value]
  const fromIdx = cols.findIndex(c => c.id === dragCol.value.id)
  const toIdx = cols.findIndex(c => c.id === targetCol.id)

  if (fromIdx === -1 || toIdx === -1) return

  // 移动列
  const [movedCol] = cols.splice(fromIdx, 1)
  cols.splice(toIdx, 0, movedCol)

  // 更新排序
  const items = cols.map((c, idx) => ({ id: c.id, sort_order: idx }))
  try {
    await gotionApi.reorderColumns(store.currentTableId, items)
  } catch (err) {
    // http.js 已统一提示
  } finally {
    // 无论成败都刷新，保证界面与后端一致
    await store.loadTableData(store.currentTableId)
  }
}

function onColDragEnd() {
  dragCol.value = null
  dragOverCol.value = null
  columns.value.forEach(c => c._dragOver = false)
}

// ── 导出 CSV ───────────────────────────────────────────────
function csvEscape(v) {
  const s = v == null ? '' : String(v)
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
}

/** 单元格值转导出文本：tags 数组用逗号连接，table_ref 导出目标表名 */
function cellToText(col, val) {
  if (val == null) return ''
  if (col.type === 'tags') return Array.isArray(val) ? val.join(',') : String(val)
  if (col.type === 'table_ref') {
    const tb = store.allTables.find(t2 => t2.id == val)
    return tb ? tb.name : String(val)
  }
  return String(val)
}

function doExport() {
  const cols = columns.value
  if (!cols.length) return
  const lines = [cols.map(c => csvEscape(c.name)).join(',')]
  for (const row of rows.value) {
    lines.push(cols.map(c => csvEscape(cellToText(c, row.data[c.key]))).join(','))
  }
  // BOM 让 Excel 正确识别 UTF-8 中日文；CRLF 行尾兼容 Excel
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${store.currentTable?.name || 'table'}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ── 导入 CSV/Excel ─────────────────────────────────────────
const showImportDialog = ref(false)
const uploadRef = ref(null)
const importFile = ref(null)
const importHasHeader = ref(true)
const importing = ref(false)

function handleImportFileChange(fileObj) {
  importFile.value = fileObj.raw
}

function handleImportExceed() {
  // 清除已选文件再设置新文件
  if (uploadRef.value) uploadRef.value.clearFiles()
}

function cancelImport() {
  importFile.value = null
  if (uploadRef.value) uploadRef.value.clearFiles()
  showImportDialog.value = false
}

async function doImport() {
  if (!importFile.value || !store.currentTableId) return
  importing.value = true
  try {
    // http 拦截器已经解包 response.data，res 就是响应体
    const res = await gotionApi.importFromFile(store.currentTableId, importFile.value, importHasHeader.value)
    ElMessageBox.alert(res?.message || t('gotion.grid.importSuccess'), t('gotion.grid.importDoneTitle'), { type: 'success' })
    await store.loadTableData(store.currentTableId)
    await store.fetchTables()
    cancelImport()
  } catch (err) {
    ElMessageBox.alert(err.message || t('gotion.grid.importFailed'), t('gotion.grid.importFailed'), { type: 'error' })
  } finally {
    importing.value = false
  }
}

</script>

<style scoped>
.gtn-grid-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #131c2f;
  min-width: 0;
}
.gtn-grid-header { padding: 14px 20px 10px; border-bottom: 1px solid #28354a; }
.gtn-title-bar { display:flex; align-items:center; gap:8px; }
.gtn-icon-big { font-size:24px; }
.gtn-title { margin:0; font-size:18px; font-weight:600; color:#e6edf7; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.gtn-row-count {
  font-size: 12px;
  color: #9ba8bf;
  background: #18233a;
  padding: 2px 8px;
  border-radius: 10px;
  white-space: nowrap;
}
.gtn-desc { margin:6px 0 0; font-size:12px; color:#9ba8bf; }

.gtn-grid-scroll {
  flex: 1;
  overflow: auto;
}
.gtn-grid-table {
  border-collapse: collapse;
  font-size: 13px;
  color: #d6deea;
}

/* 列头 */
.gtn-th-row-num { width:40px; background:#18233a; border-bottom:2px solid #28354a; position:sticky; top:0; z-index:2; }
.gtn-th-col {
  background: #18233a;
  border-bottom: 2px solid #28354a;
  border-right: 1px solid #28354a;
  padding: 0;
  position: sticky;
  top: 0;
  z-index: 2;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
}
.gtn-th-col:hover { background: #1d2a45; }
.gtn-th-col[draggable="true"] { cursor: grab; }
.gtn-th-col[draggable="true"]:active { cursor: grabbing; }
.gtn-th-col.dragging { opacity: 0.5; }
.gtn-th-inner {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
  position: relative;
}
.gtn-col-name { font-weight:500; color:#d6deea; font-size:12px; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.gtn-col-menu-btn {
  opacity: 0;
  font-size: 12px;
  color: #9ba8bf;
  flex-shrink: 0;
  padding: 2px;
  border-radius: 3px;
  transition: opacity 0.15s;
  transform: rotate(90deg); /* 横向三点旋转成竖向 ⋮ */
}
.gtn-th-col:hover .gtn-col-menu-btn { opacity: 1; }
.gtn-col-menu-btn:hover { color: #e6edf7; background: #28354a; }

.gtn-col-resize-handle {
  position: absolute; right: 0; top: 0; bottom: 0;
  width: 5px; cursor: col-resize; z-index: 1;
}
.gtn-col-resize-handle:hover { background: #3a4a6b; }
.gtn-th-add-col {
  background: #18233a;
  border-bottom: 2px solid #28354a;
  padding: 8px;
  cursor: pointer;
  color: #9ba8bf;
  text-align: center;
  position: sticky; top: 0; z-index: 2;
}
.gtn-th-add-col:hover { background:#1d2a45; color:#e6edf7; }

/* 数据行 */
.gtn-data-row:hover td { background: #1b2942; }
.gtn-td-row-num {
  width: 40px;
  text-align: center;
  color: #6b7a93;
  font-size: 11px;
  border-bottom: 1px solid #202c44;
  border-right: 1px solid #28354a;
  position: relative;
}
.gtn-row-delete-btn {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  display: none; cursor: pointer; color: #f56c6c; font-size: 14px;
}
.gtn-td-row-num:hover .gtn-row-num-text { opacity:0; }
.gtn-td-row-num:hover .gtn-row-delete-btn { display:inline-flex; }

.gtn-td-cell {
  border-bottom: 1px solid #202c44;
  border-right: 1px solid #28354a;
  height: 36px;
  padding: 0;
  max-width: 0;
  overflow: visible;
}
.gtn-td-empty { border-bottom:1px solid #202c44; }

/* 添加行 */
.gtn-add-row-tr td { background: #10192c; }
.gtn-add-row-num {
  color: #5c6b85;
  cursor: pointer;
}
.gtn-add-row-num:hover { color: #67c23a; background: rgba(103, 194, 58, 0.1); }
.gtn-commit-icon { color: #67c23a; }
.gtn-add-row-cell {
  opacity: 0.6;
}
.gtn-add-row-cell:focus-within, .gtn-add-row-cell:hover {
  opacity: 1;
  background: #16233c;
}

/* 空状态 */
.gtn-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}
.gtn-empty-icon { font-size: 60px; }
.gtn-empty-text { color: #9ba8bf; font-size: 14px; }

/* 导入对话框 */
.gtn-import-hint {
  margin: 0 0 12px;
  font-size: 13px;
  color: #9ba8bf;
}

/* 对冲全局 .el-input { width:180px !important }：弹窗表单内输入框占满整行 */
.gtn-form :deep(.el-input),
.gtn-form :deep(.el-select) {
  width: 100% !important;
}
</style>
