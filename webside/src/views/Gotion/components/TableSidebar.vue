<template>
  <div class="gtn-sidebar">
    <div class="gtn-sidebar-header">
      <span class="gtn-section-title">{{ t('gotion.sidebar.sectionTables') }}</span>
      <el-button size="small" text class="gtn-header-btn" @click="toggleAllExpand" :title="allExpanded ? t('gotion.sidebar.collapseAll') : t('gotion.sidebar.expandAll')">
        <el-icon><component :is="allExpanded ? 'FolderOpened' : 'Folder'" /></el-icon>
      </el-button>
    </div>

    <div class="gtn-table-list">
      <template v-for="tbl in topTables" :key="tbl.id">
        <!-- 有子表的父表 -->
        <div v-if="tbl.children && tbl.children.length > 0" class="gtn-table-group">
          <div
            class="gtn-table-item gtn-parent-item"
            :class="{ active: tbl.id === currentTableId, expanded: isExpanded(tbl.id), 'drag-over': dragOverId === tbl.id }"
            draggable="true"
            @click="selectTable(tbl.id)"
            @dragstart="onTableDragStart($event, tbl)"
            @dragover.prevent="onTableDragOver($event, tbl)"
            @dragleave="onTableDragLeave($event, tbl)"
            @drop="onTableDrop($event, tbl)"
            @dragend="onTableDragEnd"
          >
            <el-icon class="gtn-expand-icon" :class="{ rotated: isExpanded(tbl.id) }" @click.stop="toggleExpand(tbl.id)">
              <ArrowRight />
            </el-icon>
            <span class="gtn-table-icon">{{ tbl.icon }}</span>
            <span class="gtn-table-name">{{ tbl.name }}</span>
            <el-dropdown trigger="click" @command="cmd => onTableCmd(cmd, tbl)" @click.stop>
              <span class="gtn-table-more" @click.stop><el-icon><MoreFilled /></el-icon></span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">{{ t('gotion.sidebar.rename') }}</el-dropdown-item>
                  <el-dropdown-item command="add-child">{{ t('gotion.sidebar.addChild') }}</el-dropdown-item>
                  <el-dropdown-item command="delete" divided style="color:#f56c6c">{{ t('common.delete') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <!-- 子表列表 -->
          <div
            v-show="isExpanded(tbl.id)"
            class="gtn-children-list"
            :class="{ 'gtn-children-drop-zone': dragOverId === 'children-' + tbl.id }"
            @dragover.prevent="onChildrenDragOver($event, tbl)"
            @dragleave="onChildrenDragLeave($event, tbl)"
            @drop="onChildrenDrop($event, tbl)"
          >
            <div
              v-for="child in tbl.children"
              :key="child.id"
              class="gtn-table-item gtn-child-item"
              :class="{ active: child.id === currentTableId, 'drag-over': dragOverId === child.id }"
              draggable="true"
              @click="selectTable(child.id)"
              @dragstart="onTableDragStart($event, child)"
              @dragover.prevent="onTableDragOver($event, child)"
              @dragleave="onTableDragLeave($event, child)"
              @drop="onTableDrop($event, child)"
              @dragend="onTableDragEnd"
            >
              <span class="gtn-table-icon">{{ child.icon }}</span>
              <span class="gtn-table-name">{{ child.name }}</span>
              <el-dropdown trigger="click" @command="cmd => onTableCmd(cmd, child)" @click.stop>
                <span class="gtn-table-more" @click.stop><el-icon><MoreFilled /></el-icon></span>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="rename">{{ t('gotion.sidebar.rename') }}</el-dropdown-item>
                    <el-dropdown-item command="delete" divided style="color:#f56c6c">{{ t('common.delete') }}</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>

        <!-- 无子表的顶级表 -->
        <div v-else
          class="gtn-table-item"
          :class="{ active: tbl.id === currentTableId, 'drag-over': dragOverId === tbl.id }"
          draggable="true"
          @click="selectTable(tbl.id)"
          @dragstart="onTableDragStart($event, tbl)"
          @dragover.prevent="onTableDragOver($event, tbl)"
          @dragleave="onTableDragLeave($event, tbl)"
          @drop="onTableDrop($event, tbl)"
          @dragend="onTableDragEnd"
        >
          <span class="gtn-table-icon">{{ tbl.icon }}</span>
          <span class="gtn-table-name">{{ tbl.name }}</span>
          <el-dropdown trigger="click" @command="cmd => onTableCmd(cmd, tbl)" @click.stop>
            <span class="gtn-table-more" @click.stop><el-icon><MoreFilled /></el-icon></span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="rename">{{ t('gotion.sidebar.rename') }}</el-dropdown-item>
                <el-dropdown-item command="add-child">{{ t('gotion.sidebar.addChild') }}</el-dropdown-item>
                <el-dropdown-item command="delete" divided style="color:#f56c6c">{{ t('common.delete') }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </template>
    </div>

    <div class="gtn-sidebar-actions">
      <el-button size="small" @click="showCreate = true; createParentId = null" :icon="Plus" type="primary" plain style="width:100%">
        {{ t('gotion.sidebar.newTopTable') }}
      </el-button>
    </div>

    <!-- 新建表弹窗 -->
    <el-dialog v-model="showCreate" :title="createParentId ? t('gotion.sidebar.createChildTable') : t('gotion.sidebar.createTopTable')" width="380px">
      <el-form class="gtn-form" @submit.prevent>
        <el-form-item :label="t('gotion.sidebar.iconLabel')">
          <EmojiPicker v-model="newIcon" />
        </el-form-item>
        <el-form-item :label="t('gotion.sidebar.nameLabel')">
          <el-input v-model="newName" :placeholder="t('gotion.sidebar.tableNamePlaceholder')" @keydown.enter="doCreate" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="doCreate">{{ t('common.create') }}</el-button>
      </template>
    </el-dialog>

    <!-- 重命名弹窗 -->
    <el-dialog v-model="showRename" :title="t('gotion.sidebar.renameTable')" width="380px">
      <el-form class="gtn-form" @submit.prevent>
        <el-form-item :label="t('gotion.sidebar.iconLabel')">
          <EmojiPicker v-model="renameIcon" />
        </el-form-item>
        <el-form-item :label="t('gotion.sidebar.nameLabel')">
          <el-input v-model="renameName" @keydown.enter="doRename" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showRename = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" @click="doRename">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, reactive } from 'vue'
import { MoreFilled, Plus, ArrowRight } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useGotionTableStore } from '@/stores/gotionTable.js'
import EmojiPicker from './EmojiPicker.vue'

const store = useGotionTableStore()
const { t } = useI18n()
const topTables = computed(() => store.topTables)
const currentTableId = computed(() => store.currentTableId)

// 默认全部展开：只记录被用户收起的父表ID（空集合 = 全展开，新建父表天然展开）。
// 用户切换过的展示状态持久化到 localStorage，刷新/切页后保持。
const COLLAPSE_KEY = 'gotion.collapsed_table_ids'

function readCollapsed() {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return new Set(Array.isArray(arr) ? arr.filter(n => Number.isFinite(n)) : [])
  } catch {
    return new Set()
  }
}

function writeCollapsed(set) {
  try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...set])) } catch { /* ignore */ }
}

const collapsedIds = reactive(readCollapsed())

function isExpanded(id) {
  return !collapsedIds.has(id)
}

function setCollapsed(id, collapsed) {
  if (collapsed) collapsedIds.add(id)
  else collapsedIds.delete(id)
  writeCollapsed(collapsedIds)
}

// 是否全部展开
const allExpanded = computed(() => {
  const parentIds = topTables.value.filter(tbl => tbl.children?.length > 0).map(tbl => tbl.id)
  return parentIds.length > 0 && parentIds.every(id => !collapsedIds.has(id))
})

// 切换单个展开（仅三角箭头触发，不影响选中）
function toggleExpand(id) {
  setCollapsed(id, isExpanded(id))
}

// 切换全部展开/折叠
function toggleAllExpand() {
  if (allExpanded.value) {
    for (const tbl of topTables.value) {
      if (tbl.children && tbl.children.length > 0) {
        collapsedIds.add(tbl.id)
      }
    }
  } else {
    collapsedIds.clear()
  }
  writeCollapsed(collapsedIds)
}

// 选择表（不改变展开状态）
function selectTable(id) {
  store.switchTable(id)
}

const showCreate = ref(false)
const newName = ref('')
const newIcon = ref('')
const createParentId = ref(null)

// 供页面空状态按钮调用
function openCreate() {
  createParentId.value = null
  newName.value = ''
  newIcon.value = ''
  showCreate.value = true
}
defineExpose({ openCreate })

const showRename = ref(false)
const renameName = ref('')
const renameIcon = ref('')
const renameTarget = ref(null)

async function doCreate() {
  if (!newName.value.trim()) return
  const created = await store.addTable(newName.value.trim(), newIcon.value || '', createParentId.value)
  if (created) {
    selectTable(created.id)
    // 如果是子表，展开父表
    if (createParentId.value) {
      setCollapsed(createParentId.value, false)
    }
  }
  newName.value = ''
  newIcon.value = ''
  createParentId.value = null
  showCreate.value = false
}

function onTableCmd(cmd, tbl) {
  if (cmd === 'rename') {
    renameTarget.value = tbl
    renameName.value = tbl.name
    renameIcon.value = tbl.icon || ''
    showRename.value = true
  } else if (cmd === 'add-child') {
    createParentId.value = tbl.id
    newName.value = ''
    newIcon.value = ''
    showCreate.value = true
  } else if (cmd === 'delete') {
    const childCount = tbl.children?.length || 0
    const msg = childCount > 0
      ? t('gotion.sidebar.deleteConfirmWithChildren', { name: tbl.name, count: childCount })
      : t('gotion.sidebar.deleteConfirmSingle', { name: tbl.name })
    ElMessageBox.confirm(msg, t('gotion.sidebar.deleteConfirmTitle'), { type: 'warning', confirmButtonText: t('common.delete'), confirmButtonClass: 'el-button--danger' })
      .then(() => store.removeTable(tbl.id))
      .catch(() => {})
  }
}

async function doRename() {
  if (!renameTarget.value || !renameName.value.trim()) return
  await store.updateTableMeta(renameTarget.value.id, {
    name: renameName.value.trim(),
    icon: renameIcon.value || '',
  })
  showRename.value = false
}

// ── 表格拖拽移动层级 ─────────────────────────────────────
const dragTable = ref(null)
const dragOverId = ref(null)

function onTableDragStart(e, table) {
  dragTable.value = table
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(table.id))
}

function onTableDragOver(e, target) {
  if (!dragTable.value || dragTable.value.id === target.id) return
  // 不能拖到自己的子表上
  if (dragTable.value.children?.some(c => c.id === target.id)) return
  dragOverId.value = target.id
  e.dataTransfer.dropEffect = 'move'
}

function onTableDragLeave(e, target) {
  if (dragOverId.value === target.id) {
    dragOverId.value = null
  }
}

// 侧栏只渲染两级，带子表的表不能再被嵌套到别的表下，否则其子表会从界面上消失
function canNest(table) {
  if (table.children?.length > 0) {
    ElMessage.warning(t('gotion.sidebar.hasChildrenCannotMove', { name: table.name }))
    return false
  }
  return true
}

async function onTableDrop(e, target) {
  e.preventDefault()
  if (!dragTable.value || dragTable.value.id === target.id) return

  const sourceId = dragTable.value.id
  dragOverId.value = null

  // 如果目标是子表，让源表成为同一父表下的子表（同级排列）
  if (target.parent_id) {
    if (!canNest(dragTable.value)) return
    await store.moveTable(sourceId, target.parent_id)
    setCollapsed(target.parent_id, false)
    return
  }

  // 目标是父表或顶级表：询问是否成为子表
  if (!canNest(dragTable.value)) return
  try {
    await ElMessageBox.confirm(
      t('gotion.sidebar.moveIntoConfirm', { source: dragTable.value.name, target: target.name }),
      t('gotion.sidebar.moveTableTitle'),
      { confirmButtonText: t('gotion.sidebar.moveIntoBtn'), cancelButtonText: t('common.cancel') }
    )
    await store.moveTable(sourceId, target.id)
    setCollapsed(target.id, false)
  } catch {
    // 取消操作
  }
}

function onChildrenDragOver(e, parentTable) {
  if (!dragTable.value) return
  if (dragTable.value.id === parentTable.id) return
  if (dragTable.value.children?.some(c => c.id === parentTable.id)) return
  dragOverId.value = 'children-' + parentTable.id
  e.dataTransfer.dropEffect = 'move'
}

function onChildrenDragLeave(e, parentTable) {
  if (dragOverId.value === 'children-' + parentTable.id) {
    dragOverId.value = null
  }
}

async function onChildrenDrop(e, parentTable) {
  e.preventDefault()
  if (!dragTable.value || dragTable.value.id === parentTable.id) return
  dragOverId.value = null
  if (!canNest(dragTable.value)) return
  await store.moveTable(dragTable.value.id, parentTable.id)
  setCollapsed(parentTable.id, false)
}

function onTableDragEnd() {
  dragTable.value = null
  dragOverId.value = null
}
</script>

<style scoped>
.gtn-sidebar {
  width: 240px;
  min-width: 240px;
  height: 100%;
  background: #0e1830;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  flex-direction: column;
  padding: 0;
}
.gtn-sidebar-header {
  padding: 12px 14px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.gtn-section-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #9ba8bf;
}
.gtn-header-btn {
  color: #9ba8bf !important;
  padding: 4px !important;
}
.gtn-table-list { flex: 1; overflow-y: auto; padding: 6px 8px; }

.gtn-table-group { margin-bottom: 2px; }

.gtn-table-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
  position: relative;
  color: #a6adb4;
}
.gtn-table-item:hover { background: #1b2942; }
.gtn-table-item.active { background: #1890ff; color: #ffffff; }

.gtn-parent-item {
  font-weight: 500;
}
.gtn-parent-item .gtn-expand-icon {
  font-size: 18px;
  color: #c6d2e3;
  transition: transform 0.15s;
  padding: 4px;
  margin: -4px;
  border-radius: 4px;
  flex-shrink: 0;
}
.gtn-parent-item .gtn-expand-icon:hover {
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
}
.gtn-table-item.active .gtn-expand-icon { color: #ffffff; }
.gtn-parent-item .gtn-expand-icon.rotated {
  transform: rotate(90deg);
}

.gtn-child-item {
  padding-left: 28px;
  font-size: 13px;
}

.gtn-table-icon { font-size: 16px; line-height: 1; }
.gtn-table-name { flex: 1; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gtn-table-more {
  opacity: 0;
  transition: opacity 0.15s;
  padding: 2px;
  border-radius: 4px;
  cursor: pointer;
  color: #9ba8bf;
}
.gtn-table-item.active .gtn-table-more { color: #d8e6ff; }
.gtn-table-item:hover .gtn-table-more { opacity: 1; }

.gtn-children-list {
  padding-left: 0;
  min-height: 4px;
}

/* 拖拽反馈 */
.gtn-table-item.drag-over {
  background: rgba(24, 144, 255, 0.15);
  outline: 2px dashed #1890ff;
  outline-offset: -2px;
}
.gtn-children-drop-zone {
  background: rgba(24, 144, 255, 0.08);
  outline: 2px dashed #1890ff;
  border-radius: 4px;
}

.gtn-sidebar-actions { padding: 8px 12px 14px; }

/* 对冲全局 .el-input { width:180px !important }：弹窗表单内输入框占满整行 */
.gtn-form :deep(.el-input),
.gtn-form :deep(.el-select) {
  width: 100% !important;
}
</style>
