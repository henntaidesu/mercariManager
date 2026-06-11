<template>
  <div class="gtn-cell-tableref" @click.stop @mousedown.stop>
    <el-popover
      :visible="popVisible"
      :width="240"
      placement="bottom-start"
      :teleported="false"
      @update:visible="v => { if (!v) popVisible = false }"
    >
      <template #reference>
        <div class="gtn-ref-display" @click.stop="openPopover">
          <template v-if="targetTable">
            <span class="gtn-ref-link" @click.stop="navigate">
              <el-icon><Link /></el-icon>
              {{ targetTable.icon || '' }} {{ targetTable.name }}
            </span>
          </template>
          <span v-else class="gtn-empty-hint" @click.stop="openPopover">{{ t('gotion.cell.clickToLinkTable') }}</span>
        </div>
      </template>

      <div class="gtn-ref-panel" @click.stop>
        <div class="gtn-ref-title">{{ t('gotion.cell.linkTableTitle') }}</div>
        <div class="gtn-ref-list">
          <div
            v-for="tb in allTables"
            :key="tb.id"
            class="gtn-ref-item"
            :class="{ active: modelValue == tb.id }"
            @click.stop="choose(tb.id)"
          >
            {{ tb.name }}
          </div>
        </div>
        <div v-if="modelValue" class="gtn-clear-btn" @click.stop="choose(null)">
          <el-icon><Close /></el-icon> {{ t('gotion.cell.clearLink') }}
        </div>
      </div>
    </el-popover>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Link, Close } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useGotionTableStore } from '@/stores/gotionTable.js'

const { t } = useI18n()
const props = defineProps({
  modelValue: { default: null },
  column: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue', 'change'])

const store = useGotionTableStore()
const popVisible = ref(false)

const allTables = computed(() => store.allTables)
const targetTable = computed(() => store.allTables.find(tb => tb.id == props.modelValue) || null)

function openPopover() {
  popVisible.value = true
}

function navigate() {
  if (!props.modelValue) return
  popVisible.value = false
  store.switchTable(props.modelValue)
}

function choose(id) {
  popVisible.value = false
  emit('update:modelValue', id)
  emit('change', id)
}
</script>

<style scoped>
.gtn-cell-tableref { width:100%; height:100%; padding:0 6px; cursor:pointer; }
.gtn-ref-display { display:flex; align-items:center; height:100%; }
.gtn-ref-link { display:flex; align-items:center; gap:4px; color:#8fb8ff; text-decoration:underline; cursor:pointer; }
.gtn-ref-link:hover { color:#b3d1ff; }
.gtn-empty-hint { color:#5c6b85; font-size:12px; cursor:pointer; }
.gtn-ref-title { font-size:12px; color:#9ba8bf; margin-bottom:8px; }
.gtn-ref-list { display:flex; flex-direction:column; gap:2px; max-height:200px; overflow-y:auto; }
.gtn-ref-item { padding:6px 8px; border-radius:4px; cursor:pointer; font-size:13px; }
.gtn-ref-item:hover { background:#1b2942; }
.gtn-ref-item.active { background:rgba(24, 144, 255, 0.15); color:#8fb8ff; }
.gtn-clear-btn { display:flex; align-items:center; gap:4px; padding:6px 8px; cursor:pointer; color:#9ba8bf; font-size:12px; border-top:1px solid #28354a; margin-top:4px; }
.gtn-clear-btn:hover { color:#f56c6c; }
</style>
